from pathlib import Path

import pytest

from underwriting_agent.ui_support import format_money, format_percent, safe_pdf_name, save_uploaded_pdfs


class FakeUpload:
    def __init__(self, name: str, content: bytes):
        self.name = name
        self._content = content

    def getvalue(self) -> bytes:
        return self._content


def test_safe_pdf_name_removes_traversal_and_unsafe_characters():
    assert safe_pdf_name("../../Tax Return (final).PDF") == "Tax_Return_final.pdf"


def test_safe_pdf_name_rejects_non_pdf():
    with pytest.raises(ValueError):
        safe_pdf_name("document.exe")


def test_save_uploaded_pdfs_validates_header_and_duplicate_names(tmp_path: Path):
    saved = save_uploaded_pdfs([FakeUpload("application.pdf", b"%PDF-1.4\nfixture")], tmp_path)
    assert saved == [tmp_path / "application.pdf"]

    with pytest.raises(ValueError, match="valid PDF header"):
        save_uploaded_pdfs([FakeUpload("fake.pdf", b"not a pdf")], tmp_path)

    with pytest.raises(ValueError, match="Duplicate"):
        save_uploaded_pdfs(
            [FakeUpload("same.pdf", b"%PDF-1.4"), FakeUpload("same.pdf", b"%PDF-1.4")],
            tmp_path,
        )


def test_display_formatters():
    assert format_money(1234.5) == "$1,234.50"
    assert format_percent(43.125) == "43.12%"
    assert format_money(None) == "—"
