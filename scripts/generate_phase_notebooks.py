#!/usr/bin/env python3
"""Generate the guided notebook-first walkthroughs for underwriting Phases 4-7."""

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def markdown(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def code(text):
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": text.splitlines(keepends=True)}


def write_notebook(name, cells):
    payload = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "underwritingAgent (.venv)", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.13"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    (ROOT / name).write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")


SETUP = '''# Locate the src-layout project and import the completed earlier phases.
from pathlib import Path
import sys

candidates = [Path.cwd(), Path.cwd() / "underwritingAgent", Path.cwd().parent / "underwritingAgent"]
PROJECT_ROOT = next(path.resolve() for path in candidates if (path / "pyproject.toml").exists())
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

PDF_ROOT = PROJECT_ROOT / "data" / "realistic_pdfs"
GUIDELINES = PROJECT_ROOT / "data" / "underwriting_guidelines.jsonl"
INTAKE_REFERENCES = ["UW-26-0417-A", "BRK-90831", "WHL-77-2206"]
print(PROJECT_ROOT)
'''


PRIOR_STATE = '''from underwriting_agent.document_layer import build_document_workflow
from underwriting_agent.borrower_analysis import build_borrower_workflow
from underwriting_agent.intake_packages import resolve_document_paths

def through_phase_3(loan_id):
    paths = resolve_document_paths(PDF_ROOT, loan_id)
    state = build_document_workflow().invoke({
        "loan_id": loan_id,
        "document_paths": [str(path) for path in paths],
        "workflow_status": "INTAKE",
    })
    return build_borrower_workflow().invoke(state)
'''


write_notebook("2_Borrower_Analysis_Phase3.ipynb", [
    markdown("""# Phase 3: Borrower Financial Analysis

Phase 3 consumes canonical fields extracted from the lender-style documents in `data/realistic_pdfs`. It routes the borrower to an income specialist, verifies assets, and extracts recurring credit obligations.

```text
Phase 2 state → borrower routing → income specialist → assets → liabilities
```"""),
    code(SETUP),
    code(PRIOR_STATE),
    markdown("""## 1. Inspect the realistic Phase 2 handoff

The wage-earner package contains a W-2, bank statement, merged credit report, long contract, and appraisal. Phase 2 normalizes the different layouts once; Phase 3 consumes those fields."""),
    code('''paths = resolve_document_paths(PDF_ROOT, "UW-26-0417-A")
phase2_state = build_document_workflow().invoke({
    "loan_id": "UW-26-0417-A",
    "document_paths": [str(path) for path in paths],
    "workflow_status": "INTAKE",
})
for document in phase2_state["parsed_documents"]:
    print(document.document_type.value, document.extracted_fields)
'''),
    markdown("""## 2. Route the borrower

Employment type comes from application content. A conditional edge selects exactly one of the salaried, self-employed, mixed-income, or unsupported paths."""),
    code('''from underwriting_agent.borrower_analysis import classify_borrower_node, route_borrower

route_update = classify_borrower_node(phase2_state)
print(route_update)
print("Next node:", route_borrower({**phase2_state, **route_update}))
'''),
    markdown("""## 3. Run the complete Phase 3 subgraph"""),
    code('''phase3 = build_borrower_workflow()
result = phase3.invoke(phase2_state)
print(result["income_analysis"].model_dump(mode="json"))
print(result["asset_analysis"].model_dump(mode="json"))
print(result["liability_analysis"].model_dump(mode="json"))
'''),
    markdown("""## 4. Compare the three realistic packages"""),
    code('''portfolio = []
for reference in INTAKE_REFERENCES:
    result = through_phase_3(reference)
    portfolio.append({
        "intake_reference": reference,
        "borrower_path": result["borrower_path"].value,
        "qualifying_income": result["income_analysis"].qualifying_monthly_income,
        "verified_assets": result["asset_analysis"].verified_assets,
        "monthly_debt": result["liability_analysis"].total_monthly_debt,
        "exceptions": result["income_analysis"].exceptions + result["asset_analysis"].exceptions,
    })
portfolio
'''),
    markdown("""## Phase 3 handoff

Phase 4 receives typed income, asset, and liability analyses with document provenance. Missing evidence remains visible for orchestration and human review."""),
])


