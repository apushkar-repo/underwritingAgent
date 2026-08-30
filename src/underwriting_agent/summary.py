"""Phase 7 evidence-backed underwriting review package generation."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from underwriting_agent.models import UnderwritingReviewPackage, UnderwritingState
from underwriting_agent.observability import workflow_event


def _disposition(state: UnderwritingState) -> str:
    codes = {item.code for item in state.get("exceptions", [])}
    if "MISSING_DOCUMENT" in codes:
        return "suspended_missing_documents"
    if len(codes) >= 3:
        return "escalated_review"
    if codes:
        return "conditional_review"
    return "standard_human_review"


def generate_summary_node(state: UnderwritingState, narrator=None) -> dict[str, Any]:
    """Produce a deterministic, traceable package for a human underwriter."""
    disposition = _disposition(state)
    facts = {fact.name: fact.value for fact in state["canonical_facts"]}
    exception_codes = [item.code for item in state.get("exceptions", [])]
    executive_summary = (
        f"Loan {state['loan_id']} has qualifying monthly income of "
        f"{facts.get('qualifying_monthly_income')}, verified assets of "
        f"{facts.get('verified_assets')}, DTI of {facts.get('dti_percent')}%, and "
        f"LTV of {facts.get('ltv_percent')}%. "
        f"Review recommendation: {disposition}. Exceptions: "
        f"{', '.join(exception_codes) if exception_codes else 'none'}."
    )
    reviewer_focus = [item.details for item in state.get("exceptions", [])]
    if narrator is not None:
        narrative = narrator.draft(state)
        executive_summary = narrative.executive_summary
        reviewer_focus = narrative.reviewer_focus
    final_event = workflow_event(
        "ai",
        "Phase 7 · Recommendation",
        "Prepared underwriting recommendation",
        f"Prepared {disposition} recommendation for qualified human review.",
        recommendation=disposition,
    )[0]
    final_log = [*state.get("observability_events", []), final_event]
    package = UnderwritingReviewPackage(
        loan_id=state["loan_id"],
        review_disposition=disposition,
        workflow_status="READY_FOR_HUMAN_REVIEW",
        executive_summary=executive_summary,
        reviewer_focus=reviewer_focus,
        key_facts=state["canonical_facts"],
        applicable_rule_ids=sorted(rule.rule_id for rule in state["retrieved_rules"]),
        exceptions=state.get("exceptions", []),
        conditions=state.get("conditions", []),
        human_review_required=True,
        human_review=state.get("human_review"),
        external_property_research=state.get("property_research"),
        observability_log=final_log,
    )
    return {
        "review_package": package,
        "workflow_status": "READY_FOR_HUMAN_REVIEW",
        "observability_events": final_log,
    }


def build_summary_workflow(*, narrator=None):
    """Compile the Phase 7 reporting subgraph."""
    workflow = StateGraph(UnderwritingState)
    workflow.add_node(
        "underwriting_summary",
        lambda state: generate_summary_node(state, narrator),
    )
    workflow.add_edge(START, "underwriting_summary")
    workflow.add_edge("underwriting_summary", END)
    return workflow.compile()
