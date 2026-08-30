#!/usr/bin/env python3
"""Generate the notebook-first Phase 4B You.com property-research lesson."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def markdown(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def code(text):
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": text.splitlines(keepends=True)}


cells = [
    markdown("""# Phase 4B: Cited Property Web Research with You.com

This optional subgraph researches the subject property after the appraisal review. It sends only the property address to You.com and returns cited public-web observations for a human underwriter.

```text
PropertyAnalysis → address-only You.com search → cited PropertyResearchResult
```

Online estimates and reported sale history are reviewer context. They never replace the appraisal or change the LTV denominator."""),
    code('''from pathlib import Path
import os
import sys

candidates = [Path.cwd(), Path.cwd() / "underwritingAgent", Path.cwd().parent / "underwritingAgent"]
PROJECT_ROOT = next(path.resolve() for path in candidates if (path / "pyproject.toml").exists())
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

PDF_ROOT = PROJECT_ROOT / "data" / "realistic_pdfs"
'''),
    markdown("""## 1. Build the Phase 4 state

The address comes from normalized contract/appraisal evidence. Borrower names, income, credit, account numbers, and loan identifiers are not sent to the search provider."""),
    code('''from underwriting_agent.document_layer import build_document_workflow
from underwriting_agent.borrower_analysis import build_borrower_workflow
from underwriting_agent.property_analysis import build_property_workflow
from underwriting_agent.intake_packages import resolve_document_paths

reference = "UW-26-0417-A"
paths = resolve_document_paths(PDF_ROOT, reference)
state = build_document_workflow().invoke({
    "loan_id": reference,
    "document_paths": [str(path) for path in paths],
    "workflow_status": "INTAKE",
})
state = build_borrower_workflow().invoke(state)
state = build_property_workflow().invoke(state)
state["property_analysis"].model_dump(mode="json")
'''),
    markdown("""## 2. Test normalization without an internet call

Unit tests and this default notebook path use a fake search client. This keeps results reproducible while exercising source tiers, citations, value observations, and discrepancy detection."""),
    code('''from underwriting_agent.models import WebEvidenceSource
from underwriting_agent.property_research import YouComPropertyResearchService

class FakeSearchClient:
    def search(self, query):
        return [WebEvidenceSource(
            url="https://county.example.gov/property/1847-larkspur",
            title="Recorded property transfer",
            excerpt="Public record reports the property sold in 2024 for $275,000.",
            domain="county.example.gov",
            query=query,
            source_tier=1,
        )]

offline_service = YouComPropertyResearchService(
    FakeSearchClient(), variance_threshold_percent=10
)
offline_result = offline_service.research(
    state["property_analysis"].property_address,
    purchase_price=state["property_analysis"].purchase_price,
    appraised_value=state["property_analysis"].appraised_value,
)
offline_result.model_dump(mode="json")
'''),
    markdown("""## 3. Run the Phase 4B LangGraph subgraph"""),
    code('''from underwriting_agent.property_research import build_property_research_workflow

phase4b = build_property_research_workflow(service=offline_service)
researched_state = phase4b.invoke(state)
print(researched_state["workflow_status"])
print(researched_state["property_research"].discrepancies)
for source in researched_state["property_research"].sources:
    print(source.title, source.url, "tier", source.source_tier)
'''),
    markdown("""## 4. Optional live You.com search

Set these values in `.env` before running this cell:

```env
YDC_API_KEY=your-key
USE_PROPERTY_WEB_RESEARCH=true
```

The service makes three searches: assessor/sale history, sold/listing history, and assessment/value estimates. Search failures are non-blocking and appear as warnings."""),
    code('''from dotenv import load_dotenv
from underwriting_agent.integrations import build_integrations_from_env

load_dotenv(PROJECT_ROOT / ".env", override=False)
if os.getenv("USE_PROPERTY_WEB_RESEARCH", "false").casefold() == "true":
    integrations = build_integrations_from_env(
        PROJECT_ROOT / "data" / "underwriting_guidelines.jsonl",
        dotenv_path=PROJECT_ROOT / ".env",
    )
    live_phase4b = build_property_research_workflow(
        service=integrations.property_research_service
    )
    live_result = live_phase4b.invoke(state)["property_research"]
    print("Status:", live_result.research_status)
    for source in live_result.sources:
        print(source.title, source.url)
else:
    print("Live You.com research disabled; no internet request was made.")
'''),
    markdown("""## 5. Underwriting boundary

Phase 6 may convert a material cited discrepancy into `EXTERNAL_VALUE_VARIANCE`. The final review package includes the complete `external_property_research` object and URLs. The finding requires human verification and does not modify purchase price, appraisal value, DTI, LTV, or eligibility."""),
]

notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "underwritingAgent (.venv)", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.13"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}
(ROOT / "3B_Property_Web_Research.ipynb").write_text(
    json.dumps(notebook, indent=1) + "\n", encoding="utf-8"
)
print("Generated 3B_Property_Web_Research.ipynb")
