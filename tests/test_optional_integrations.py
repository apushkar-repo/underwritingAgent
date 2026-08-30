from pathlib import Path
from types import SimpleNamespace

from underwriting_agent.calculations_policy import PineconeGuidelineVectorStore
from underwriting_agent.document_layer import classify_and_extract_with_model_node
from underwriting_agent.models import (
    DocumentType,
    IntakeDocument,
    ModelDocumentExtraction,
    ModelReviewNarrative,
)
from underwriting_agent.pipeline import run_underwriting_pipeline


ROOT = Path(__file__).resolve().parents[1]


class FakeDocumentInterpreter:
    def extract(self, document):
        return ModelDocumentExtraction(
            document_type=DocumentType.LOAN_APPLICATION,
            loan_id="LOAN-MODEL",
            document_id="APP-MODEL",
            borrower_employment_type="salaried",
        )


class FakeNarrator:
    def draft(self, state):
        return ModelReviewNarrative(
            executive_summary="Model-assisted wording based only on verified synthetic facts.",
            reviewer_focus=["Confirm cited evidence."],
        )


class FakeEmbeddings:
    def embed_query(self, query):
        return [0.1, 0.2]


class FakePineconeIndex:
    def query(self, **kwargs):
        rule_json = (ROOT / "data" / "underwriting_guidelines.jsonl").read_text().splitlines()[0]
        return SimpleNamespace(
            matches=[SimpleNamespace(metadata={"rule_json": rule_json}, score=0.87)]
        )


def test_model_document_output_maps_to_existing_parsed_contract():
    document = IntakeDocument(
        source_path=Path("application.pdf"),
        file_name="application.pdf",
        page_count=1,
        text="unstructured test text",
    )
    update = classify_and_extract_with_model_node(
        {"intake_documents": [document]}, FakeDocumentInterpreter()
    )

    parsed = update["parsed_documents"][0]
    assert parsed.document_type is DocumentType.LOAN_APPLICATION
    assert parsed.loan_id == "LOAN-MODEL"
    assert parsed.document_id == "APP-MODEL"


def test_pinecone_adapter_reconstructs_validated_policy_rule():
    store = PineconeGuidelineVectorStore(
        FakePineconeIndex(), FakeEmbeddings(), namespace="test", rule_count=1
    )
    results = store.search("income mismatch", k=1, categories={"income"})

    assert results[0].rule_id == "UW-INC-001"
    assert results[0].similarity_score == 0.87


def test_injected_model_narrator_only_changes_narrative_fields():
    result = run_underwriting_pipeline(
        "LOAN-001",
        ROOT / "data" / "pdfs",
        ROOT / "data" / "underwriting_guidelines.jsonl",
        review_narrator=FakeNarrator(),
    )
    package = result["review_package"]

    assert package.executive_summary.startswith("Model-assisted wording")
    assert package.reviewer_focus == ["Confirm cited evidence."]
    assert package.applicable_rule_ids == ["UW-DTI-001", "UW-LTV-001"]
    assert package.review_disposition == "standard_human_review"
