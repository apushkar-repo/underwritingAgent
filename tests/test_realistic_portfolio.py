from pathlib import Path

import pytest

from underwriting_agent.document_layer import build_document_workflow
from underwriting_agent.intake_packages import resolve_document_paths
from underwriting_agent.models import BorrowerPath, DocumentType
from underwriting_agent.pipeline import run_underwriting_pipeline


ROOT = Path(__file__).resolve().parents[1]
PDF_ROOT = ROOT / "data" / "realistic_pdfs"
GUIDELINES = ROOT / "data" / "underwriting_guidelines.jsonl"
EXPECTED_TYPES = {
    DocumentType.LOAN_APPLICATION,
    DocumentType.INCOME_DOCUMENTS,
    DocumentType.ASSET_STATEMENT,
    DocumentType.CREDIT_REPORT,
    DocumentType.PURCHASE_CONTRACT,
    DocumentType.APPRAISAL,
}


def document_state(reference: str):
    paths = resolve_document_paths(PDF_ROOT, reference)
    return build_document_workflow().invoke({
        "loan_id": reference,
        "document_paths": [str(path) for path in paths],
        "workflow_status": "INTAKE",
    })


@pytest.mark.parametrize("reference", ["UW-26-0417-A", "BRK-90831", "WHL-77-2206"])
def test_manifest_resolves_six_realistic_documents(reference):
    assert len(resolve_document_paths(PDF_ROOT, reference)) == 6


@pytest.mark.parametrize("reference", ["UW-26-0417-A", "BRK-90831", "WHL-77-2206"])
def test_document_layer_classifies_every_realistic_document(reference):
    state = document_state(reference)
    assert {document.document_type for document in state["parsed_documents"]} == EXPECTED_TYPES
    assert all(document.document_id for document in state["parsed_documents"])


def test_self_employed_package_requests_current_profit_and_loss():
    state = document_state("BRK-90831")
    assert state["workflow_status"] == "NEEDS_DOCUMENTS"
    assert "current_year_profit_and_loss_statement" in state["requirements"].missing_evidence


@pytest.mark.parametrize(
    ("reference", "path", "income", "assets", "purchase_price", "appraised_value"),
    [
        ("UW-26-0417-A", BorrowerPath.SALARIED, 8250.0, 61884.29, 375000.0, 382000.0),
        ("BRK-90831", BorrowerPath.SELF_EMPLOYED, 9353.333333333334, 71729.17, 525000.0, 510000.0),
        ("WHL-77-2206", BorrowerPath.MIXED, 7600.0, 24407.66, 310000.0, 305000.0),
    ],
)
def test_realistic_portfolio_runs_end_to_end(
    reference, path, income, assets, purchase_price, appraised_value
):
    state = run_underwriting_pipeline(reference, PDF_ROOT, GUIDELINES)
    assert state["borrower_path"] is path
    assert state["income_analysis"].qualifying_monthly_income == pytest.approx(income)
    assert state["asset_analysis"].verified_assets == pytest.approx(assets)
    assert state["property_analysis"].purchase_price == purchase_price
    assert state["property_analysis"].appraised_value == appraised_value
    assert state["review_package"].human_review_required is True
