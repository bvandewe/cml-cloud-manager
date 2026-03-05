"""LabletSession Data Transfer Objects for API responses.

Phase 7D: Replaces lablet_instance_dto.py.
Maps LabletSession aggregate to DTOs with child entity FK references
instead of embedded LDS/grading fields.

ADR-020: Session Entity Model — state fields renamed.
ADR-021: Child Entity Architecture — child refs via IDs, not embedded data.
"""

from dataclasses import dataclass
from typing import Any

from domain.entities.lablet_session import LabletSession


@dataclass
class StateTransitionDto:
    """DTO for a state transition in session history."""

    from_state: str | None
    to_state: str
    transitioned_at: str
    triggered_by: str
    reason: str | None
    metadata: dict[str, Any] | None


@dataclass
class LabletSessionCreatedDto:
    """DTO returned after creating a LabletSession."""

    id: str
    definition_id: str
    definition_name: str
    definition_version: str
    owner_id: str
    status: str
    timeslot_start: str
    timeslot_end: str
    reservation_id: str | None
    created_at: str


@dataclass
class LabletSessionSummaryDto:
    """Summary DTO for list queries — lightweight representation."""

    id: str
    definition_id: str
    definition_name: str
    definition_version: str
    owner_id: str
    status: str
    worker_id: str | None
    timeslot_start: str
    timeslot_end: str
    created_at: str
    started_at: str | None
    is_active: bool
    is_terminal: bool
    # Child entity FK references (ADR-021)
    user_session_id: str | None
    cml_lab_id: str | None
    # Cross-aggregate enrichment (Phase 1 UX)
    form_qualified_name: str | None
    node_count: int | None
    worker_name: str | None
    upstream_sync_status: dict | None
    lab_record_id: str | None
    grade_result: str | None


@dataclass
class LabletSessionDto:
    """Full DTO for single LabletSession retrieval."""

    # Identity
    id: str
    definition_id: str
    definition_name: str
    definition_version: str

    # Assignment
    worker_id: str | None
    lab_record_id: str | None
    allocated_ports: dict[str, int] | None
    cml_lab_id: str | None

    # Lifecycle
    status: str
    state_history: list[StateTransitionDto]

    # Timeslot
    timeslot_start: str
    timeslot_end: str
    duration_minutes: int

    # Ownership
    owner_id: str
    reservation_id: str | None

    # Child entity FK references (ADR-021)
    user_session_id: str | None
    grading_session_id: str | None
    score_report_id: str | None
    grade_result: str | None

    # Timestamps
    created_at: str
    scheduled_at: str | None
    started_at: str | None
    ended_at: str | None
    terminated_at: str | None

    # Computed
    is_active: bool
    is_terminal: bool
    can_be_terminated: bool
    actual_duration_minutes: int | None
    transition_count: int

    # Cross-aggregate enrichment (Phase 1 UX)
    form_qualified_name: str | None
    node_count: int | None
    worker_name: str | None
    worker_region: str | None
    resource_requirements: dict | None
    port_template: dict | None
    upstream_sync_status: dict | None
    upstream_version: str | None
    content_package_hash: str | None
    lab_record_status: str | None
    lab_record_node_count: int | None
    lab_record_link_count: int | None

    # Resource observation (ADR-030)
    observed_resources: dict | None
    observed_ports: dict[str, int] | None
    observation_count: int
    observed_at: str | None
    port_drift_detected: bool

    # Instantiation pipeline (ADR-031)
    instantiation_progress: dict | None


# ---------------------------------------------------------------------------
# Mapping Functions
# ---------------------------------------------------------------------------


def map_state_history_to_dto(state_history: list) -> list[StateTransitionDto]:
    """Map state history to DTOs.

    Args:
        state_history: List of StateTransition value objects

    Returns:
        List of StateTransitionDto
    """
    return [
        StateTransitionDto(
            from_state=transition.from_state.value if transition.from_state else None,
            to_state=transition.to_state.value,
            transitioned_at=transition.transitioned_at.isoformat(),
            triggered_by=transition.triggered_by,
            reason=transition.reason,
            metadata=transition.metadata,
        )
        for transition in state_history
    ]


