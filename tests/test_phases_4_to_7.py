import json
from pathlib import Path

import pytest

from underwriting_agent.pipeline import run_underwriting_pipeline


ROOT = Path(__file__).resolve().parents[1]
PDF_ROOT = ROOT / "data" / "pdfs"
GUIDELINES = ROOT / "data" / "underwriting_guidelines.jsonl"


def gold_records():
    with (ROOT / "data" / "expected_results.jsonl").open() as handle:
        return {record["loan_id"]: record for record in map(json.loads, handle)}


@pytest.mark.parametrize("loan_id", [f"LOAN-{number:03d}" for number in range(1, 9)])
def test_pipeline_matches_gold_calculations_and_rules(loan_id):
    gold = gold_records()[loan_id]
    result = run_underwriting_pipeline(loan_id, PDF_ROOT, GUIDELINES)
    facts = {fact.name: fact.value for fact in result["canonical_facts"]}

    assert facts["dti_percent"] == gold["dti_percent"]
    assert facts["ltv_percent"] == gold["ltv_percent"]
    assert {rule.rule_id for rule in result["retrieved_rules"]} == set(gold["applicable_rule_ids"])
    assert {item.code for item in result["exceptions"]} == {
        item["code"] for item in gold["exceptions"]
    }
    assert result["review_package"].human_review_required is True
    assert result["review_package"].workflow_status == "READY_FOR_HUMAN_REVIEW"


def test_low_appraisal_uses_lower_value_for_ltv():
    result = run_underwriting_pipeline("LOAN-003", PDF_ROOT, GUIDELINES)

    assert result["property_analysis"].value_variance == -50000
    assert result["calculations"].ltv_percent == 88
    assert {item.code for item in result["exceptions"]} == {"LOW_APPRAISAL", "HIGH_LTV"}


def test_showcase_case_is_escalated_with_provenance():
    result = run_underwriting_pipeline("LOAN-007", PDF_ROOT, GUIDELINES)
    package = result["review_package"]

    assert package.review_disposition == "escalated_review"
    assert {item.code for item in package.exceptions} == {
        "INCOME_DECLINE", "LARGE_DEPOSIT", "LOW_APPRAISAL", "HIGH_LTV"
    }
    assert all(fact.source_document_ids for fact in package.key_facts if fact.name not in {"borrower_path", "dti_percent", "ltv_percent"})


def test_missing_pl_is_suspended_for_documents():
    result = run_underwriting_pipeline("LOAN-006", PDF_ROOT, GUIDELINES)

    assert result["calculations"].dti_percent is None
    assert result["review_package"].review_disposition == "suspended_missing_documents"
    assert {item.code for item in result["exceptions"]} == {"MISSING_DOCUMENT"}


def test_clean_case_still_requires_final_human_review():
    package = run_underwriting_pipeline("LOAN-001", PDF_ROOT, GUIDELINES)["review_package"]

    assert package.review_disposition == "standard_human_review"
    assert package.exceptions == []
    assert "final lending decision" in package.disclaimer
