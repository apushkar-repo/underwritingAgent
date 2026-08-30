#!/usr/bin/env python3
"""Run Phase 2 and Phase 3 against one synthetic borrower package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from underwriting_agent.borrower_analysis import build_borrower_workflow
from underwriting_agent.document_layer import build_document_workflow
from underwriting_agent.intake_packages import resolve_document_paths


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("loan_id", nargs="?", default="UW-26-0417-A")
    args = parser.parse_args()
    loan_id = args.loan_id.upper()
    paths = resolve_document_paths(ROOT / "data" / "realistic_pdfs", loan_id)
    if not paths:
        raise SystemExit(f"No synthetic PDFs found for {loan_id}")

    document_state = build_document_workflow().invoke(
        {
            "loan_id": loan_id,
            "document_paths": [str(path) for path in paths],
            "workflow_status": "INTAKE",
        }
    )
    result = build_borrower_workflow().invoke(document_state)
    summary = {
        "loan_id": loan_id,
        "borrower_path": result["borrower_path"],
        "workflow_status": result["workflow_status"],
        "income": result["income_analysis"].model_dump(mode="json"),
        "assets": result["asset_analysis"].model_dump(mode="json"),
        "liabilities": result["liability_analysis"].model_dump(mode="json"),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
