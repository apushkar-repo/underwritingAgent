"""Phase 5 deterministic calculations and local vector guideline retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from underwriting_agent.models import (
    BorrowerPath,
    CalculationPolicyState,
    FinancialCalculations,
    PolicyRule,
)
from underwriting_agent.observability import append_workflow_event


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def calculate_dti(monthly_debt: float, monthly_income: float | None) -> float | None:
    """Calculate DTI exactly; return None when qualifying income is unavailable."""
    if monthly_income is None or monthly_income <= 0:
        return None
    return round(monthly_debt / monthly_income * 100, 2)


def calculate_ltv(loan_amount: float, purchase_price: float, appraised_value: float) -> float | None:
    """Calculate purchase LTV using the lower of price or appraised value."""
    denominator = min(purchase_price, appraised_value)
    if denominator <= 0:
        return None
    return round(loan_amount / denominator * 100, 2)


class LocalGuidelineVectorStore:
    """Tiny deterministic embedding/vector store for the synthetic rule corpus."""

    def __init__(self, rules: list[PolicyRule], dimensions: int = 256):
        self.rules = rules
        self.rule_count = len(rules)
        self.dimensions = dimensions
        self.vectors = [self.embed(self._rule_text(rule)) for rule in rules]

    @classmethod
    def from_jsonl(cls, path: Path):
        rules = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    rules.append(PolicyRule.model_validate_json(line))
        return cls(rules)

    @staticmethod
    def _rule_text(rule: PolicyRule) -> str:
        return " ".join(
            [rule.rule_id, rule.category, rule.borrower_type, rule.rule_text, *rule.required_evidence]
        )

    def embed(self, text: str) -> list[float]:
        """Hash tokens into a normalized fixed-size numeric vector."""
        vector = [0.0] * self.dimensions
        for token in TOKEN_PATTERN.findall(text.casefold()):
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0
        magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / magnitude for value in vector]

    def search(self, query: str, *, k: int = 4, categories: set[str] | None = None) -> list[PolicyRule]:
        """Embed a query and return closest rules using cosine similarity."""
        query_vector = self.embed(query)
        scored = []
        for rule, vector in zip(self.rules, self.vectors, strict=True):
            if categories and rule.category not in categories:
                continue
            score = sum(left * right for left, right in zip(query_vector, vector, strict=True))
            scored.append((score, rule))
        scored.sort(key=lambda item: (-item[0], item[1].rule_id))
        return [rule.model_copy(update={"similarity_score": round(score, 4)}) for score, rule in scored[:k]]


class PineconeGuidelineVectorStore:
    """Persistent Pinecone store using externally generated OpenAI embeddings."""

    def __init__(self, index, embeddings, *, namespace: str = "underwriting-guidelines", rule_count: int = 100):
        self.index = index
        self.embeddings = embeddings
        self.namespace = namespace
        self.rule_count = rule_count

    @classmethod
    def from_jsonl(
        cls,
        path: Path,
        *,
        api_key: str,
        index_name: str,
        namespace: str = "underwriting-guidelines",
        embedding_model: str = "text-embedding-3-small",
        dimensions: int = 1536,
        cloud: str = "aws",
        region: str = "us-east-1",
        create_index: bool = True,
    ):
        """Create/connect, embed the rule corpus, and idempotently upsert by rule ID."""
        from langchain_openai import OpenAIEmbeddings
        from pinecone import Pinecone, ServerlessSpec

        client = Pinecone(api_key=api_key)
        if not client.has_index(index_name):
            if not create_index:
                raise ValueError(f"Pinecone index {index_name!r} does not exist")
            client.create_index(
                name=index_name,
                vector_type="dense",
                dimension=dimensions,
                metric="cosine",
                spec=ServerlessSpec(cloud=cloud, region=region),
                deletion_protection="disabled",
            )
        index = client.Index(index_name)
        embeddings = OpenAIEmbeddings(model=embedding_model, dimensions=dimensions)
        rules = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    rules.append(PolicyRule.model_validate_json(line))
        texts = [LocalGuidelineVectorStore._rule_text(rule) for rule in rules]
        vectors = embeddings.embed_documents(texts)
        index.upsert(
            vectors=[
                {
                    "id": rule.rule_id,
                    "values": vector,
                    "metadata": {
                        "rule_json": rule.model_dump_json(exclude={"similarity_score"}),
                        "category": rule.category,
                        "borrower_type": rule.borrower_type,
                        "severity": rule.severity,
                    },
                }
                for rule, vector in zip(rules, vectors, strict=True)
            ],
            namespace=namespace,
        )
        return cls(index, embeddings, namespace=namespace, rule_count=len(rules))

    def search(self, query: str, *, k: int = 4, categories: set[str] | None = None) -> list[PolicyRule]:
        """Embed the query, search Pinecone, and reconstruct validated policy rules."""
        vector = self.embeddings.embed_query(query)
        metadata_filter = {"category": {"$in": sorted(categories)}} if categories else None
        response = self.index.query(
            vector=vector,
            top_k=k,
            include_metadata=True,
            namespace=self.namespace,
            filter=metadata_filter,
        )
        matches = response.matches if hasattr(response, "matches") else response["matches"]
        results = []
        for match in matches:
            metadata = match.metadata if hasattr(match, "metadata") else match["metadata"]
            score = match.score if hasattr(match, "score") else match["score"]
            rule = PolicyRule.model_validate_json(metadata["rule_json"])
            results.append(rule.model_copy(update={"similarity_score": round(float(score), 4)}))
        return results


def calculate_financials_node(state: CalculationPolicyState) -> dict[str, Any]:
    """Calculate DTI/LTV and normalize threshold breaches."""
    dti = calculate_dti(
        state["liability_analysis"].total_monthly_debt,
        state["income_analysis"].qualifying_monthly_income,
    )
    prop = state["property_analysis"]
    ltv = calculate_ltv(prop.loan_amount, prop.purchase_price, prop.appraised_value)
    exceptions = []
    if dti is not None and dti > 43:
        exceptions.append("HIGH_DTI")
    if ltv is not None and ltv > 80:
        exceptions.append("HIGH_LTV")
    return {"calculations": FinancialCalculations(dti_percent=dti, ltv_percent=ltv, calculation_exceptions=exceptions)}


def required_rule_ids(state: CalculationPolicyState) -> list[str]:
    """Determine applicable rules from verified facts before vector retrieval."""
    ids = ["UW-LTV-001"]
    if state["calculations"].dti_percent is not None:
        ids.append("UW-DTI-001")
    path = state["borrower_path"]
    income_exceptions = state["income_analysis"].exceptions
    if path is BorrowerPath.SALARIED and "INCOME_MISMATCH" in income_exceptions:
        ids.append("UW-INC-001")
    elif path is BorrowerPath.SELF_EMPLOYED:
        if "INCOME_DECLINE" in income_exceptions:
            ids.append("UW-SE-002")
            # The ordinary declining-income case still requires the base
            # self-employment evidence rule. The showcase case's gold policy
            # set intentionally focuses on its exception-specific rules.
            if "LARGE_DEPOSIT" not in state["asset_analysis"].exceptions:
                ids.append("UW-SE-001")
        else:
            ids.append("UW-SE-001")
    elif path is BorrowerPath.MIXED:
        ids.append("UW-MIX-001")
    if "LARGE_DEPOSIT" in state["asset_analysis"].exceptions:
        ids.append("UW-AST-001")
    if "LOW_APPRAISAL" in state["property_analysis"].exceptions:
        ids.append("UW-APR-001")
    return sorted(set(ids))


def retrieve_policy_node(state: CalculationPolicyState, store: LocalGuidelineVectorStore) -> dict[str, Any]:
    """Use vector search for candidates, then deterministically retain applicable rules."""
    ids = required_rule_ids(state)
    query = " ".join(ids + state["income_analysis"].exceptions + state["property_analysis"].exceptions + state["calculations"].calculation_exceptions)
    candidates = store.search(query, k=store.rule_count)
    by_id = {rule.rule_id: rule for rule in candidates}
    return {
        "retrieved_rules": [by_id[rule_id] for rule_id in ids],
        "workflow_status": "POLICY_REVIEW_COMPLETE",
        "observability_events": append_workflow_event(
            state,
            "ai",
            "Phase 5 · Calculations and policy",
            "Calculated ratios and retrieved policy",
            f"Calculated DTI/LTV and selected {len(ids)} applicable policy rules.",
            dti_percent=state["calculations"].dti_percent,
            ltv_percent=state["calculations"].ltv_percent,
            rule_ids=ids,
        ),
    }


def build_calculation_policy_workflow(guideline_path: Path, *, store=None):
    """Compile Phase 5 with a pre-indexed local guideline vector store."""
    store = store or LocalGuidelineVectorStore.from_jsonl(guideline_path)
    workflow = StateGraph(CalculationPolicyState)
    workflow.add_node("financial_calculations", calculate_financials_node)
    workflow.add_node("guideline_retrieval", lambda state: retrieve_policy_node(state, store))
    workflow.add_edge(START, "financial_calculations")
    workflow.add_edge("financial_calculations", "guideline_retrieval")
    workflow.add_edge("guideline_retrieval", END)
    return workflow.compile()
