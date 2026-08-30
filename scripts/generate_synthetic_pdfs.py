#!/usr/bin/env python3
"""Generate text-searchable synthetic mortgage PDFs from the JSONL fixtures."""

from __future__ import annotations

import json
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUTPUT_DIR = DATA_DIR / "pdfs"

DOCUMENT_SOURCES = {
    "loan_application": DATA_DIR / "loan_applications.jsonl",
    "income_documents": DATA_DIR / "income_documents.jsonl",
    "asset_statement": DATA_DIR / "asset_statements.jsonl",
    "credit_report": DATA_DIR / "credit_reports.jsonl",
    "purchase_contract": DATA_DIR / "purchase_contracts.jsonl",
    "appraisal": DATA_DIR / "appraisals.jsonl",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load one JSON object per non-empty line."""
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def humanize(value: str) -> str:
    """Convert machine field names to readable labels."""
    return value.replace("_", " ").strip().title()


def format_value(value: Any, indent: int = 0) -> list[str]:
    """Render nested JSON as simple labeled text suitable for extraction tests."""
    prefix = "  " * indent
    lines: list[str] = []

    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}{humanize(key)}:")
                lines.extend(format_value(child, indent + 1))
            else:
                rendered = "Not provided" if child is None else str(child)
                lines.append(f"{prefix}{humanize(key)}: {rendered}")
        return lines

    if isinstance(value, list):
        if not value:
            return [f"{prefix}None"]
        for index, child in enumerate(value, start=1):
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}Item {index}:")
                lines.extend(format_value(child, indent + 1))
            else:
                lines.append(f"{prefix}- {child}")
        return lines

    return [f"{prefix}{value}"]


def build_document(title: str, records: list[dict[str, Any]]) -> str:
    """Build the printable text for one synthetic source document."""
    loan_id = records[0].get("loan_id", "SHARED")
    lines = [
        "SYNTHETIC TRAINING DOCUMENT - NOT FOR REAL UNDERWRITING",
        "=" * 68,
        title,
        f"Loan ID: {loan_id}",
        "=" * 68,
        "",
    ]

    for index, record in enumerate(records, start=1):
        if len(records) > 1:
            lines.extend([f"Record {index}", "-" * 68])
        lines.extend(format_value(record))
        lines.append("")

    lines.extend(
        [
            "Synthetic data notice:",
            "All people, companies, accounts, addresses, and transactions are fictional.",
        ]
    )
    return "\n".join(lines)


def text_to_pdf(text: str, destination: Path) -> None:
    """Use the native macOS print filter to produce a searchable PDF."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8") as source:
        source.write(text)
        source.flush()
        completed = subprocess.run(
            ["/usr/sbin/cupsfilter", "-m", "application/pdf", source.name],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    destination.write_bytes(completed.stdout)


def main() -> None:
    """Generate per-loan PDFs, a guideline PDF, and a machine-readable manifest."""
    records_by_type: dict[str, dict[str, list[dict[str, Any]]]] = {}
    loan_ids: set[str] = set()

    for document_type, source_path in DOCUMENT_SOURCES.items():
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in load_jsonl(source_path):
            grouped[record["loan_id"]].append(record)
            loan_ids.add(record["loan_id"])
        records_by_type[document_type] = grouped

    manifest: dict[str, Any] = {
        "description": "Synthetic, text-searchable PDFs generated from data/*.jsonl",
        "loans": {},
        "shared_documents": [],
    }

    for loan_id in sorted(loan_ids):
        loan_files: list[dict[str, str]] = []
        for document_type, grouped in records_by_type.items():
            records = grouped.get(loan_id, [])
            if not records:
                continue
            relative_path = Path(loan_id) / f"{document_type}.pdf"
            destination = OUTPUT_DIR / relative_path
            text_to_pdf(build_document(humanize(document_type), records), destination)
            loan_files.append(
                {
                    "document_type": document_type,
                    "path": relative_path.as_posix(),
                }
            )
        manifest["loans"][loan_id] = loan_files

    guidelines = load_jsonl(DATA_DIR / "underwriting_guidelines.jsonl")
    guideline_path = Path("shared") / "underwriting_guidelines.pdf"
    text_to_pdf(
        build_document("Synthetic Underwriting Guideline Corpus", guidelines),
        OUTPUT_DIR / guideline_path,
    )
    manifest["shared_documents"].append(
        {"document_type": "underwriting_guidelines", "path": guideline_path.as_posix()}
    )

    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    pdf_count = sum(len(files) for files in manifest["loans"].values()) + 1
    print(f"Generated {pdf_count} PDFs in {OUTPUT_DIR}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
