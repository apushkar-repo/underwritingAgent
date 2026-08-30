"""Phase 3 borrower routing, income, asset, and liability specialists."""

from __future__ import annotations

import re
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from underwriting_agent.models import (
    AssetAnalysis,
    BorrowerAnalysisState,
    BorrowerPath,
    DocumentType,
    IncomeAnalysis,
    LiabilityAnalysis,
)
from underwriting_agent.observability import append_workflow_event


def find_intake_document(state: BorrowerAnalysisState, document_type: DocumentType):
    """Return matching parsed metadata and extracted PDF text with shared provenance."""
    parsed = next(
        document
        for document in state["parsed_documents"]
        if document.document_type == document_type
    )
    intake = next(
        document
        for document in state["intake_documents"]
        if document.source_path == parsed.source_path
    )
    return parsed, intake


def extract_field(text: str, label: str, cast: type = str):
    """Read the first labeled value from the synthetic text-searchable PDFs."""
    match = re.search(
        rf"^\s*{re.escape(label)}:\s*(.+?)\s*$",
        text,
        re.MULTILINE | re.IGNORECASE,
    )
    if not match or match.group(1).casefold() == "not provided":
        return None
    return cast(match.group(1).replace(",", ""))


def extract_all_fields(text: str, label: str, cast: type = float) -> list[Any]:
    """Read every occurrence of a repeated labeled value."""
    values = re.findall(
        rf"^\s*{re.escape(label)}:\s*(.+?)\s*$",
        text,
        re.MULTILINE | re.IGNORECASE,
    )
    return [
        cast(value.replace(",", ""))
        for value in values
        if value.casefold() != "not provided"
    ]


def _stated_income(state: BorrowerAnalysisState) -> float | None:
    parsed, application = find_intake_document(state, DocumentType.LOAN_APPLICATION)
    return parsed.extracted_fields.get("stated_monthly_income") or extract_field(
        application.text, "Stated Monthly Income", float
    )


def classify_borrower_node(state: BorrowerAnalysisState) -> dict[str, Any]:
    """Route from the employment type extracted from the loan application."""
    application, _ = find_intake_document(state, DocumentType.LOAN_APPLICATION)
    raw_type = application.borrower_employment_type or "unknown"
    try:
        borrower_path = BorrowerPath(raw_type)
    except ValueError:
        borrower_path = BorrowerPath.UNKNOWN
    return {
        "borrower_path": borrower_path,
        "workflow_status": "BORROWER_ANALYSIS",
    }


def route_borrower(
    state: BorrowerAnalysisState,
) -> Literal[
    "salaried_income", "self_employed_income", "mixed_income", "unsupported_borrower"
]:
    """Select exactly one income specialist for the classified borrower."""
    routes = {
        BorrowerPath.SALARIED: "salaried_income",
        BorrowerPath.SELF_EMPLOYED: "self_employed_income",
        BorrowerPath.MIXED: "mixed_income",
    }
    return routes.get(state["borrower_path"], "unsupported_borrower")


def unsupported_borrower_node(state: BorrowerAnalysisState) -> dict[str, Any]:
    """Carry an unknown income path forward without leaving partial state."""
    return {
        "income_analysis": IncomeAnalysis(
            borrower_path=BorrowerPath.UNKNOWN,
            stated_monthly_income=_stated_income(state),
            qualifying_monthly_income=None,
            trend="unknown",
            exceptions=["UNSUPPORTED_BORROWER"],
        ),
        "workflow_status": "NEEDS_HUMAN_REVIEW",
    }


def salaried_income_node(state: BorrowerAnalysisState) -> dict[str, Any]:
    """Verify salary and flag material differences from application income."""
    parsed, income_document = find_intake_document(
        state, DocumentType.INCOME_DOCUMENTS
    )
    stated = _stated_income(state)
    verified = parsed.extracted_fields.get("qualifying_monthly_income") or extract_field(
        income_document.text, "Monthly Base Income", float
    )
    exceptions: list[str] = []
    if stated and verified and abs(stated - verified) / stated > 0.05:
        exceptions.append("INCOME_MISMATCH")
    return {
        "income_analysis": IncomeAnalysis(
            borrower_path=BorrowerPath.SALARIED,
            stated_monthly_income=stated,
            qualifying_monthly_income=verified,
            income_sources={"salary": verified} if verified is not None else {},
            trend="stable",
            exceptions=exceptions,
            source_document_ids=[parsed.document_id] if parsed.document_id else [],
        )
    }


