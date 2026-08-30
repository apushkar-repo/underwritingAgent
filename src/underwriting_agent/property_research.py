"""Phase 4B address-only You.com property research with cited evidence."""

from __future__ import annotations

import re
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
from langgraph.graph import END, START, StateGraph

from underwriting_agent.models import (
    PropertyResearchResult,
    PropertyResearchState,
    PropertyValueObservation,
    WebEvidenceSource,
)
from underwriting_agent.observability import append_workflow_event


MONEY_PATTERN = re.compile(r"\$\s*([1-9]\d{2,}(?:,\d{3})*(?:\.\d{2})?)")
DATE_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")


class PropertyResearchService(Protocol):
    def research(self, address: str, *, purchase_price: float, appraised_value: float) -> PropertyResearchResult: ...


def _source_tier(domain: str) -> int:
    domain = domain.casefold()
    if any(token in domain for token in (".gov", "assessor", "recorder", "treasurer", "auditor")):
        return 1
    if any(token in domain for token in ("realtor.com", "redfin.com", "zillow.com", "homes.com")):
        return 2
    if any(token in domain for token in ("trulia.com", "movoto.com", "propertyshark.com")):
        return 3
    return 4


def _observation_type(text: str) -> str:
    lowered = text.casefold()
    if any(term in lowered for term in ("sold", "sale price", "last sale", "sale history")):
        return "reported_sale"
    if any(term in lowered for term in ("estimate", "estimated value", "home value")):
        return "online_estimate"
    if any(term in lowered for term in ("assessed value", "tax assessment", "assessment")):
        return "public_assessment"
    if any(term in lowered for term in ("listed", "listing price", "for sale")):
        return "listing"
    return "unclassified_value"


def _matches_subject_address(address: str, source: WebEvidenceSource) -> bool:
    """Require the street number and at least one street-name token in evidence."""
    subject = re.findall(r"[a-z0-9]+", address.casefold().split(",", 1)[0])
    evidence = set(re.findall(
        r"[a-z0-9]+",
        f"{source.title} {source.excerpt} {source.url}".casefold(),
    ))
    if len(subject) < 2:
        return False
    street_number, street_tokens = subject[0], subject[1:]
    return street_number in evidence and any(token in evidence for token in street_tokens)


class YouComSearchClient:
    """Minimal client for You.com's POST /v1/search endpoint."""

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = "https://ydc-index.io/v1/search",
        count: int = 8,
        country: str = "US",
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key
        self.endpoint = endpoint
        self.count = count
        self.country = country
        self.timeout = timeout
        self.transport = transport

    def search(self, query: str) -> list[WebEvidenceSource]:
        """Return structured sources with query-relevant highlights."""
        payload = {
            "query": query,
            "count": self.count,
            "country": self.country,
            "language": "EN",
            "safesearch": "strict",
            "extraction": {"extraction_mode": "highlights"},
        }
        with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
            response = client.post(
                self.endpoint,
                headers={"X-API-Key": self.api_key, "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
        results = response.json().get("results", {})
        sources: list[WebEvidenceSource] = []
        for section in ("web", "news"):
            for item in results.get(section, []) or []:
                contents = item.get("contents") or {}
                highlights = contents.get("highlights") or item.get("snippets") or []
                if isinstance(highlights, str):
                    highlights = [highlights]
                excerpt = " ".join(
                    value.get("text", "") if isinstance(value, dict) else str(value)
                    for value in highlights
                ).strip() or item.get("description", "")
                url = item.get("url", "")
                if not url:
                    continue
                domain = urlparse(url).netloc.casefold().removeprefix("www.")
                sources.append(WebEvidenceSource(
                    url=url,
                    title=item.get("title", "Untitled result"),
                    excerpt=excerpt[:4000],
                    domain=domain,
                    query=query,
                    source_tier=_source_tier(domain),
                ))
        return sources


class YouComPropertyResearchService:
    """Run address-only searches and conservatively normalize public claims."""

    def __init__(self, client: YouComSearchClient, *, variance_threshold_percent: float = 10.0):
        self.client = client
        self.variance_threshold_percent = variance_threshold_percent

    def research(self, address: str, *, purchase_price: float, appraised_value: float) -> PropertyResearchResult:
        queries = [
            f'"{address}" property sale history county assessor',
            f'"{address}" sold listing price history',
            f'"{address}" assessed value property tax home value estimate',
        ]
        sources: list[WebEvidenceSource] = []
        warnings: list[str] = []
        for query in queries:
            try:
                sources.extend(self.client.search(query))
            except Exception as exc:
                warnings.append(f"You.com search failed for one query: {type(exc).__name__}")

        # De-duplicate URLs while retaining the first query and evidence excerpt.
        sources = list({source.url: source for source in reversed(sources)}.values())
        observations: list[PropertyValueObservation] = []
        for source in sources:
            if not _matches_subject_address(address, source):
                continue
            combined = f"{source.title} {source.excerpt}"
            kind = _observation_type(combined)
            if kind == "unclassified_value":
                continue
            year = DATE_PATTERN.search(combined)
            for amount_text in MONEY_PATTERN.findall(combined)[:3]:
                amount = float(amount_text.replace(",", ""))
                if amount < 25000:
                    continue
                observations.append(PropertyValueObservation(
                    observation_type=kind,
                    amount=amount,
                    event_date=year.group(1) if year else None,
                    source_url=source.url,
                    corroboration_status="authoritative" if source.source_tier == 1 else "unconfirmed",
                ))

        discrepancies: list[str] = []
        comparable = [
            item for item in observations
            if item.observation_type in {"reported_sale", "online_estimate", "listing"}
        ]
        for item in comparable:
            if appraised_value > 0:
                variance = abs(item.amount - appraised_value) / appraised_value * 100
                if variance >= self.variance_threshold_percent:
                    discrepancies.append("EXTERNAL_VALUE_VARIANCE")
                    break
        if not sources:
            warnings.append("No usable public-web property sources were returned")
        elif not observations:
            warnings.append(
                "No value observation could be tied to an exact subject-address match"
            )
        return PropertyResearchResult(
            property_address=address,
            research_status="completed" if sources else "unavailable",
            sources=sources,
            observations=observations,
            discrepancies=sorted(set(discrepancies)),
            warnings=warnings,
        )


def research_property_node(state: PropertyResearchState, service: PropertyResearchService | None) -> dict[str, Any]:
    """Research only the property address; never send borrower or loan facts."""
    prop = state["property_analysis"]
    address = prop.property_address or ""
    if service is None:
        result = PropertyResearchResult(
            property_address=address,
            research_status="disabled",
            warnings=["External property research is disabled"],
        )
    elif not address:
        result = PropertyResearchResult(
            property_address="",
            research_status="unavailable",
            warnings=["Property address is unavailable"],
        )
    else:
        result = service.research(
            address,
            purchase_price=prop.purchase_price,
            appraised_value=prop.appraised_value,
        )
    return {
        "property_research": result,
        "workflow_status": "PROPERTY_RESEARCH_COMPLETE",
        "observability_events": append_workflow_event(
            state,
            "ai",
            "Phase 4B · Property research",
            "Researched public property evidence",
            f"Research status: {result.research_status}; cited sources: {len(result.sources)}.",
            research_status=result.research_status,
            source_count=len(result.sources),
        ),
    }


def build_property_research_workflow(*, service: PropertyResearchService | None = None):
    workflow = StateGraph(PropertyResearchState)
    workflow.add_node("property_web_research", lambda state: research_property_node(state, service))
    workflow.add_edge(START, "property_web_research")
    workflow.add_edge("property_web_research", END)
    return workflow.compile()
