"""Framework-independent helpers used by the Streamlit reviewer UI."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Protocol


MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class UploadedFile(Protocol):
    name: str

    def getvalue(self) -> bytes: ...


def safe_pdf_name(name: str) -> str:
    """Return a traversal-safe PDF filename suitable for temporary storage."""
    base = Path(name).name
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(base).stem).strip("._")
    if Path(base).suffix.casefold() != ".pdf" or not stem:
        raise ValueError(f"Only named PDF files are accepted: {name!r}")
    return f"{stem}.pdf"


def save_uploaded_pdfs(uploads: Iterable[UploadedFile], destination: Path) -> list[Path]:
    """Validate and persist uploaded PDFs in a per-session temporary folder."""
    destination.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    used_names: set[str] = set()
    for upload in uploads:
        name = safe_pdf_name(upload.name)
        if name.casefold() in used_names:
            raise ValueError(f"Duplicate PDF filename: {name}")
        content = upload.getvalue()
        if len(content) > MAX_UPLOAD_BYTES:
            raise ValueError(f"{name} exceeds the 25 MB upload limit")
        if not content.startswith(b"%PDF-"):
            raise ValueError(f"{name} does not have a valid PDF header")
        path = destination / name
        path.write_bytes(content)
        saved.append(path)
        used_names.add(name.casefold())
    return saved


def fact_map(review_package) -> dict[str, object]:
    """Convert canonical facts into a presentation-friendly mapping."""
    return {fact.name: fact.value for fact in review_package.key_facts}


def format_money(value: object) -> str:
    return "—" if value is None else f"${float(value):,.2f}"


def format_percent(value: object) -> str:
    return "—" if value is None else f"{float(value):,.2f}%"
