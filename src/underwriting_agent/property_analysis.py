"""Phase 4 property and appraisal review subgraph."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from underwriting_agent.borrower_analysis import extract_field, find_intake_document
from underwriting_agent.models import DocumentType, PropertyAnalysis, PropertyAnalysisState
from underwriting_agent.observability import append_workflow_event


def review_property_node(state: PropertyAnalysisState) -> dict[str, Any]:
    """Reconcile application, contract, and appraisal values and flag shortfalls."""
    application_meta, application = find_intake_document(
        state, DocumentType.LOAN_APPLICATION
    )
    contract_meta, contract = find_intake_document(
        state, DocumentType.PURCHASE_CONTRACT
    )
    appraisal_meta, appraisal = find_intake_document(state, DocumentType.APPRAISAL)
    loan_amount = (
        application_meta.extracted_fields.get("loan_amount")
        or contract_meta.extracted_fields.get("loan_amount")
        or extract_field(application.text, "Loan Amount", float)
        or 0
    )
    purchase_price = contract_meta.extracted_fields.get("purchase_price") or extract_field(
        contract.text, "Purchase Price", float
    ) or 0
    appraised_value = appraisal_meta.extracted_fields.get("appraised_value") or extract_field(
        appraisal.text, "Appraised Value", float
    ) or 0
    variance = appraised_value - purchase_price
    exceptions = ["LOW_APPRAISAL"] if variance < 0 else []
    analysis = PropertyAnalysis(
        property_address=contract_meta.extracted_fields.get("property_address") or extract_field(
            contract.text, "Property Address"
        ),
        loan_amount=loan_amount,
        purchase_price=purchase_price,
        appraised_value=appraised_value,
        value_variance=variance,
        appraisal_status="below_contract_price" if variance < 0 else "supported",
        exceptions=exceptions,
        source_document_ids=[
            document_id
            for document_id in [
                application_meta.document_id,
                contract_meta.document_id,
                appraisal_meta.document_id,
            ]
            if document_id
        ],
    )
    return {
        "property_analysis": analysis,
        "workflow_status": "PROPERTY_REVIEW_COMPLETE",
        "observability_events": append_workflow_event(
            state,
            "ai",
            "Phase 4 · Property analysis",
            "Reconciled collateral values",
            f"Compared purchase price {purchase_price:.2f} with appraised value {appraised_value:.2f}.",
            appraisal_status=analysis.appraisal_status,
        ),
    }


def build_property_workflow():
    """Compile the Phase 4 collateral-analysis subgraph."""
    workflow = StateGraph(PropertyAnalysisState)
    workflow.add_node("appraisal_review", review_property_node)
    workflow.add_edge(START, "appraisal_review")
    workflow.add_edge("appraisal_review", END)
    return workflow.compile()
