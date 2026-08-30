#!/usr/bin/env python3
"""Run the checkpointed parent orchestrator and display interrupt payloads."""

import argparse
import json
from pathlib import Path

from underwriting_agent.orchestrator import build_underwriting_orchestrator
from underwriting_agent.integrations import build_integrations_from_env
from underwriting_agent.intake_packages import resolve_document_paths


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("loan_id", nargs="?", default="UW-26-0417-A")
    parser.add_argument(
        "--services-from-env",
        action="store_true",
        help="Enable optional OpenAI, Pinecone, and You.com services from .env",
    )
    args = parser.parse_args()
    loan_id = args.loan_id.upper()
    guideline_path = ROOT / "data" / "underwriting_guidelines.jsonl"
    integrations = (
        build_integrations_from_env(guideline_path, dotenv_path=ROOT / ".env")
        if args.services_from_env
        else None
    )
    orchestrator = build_underwriting_orchestrator(
        guideline_path,
        document_interpreter=integrations.document_interpreter if integrations else None,
        guideline_store=integrations.guideline_store if integrations else None,
        review_narrator=integrations.review_narrator if integrations else None,
        property_research_service=(
            integrations.property_research_service if integrations else None
        ),
    )
    paths = resolve_document_paths(ROOT / "data" / "realistic_pdfs", loan_id)
    result = orchestrator.invoke(
        {
            "loan_id": loan_id,
            "document_paths": [str(path) for path in paths],
            "workflow_status": "INTAKE",
        },
        config={"configurable": {"thread_id": f"cli-{loan_id}"}},
    )
    if "__interrupt__" in result:
        print(json.dumps(result["__interrupt__"][0].value, indent=2))
    else:
        print(json.dumps(result["review_package"].model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