def map_lablet_session_to_dto(
    entity: LabletSession,
    definition_enrichment: dict[str, Any] | None = None,
    worker_enrichment: dict[str, Any] | None = None,
    lab_record_enrichment: dict[str, Any] | None = None,
) -> LabletSessionDto:
    """Map a LabletSession entity to its full DTO representation.

    Args:
        entity: The LabletSession aggregate.
        definition_enrichment: Optional dict with keys form_qualified_name, node_count,
            resource_requirements, port_template, upstream_sync_status, upstream_version,
            content_package_hash from the LabletDefinition aggregate.
        worker_enrichment: Optional dict with keys name, aws_region from CMLWorker.
        lab_record_enrichment: Optional dict with keys status, node_count, link_count
            from the LabRecord aggregate.
    """
    state = entity.state
    defn = definition_enrichment or {}
    wkr = worker_enrichment or {}
    lab = lab_record_enrichment or {}

    return LabletSessionDto(
        # Identity
        id=entity.id(),
        definition_id=state.definition_id,
        definition_name=state.definition_name,
        definition_version=state.definition_version,
        # Assignment
        worker_id=state.worker_id,
        lab_record_id=state.lab_record_id,
        allocated_ports=state.allocated_ports,
        cml_lab_id=state.cml_lab_id,
        # Lifecycle
        status=state.status.value,
        state_history=map_state_history_to_dto(state.state_history),
        # Timeslot
        timeslot_start=state.timeslot_start.isoformat(),
        timeslot_end=state.timeslot_end.isoformat(),
        duration_minutes=entity.duration_minutes,
        # Ownership
        owner_id=state.owner_id,
        reservation_id=state.reservation_id,
        # Child entity FK references (ADR-021)
        user_session_id=state.user_session_id,
        grading_session_id=state.grading_session_id,
        score_report_id=state.score_report_id,
        grade_result=state.grade_result,
        # Timestamps
        created_at=state.created_at.isoformat(),
        scheduled_at=state.scheduled_at.isoformat() if state.scheduled_at else None,
        started_at=state.started_at.isoformat() if state.started_at else None,
        ended_at=state.ended_at.isoformat() if state.ended_at else None,
        terminated_at=state.terminated_at.isoformat() if state.terminated_at else None,
        # Computed
        is_active=entity.is_active,
        is_terminal=entity.is_terminal,
        can_be_terminated=entity.can_be_terminated,
        actual_duration_minutes=entity.actual_duration_minutes,
        transition_count=entity.transition_count,
        # Cross-aggregate enrichment
        form_qualified_name=defn.get("form_qualified_name"),
        node_count=defn.get("node_count"),
        worker_name=wkr.get("name"),
        worker_region=wkr.get("aws_region"),
        resource_requirements=defn.get("resource_requirements"),
        port_template=defn.get("port_template"),
        upstream_sync_status=defn.get("upstream_sync_status"),
        upstream_version=defn.get("upstream_version"),
        content_package_hash=defn.get("content_package_hash"),
        lab_record_status=lab.get("status"),
        lab_record_node_count=lab.get("node_count"),
        lab_record_link_count=lab.get("link_count"),
        # Resource observation (from session state)
        observed_resources=state.observed_resources,
        observed_ports=state.observed_ports,
        observation_count=state.observation_count,
        observed_at=state.observed_at.isoformat() if state.observed_at else None,
        port_drift_detected=state.port_drift_detected,
        # Instantiation pipeline (ADR-031)
        instantiation_progress=state.instantiation_progress,
    )


def map_lablet_session_to_summary_dto(
    entity: LabletSession,
    definition_enrichment: dict[str, Any] | None = None,
    worker_enrichment: dict[str, Any] | None = None,
) -> LabletSessionSummaryDto:
    """Map a LabletSession entity to a summary DTO for lists.

    Args:
        entity: The LabletSession aggregate.
        definition_enrichment: Optional dict with keys form_qualified_name, node_count,
            upstream_sync_status from the LabletDefinition aggregate.
        worker_enrichment: Optional dict with key name from CMLWorker.
    """
    state = entity.state
    defn = definition_enrichment or {}
    wkr = worker_enrichment or {}

    return LabletSessionSummaryDto(
        id=entity.id(),
        definition_id=state.definition_id,
        definition_name=state.definition_name,
        definition_version=state.definition_version,
        owner_id=state.owner_id,
        status=state.status.value,
        worker_id=state.worker_id,
        timeslot_start=state.timeslot_start.isoformat(),
        timeslot_end=state.timeslot_end.isoformat(),
        created_at=state.created_at.isoformat(),
        started_at=state.started_at.isoformat() if state.started_at else None,
        is_active=entity.is_active,
        is_terminal=entity.is_terminal,
        # Child entity FK references (ADR-021)
        user_session_id=state.user_session_id,
        cml_lab_id=state.cml_lab_id,
        # Cross-aggregate enrichment
        form_qualified_name=defn.get("form_qualified_name"),
        node_count=defn.get("node_count"),
        worker_name=wkr.get("name"),
        upstream_sync_status=defn.get("upstream_sync_status"),
        lab_record_id=state.lab_record_id,
        grade_result=state.grade_result,
    )
