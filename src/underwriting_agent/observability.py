"""Small helpers for attributable workflow audit events."""

from __future__ import annotations

from typing import Any, Literal, Mapping

from underwriting_agent.models import WorkflowEvent


def workflow_event(
    actor: Literal["ai", "human"],
    phase: str,
    action: str,
    details: str,
    **metadata: Any,
) -> list[WorkflowEvent]:
    """Return a one-item list compatible with the LangGraph list reducer."""
    return [WorkflowEvent(
        actor=actor,
        phase=phase,
        action=action,
        details=details,
        metadata=metadata,
    )]


def append_workflow_event(
    state: Mapping[str, Any],
    actor: Literal["ai", "human"],
    phase: str,
    action: str,
    details: str,
    **metadata: Any,
) -> list[WorkflowEvent]:
    """Append exactly one event to sequential LangGraph state."""
    return [
        *state.get("observability_events", []),
        *workflow_event(actor, phase, action, details, **metadata),
    ]
