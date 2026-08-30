import json
from pathlib import Path

import pytest

from underwriting_agent.borrower_analysis import build_borrower_workflow, route_borrower
from underwriting_agent.document_layer import build_document_workflow
from underwriting_agent.models import BorrowerPath, DocumentType


ROOT = Path(__file__).resolve().parents[1]
PDF_ROOT = ROOT / "data" / "pdfs"


def load_gold() -> dict[str, dict]:
    with (ROOT / "data" / "expected_results.jsonl").open() as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    return {record["loan_id"]: record for record in records}


def run_loan(loan_id: str):
    paths = sorted((PDF_ROOT / loan_id).glob("*.pdf"))
    document_state = build_document_workflow().invoke(
        {
            "loan_id": loan_id,
            "document_paths": [str(path) for path in paths],
            "workflow_status": "INTAKE",
        }
    )
    return build_borrower_workflow().invoke(document_state)


EXPECTED_PATHS = {
    "LOAN-001": BorrowerPath.SALARIED,
    "LOAN-002": BorrowerPath.SALARIED,
    "LOAN-003": BorrowerPath.SALARIED,
    "LOAN-004": BorrowerPath.SELF_EMPLOYED,
    "LOAN-005": BorrowerPath.SELF_EMPLOYED,
    "LOAN-006": BorrowerPath.SELF_EMPLOYED,
    "LOAN-007": BorrowerPath.SELF_EMPLOYED,
    "LOAN-008": BorrowerPath.MIXED,
}


@pytest.mark.parametrize("loan_id", sorted(EXPECTED_PATHS))
def test_borrower_path_and_gold_financial_facts(loan_id: str):
    gold = load_gold()[loan_id]
    result = run_loan(loan_id)

    assert result["borrower_path"] == EXPECTED_PATHS[loan_id]
    assert result["income_analysis"].qualifying_monthly_income == pytest.approx(
        gold["qualifying_monthly_income"]
    ) if gold["qualifying_monthly_income"] is not None else (
        result["income_analysis"].qualifying_monthly_income is None
    )
    assert result["asset_analysis"].verified_assets == pytest.approx(
        gold["verified_assets"]
    )
    assert result["liability_analysis"].total_monthly_debt == pytest.approx(
        gold["monthly_debt"]
    )
    assert result["workflow_status"] == "BORROWER_ANALYSIS_COMPLETE"


def test_salary_mismatch_is_flagged():
    assert run_loan("LOAN-002")["income_analysis"].exceptions == [
        "INCOME_MISMATCH"
    ]


@pytest.mark.parametrize("loan_id", ["LOAN-005", "LOAN-007"])
def test_declining_business_income_uses_current_lower_income(loan_id: str):
    analysis = run_loan(loan_id)["income_analysis"]

    assert analysis.trend == "declining"
    assert "INCOME_DECLINE" in analysis.exceptions


def test_missing_profit_and_loss_prevents_income_qualification():
    analysis = run_loan("LOAN-006")["income_analysis"]

    assert analysis.qualifying_monthly_income is None
    assert analysis.exceptions == ["MISSING_CURRENT_PL"]


def test_unsupported_large_deposit_is_excluded():
    analysis = run_loan("LOAN-007")["asset_analysis"]

    assert analysis.reported_assets == 250000
    assert analysis.excluded_assets == 80000
    assert analysis.verified_assets == 170000
    assert analysis.exceptions == ["LARGE_DEPOSIT"]


def test_mixed_income_combines_independently_verified_sources():
    analysis = run_loan("LOAN-008")["income_analysis"]

    assert analysis.income_sources == {"salary": 7000, "business": 4000}
    assert analysis.qualifying_monthly_income == 11000


def test_unknown_borrower_never_defaults_to_salaried():
    assert route_borrower({"borrower_path": BorrowerPath.UNKNOWN}) == "unsupported_borrower"


def test_unknown_borrower_still_produces_complete_downstream_financial_state():
    paths = sorted((PDF_ROOT / "LOAN-001").glob("*.pdf"))
    state = build_document_workflow().invoke({
        "loan_id": "LOAN-001",
        "document_paths": [str(path) for path in paths],
        "workflow_status": "INTAKE",
    })
    state["parsed_documents"] = [
        document.model_copy(update={"borrower_employment_type": "unknown"})
        if document.document_type is DocumentType.LOAN_APPLICATION else document
        for document in state["parsed_documents"]
    ]

    result = build_borrower_workflow().invoke(state)

    assert result["borrower_path"] is BorrowerPath.UNKNOWN
    assert result["income_analysis"].exceptions == ["UNSUPPORTED_BORROWER"]
    assert result["income_analysis"].qualifying_monthly_income is None
    assert result["asset_analysis"].verified_assets == 120000
    assert result["liability_analysis"].total_monthly_debt == 2500
