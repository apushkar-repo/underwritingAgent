from pathlib import Path

import pytest

from underwriting_agent.document_layer import build_document_workflow
from underwriting_agent.models import DocumentType


ROOT = Path(__file__).resolve().parents[1]
PDF_ROOT = ROOT / "data" / "pdfs"


def run_loan(loan_id: str, *, exclude: str | None = None):
    paths = sorted(PDF_ROOT.joinpath(loan_id).glob("*.pdf"))
    if exclude:
        paths = [path for path in paths if path.name != exclude]
    return build_document_workflow().invoke(
        {
            "loan_id": loan_id,
            "document_paths": [str(path) for path in paths],
            "workflow_status": "INTAKE",
        }
    )


@pytest.mark.parametrize(
    ("loan_id", "borrower_type"),
    [
        ("LOAN-001", "salaried"),
        ("LOAN-002", "salaried"),
        ("LOAN-003", "salaried"),
        ("LOAN-004", "self_employed"),
        ("LOAN-005", "self_employed"),
        ("LOAN-006", "self_employed"),
        ("LOAN-007", "self_employed"),
        ("LOAN-008", "mixed"),
    ],
)
def test_classifies_complete_document_inventory(loan_id: str, borrower_type: str):
    result = run_loan(loan_id)

    assert len(result["parsed_documents"]) == 6
    assert {document.document_type for document in result["parsed_documents"]} == {
        DocumentType.LOAN_APPLICATION,
        DocumentType.INCOME_DOCUMENTS,
        DocumentType.ASSET_STATEMENT,
        DocumentType.CREDIT_REPORT,
        DocumentType.PURCHASE_CONTRACT,
        DocumentType.APPRAISAL,
    }
    assert result["requirements"].borrower_type == borrower_type


def test_clean_loan_advances_to_verification():
    result = run_loan("LOAN-001")

    assert result["workflow_status"] == "VERIFICATION"
    assert result["requirements"].complete is True
    assert result["requirements"].missing_document_types == []
    assert result["requirements"].missing_evidence == []


def test_missing_pdf_is_reported():
    result = run_loan("LOAN-001", exclude="appraisal.pdf")

    assert result["workflow_status"] == "NEEDS_DOCUMENTS"
    assert result["requirements"].missing_document_types == [DocumentType.APPRAISAL]


def test_missing_current_profit_and_loss_statement_is_reported():
    result = run_loan("LOAN-006")

    assert result["workflow_status"] == "NEEDS_DOCUMENTS"
    assert result["requirements"].missing_evidence == [
        "current_year_profit_and_loss_statement"
    ]


def test_unexplained_deposit_source_is_reported():
    result = run_loan("LOAN-007")

    # Unsupported funds can be excluded and carried forward as a condition.
    assert result["workflow_status"] == "VERIFICATION"
    assert result["requirements"].complete is True
    assert result["requirements"].missing_evidence == ["deposit_source_documentation"]
