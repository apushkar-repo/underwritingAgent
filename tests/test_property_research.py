import json
from pathlib import Path

import httpx

from underwriting_agent.models import PropertyResearchResult, PropertyValueObservation, WebEvidenceSource
from underwriting_agent.pipeline import run_underwriting_pipeline
from underwriting_agent.property_research import YouComPropertyResearchService, YouComSearchClient


ROOT = Path(__file__).resolve().parents[1]


def test_you_com_search_is_address_only_and_preserves_citations():
    requests = []

    def handler(request: httpx.Request):
        payload = json.loads(request.content)
        requests.append((request, payload))
        return httpx.Response(200, json={
            "results": {
                "web": [{
                    "url": f"https://county.example.gov/property/{len(requests)}",
                    "title": "1847 Larkspur Ridge property sale record",
                    "contents": {"highlights": ["The property sold in 2024 for $275,000."]},
                }],
                "news": [],
            }
        })

    client = YouComSearchClient(
        "test-key", transport=httpx.MockTransport(handler), count=3
    )
    service = YouComPropertyResearchService(client, variance_threshold_percent=10)
    result = service.research(
        "1847 Larkspur Ridge, Columbus, OH 43215",
        purchase_price=375000,
        appraised_value=382000,
    )

    assert len(requests) == 3
    assert all(request.headers["X-API-Key"] == "test-key" for request, _ in requests)
    assert all("1847 Larkspur Ridge" in payload["query"] for _, payload in requests)
    assert all("Elena" not in payload["query"] and "UW-" not in payload["query"] for _, payload in requests)
    assert len(result.sources) == 3
    assert all(source.source_tier == 1 for source in result.sources)
    assert result.observations[0].amount == 275000
    assert result.observations[0].source_url.startswith("https://county.example.gov")
    assert result.discrepancies == ["EXTERNAL_VALUE_VARIANCE"]


class FakePropertyResearchService:
    def research(self, address: str, *, purchase_price: float, appraised_value: float):
        return PropertyResearchResult(
            property_address=address,
            research_status="completed",
            sources=[WebEvidenceSource(
                url="https://county.example.gov/record/1",
                title="Recorded sale",
                excerpt="Reported sold price $275,000 in 2024",
                domain="county.example.gov",
                query=f'"{address}" sale history',
                source_tier=1,
            )],
            observations=[PropertyValueObservation(
                observation_type="reported_sale",
                amount=275000,
                event_date="2024",
                source_url="https://county.example.gov/record/1",
                corroboration_status="authoritative",
            )],
            discrepancies=["EXTERNAL_VALUE_VARIANCE"],
        )


def test_property_research_is_included_in_underwriting_outcome():
    state = run_underwriting_pipeline(
        "UW-26-0417-A",
        ROOT / "data" / "realistic_pdfs",
        ROOT / "data" / "underwriting_guidelines.jsonl",
        property_research_service=FakePropertyResearchService(),
    )
    package = state["review_package"]
    assert package.external_property_research.research_status == "completed"
    assert package.external_property_research.sources[0].url.startswith("https://")
    assert "EXTERNAL_VALUE_VARIANCE" in {item.code for item in package.exceptions}


def test_disabled_property_research_is_non_blocking():
    state = run_underwriting_pipeline(
        "UW-26-0417-A",
        ROOT / "data" / "realistic_pdfs",
        ROOT / "data" / "underwriting_guidelines.jsonl",
    )
    assert state["property_research"].research_status == "disabled"
    assert "EXTERNAL_VALUE_VARIANCE" not in {item.code for item in state["exceptions"]}