write_notebook("3_Property_Analysis_Phase4.ipynb", [
    markdown("""# Phase 4: Property and Appraisal Review

This notebook prototypes the collateral specialist. It reconciles the application loan amount, purchase contract price, and appraisal value. A low appraisal is a review exception—not an autonomous lending decision.

```text
Phase 3 state → appraisal_review → PropertyAnalysis
```"""),
    code(SETUP),
    code(PRIOR_STATE),
    markdown("""## 1. Inspect the three collateral evidence sources

The specialist keeps all three document IDs so every value in the later review package can be traced back to its source PDF."""),
    code('''from underwriting_agent.borrower_analysis import find_intake_document
from underwriting_agent.models import DocumentType

state = through_phase_3("BRK-90831")
for kind in [DocumentType.LOAN_APPLICATION, DocumentType.PURCHASE_CONTRACT, DocumentType.APPRAISAL]:
    parsed, intake = find_intake_document(state, kind)
    print(kind, parsed.document_id, intake.source_path.name)
'''),
    markdown("""## 2. Run the property subgraph

For a purchase, later LTV calculations must use the lower of contract price and appraised value."""),
    code('''from underwriting_agent.property_analysis import build_property_workflow

property_workflow = build_property_workflow()
result = property_workflow.invoke(state)
result["property_analysis"].model_dump(mode="json")
'''),
    markdown("""## 3. Evaluate all appraisals

The Hayes and Nguyen packages should report negative variance and `LOW_APPRAISAL`."""),
    code('''portfolio = []
for loan_id in INTAKE_REFERENCES:
    result = property_workflow.invoke(through_phase_3(loan_id))
    prop = result["property_analysis"]
    portfolio.append({"loan_id": loan_id, "purchase_price": prop.purchase_price, "appraised_value": prop.appraised_value, "variance": prop.value_variance, "exceptions": prop.exceptions})
portfolio
'''),
    markdown("""## Phase 4 handoff

The stable output is `PropertyAnalysis`. Phase 4B uses its address for isolated public-web research before Phase 5 calculates LTV."""),
])


write_notebook("4_Calculations_and_Policy_Phase5.ipynb", [
    markdown("""# Phase 5: Financial Calculations and Guideline Retrieval

This phase separates two responsibilities:

1. Deterministic functions calculate DTI and LTV.
2. A local vector store embeds and retrieves synthetic underwriting rules.

The vector store uses reproducible hashing embeddings rather than an external API. Text becomes a normalized numeric vector; cosine similarity compares a query vector with stored rule vectors. Raw vectors are never placed in the review package."""),
    code(SETUP),
    code(PRIOR_STATE + '''\nfrom underwriting_agent.property_analysis import build_property_workflow
from underwriting_agent.property_research import build_property_research_workflow

def through_phase_4(loan_id):
    state = build_property_workflow().invoke(through_phase_3(loan_id))
    return build_property_research_workflow().invoke(state)
'''),
    markdown("""## 1. Test the deterministic formulas in isolation"""),
    code('''from underwriting_agent.calculations_policy import calculate_dti, calculate_ltv

print("DTI:", calculate_dti(monthly_debt=2600, monthly_income=11000))
print("LTV:", calculate_ltv(loan_amount=440000, purchase_price=550000, appraised_value=500000))
'''),
    markdown("""## 2. Build and inspect the guideline vector store

At indexing time every rule is embedded once. At query time the query is embedded with the same function, then compared by cosine similarity."""),
    code('''from underwriting_agent.calculations_policy import LocalGuidelineVectorStore

store = LocalGuidelineVectorStore.from_jsonl(GUIDELINES)
print("Rules indexed:", len(store.rules))
print("Embedding dimensions:", len(store.vectors[0]))
[(rule.rule_id, rule.similarity_score) for rule in store.search("low appraisal and high loan to value", k=3)]
'''),
    markdown("""## 3. Run calculation and policy nodes as one subgraph"""),
    code('''from underwriting_agent.calculations_policy import build_calculation_policy_workflow

phase5 = build_calculation_policy_workflow(GUIDELINES)
result = phase5.invoke(through_phase_4("BRK-90831"))
print(result["calculations"].model_dump())
[(rule.rule_id, rule.similarity_score) for rule in result["retrieved_rules"]]
'''),
    markdown("""## 4. Evaluate all calculated ratios and retrieved rule IDs"""),
    code('''portfolio = []
for loan_id in INTAKE_REFERENCES:
    result = phase5.invoke(through_phase_4(loan_id))
    portfolio.append({"loan_id": loan_id, "dti": result["calculations"].dti_percent, "ltv": result["calculations"].ltv_percent, "rules": [rule.rule_id for rule in result["retrieved_rules"]]})
portfolio
'''),
    markdown("""## Phase 5 handoff

Phase 6 receives exact ratios plus retrieved rule objects. Rules retain IDs so every exception can cite policy provenance."""),
])


