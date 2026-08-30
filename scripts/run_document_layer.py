#!/usr/bin/env python3
"""Run the Phase 2 document workflow against one synthetic loan package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from underwriting_agent.document_layer import build_document_workflow
from underwriting_agent.intake_packages import resolve_document_paths


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("loan_id", nargs="?", default="UW-26-0417-A")
    args = parser.parse_args()

    pdf_root = ROOT / "data" / "realistic_pdfs"
    paths = [str(path) for path in resolve_document_paths(pdf_root, args.loan_id)]
    if not paths:
        raise SystemExit(f"No PDFs found for {args.loan_id!r} under {pdf_root}")

    workflow = build_document_workflow()
    result = workflow.invoke(
        {
            "loan_id": args.loan_id,
            "document_paths": paths,
            "workflow_status": "INTAKE",
        }
    )

    requirements = result["requirements"].model_dump(mode="json")
    summary = {
        "loan_id": result["loan_id"],
        "workflow_status": result["workflow_status"],
        "documents": [
            {
                "file": document.source_path.name,
                "type": document.document_type,
                "document_id": document.document_id,
                "confidence": document.confidence,
                "warnings": document.warnings,
            }
            for document in result["parsed_documents"]
        ],
        "requirements": requirements,
    }
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
