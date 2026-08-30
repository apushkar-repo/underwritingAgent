"""Parent LangGraph orchestrator for the synthetic underwriting workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from enum import Enum

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel

import underwriting_agent.models as state_models
from underwriting_agent.borrower_analysis import build_borrower_workflow
from underwriting_agent.calculations_policy import build_calculation_policy_workflow
from underwriting_agent.document_layer import build_document_workflow
from underwriting_agent.models import UnderwritingState
from underwriting_agent.property_analysis import build_property_workflow
from underwriting_agent.property_research import build_property_research_workflow
from underwriting_agent.reconciliation import build_reconciliation_workflow
from underwriting_agent.summary import build_summary_workflow
from underwriting_agent.observability import append_workflow_event


def route_document_status(
    state: UnderwritingState,
) -> Literal["borrower_analysis", "request_missing_documents"]:
    """Advance complete packages and pause incomplete packages."""
    return (
        "borrower_analysis"
        if state["requirements"].complete
        else "request_missing_documents"
    )


def request_missing_documents_node(state: UnderwritingState) -> dict[str, Any]:
    """Pause until a human supplies replacement or additional PDF paths."""
    requirements = state["requirements"]
    response = interrupt(
        {
            "type": "missing_documents",
            "loan_id": state["loan_id"],
            "missing_document_types": [
                str(item) for item in requirements.missing_document_types
            ],
            "missing_evidence": requirements.missing_evidence,
            "message": "Upload the requested evidence and resume this thread.",
        }
    )
    supplied_paths = response.get("document_paths", [])
    if not supplied_paths:
        raise ValueError("Resume value must contain a non-empty document_paths list")
    combined_paths = list(dict.fromkeys([*state["document_paths"], *supplied_paths]))
    return {
        "document_paths": combined_paths,
        "workflow_status": "INTAKE",
        "observability_events": append_workflow_event(
            state,
            "human",
            "Human input · Documents",
            "Uploaded requested evidence",
            f"Added {len(supplied_paths)} document(s) and resumed the workflow.",
            file_names=[Path(path).name for path in supplied_paths],
        ),
    }


def route_exception_status(
    state: UnderwritingState,
) -> Literal["exception_review", "underwriting_summary"]:
    """Only exception-bearing files require an in-graph review pause."""
    return "exception_review" if state.get("exceptions") else "underwriting_summary"


def exception_review_node(state: UnderwritingState) -> dict[str, Any]:
    """Pause for a human to acknowledge or return exception conditions."""
    response = interrupt(
        {
            "type": "exception_review",
            "loan_id": state["loan_id"],
            "exceptions": [item.model_dump(mode="json") for item in state["exceptions"]],
            "conditions": state.get("conditions", []),
            "allowed_actions": ["acknowledge", "request_changes"],
            "message": "A human underwriter must review these exceptions.",
        }
    )
    action = response.get("action")
    if action not in {"acknowledge", "request_changes"}:
        raise ValueError("Review action must be 'acknowledge' or 'request_changes'")
    return {
        "human_review": {
            "action": action,
            "reviewer": response.get("reviewer", "unspecified"),
            "notes": response.get("notes", ""),
        },
        "workflow_status": "EXCEPTION_REVIEWED",
        "observability_events": append_workflow_event(
            state,
            "human",
            "Human input · Exception review",
            "Submitted exception review",
            f"Reviewer {response.get('reviewer', 'unspecified')} selected {action}.",
            reviewer=response.get("reviewer", "unspecified"),
            review_action=action,
            notes=response.get("notes", ""),
        ),
    }


def build_underwriting_orchestrator(
    guideline_path: Path,
    *,
    checkpointer=None,
    document_interpreter=None,
    guideline_store=None,
    review_narrator=None,
    property_research_service=None,
):
    """Compile the parent graph and propagate its checkpointer to all subgraphs."""
    workflow = StateGraph(UnderwritingState)
    workflow.add_node(
        "document_layer",
        build_document_workflow(document_interpreter=document_interpreter),
    )
    workflow.add_node("request_missing_documents", request_missing_documents_node)
    workflow.add_node("borrower_analysis", build_borrower_workflow())
    workflow.add_node("property_analysis", build_property_workflow())
    workflow.add_node(
        "property_research",
        build_property_research_workflow(service=property_research_service),
    )
    workflow.add_node(
        "calculations_and_policy",
        build_calculation_policy_workflow(guideline_path, store=guideline_store),
    )
    workflow.add_node("reconciliation", build_reconciliation_workflow())
    workflow.add_node("exception_review", exception_review_node)
    workflow.add_node(
        "underwriting_summary",
        build_summary_workflow(narrator=review_narrator),
    )

    workflow.add_edge(START, "document_layer")
    workflow.add_conditional_edges(
        "document_layer",
        route_document_status,
        ["borrower_analysis", "request_missing_documents"],
    )
    workflow.add_edge("request_missing_documents", "document_layer")
    workflow.add_edge("borrower_analysis", "property_analysis")
    workflow.add_edge("property_analysis", "property_research")
    workflow.add_edge("property_research", "calculations_and_policy")
    workflow.add_edge("calculations_and_policy", "reconciliation")
    workflow.add_conditional_edges(
        "reconciliation",
        route_exception_status,
        ["exception_review", "underwriting_summary"],
    )
    workflow.add_edge("exception_review", "underwriting_summary")
    workflow.add_edge("underwriting_summary", END)
    if checkpointer is None:
        # Checkpoints contain our Pydantic models and enums. Explicitly allow
        # only those trusted local types instead of permissive deserialization.
        trusted_types = [
            value
            for value in vars(state_models).values()
            if isinstance(value, type)
            and value.__module__ == state_models.__name__
            and (issubclass(value, BaseModel) or issubclass(value, Enum))
        ]
        checkpointer = InMemorySaver(
            serde=JsonPlusSerializer(allowed_msgpack_modules=trusted_types)
        )
    return workflow.compile(checkpointer=checkpointer)