write_notebook("5_Reconciliation_and_Exceptions_Phase6.ipynb", [
    markdown("""# Phase 6: Evidence Reconciliation, Exceptions, and Conditions

Specialists can describe the same loan in different ways. This phase creates canonical facts, deduplicates exception codes, links findings to rule IDs, and proposes conditions for human review."""),
    code(SETUP),
    code('''from underwriting_agent.document_layer import build_document_workflow
from underwriting_agent.borrower_analysis import build_borrower_workflow
from underwriting_agent.property_analysis import build_property_workflow
from underwriting_agent.property_research import build_property_research_workflow
from underwriting_agent.calculations_policy import build_calculation_policy_workflow
from underwriting_agent.intake_packages import resolve_document_paths

def through_phase_5(loan_id):
    paths = resolve_document_paths(PDF_ROOT, loan_id)
    state = build_document_workflow().invoke({"loan_id": loan_id, "document_paths": [str(path) for path in paths], "workflow_status": "INTAKE"})
    state = build_borrower_workflow().invoke(state)
    state = build_property_workflow().invoke(state)
    state = build_property_research_workflow().invoke(state)
    return build_calculation_policy_workflow(GUIDELINES).invoke(state)
'''),
    markdown("""## 1. Reconcile specialist outputs into canonical facts

Each important fact carries source document IDs. Calculated facts have no source document because they are derived deterministically from other canonical facts."""),
    code('''from underwriting_agent.reconciliation import reconcile_facts_node

phase5_state = through_phase_5("WHL-77-2206")
facts_update = reconcile_facts_node(phase5_state)
[fact.model_dump(mode="json") for fact in facts_update["canonical_facts"]]
'''),
    markdown("""## 2. Normalize exceptions and create conditions"""),
    code('''from underwriting_agent.reconciliation import build_reconciliation_workflow

phase6 = build_reconciliation_workflow()
result = phase6.invoke(phase5_state)
print("Status:", result["workflow_status"])
print("Exceptions:")
for item in result["exceptions"]:
    print(" -", item.code, item.severity, item.rule_ids)
print("Conditions:")
for condition in result["conditions"]:
    print(" -", condition)
'''),
    markdown("""## 3. Compare clean, missing-document, and showcase cases"""),
    code('''comparison = []
for loan_id in INTAKE_REFERENCES:
    result = phase6.invoke(through_phase_5(loan_id))
    comparison.append({"loan_id": loan_id, "status": result["workflow_status"], "exceptions": [item.code for item in result["exceptions"]], "conditions": result["conditions"]})
comparison
'''),
    markdown("""## Phase 6 handoff

Phase 7 receives canonical facts, retrieved rules, normalized exceptions, and proposed conditions—all structured and traceable."""),
])


write_notebook("6_Underwriting_Summary_Phase7.ipynb", [
    markdown("""# Phase 7: Evidence-Backed Underwriting Review Package

The last phase converts structured workflow state into a package for a qualified human underwriter. It never returns `approved` or `denied`; it returns a recommendation, evidence, rules, exceptions, conditions, and an attributable activity log. The internal field remains `review_disposition` for API compatibility."""),
    code(SETUP),
    markdown("""## 1. Run the complete Phase 2→7 pipeline"""),
    code('''from underwriting_agent.pipeline import run_underwriting_pipeline

def run(loan_id):
    return run_underwriting_pipeline(loan_id, PDF_ROOT, GUIDELINES)

clean = run("UW-26-0417-A")
clean["review_package"].model_dump(mode="json")
'''),
    markdown("""## 2. Inspect the showcase review package

The Nguyen package combines mixed income, a deposit requiring documentation, and a low appraisal. The package escalates those facts; a human makes the final decision."""),
    code('''showcase = run("WHL-77-2206")["review_package"]
print(showcase.executive_summary)
print("\\nRules:", showcase.applicable_rule_ids)
print("\\nConditions:")
for condition in showcase.conditions:
    print(" -", condition)
print("\\n", showcase.disclaimer)
'''),
    markdown("""## 3. Evaluate final recommendations for all packages"""),
    code('''portfolio = []
for loan_id in INTAKE_REFERENCES:
    package = run(loan_id)["review_package"]
    portfolio.append({"intake_reference": loan_id, "recommendation": package.review_disposition, "exceptions": [item.code for item in package.exceptions], "human_review_required": package.human_review_required})
portfolio
'''),
    markdown("""## 4. Activity log and UI integration boundary

`observability_log` identifies each action as `ai` or `human`, including uploads and exception-review responses. `UnderwritingReviewPackage` is the Streamlit contract, so the UI renders facts, provenance, citations, conditions, research, and activity without parsing prose."""),
    code('''for event in showcase.observability_log:
    print(event.timestamp, event.actor, event.phase, "-", event.action)
'''),
])

