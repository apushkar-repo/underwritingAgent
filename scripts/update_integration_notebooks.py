#!/usr/bin/env python3
"""Add optional OpenAI/Pinecone walkthroughs to the existing guided notebooks."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKER = "Optional production services: OpenAI and Pinecone"
REALISTIC_MARKER = "Realistic lender-style intake packages"


def markdown(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def code(text):
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": text.splitlines(keepends=True)}


def append_once(path: Path, cells):
    notebook = json.loads(path.read_text())
    if path.name == "1_Document_Layer_Phase2.ipynb" and any(
        "Phase 2: Realistic Mortgage Document Intake" in "".join(cell.get("source", []))
        for cell in notebook["cells"]
    ):
        return
    if any(MARKER in "".join(cell.get("source", [])) for cell in notebook["cells"]):
        return
    notebook["cells"].extend(cells)
    path.write_text(json.dumps(notebook, indent=1) + "\n", encoding="utf-8")


def add_realistic_phase2_walkthrough(path: Path):
    """Replace the complete realistic-PDF lesson before optional services."""
    notebook = json.loads(path.read_text())
    if any(
        "Phase 2: Realistic Mortgage Document Intake" in "".join(cell.get("source", []))
        for cell in notebook["cells"]
    ):
        return
    optional_index = next(
        (index for index, cell in enumerate(notebook["cells"])
         if MARKER in "".join(cell.get("source", []))),
        len(notebook["cells"]),
    )
    realistic_index = next(
        (index for index, cell in enumerate(notebook["cells"])
         if REALISTIC_MARKER in "".join(cell.get("source", []))),
        None,
    )
    if realistic_index is None:
        insertion_index = optional_index
    else:
        # The optional-services heading is the explicit end boundary. Replacing
        # this complete slice repairs partially saved or manually edited cells.
        del notebook["cells"][realistic_index:optional_index]
        insertion_index = realistic_index
    cells = [
        markdown(f"""## 10. {REALISTIC_MARKER}

The curated PDFs above are controlled fixtures: every document uses predictable labels, includes a canonical `Loan Id`, and has a known expected result. That makes them ideal for unit tests but not a fair simulation of lender intake.

`data/realistic_pdfs` is a separate **uncurated evaluation set**. It uses vendor-style filenames, boxed W-2 fields, a four-page tax filing, six-page purchase agreements, narrative wording, masked identifiers, and intentionally ambiguous or missing evidence. There is no gold-results file exposed to the agent.

This section uses the Hayes broker upload because it contains a self-employed tax return, a large deposit, a low appraisal, and no current-year P&L."""),
        code('''# Discover a package without assuming that filenames identify document types.
REALISTIC_PDF_ROOT = PROJECT_ROOT / "data" / "realistic_pdfs"
realistic_package = REALISTIC_PDF_ROOT / "broker_upload_hayes_0821"
realistic_paths = sorted(realistic_package.glob("*.pdf"))
realistic_reference = "BRK-90831"  # Intake-system reference, not a trusted extracted fact.

for path in realistic_paths:
    intake = extract_pdf(path)
    print(f"{path.name:34} pages={intake.page_count}  characters={len(intake.text):,}")
'''),
        markdown("""### 10.1 Establish an honest deterministic baseline

The original classifier looks for exact phrases emitted by the curated PDF generator. Running it here is intentionally instructive: a result of `UNKNOWN` or low confidence is not a notebook failure. It proves that fixed keyword signatures do not generalize to real document layouts.

