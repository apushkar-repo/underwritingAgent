#!/usr/bin/env python3
"""Generate the Phase 2 notebook with realistic PDFs as its primary input."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "1_Document_Layer_Phase2.ipynb"


def markdown(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def code(text: str) -> dict:
    return {
        "cell_type": "code", "execution_count": None, "metadata": {},
        "outputs": [], "source": text.splitlines(keepends=True),
    }


cells = [
    markdown("""# Phase 2: Realistic Mortgage Document Intake

This notebook builds the document layer using the lender-style packages in `data/realistic_pdfs`. These PDFs have varied filenames and layouts, multi-page tax returns and contracts, masked identifiers, narrative wording, and incomplete or ambiguous evidence.

Phase 2 does not approve or deny a loan. It converts uploaded documents into a typed, reviewable package for later agents.

```text
PDF upload → text extraction → document interpretation → requirement validation
```

The compact PDFs in `data/pdfs` are retained only as deterministic regression fixtures. They are not the primary inputs in this notebook."""),
    markdown("""## 1. Environment setup

Select the repository `.venv` as the Jupyter kernel. If dependencies have not been installed, run `uv sync` in a terminal from the project root."""),
    code('''# Locate the repository and expose its src-layout package to this kernel.
from pathlib import Path
import json
import os
import sys

candidate_roots = [
    Path.cwd(),
    Path.cwd() / "underwritingAgent",
    Path.cwd().parent / "underwritingAgent",
]
PROJECT_ROOT = next(
    path.resolve() for path in candidate_roots if (path / "pyproject.toml").exists()
)
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Realistic PDFs are the notebook's primary input.
PDF_ROOT = PROJECT_ROOT / "data" / "realistic_pdfs"
CURATED_PDF_ROOT = PROJECT_ROOT / "data" / "pdfs"
print("Project:", PROJECT_ROOT)
print("Primary PDF input:", PDF_ROOT)
'''),
    code('''# Import the core Phase 2 contracts and nodes.
# The optional OpenAI service is imported later only when it is enabled.
from dotenv import load_dotenv
from underwriting_agent.models import DocumentLayerState, DocumentType
from underwriting_agent.document_layer import (
    build_document_workflow,
    check_requirements_node,
    classify_document,
    extract_key_fields,
    extract_pdf,
    intake_documents_node,
)

load_dotenv(PROJECT_ROOT / ".env", override=False)
'''),
    markdown("""## 2. Select an uncurated intake package

The manifest represents metadata supplied by an upload or loan-origination system. `document_type_hint` is included for evaluation, but the agent will not use it as input. In production, filenames and uploader labels are helpful clues—not trusted evidence.

We start with the Hayes broker package because it contains:

- a four-page Form 1040 and Schedule C;
- a six-page purchase agreement;
- a large business-related deposit;
- an appraised value below the purchase price; and
- no current-year profit-and-loss statement."""),
    code('''# Read package metadata and select one realistic upload folder.
manifest = json.loads((PDF_ROOT / "manifest.json").read_text())
for package in manifest["packages"]:
    print(package["intake_reference"], "->", package["folder"])

selected = next(
    package for package in manifest["packages"]
    if package["intake_reference"] == "BRK-90831"
)
intake_reference = selected["intake_reference"]
package_dir = PDF_ROOT / selected["folder"]
document_paths = sorted(package_dir.glob("*.pdf"))

print("\\nSelected:", intake_reference)
for path in document_paths:
    print(f"{path.name:36} {path.stat().st_size:>8,} bytes")
'''),
    markdown("""## 3. Intake: PDF pages to searchable text

`extract_pdf` uses `pypdf` to read every page and returns an `IntakeDocument`. It retains the source path, page count, extracted text, and any extraction error.

These samples contain searchable text. An image-only scan would produce little or no text and must be sent through OCR before document interpretation."""),
    code('''# Extract every realistic document without classifying it yet.
intake_documents = [extract_pdf(path) for path in document_paths]
for document in intake_documents:
    print(
        f"{document.file_name:36} pages={document.page_count:<2} "
        f"characters={len(document.text):>6,} error={document.extraction_error}"
    )
'''),
    code('''# Inspect a multi-page tax return and long contract.
tax_return = next(doc for doc in intake_documents if "1040" in doc.file_name)
purchase_agreement = next(doc for doc in intake_documents if "agreement" in doc.file_name)

print("TAX RETURN - first 1,000 extracted characters")
print(tax_return.text[:1000])
print("\\nPURCHASE AGREEMENT - first 1,000 extracted characters")
print(purchase_agreement.text[:1000])
'''),
    markdown("""## 4. Deterministic normalization for known sample layouts

The offline adapter recognizes the known layouts in this synthetic portfolio and normalizes their important fields. This makes the notebooks reproducible without sending financial documents to an external service.

This is still a deterministic baseline, not a universal mortgage-document parser. New lenders, changed forms, handwriting, and image-only scans require OCR plus model-assisted interpretation or a maintained document-processing service. Filenames must never be treated as proof of document type."""),
    code('''# Inspect deterministic classification of the known realistic layouts.
baseline = []
for document in intake_documents:
    document_type, confidence = classify_document(document.text)
    baseline.append({
        "file": document.file_name,
        "pages": document.page_count,
        "predicted_type": document_type.value,
        "confidence": round(confidence, 2),
    })

baseline
'''),
    markdown("""## 5. Model-assisted structured interpretation

