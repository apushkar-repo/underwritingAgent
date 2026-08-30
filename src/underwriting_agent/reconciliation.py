"""Phase 6 canonical fact reconciliation and exception normalization."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from underwriting_agent.models import CanonicalFact, ExceptionItem, ReconciliationState
from underwriting_agent.observability import append_workflow_event


EXCEPTION_DETAILS = {
    "UNSUPPORTED_BORROWER": (
        "UNSUPPORTED_BORROWER",
        "high",
        "Borrower income type could not be routed automatically; manual income review is required.",
    ),
    "MISSING_CURRENT_PL": ("MISSING_DOCUMENT", "high", "Current year-to-date P&L is required for self-employed income."),
    "INCOME_MISMATCH": ("INCOME_MISMATCH", "medium", "Application income differs materially from verified salary income."),
    "INCOME_DECLINE": ("INCOME_DECLINE", "high", "Current business income is declining; lower sustainable income was used."),
    "LARGE_DEPOSIT": ("LARGE_DEPOSIT", "high", "An unsupported large deposit was excluded from verified assets."),
    "LOW_APPRAISAL": ("LOW_APPRAISAL", "high", "Appraised value is below the purchase contract price."),
    "HIGH_DTI": ("HIGH_DTI", "high", "Debt-to-income ratio exceeds the standard guideline threshold."),
    "HIGH_LTV": ("HIGH_LTV", "high", "Loan-to-value ratio exceeds the standard guideline threshold."),
    "EXTERNAL_VALUE_VARIANCE": (
        "EXTERNAL_VALUE_VARIANCE",
        "medium",
        "A cited public-web value differs materially from the appraisal; verify before relying on it.",
    ),
}

RULE_BY_EXCEPTION = {
    "MISSING_DOCUMENT": ["UW-SE-001"],
    "INCOME_MISMATCH": ["UW-INC-001"],
    "INCOME_DECLINE": ["UW-SE-002"],
    "LARGE_DEPOSIT": ["UW-AST-001"],
    "LOW_APPRAISAL": ["UW-APR-001"],
    "HIGH_DTI": ["UW-DTI-001"],
    "HIGH_LTV": ["UW-LTV-001"],
}


def reconcile_facts_node(state: ReconciliationState) -> dict[str, Any]:
    """Create one canonical value for each downstream calculation/reporting fact."""
    income = state["income_analysis"]
    assets = state["asset_analysis"]
    liabilities = state["liability_analysis"]
    prop = state["property_analysis"]
    facts = [
        CanonicalFact(name="borrower_path", value=state["borrower_path"]),
        CanonicalFact(name="qualifying_monthly_income", value=income.qualifying_monthly_income, source_document_ids=income.source_document_ids),
        CanonicalFact(name="verified_assets", value=assets.verified_assets, source_document_ids=assets.source_document_ids),
        CanonicalFact(name="monthly_debt", value=liabilities.total_monthly_debt, source_document_ids=liabilities.source_document_ids),
        CanonicalFact(name="purchase_price", value=prop.purchase_price, source_document_ids=prop.source_document_ids),
        CanonicalFact(name="appraised_value", value=prop.appraised_value, source_document_ids=prop.source_document_ids),
        CanonicalFact(name="dti_percent", value=state["calculations"].dti_percent),
        CanonicalFact(name="ltv_percent", value=state["calculations"].ltv_percent),
    ]
    return {"canonical_facts": facts, "workflow_status": "RECONCILIATION_COMPLETE"}


def normalize_exceptions_node(state: ReconciliationState) -> dict[str, Any]:
    """Merge specialist findings into unique, rule-linked human review items."""
    raw_codes = (
        state["income_analysis"].exceptions
        + state["asset_analysis"].exceptions
        + state["liability_analysis"].exceptions
        + state["property_analysis"].exceptions
        + state["calculations"].calculation_exceptions
        + (state["property_research"].discrepancies if state.get("property_research") else [])
    )
    items = []
    seen = set()
    for raw_code in raw_codes:
        code, severity, details = EXCEPTION_DETAILS[raw_code]
        if code in seen:
            continue
        seen.add(code)
        items.append(ExceptionItem(code=code, severity=severity, details=details, rule_ids=RULE_BY_EXCEPTION.get(code, [])))
    items.sort(key=lambda item: item.code)
    conditions = [f"Resolve {item.code}: {item.details}" for item in items]
    return {
        "exceptions": items,
        "conditions": conditions,
        "human_review_items": conditions.copy(),
        "workflow_status": "NEEDS_EXCEPTION_REVIEW" if items else "READY_FOR_HUMAN_REVIEW",
        "observability_events": append_workflow_event(
            state,
            "ai",
            "Phase 6 · Reconciliation",
            "Reconciled evidence and exceptions",
            f"Created {len(items)} review exceptions and {len(conditions)} conditions.",
            exception_codes=[item.code for item in items],
        ),
    }


def build_reconciliation_workflow():
    """Compile the Phase 6 fact and exception subgraph."""
    workflow = StateGraph(ReconciliationState)
    workflow.add_node("evidence_reconciliation", reconcile_facts_node)
    workflow.add_node("exceptions_and_conditions", normalize_exceptions_node)
    workflow.add_edge(START, "evidence_reconciliation")
    workflow.add_edge("evidence_reconciliation", "exceptions_and_conditions")
    workflow.add_edge("exceptions_and_conditions", END)
    return workflow.compile()