Do not keep adding filename rules until this package passes. That would overfit the evaluation set and silently fail on the next lender's documents."""),
        code('''# Measure the existing classifier; do not trust filenames to correct its answers.
baseline_rows = []
for path in realistic_paths:
    intake = extract_pdf(path)
    document_type, confidence = classify_document(intake.text)
    baseline_rows.append({
        "file": path.name,
        "pages": intake.page_count,
        "predicted_type": document_type.value,
        "confidence": round(confidence, 2),
    })

baseline_rows
'''),
        markdown("""### 10.2 What Phase 2 must do for realistic documents

For production-style intake, Phase 2 needs the following boundary:

1. **Read every page.** `pypdf` handles searchable text; scanned pages need OCR before interpretation.
2. **Classify from content.** A filename is metadata, never proof of document type.
3. **Extract only stated facts.** Preserve missing and conflicting values instead of guessing.
4. **Attach provenance.** Every extracted fact should ultimately retain its file and page reference.
5. **Validate the package deterministically.** The model interprets documents, while typed Python checks required categories and blocking evidence.

The current `OpenAIDocumentInterpreter` implements the content-classification and structured-extraction boundary. The requirement node remains deterministic. A future enhancement should add page-level citations to each extracted field, not merely the source file path."""),
        code('''# Preview representative source text before sending anything to a model.
# Limiting output keeps account numbers and long contract boilerplate out of notebook logs.
tax_return = extract_pdf(realistic_package / "2025_1040_with_Schedule_C.pdf")
purchase_agreement = extract_pdf(realistic_package / "purchase_agreement_v3.pdf")

print("TAX RETURN PREVIEW")
print(tax_return.text[:900])
print("\\nPURCHASE AGREEMENT PREVIEW")
print(purchase_agreement.text[:900])
'''),
        markdown("""### 10.3 Run model-assisted interpretation when enabled

This cell makes up to six model requests, one per document, only when `USE_OPENAI_DOCUMENT_MODEL=true` in `.env`. The model returns the same typed `ParsedDocument` objects used by the offline graph; it does not calculate DTI/LTV or approve the loan.

The intake reference is supplied by the surrounding loan-origination system. It is intentionally kept separate from facts extracted from the documents."""),
        code('''# Run the realistic package through structured model interpretation only when opted in.
import os
from dotenv import load_dotenv
from underwriting_agent.model_services import OpenAIDocumentInterpreter

load_dotenv(PROJECT_ROOT / ".env", override=False)
use_document_model = os.getenv("USE_OPENAI_DOCUMENT_MODEL", "false").lower() == "true"

if use_document_model:
    interpreter = OpenAIDocumentInterpreter(os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    realistic_workflow = build_document_workflow(document_interpreter=interpreter)
    realistic_result = realistic_workflow.invoke({
        "loan_id": realistic_reference,
        "document_paths": [str(path) for path in realistic_paths],
        "workflow_status": "INTAKE",
    })
    print("Final status:", realistic_result["workflow_status"])
    for document in realistic_result["parsed_documents"]:
        print(document.source_path.name, "->", document.document_type.value,
              "warnings=", document.warnings)
    display(realistic_result["requirements"].model_dump(mode="json"))
else:
    print("Model run skipped. Set USE_OPENAI_DOCUMENT_MODEL=true in .env to enable it.")
'''),
    ]
    notebook["cells"][insertion_index:insertion_index] = cells

    # The handoff belongs at the end of the lesson, after both the realistic
    # exercise and the optional production-service explanation.
    boundary_index = next(
        (index for index, cell in enumerate(notebook["cells"])
         if "Phase 2 boundary and next step" in "".join(cell.get("source", []))),
        None,
    )
    if boundary_index is not None:
        boundary = notebook["cells"].pop(boundary_index)
        boundary["source"] = "".join(boundary["source"]).replace(
            "## 10. Phase 2 boundary and next step",
            "## 11. Phase 2 boundary and next step",
        ).splitlines(keepends=True)
        notebook["cells"].append(boundary)
    path.write_text(json.dumps(notebook, indent=1) + "\n", encoding="utf-8")


append_once(ROOT / "1_Document_Layer_Phase2.ipynb", [
    markdown(f"""## {MARKER}

Real lender PDFs vary in layout and terminology, so deterministic signatures will eventually be insufficient. `OpenAIDocumentInterpreter` sends extracted PDF text to a chat model configured with strict Pydantic structured output. The model may classify and extract explicitly stated facts, but it is instructed not to calculate ratios or make lending decisions.

The service is optional. Keep `USE_OPENAI_DOCUMENT_MODEL=false` for deterministic fixtures and tests. Model output still becomes the same validated `ParsedDocument` contract used by every downstream phase."""),
    code('''# This cell is safe when no API key is configured; it explains which backend is active.
import os
from dotenv import load_dotenv
from underwriting_agent.model_services import OpenAIDocumentInterpreter

load_dotenv(PROJECT_ROOT / ".env", override=False)
if os.getenv("USE_OPENAI_DOCUMENT_MODEL", "false").lower() == "true":
    interpreter = OpenAIDocumentInterpreter(os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    model_document_workflow = build_document_workflow(document_interpreter=interpreter)
    print("OpenAI structured document interpretation enabled")
else:
    print("Deterministic document interpretation enabled (offline default)")
'''),
])

add_realistic_phase2_walkthrough(ROOT / "1_Document_Layer_Phase2.ipynb")

