"""Phase 2 document intake, classification, extraction, and requirement checks."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from pypdf import PdfReader

from underwriting_agent.models import (
    DocumentLayerState,
    DocumentType,
    IntakeDocument,
    ParsedDocument,
    RequirementResult,
)
from underwriting_agent.observability import append_workflow_event


# Every supported borrower path needs the same top-level document categories in
# the current synthetic portfolio. The income PDF contains borrower-specific
# evidence such as pay/W-2 data, tax returns, or both.
BASE_REQUIRED_DOCUMENTS = {
    DocumentType.LOAN_APPLICATION,
    DocumentType.INCOME_DOCUMENTS,
    DocumentType.ASSET_STATEMENT,
    DocumentType.CREDIT_REPORT,
    DocumentType.PURCHASE_CONTRACT,
    DocumentType.APPRAISAL,
}

# These items prevent downstream calculations. Other missing evidence can be
# carried forward as an exception while the related funds/facts are excluded.
BLOCKING_MISSING_EVIDENCE = {"current_year_profit_and_loss_statement"}

DOCUMENT_SIGNATURES: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.LOAN_APPLICATION: ("loan application", "stated monthly income"),
    DocumentType.INCOME_DOCUMENTS: ("income documents", "document type"),
    DocumentType.ASSET_STATEMENT: ("asset statement", "verified total"),
    DocumentType.CREDIT_REPORT: ("credit report", "tradelines"),
    DocumentType.PURCHASE_CONTRACT: ("purchase contract", "contract date"),
    DocumentType.APPRAISAL: ("appraisal", "appraised value"),
}

REALISTIC_SIGNATURES: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.LOAN_APPLICATION: (
        "uniform residential loan application", "borrower information"
    ),
    DocumentType.INCOME_DOCUMENTS: (
        "wage and tax statement", "form w-2", "u.s. individual income tax return",
        "schedule c (form 1040)",
    ),
    DocumentType.ASSET_STATEMENT: ("account statement", "closing balance"),
    DocumentType.CREDIT_REPORT: ("merged credit report", "tradeline"),
    DocumentType.PURCHASE_CONTRACT: (
        "residential real estate purchase agreement", "residential purchase agreement"
    ),
    DocumentType.APPRAISAL: (
        "uniform residential appraisal report", "opinion of market value"
    ),
}

FIELD_PATTERNS = {
    "loan_id": re.compile(r"^Loan Id:\s*(.+)$", re.MULTILINE | re.IGNORECASE),
    "document_id": re.compile(r"^Document Id:\s*(.+)$", re.MULTILINE | re.IGNORECASE),
    "employment_type": re.compile(
        r"^\s*Employment Type:\s*(.+)$", re.MULTILINE | re.IGNORECASE
    ),
    "status": re.compile(r"^\s*Status:\s*(.+)$", re.MULTILINE | re.IGNORECASE),
}


def extract_pdf(path: Path) -> IntakeDocument:
    """Extract searchable text and basic metadata from a PDF."""
    try:
        reader = PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        warning = None if text else "PDF contains no extractable text"
        return IntakeDocument(
            source_path=path,
            file_name=path.name,
            page_count=max(len(reader.pages), 1),
            text=text,
            extraction_error=warning,
        )
    except Exception as exc:  # Keep one bad PDF from crashing the entire package.
        return IntakeDocument(
            source_path=path,
            file_name=path.name,
            page_count=1,
            text="",
            extraction_error=f"{type(exc).__name__}: {exc}",
        )


def classify_document(text: str) -> tuple[DocumentType, float]:
    """Classify a synthetic PDF using stable content signatures."""
    normalized = text.casefold()
    scores = {
        document_type: sum(signature in normalized for signature in signatures)
        for document_type, signatures in DOCUMENT_SIGNATURES.items()
    }
    best_type, score = max(scores.items(), key=lambda item: item[1])
    if score == len(DOCUMENT_SIGNATURES[best_type]):
        return best_type, score / len(DOCUMENT_SIGNATURES[best_type])
    realistic_scores = {
        document_type: sum(signature in normalized for signature in signatures)
        for document_type, signatures in REALISTIC_SIGNATURES.items()
    }
    best_type, score = max(realistic_scores.items(), key=lambda item: item[1])
    if score == 0:
        # One curated signature is weak evidence but still useful for legacy
        # fixtures when no realistic-layout signature matches.
        legacy_type, legacy_score = max(scores.items(), key=lambda item: item[1])
        if legacy_score:
            return legacy_type, legacy_score / len(DOCUMENT_SIGNATURES[legacy_type])
        return DocumentType.UNKNOWN, 0.0
    return best_type, min(0.95, 0.7 + 0.15 * score)


def _match(pattern_name: str, text: str) -> str | None:
    match = FIELD_PATTERNS[pattern_name].search(text)
    return match.group(1).strip() if match else None


def _first_match(text: str, *patterns: str, flags: int = re.IGNORECASE | re.MULTILINE):
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1).strip()
    return None


def _money(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9.-]", "", value)
    return float(cleaned) if cleaned else None


def extract_canonical_fields(text: str, document_type: DocumentType) -> dict[str, Any]:
    """Normalize known lender-style layouts into downstream field names."""
    fields: dict[str, Any] = {}
    normalized_text = re.sub(r"\s+", " ", text).casefold()
    if document_type is DocumentType.LOAN_APPLICATION:
        fields.update({
            "property_address": _first_match(text, r"^Subject property\s+(.+)$"),
            "stated_monthly_income": _money(_first_match(
                text, r"^Gross monthly income \(stated\)\s+(.+)$"
            )),
            "loan_amount": _money(_first_match(
                text, r"Loan amount (?:requested:\s*|\s+)(\$?[\d,]+(?:\.\d+)?)"
            )),
        })
    elif document_type is DocumentType.INCOME_DOCUMENTS:
        w2_wages = _money(_first_match(
            text, r"1 Wages, tips, other compensation\s*\n?\s*(\$?[\d,]+(?:\.\d+)?)"
        ))
        business_profit = _money(_first_match(
            text, r"(?:31\s+)?Net profit\s+(\$?[\d,]+(?:\.\d+)?)"
        ))
        annual = business_profit or w2_wages
        fields.update({
            "annual_income": annual,
            "qualifying_monthly_income": annual / 12 if annual else None,
            "income_kind": "business" if business_profit else "salary",
        })
        if "no 2026 year-to-date profit and loss statement" in normalized_text:
            fields["missing_evidence"] = ["current_year_profit_and_loss_statement"]
    elif document_type is DocumentType.ASSET_STATEMENT:
        balance = _money(_first_match(text, r"Closing balance\s+(\$?[\d,]+(?:\.\d+)?)"))
        amounts = [
            _money(value) for value in re.findall(
                r"^\d{2}/\d{2}.*?(-?\$\d[\d,]*\.\d{2})", text, re.MULTILINE
            )
        ]
        large = sorted({value for value in amounts if value is not None and value >= 10000})
        fields.update({"reported_assets": balance, "large_deposits": large})
        unsupported = any(
            phrase in text.casefold()
            for phrase in ("incoming wire - client project", "transfer from family savings")
        )
        fields["unsupported_deposits"] = large if unsupported else []
        if unsupported:
            fields["missing_evidence"] = ["deposit_source_documentation"]
    elif document_type is DocumentType.CREDIT_REPORT:
        score = _first_match(text, r"Scores?:\s*(\d{3})", r"Scores?\s+(\d{3})")
        debt = _money(_first_match(
            text, r"TOTAL MONTHLY OBLIGATIONS SHOWN\s+(\$?[\d,]+(?:\.\d+)?)"
        ))
        fields.update({"credit_score": int(score) if score else None, "total_monthly_debt": debt})
    elif document_type is DocumentType.PURCHASE_CONTRACT:
        fields.update({
            "property_address": _first_match(text, r"^Property\s+(.+)$"),
            "purchase_price": _money(_first_match(
                text, r"Purchase price\s*:?\s*(\$?[\d,]+(?:\.\d+)?)"
            )),
            "loan_amount": _money(_first_match(
                text, r"anticipated amount\s+(\$?[\d,]+(?:\.\d+)?)"
            )),
        })
    elif document_type is DocumentType.APPRAISAL:
        fields.update({
            "property_address": _first_match(text, r"^Property:\s*(.+)$"),
            "appraised_value": _money(_first_match(
                text, r"OPINION OF MARKET VALUE\s+(\$?[\d,]+(?:\.\d+)?)"
            )),
        })
    return {key: value for key, value in fields.items() if value is not None}


def extract_key_fields(document: IntakeDocument) -> ParsedDocument:
    """Extract routing/provenance fields while retaining the source PDF path."""
    document_type, confidence = classify_document(document.text)
    warnings: list[str] = []
    if document.extraction_error:
        warnings.append(document.extraction_error)
    if document_type is DocumentType.UNKNOWN:
        warnings.append("Document type could not be classified")

    employment_type = _match("employment_type", document.text)
    if not employment_type and document_type is DocumentType.LOAN_APPLICATION:
        position = _first_match(document.text, r"^Position\s+(.+)$") or ""
        employer = _first_match(document.text, r"^Employment / business\s+(.+)$") or ""
        combined = f"{position} {employer}".casefold()
        if "sole proprietor" in combined or "self-employed" in combined:
            employment_type = "self_employed"
        elif "adjunct" in combined or " / " in employer:
            employment_type = "mixed"
        elif combined.strip():
            employment_type = "salaried"
    status = _match("status", document.text)
    fields: dict[str, Any] = extract_canonical_fields(document.text, document_type)
    if status:
        fields["status"] = status.casefold()

    # The PDF generator prints missing evidence as explicit labeled content.
    missing_evidence: list[str] = list(fields.get("missing_evidence", []))
    if "Current Pl Annualized Income: Not provided" in document.text:
        missing_evidence.append("current_year_profit_and_loss_statement")
    if "Source: unexplained" in document.text and "Documentation Received: False" in document.text:
        missing_evidence.append("deposit_source_documentation")
    if missing_evidence:
        fields["missing_evidence"] = missing_evidence

    return ParsedDocument(
        source_path=document.source_path,
        document_type=document_type,
        loan_id=_match("loan_id", document.text),
        document_id=_match("document_id", document.text) or document.source_path.stem,
        borrower_employment_type=employment_type.casefold() if employment_type else None,
        extracted_fields=fields,
        confidence=confidence,
        warnings=warnings,
    )


def intake_documents_node(state: DocumentLayerState) -> dict[str, Any]:
    """LangGraph node: read every supplied PDF and collect extraction errors."""
    documents = [extract_pdf(Path(path)) for path in state["document_paths"]]
    errors = [
        f"{document.file_name}: {document.extraction_error}"
        for document in documents
        if document.extraction_error
    ]
    return {
        "intake_documents": documents,
        "extraction_errors": errors,
        "workflow_status": "DOCUMENT_REVIEW",
    }


def classify_and_extract_node(state: DocumentLayerState) -> dict[str, Any]:
    """LangGraph node: classify PDFs and extract canonical identifiers."""
    parsed = [extract_key_fields(document) for document in state["intake_documents"]]
    return {"parsed_documents": parsed}


def classify_and_extract_with_model_node(
    state: DocumentLayerState, interpreter
) -> dict[str, Any]:
    """Use an injected structured-output model service for real-world layouts."""
    parsed_documents = []
    for document in state["intake_documents"]:
        deterministic = extract_key_fields(document)
        extraction = interpreter.extract(document)
        employment_type = extraction.borrower_employment_type
        if employment_type in {None, "unknown"}:
            employment_type = deterministic.borrower_employment_type
        fields = dict(deterministic.extracted_fields)
        if extraction.missing_evidence:
            fields["missing_evidence"] = sorted(set(
                fields.get("missing_evidence", []) + extraction.missing_evidence
            ))
        parsed_documents.append(
            ParsedDocument(
                source_path=document.source_path,
                document_type=extraction.document_type,
                loan_id=extraction.loan_id,
                document_id=extraction.document_id or deterministic.document_id,
                borrower_employment_type=employment_type,
                extracted_fields=fields,
                confidence=1.0,
                warnings=extraction.warnings,
            )
        )
    return {"parsed_documents": parsed_documents}


def _borrower_type(documents: Iterable[ParsedDocument]) -> str:
    for document in documents:
        if document.document_type is DocumentType.LOAN_APPLICATION:
            return document.borrower_employment_type or "unknown"
    return "unknown"


def check_requirements_node(state: DocumentLayerState) -> dict[str, Any]:
    """LangGraph node: compare received evidence with the Phase 2 requirement matrix."""
    documents = state["parsed_documents"]
    received = {doc.document_type for doc in documents if doc.document_type is not DocumentType.UNKNOWN}
    missing_types = sorted(BASE_REQUIRED_DOCUMENTS - received, key=str)
    missing_evidence = sorted(
        {
            item
            for document in documents
            for item in document.extracted_fields.get("missing_evidence", [])
        }
    )
    borrower_type = _borrower_type(documents)
    blocking_evidence = BLOCKING_MISSING_EVIDENCE.intersection(missing_evidence)
    complete = not missing_types and not blocking_evidence and not state.get("extraction_errors")
    result = RequirementResult(
        loan_id=state["loan_id"],
        borrower_type=borrower_type,
        received_document_types=sorted(received, key=str),
        missing_document_types=missing_types,
        missing_evidence=missing_evidence,
        complete=complete,
    )
    return {
        "requirements": result,
        "workflow_status": "VERIFICATION" if complete else "NEEDS_DOCUMENTS",
        "observability_events": append_workflow_event(
            state,
            "ai",
            "Phase 2 · Document intake",
            "Validated document package",
            f"Classified {len(documents)} documents; package complete: {complete}.",
            received_document_types=[item.value for item in result.received_document_types],
            missing_document_types=[item.value for item in result.missing_document_types],
            missing_evidence=result.missing_evidence,
        ),
    }


def build_document_workflow(*, document_interpreter=None):
    """Compile the independently runnable Phase 2 LangGraph subgraph."""
    workflow = StateGraph(DocumentLayerState)
    workflow.add_node("document_intake", intake_documents_node)
    if document_interpreter is None:
        workflow.add_node("classify_and_extract", classify_and_extract_node)
    else:
        workflow.add_node(
            "classify_and_extract",
            lambda state: classify_and_extract_with_model_node(
                state, document_interpreter
            ),
        )
    workflow.add_node("check_requirements", check_requirements_node)
    workflow.add_edge(START, "document_intake")
    workflow.add_edge("document_intake", "classify_and_extract")
    workflow.add_edge("classify_and_extract", "check_requirements")
    workflow.add_edge("check_requirements", END)
    return workflow.compile()