def self_employed_income_node(state: BorrowerAnalysisState) -> dict[str, Any]:
    """Use stable averages or the lower current income when business income declines."""
    parsed, income_document = find_intake_document(
        state, DocumentType.INCOME_DOCUMENTS
    )
    annual_from_normalization = parsed.extracted_fields.get("annual_income")
    average = annual_from_normalization or extract_field(
        income_document.text, "Two Year Average Annual Income", float
    )
    current = extract_field(
        income_document.text, "Current Pl Annualized Income", float
    )
    trend = extract_field(income_document.text, "Trend") or "unknown"
    exceptions: list[str] = []
    missing_evidence = parsed.extracted_fields.get("missing_evidence", [])
    if current is None and "current_year_profit_and_loss_statement" in missing_evidence:
        exceptions.append("MISSING_CURRENT_PL")
    if trend.casefold() == "declining":
        exceptions.append("INCOME_DECLINE")
    annual_income = current if trend.casefold() == "declining" else average
    qualifying = annual_income / 12 if annual_income is not None else None
    return {
        "income_analysis": IncomeAnalysis(
            borrower_path=BorrowerPath.SELF_EMPLOYED,
            stated_monthly_income=_stated_income(state),
            qualifying_monthly_income=qualifying,
            income_sources={"business": qualifying} if qualifying is not None else {},
            trend=trend.casefold(),
            exceptions=exceptions,
            source_document_ids=[parsed.document_id] if parsed.document_id else [],
        )
    }


def mixed_income_node(state: BorrowerAnalysisState) -> dict[str, Any]:
    """Verify salary and business evidence separately before combining them."""
    parsed, income_document = find_intake_document(
        state, DocumentType.INCOME_DOCUMENTS
    )
    salary = parsed.extracted_fields.get("qualifying_monthly_income") or extract_field(
        income_document.text, "Monthly Base Income", float
    ) or 0
    business_annual = extract_field(
        income_document.text, "Two Year Average Annual Income", float
    ) or 0
    business = business_annual / 12
    return {
        "income_analysis": IncomeAnalysis(
            borrower_path=BorrowerPath.MIXED,
            stated_monthly_income=_stated_income(state),
            qualifying_monthly_income=salary + business,
            income_sources={"salary": salary, "business": business},
            trend="stable",
            source_document_ids=[parsed.document_id] if parsed.document_id else [],
        )
    }


def asset_verification_node(state: BorrowerAnalysisState) -> dict[str, Any]:
    """Calculate verified assets after excluding unsupported large deposits."""
    parsed, asset_document = find_intake_document(
        state, DocumentType.ASSET_STATEMENT
    )
    reported = parsed.extracted_fields.get("reported_assets") or extract_field(
        asset_document.text, "Verified Total", float
    ) or 0
    deposits = parsed.extracted_fields.get("large_deposits") or extract_all_fields(
        asset_document.text, "Amount", float
    )
    unsupported_deposits = parsed.extracted_fields.get("unsupported_deposits", [])
    unsupported = bool(unsupported_deposits) or (
        "Source: unexplained" in asset_document.text
        and "Documentation Received: False" in asset_document.text
    )
    excluded = sum(unsupported_deposits or deposits) if unsupported else 0
    return {
        "asset_analysis": AssetAnalysis(
            reported_assets=reported,
            verified_assets=reported - excluded,
            excluded_assets=excluded,
            large_deposits=deposits,
            exceptions=["LARGE_DEPOSIT"] if unsupported else [],
            source_document_ids=[parsed.document_id] if parsed.document_id else [],
        )
    }


def liability_analysis_node(state: BorrowerAnalysisState) -> dict[str, Any]:
    """Extract credit score and recurring monthly debt for later DTI calculation."""
    parsed, credit_document = find_intake_document(
        state, DocumentType.CREDIT_REPORT
    )
    return {
        "liability_analysis": LiabilityAnalysis(
            credit_score=parsed.extracted_fields.get("credit_score") or extract_field(
                credit_document.text, "Score", int
            ),
            total_monthly_debt=parsed.extracted_fields.get("total_monthly_debt") or extract_field(
                credit_document.text, "Total Monthly Debt", float
            )
            or 0,
            source_document_ids=[parsed.document_id] if parsed.document_id else [],
        ),
        "workflow_status": "BORROWER_ANALYSIS_COMPLETE",
        "observability_events": append_workflow_event(
            state,
            "ai",
            "Phase 3 · Borrower analysis",
            "Analyzed borrower finances",
            f"Completed {state['borrower_path'].value} income, asset, and liability analysis.",
            borrower_path=state["borrower_path"].value,
        ),
    }


def build_borrower_workflow():
    """Compile the independently runnable Phase 3 borrower-analysis subgraph."""
    workflow = StateGraph(BorrowerAnalysisState)
    workflow.add_node("classify_borrower", classify_borrower_node)
    workflow.add_node("salaried_income", salaried_income_node)
    workflow.add_node("self_employed_income", self_employed_income_node)
    workflow.add_node("mixed_income", mixed_income_node)
    workflow.add_node("unsupported_borrower", unsupported_borrower_node)
    workflow.add_node("asset_verification", asset_verification_node)
    workflow.add_node("liability_analysis", liability_analysis_node)
    workflow.add_edge(START, "classify_borrower")
    workflow.add_conditional_edges(
        "classify_borrower",
        route_borrower,
        [
            "salaried_income",
            "self_employed_income",
            "mixed_income",
            "unsupported_borrower",
        ],
    )
    for income_node in [
        "salaried_income",
        "self_employed_income",
        "mixed_income",
    ]:
        workflow.add_edge(income_node, "asset_verification")
    workflow.add_edge("asset_verification", "liability_analysis")
    workflow.add_edge("liability_analysis", END)
    workflow.add_edge("unsupported_borrower", "asset_verification")
    return workflow.compile()