for name in [
    "2_Borrower_Analysis_Phase3.ipynb",
    "3_Property_Analysis_Phase4.ipynb",
    "5_Reconciliation_and_Exceptions_Phase6.ipynb",
]:
    append_once(ROOT / name, [
        markdown(f"""## {MARKER}

This phase intentionally remains deterministic. An OpenAI model may normalize messy source documents in Phase 2 and draft reviewer-facing prose in Phase 7, while borrower routing, income selection, asset exclusion, appraisal comparison, reconciliation, and exception rules remain typed Python logic. Pinecone is used only for guideline retrieval in Phase 5."""),
    ])

append_once(ROOT / "4_Calculations_and_Policy_Phase5.ipynb", [
    markdown(f"""## {MARKER}

The local hashing store remains the offline test backend. In production, `PineconeGuidelineVectorStore` uses OpenAI `text-embedding-3-small` vectors and persists them in a Pinecone serverless dense index. Index dimensions must match the embedding dimensions. Rule text and filterable metadata are upserted under stable `rule_id` values.

Pinecone performs storage and similarity search; it does not generate answers or enforce thresholds. Deterministic code still selects applicable rule IDs and calculates DTI/LTV."""),
    code('''# Configure .env before enabling this cell's production path.
import os
from dotenv import load_dotenv
from underwriting_agent.integrations import build_integrations_from_env

load_dotenv(PROJECT_ROOT / ".env", override=False)
if os.getenv("GUIDELINE_VECTOR_BACKEND", "local").lower() == "pinecone":
    integrations = build_integrations_from_env(GUIDELINES, dotenv_path=PROJECT_ROOT / ".env")
    pinecone_phase5 = build_calculation_policy_workflow(GUIDELINES, store=integrations.guideline_store)
    print("Pinecone guideline retrieval enabled")
else:
    print("Local guideline vector store enabled (offline default)")
'''),
])

append_once(ROOT / "6_Underwriting_Summary_Phase7.ipynb", [
    markdown(f"""## {MARKER}

`OpenAIReviewNarrator` can turn already-verified facts, retrieved rule IDs, exceptions, and conditions into clearer prose using strict structured output. It cannot add facts, perform calculations, or make an approval/denial recommendation. The deterministic summary remains the offline default and the structured review package remains the UI contract."""),
    code('''import os
from dotenv import load_dotenv
from underwriting_agent.model_services import OpenAIReviewNarrator
from underwriting_agent.summary import build_summary_workflow

load_dotenv(PROJECT_ROOT / ".env", override=False)
if os.getenv("USE_OPENAI_REVIEW_NARRATOR", "false").lower() == "true":
    narrator = OpenAIReviewNarrator(os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    model_summary_workflow = build_summary_workflow(narrator=narrator)
    print("OpenAI review narrative enabled")
else:
    print("Deterministic review narrative enabled (offline default)")
'''),
])

append_once(ROOT / "7_Underwriting_Orchestrator.ipynb", [
    markdown(f"""## {MARKER}

The parent graph accepts four injected service seams:

- `document_interpreter`: optional OpenAI structured extraction in Phase 2;
- `guideline_store`: optional Pinecone + OpenAI embeddings in Phase 5;
- `review_narrator`: optional OpenAI structured narrative in Phase 7;
- `property_research_service`: optional address-only You.com research in Phase 4B.

If environment flags are off, every seam falls back to deterministic local behavior. SQLite is intentionally not added; the notebook continues to use `InMemorySaver`."""),
    code('''# Build the parent graph from environment-selected services.
from underwriting_agent.integrations import build_integrations_from_env

integrations = build_integrations_from_env(GUIDELINES, dotenv_path=PROJECT_ROOT / ".env")
service_orchestrator = build_underwriting_orchestrator(
    GUIDELINES,
    document_interpreter=integrations.document_interpreter,
    guideline_store=integrations.guideline_store,
    review_narrator=integrations.review_narrator,
    property_research_service=integrations.property_research_service,
)
print("Document model:", type(integrations.document_interpreter).__name__ if integrations.document_interpreter else "deterministic")
print("Guideline store:", type(integrations.guideline_store).__name__ if integrations.guideline_store else "local")
print("Review narrator:", type(integrations.review_narrator).__name__ if integrations.review_narrator else "deterministic")
print("Property research:", type(integrations.property_research_service).__name__ if integrations.property_research_service else "disabled")
'''),
])

print("Updated notebooks with optional OpenAI and Pinecone sections")
