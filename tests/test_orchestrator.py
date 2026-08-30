from pathlib import Path

from langgraph.types import Command

from underwriting_agent.orchestrator import build_underwriting_orchestrator


ROOT = Path(__file__).resolve().parents[1]
PDF_ROOT = ROOT / "data" / "pdfs"
GUIDELINES = ROOT / "data" / "underwriting_guidelines.jsonl"


def input_for(loan_id: str, *, exclude: str | None = None):
    paths = sorted((PDF_ROOT / loan_id).glob("*.pdf"))
    if exclude:
        paths = [path for path in paths if path.name != exclude]
    return {
        "loan_id": loan_id,
        "document_paths": [str(path) for path in paths],
        "workflow_status": "INTAKE",
    }


def config(thread_id: str):
    return {"configurable": {"thread_id": thread_id}}


def test_clean_file_runs_to_human_review_package_without_exception_pause():
    orchestrator = build_underwriting_orchestrator(GUIDELINES)
    result = orchestrator.invoke(input_for("LOAN-001"), config=config("clean"))

    assert "__interrupt__" not in result
    assert result["workflow_status"] == "READY_FOR_HUMAN_REVIEW"
    assert result["review_package"].review_disposition == "standard_human_review"


def test_exception_file_pauses_and_resumes_on_same_thread():
    orchestrator = build_underwriting_orchestrator(GUIDELINES)
    thread_config = config("exception-review")
    paused = orchestrator.invoke(input_for("LOAN-007"), config=thread_config)

    assert paused["__interrupt__"][0].value["type"] == "exception_review"
    assert len(paused["__interrupt__"][0].value["exceptions"]) == 4

    resumed = orchestrator.invoke(
        Command(
            resume={
                "action": "acknowledge",
                "reviewer": "test-underwriter",
                "notes": "Reviewed synthetic exceptions.",
            }
        ),
        config=thread_config,
    )

    assert resumed["workflow_status"] == "READY_FOR_HUMAN_REVIEW"
    assert resumed["review_package"].human_review["reviewer"] == "test-underwriter"
    assert resumed["review_package"].review_disposition == "escalated_review"
    events = resumed["review_package"].observability_log
    assert any(event.actor == "human" and event.action == "Submitted exception review" for event in events)
    assert any(event.actor == "ai" and event.action == "Prepared underwriting recommendation" for event in events)


def test_missing_pdf_pause_accepts_upload_and_rechecks_inventory():
    orchestrator = build_underwriting_orchestrator(GUIDELINES)
    thread_config = config("missing-appraisal")
    paused = orchestrator.invoke(
        input_for("LOAN-001", exclude="appraisal.pdf"),
        config=thread_config,
    )

    payload = paused["__interrupt__"][0].value
    assert payload["type"] == "missing_documents"
    assert payload["missing_document_types"] == ["appraisal"]

    resumed = orchestrator.invoke(
        Command(
            resume={
                "document_paths": [str(PDF_ROOT / "LOAN-001" / "appraisal.pdf")]
            }
        ),
        config=thread_config,
    )

    assert resumed["requirements"].complete is True
    assert resumed["review_package"].review_disposition == "standard_human_review"
    assert any(
        event.actor == "human" and event.action == "Uploaded requested evidence"
        for event in resumed["review_package"].observability_log
    )


def test_missing_internal_evidence_pauses_with_exact_requirement():
    orchestrator = build_underwriting_orchestrator(GUIDELINES)
    paused = orchestrator.invoke(input_for("LOAN-006"), config=config("missing-pl"))

    payload = paused["__interrupt__"][0].value
    assert payload["type"] == "missing_documents"
    assert payload["missing_evidence"] == ["current_year_profit_and_loss_statement"]