write_notebook("7_Underwriting_Orchestrator.ipynb", [
    markdown("""# Underwriting Orchestrator: Composing Phases 2–7

The orchestrator is the parent LangGraph. Each completed phase is a compiled subgraph added as one node. The parent owns conditional routing, checkpoint persistence, missing-document interrupts, and exception-review interrupts.

```text
START → document_layer ── incomplete → request_missing_documents ─┐
                     └── complete → borrower_analysis             │
                                      ↓                           │
                               property_analysis                  │
                                      ↓                           │
                               property_research                  │
                                      ↓                           │
                           calculations_and_policy                │
                                      ↓                           │
                                reconciliation                    │
                               ↙               ↘                  │
                      exception_review       underwriting_summary │
                               ↓               ↓                  │
                      underwriting_summary → END                  │
                                      ↑___________________________┘
```

The final package is decision support. A qualified human underwriter retains the final lending decision."""),
    code(SETUP),
    markdown("""## 1. Compile the checkpointed parent graph

Subgraphs do not need their own checkpointers. LangGraph propagates the parent's checkpoint context into nested graphs. Every invocation and resume must use the same `thread_id`."""),
    code('''from underwriting_agent.orchestrator import build_underwriting_orchestrator

orchestrator = build_underwriting_orchestrator(GUIDELINES)
print(orchestrator.get_graph().draw_mermaid())
'''),
    code('''from underwriting_agent.intake_packages import resolve_document_paths

def initial_input(loan_id, exclude=None):
    paths = resolve_document_paths(PDF_ROOT, loan_id)
    if exclude:
        paths = [path for path in paths if path.name != exclude]
    return {"loan_id": loan_id, "document_paths": [str(path) for path in paths], "workflow_status": "INTAKE"}

def thread(thread_id):
    return {"configurable": {"thread_id": thread_id}}
'''),
    markdown("""## 2. Complete package: automatic analysis and review routing

The Moreno package contains every required document. It runs through all specialist subgraphs automatically, then pauses because its calculated LTV exceeds the demonstration guideline. Complete documents do not imply an approval."""),
    code('''complete = orchestrator.invoke(initial_input("UW-26-0417-A"), config=thread("notebook-complete"))
print(complete["__interrupt__"][0].value["type"])
print([item["code"] for item in complete["__interrupt__"][0].value["exceptions"]])
'''),
    markdown("""## 3. Missing-document pause and resume

We omit the appraisal from input. The graph checkpoints all progress and surfaces an interrupt. Supplying the missing PDF with `Command(resume=...)` restarts the interrupted node, loops back through document intake, and continues the same thread."""),
    code('''from langgraph.types import Command

missing_config = thread("notebook-missing-appraisal")
paused = orchestrator.invoke(initial_input("UW-26-0417-A", exclude="appraisal_1847_Larkspur.pdf"), config=missing_config)
paused["__interrupt__"][0].value
'''),
    code('''resumed = orchestrator.invoke(
    Command(resume={"document_paths": [str(next(path for path in resolve_document_paths(PDF_ROOT, "UW-26-0417-A") if path.name == "appraisal_1847_Larkspur.pdf"))]}),
    config=missing_config,
)
print(resumed["requirements"].complete)
print(resumed["workflow_status"])
'''),
    markdown("""## 4. Exception-review pause and resume

The showcase file progresses through every specialist, then pauses with canonical exceptions and proposed conditions. The reviewer may acknowledge them or request changes. This action is recorded in the final package; it is not a lending decision."""),
    code('''review_config = thread("notebook-exception-review")
paused = orchestrator.invoke(initial_input("WHL-77-2206"), config=review_config)
review_payload = paused["__interrupt__"][0].value
print(review_payload["type"])
print([item["code"] for item in review_payload["exceptions"]])
print(review_payload["conditions"])
'''),
    code('''reviewed = orchestrator.invoke(
    Command(resume={"action": "acknowledge", "reviewer": "Notebook Reviewer", "notes": "Reviewed synthetic evidence."}),
    config=review_config,
)
package = reviewed["review_package"]
print(package.review_disposition)
print(package.human_review)
for event in package.observability_log:
    print(event.actor, event.phase, event.action)
print(package.disclaimer)
'''),
    markdown("""## 5. Inspect persisted thread state

The latest checkpoint is suitable for a UI status page. A production deployment would replace `InMemorySaver` with a persistent database-backed checkpointer."""),
    code('''snapshot = orchestrator.get_state(review_config)
print(snapshot.values["loan_id"])
print(snapshot.values["workflow_status"])
print(snapshot.next)
'''),
    markdown("""## UI integration boundary

The Streamlit app starts a run with displayed PDF paths and a unique workflow `thread_id`. If `__interrupt__` is present, it renders the upload or review request and sends `Command(resume=...)` under the same thread. The final recommendation includes the human response and the AI-versus-human `observability_log`."""),
])

subprocess.run(
    [sys.executable, str(ROOT / "scripts" / "update_integration_notebooks.py")],
    check=True,
)
print("Generated Phase 4-7 and orchestrator notebooks")
