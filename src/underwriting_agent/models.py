"""Typed contracts shared by the document-layer workflow."""

from __future__ import annotations

from enum import StrEnum
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


class DocumentType(StrEnum):
    """Document categories recognized during Phase 2 intake."""

    LOAN_APPLICATION = "loan_application"
    INCOME_DOCUMENTS = "income_documents"
    ASSET_STATEMENT = "asset_statement"
    CREDIT_REPORT = "credit_report"
    PURCHASE_CONTRACT = "purchase_contract"
    APPRAISAL = "appraisal"
    UNKNOWN = "unknown"


class IntakeDocument(BaseModel):
    """A PDF discovered and converted to text during intake."""

    source_path: Path
    file_name: str
    page_count: int = Field(ge=1)
    text: str
    extraction_error: str | None = None


class ParsedDocument(BaseModel):
    """Classification and canonical identifiers extracted from one PDF."""

    source_path: Path
    document_type: DocumentType
    loan_id: str | None = None
    document_id: str | None = None
    borrower_employment_type: str | None = None
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)


class ModelDocumentExtraction(BaseModel):
    """Strict model output for real-world document classification/extraction."""

    document_type: DocumentType
    loan_id: str | None = None
    document_id: str | None = None
    borrower_employment_type: Literal["salaried", "self_employed", "mixed", "unknown"] | None = None
    missing_evidence: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RequirementResult(BaseModel):
    """Deterministic document inventory decision for one loan package."""

    loan_id: str
    borrower_type: str
    received_document_types: list[DocumentType]
    missing_document_types: list[DocumentType]
    missing_evidence: list[str]
    complete: bool


class WorkflowEvent(BaseModel):
    """One attributable action in the underwriting workflow audit trail."""

    actor: Literal["ai", "human"]
    phase: str
    action: str
    details: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentLayerState(TypedDict, total=False):
    """State passed through the Phase 2 LangGraph nodes."""

    loan_id: str
    document_paths: list[str]
    intake_documents: list[IntakeDocument]
    parsed_documents: list[ParsedDocument]
    extraction_errors: list[str]
    requirements: RequirementResult
    workflow_status: str
    observability_events: list[WorkflowEvent]


class BorrowerPath(StrEnum):
    """Supported borrower-income routing paths."""

    SALARIED = "salaried"
    SELF_EMPLOYED = "self_employed"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class IncomeAnalysis(BaseModel):
    """Canonical qualifying income produced by the selected income specialist."""

    borrower_path: BorrowerPath
    stated_monthly_income: float | None = None
    qualifying_monthly_income: float | None = None
    income_sources: dict[str, float] = Field(default_factory=dict)
    trend: str | None = None
    exceptions: list[str] = Field(default_factory=list)
    source_document_ids: list[str] = Field(default_factory=list)


class AssetAnalysis(BaseModel):
    """Verified borrower funds after excluding unsupported amounts."""

    reported_assets: float
    verified_assets: float
    excluded_assets: float = 0
    large_deposits: list[float] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    source_document_ids: list[str] = Field(default_factory=list)


class LiabilityAnalysis(BaseModel):
    """Recurring obligations extracted from the synthetic credit report."""

    credit_score: int | None = None
    total_monthly_debt: float
    exceptions: list[str] = Field(default_factory=list)
    source_document_ids: list[str] = Field(default_factory=list)


class BorrowerAnalysisState(DocumentLayerState, total=False):
    """Phase 2 state enriched by Phase 3 borrower specialists."""

    borrower_path: BorrowerPath
    income_analysis: IncomeAnalysis
    asset_analysis: AssetAnalysis
    liability_analysis: LiabilityAnalysis


class PropertyAnalysis(BaseModel):
    """Canonical collateral facts reconciled from application, contract, and appraisal."""

    property_address: str | None = None
    loan_amount: float
    purchase_price: float
    appraised_value: float
    value_variance: float
    appraisal_status: str
    exceptions: list[str] = Field(default_factory=list)
    source_document_ids: list[str] = Field(default_factory=list)


class PropertyAnalysisState(BorrowerAnalysisState, total=False):
    property_analysis: PropertyAnalysis


class WebEvidenceSource(BaseModel):
    """One cited web result returned by the property-research provider."""

    url: str
    title: str
    excerpt: str
    domain: str
    query: str
    source_tier: int = Field(ge=1, le=4)
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PropertyValueObservation(BaseModel):
    """A value-like claim found online; never a substitute for an appraisal."""

    observation_type: str
    amount: float
    event_date: str | None = None
    source_url: str
    corroboration_status: str = "unconfirmed"


class PropertyResearchResult(BaseModel):
    """Address-only web research included as reviewer context."""

    property_address: str
    research_status: str
    searched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sources: list[WebEvidenceSource] = Field(default_factory=list)
    observations: list[PropertyValueObservation] = Field(default_factory=list)
    discrepancies: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PropertyResearchState(PropertyAnalysisState, total=False):
    property_research: PropertyResearchResult


class FinancialCalculations(BaseModel):
    """Exact qualification ratios; missing inputs produce missing outputs."""

    dti_percent: float | None = None
    ltv_percent: float | None = None
    calculation_exceptions: list[str] = Field(default_factory=list)


class PolicyRule(BaseModel):
    """One indexed synthetic underwriting guideline."""

    rule_id: str
    category: str
    borrower_type: str
    rule_text: str
    threshold: dict[str, Any] | None = None
    required_evidence: list[str]
    severity: str
    human_review_required: bool
    similarity_score: float | None = None


class CalculationPolicyState(PropertyResearchState, total=False):
    calculations: FinancialCalculations
    retrieved_rules: list[PolicyRule]


class CanonicalFact(BaseModel):
    """A reconciled fact with its evidence provenance."""

    name: str
    value: Any
    source_document_ids: list[str] = Field(default_factory=list)


class ExceptionItem(BaseModel):
    """Normalized exception/condition presented to a human reviewer."""

    code: str
    severity: str
    details: str
    rule_ids: list[str] = Field(default_factory=list)
    human_review_required: bool = True


class ReconciliationState(CalculationPolicyState, total=False):
    canonical_facts: list[CanonicalFact]
    exceptions: list[ExceptionItem]
    conditions: list[str]
    human_review_items: list[str]


class UnderwritingReviewPackage(BaseModel):
    """Evidence-backed decision-support package; never an autonomous credit decision."""

    loan_id: str
    review_disposition: str
    workflow_status: str
    executive_summary: str
    reviewer_focus: list[str] = Field(default_factory=list)
    key_facts: list[CanonicalFact]
    applicable_rule_ids: list[str]
    exceptions: list[ExceptionItem]
    conditions: list[str]
    human_review_required: bool
    human_review: dict[str, Any] | None = None
    external_property_research: PropertyResearchResult | None = None
    observability_log: list[WorkflowEvent] = Field(default_factory=list)
    disclaimer: str = (
        "Decision-support output only. A qualified human underwriter must make "
        "the final lending decision."
    )


class UnderwritingState(ReconciliationState, total=False):
    review_package: UnderwritingReviewPackage
    human_review: dict[str, Any]


class ModelReviewNarrative(BaseModel):
    """Strict model output used only for human-facing narrative assistance."""

    executive_summary: str
    reviewer_focus: list[str] = Field(default_factory=list)
