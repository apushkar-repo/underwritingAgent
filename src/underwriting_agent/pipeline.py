"""Convenience composition for executing Phases 2 through 7 in order."""

from pathlib import Path

from underwriting_agent.borrower_analysis import build_borrower_workflow
from underwriting_agent.calculations_policy import build_calculation_policy_workflow
from underwriting_agent.document_layer import build_document_workflow
from underwriting_agent.intake_packages import resolve_document_paths
from underwriting_agent.property_analysis import build_property_workflow
from underwriting_agent.property_research import build_property_research_workflow
from underwriting_agent.reconciliation import build_reconciliation_workflow
from underwriting_agent.summary import build_summary_workflow


def run_underwriting_pipeline(
    loan_id: str,
    pdf_root: Path,
    guideline_path: Path,
    *,
    document_interpreter=None,
    guideline_store=None,
    review_narrator=None,
    property_research_service=None,
):
    """Run independently compiled phase subgraphs with one shared state dictionary."""
    paths = resolve_document_paths(pdf_root, loan_id)
    if not paths:
        raise FileNotFoundError(f"No PDF package found for {loan_id!r} under {pdf_root}")
    state = build_document_workflow(document_interpreter=document_interpreter).invoke({
        "loan_id": loan_id,
        "document_paths": [str(path) for path in paths],
        "workflow_status": "INTAKE",
    })
    state = build_borrower_workflow().invoke(state)
    state = build_property_workflow().invoke(state)
    state = build_property_research_workflow(service=property_research_service).invoke(state)
    state = build_calculation_policy_workflow(
        guideline_path, store=guideline_store
    ).invoke(state)
    state = build_reconciliation_workflow().invoke(state)
    return build_summary_workflow(narrator=review_narrator).invoke(state)