For realistic documents, `OpenAIDocumentInterpreter` reads extracted text and returns a validated Pydantic result containing:

- controlled document type;
- loan or intake identifier when explicitly present;
- document identifier when explicitly present;
- borrower employment type;
- missing-evidence indicators; and
- warnings.

The model interprets text; it does not calculate DTI/LTV, apply policy thresholds, or make a lending decision. Set the following in `.env` to enable this section:

```env
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-4o-mini
USE_OPENAI_DOCUMENT_MODEL=true
```"""),
    code('''# Construct the appropriate workflow without making a model call yet.
use_document_model = os.getenv("USE_OPENAI_DOCUMENT_MODEL", "false").lower() == "true"

if use_document_model:
    # Import lazily so optional model dependencies cannot block offline intake.
    from underwriting_agent.model_services import OpenAIDocumentInterpreter
    interpreter = OpenAIDocumentInterpreter(os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    document_workflow = build_document_workflow(document_interpreter=interpreter)
    print("Backend: OpenAI structured document interpretation")
else:
    interpreter = None
    document_workflow = None
    print("Model workflow disabled. Enable USE_OPENAI_DOCUMENT_MODEL in .env.")
'''),
    markdown("""## 6. Shared state and LangGraph execution

The intake-system reference is supplied separately from extracted document facts. It ties the uploaded files to a workflow without pretending that every document prints the same loan ID.

```text
START
  ↓
document_intake
  ↓
classify_and_extract  ← structured model for realistic layouts
  ↓
check_requirements    ← deterministic Python validation
  ↓
END
```"""),
    code('''# This is the typed envelope sent into Phase 2.
initial_state: DocumentLayerState = {
    "loan_id": intake_reference,
    "document_paths": [str(path) for path in document_paths],
    "workflow_status": "INTAKE",
}

# Run only after the user explicitly enables model usage in .env.
if document_workflow is not None:
    realistic_result = document_workflow.invoke(initial_state)
    print("Final status:", realistic_result["workflow_status"])
    for document in realistic_result["parsed_documents"]:
        print(
            f"{document.source_path.name:36} -> {document.document_type.value:20} "
            f"warnings={document.warnings}"
        )
else:
    realistic_result = None
    print("Skipped model calls; PDF intake and baseline cells remain runnable offline.")
'''),
    markdown("""## 7. Deterministic requirement validation

After model interpretation, ordinary Python checks whether all required document categories were received and whether blocking evidence is missing. This separation is important:

- the model handles varied language and layouts;
- typed models constrain its output;
- deterministic code applies the document requirement matrix;
- a human underwriter reviews unresolved warnings and exceptions."""),
    code('''# Inspect the stable requirement contract returned by the graph.
if realistic_result is not None:
    requirements = realistic_result["requirements"]
    display(requirements.model_dump(mode="json"))
else:
    print("Requirement results will appear after model-assisted interpretation runs.")
'''),
    markdown("""## 8. Provenance and current limitations

The current `ParsedDocument` retains its source PDF path, which provides document-level provenance. Before production use, Phase 2 should be extended with:

1. OCR for image-only pages;
2. page-level citations for every material extracted fact;
3. confidence and warning review thresholds;
4. duplicate and superseded-document detection;
5. password-protected and corrupted-file handling;
6. malware scanning before parsing; and
7. sensitive-data controls for logs and model requests.

The model should never invent a value to make a package appear complete. Missing and conflicting evidence must remain visible."""),
    markdown("""## 9. Curated fixtures are still useful—but only for tests

`data/pdfs/LOAN-*` remains valuable for fast offline tests of graph wiring, state updates, and known exceptions. Production behavior should not be judged by performance on those predictable documents.

Use the two datasets for different purposes:

| Dataset | Purpose |
|---|---|
| `data/realistic_pdfs` | Notebook exploration and model-based evaluation |
| `data/pdfs` | Deterministic regression and unit tests |"""),
    code('''# Optional offline smoke test using one curated package.
curated_paths = sorted((CURATED_PDF_ROOT / "LOAN-001").glob("*.pdf"))
curated_workflow = build_document_workflow()
curated_result = curated_workflow.invoke({
    "loan_id": "LOAN-001",
    "document_paths": [str(path) for path in curated_paths],
    "workflow_status": "INTAKE",
})
print("Curated regression status:", curated_result["workflow_status"])
'''),
    markdown("""## 10. Phase 2 handoff

Phase 2 produces a stable package for the borrower-analysis phase:

- extracted documents retain source provenance;
- recognizable document types use a controlled enum;
- missing evidence remains explicit;
- complete packages move to `VERIFICATION`;
- incomplete or unreadable packages move to `NEEDS_DOCUMENTS`;
- final lending decisions remain with a qualified human underwriter.

The next implementation improvement should be page-level evidence citations, followed by OCR support for true scanned documents."""),
]


notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "underwritingAgent (.venv)", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

OUTPUT.write_text(json.dumps(notebook, indent=1) + "\n", encoding="utf-8")
print(f"Generated {OUTPUT} with {len(cells)} cells")
