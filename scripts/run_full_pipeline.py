#!/usr/bin/env python3
"""Run the synthetic underwriting workflow through the Phase 7 review package."""

import argparse
import json
from pathlib import Path

from underwriting_agent.pipeline import run_underwriting_pipeline
from underwriting_agent.integrations import build_integrations_from_env


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
    guideline_path = ROOT / "data" / "underwriting_guidelines.jsonl"
    integrations = (
        build_integrations_from_env(guideline_path, dotenv_path=ROOT / ".env")
        if args.services_from_env else None
    )
    result = run_underwriting_pipeline(
        args.loan_id.upper(),
        ROOT / "data" / "realistic_pdfs",
        guideline_path,
        document_interpreter=integrations.document_interpreter if integrations else None,
        guideline_store=integrations.guideline_store if integrations else None,
        review_narrator=integrations.review_narrator if integrations else None,
        property_research_service=(
            integrations.property_research_service if integrations else None
        ),
    )
    print(json.dumps(result["review_package"].model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
