"""Environment-driven optional OpenAI and Pinecone integrations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from underwriting_agent.calculations_policy import PineconeGuidelineVectorStore
from underwriting_agent.model_services import OpenAIDocumentInterpreter, OpenAIReviewNarrator
from underwriting_agent.property_research import YouComPropertyResearchService, YouComSearchClient


@dataclass
class IntegrationBundle:
    """Injected services; None means use the deterministic local implementation."""

    document_interpreter: object | None = None
    guideline_store: object | None = None
    review_narrator: object | None = None
    property_research_service: object | None = None


def _enabled(name: str) -> bool:
    return os.getenv(name, "false").casefold() in {"1", "true", "yes", "on"}


def build_integrations_from_env(guideline_path: Path, *, dotenv_path: Path | None = None) -> IntegrationBundle:
    """Construct only integrations explicitly enabled by environment variables."""
    load_dotenv(dotenv_path=dotenv_path, override=False)
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    document_interpreter = OpenAIDocumentInterpreter(model) if _enabled("USE_OPENAI_DOCUMENT_MODEL") else None
    review_narrator = OpenAIReviewNarrator(model) if _enabled("USE_OPENAI_REVIEW_NARRATOR") else None

    property_research_service = None
    if _enabled("USE_PROPERTY_WEB_RESEARCH"):
        api_key = os.getenv("YDC_API_KEY")
        if not api_key:
            raise ValueError("YDC_API_KEY is required when USE_PROPERTY_WEB_RESEARCH=true")
        client = YouComSearchClient(
            api_key,
            count=int(os.getenv("PROPERTY_SEARCH_RESULT_COUNT", "8")),
            country=os.getenv("PROPERTY_SEARCH_COUNTRY", "US"),
            timeout=float(os.getenv("PROPERTY_SEARCH_TIMEOUT_SECONDS", "20")),
        )
        property_research_service = YouComPropertyResearchService(
            client,
            variance_threshold_percent=float(
                os.getenv("PROPERTY_VALUE_VARIANCE_THRESHOLD", "10")
            ),
        )

    guideline_store = None
    if os.getenv("GUIDELINE_VECTOR_BACKEND", "local").casefold() == "pinecone":
        api_key = os.getenv("PINECONE_API_KEY")
        if not api_key:
            raise ValueError("PINECONE_API_KEY is required when GUIDELINE_VECTOR_BACKEND=pinecone")
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY is required to generate Pinecone vectors")
        guideline_store = PineconeGuidelineVectorStore.from_jsonl(
            guideline_path,
            api_key=api_key,
            index_name=os.getenv("PINECONE_INDEX_NAME", "underwriting-guidelines"),
            namespace=os.getenv("PINECONE_NAMESPACE", "synthetic-v1"),
            embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            dimensions=int(os.getenv("OPENAI_EMBEDDING_DIMENSIONS", "1536")),
            cloud=os.getenv("PINECONE_CLOUD", "aws"),
            region=os.getenv("PINECONE_REGION", "us-east-1"),
        )
    return IntegrationBundle(
        document_interpreter=document_interpreter,
        guideline_store=guideline_store,
        review_narrator=review_narrator,
        property_research_service=property_research_service,
    )
