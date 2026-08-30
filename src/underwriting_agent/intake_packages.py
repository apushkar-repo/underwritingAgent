"""Resolve curated folders or manifest-backed realistic intake packages."""

from __future__ import annotations

import json
from pathlib import Path


def resolve_document_paths(pdf_root: Path, intake_reference: str) -> list[Path]:
    """Return PDFs for a folder name or a manifest intake reference."""
    direct = pdf_root / intake_reference
    if direct.is_dir():
        return sorted(direct.glob("*.pdf"))

    manifest_path = pdf_root / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        package = next(
            (
                item for item in manifest.get("packages", [])
                if item.get("intake_reference", "").casefold()
                == intake_reference.casefold()
            ),
            None,
        )
        if package:
            return sorted((pdf_root / package["folder"]).glob("*.pdf"))
    return []


def available_intake_references(pdf_root: Path) -> list[str]:
    """List manifest references, falling back to child directory names."""
    manifest_path = pdf_root / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return [item["intake_reference"] for item in manifest.get("packages", [])]
    return sorted(path.name for path in pdf_root.iterdir() if path.is_dir())
