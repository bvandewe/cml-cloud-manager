"""Domain event handlers for LabletSession events that broadcast SSE updates (ADR-013).

Phase 7D: Replaces lablet_instance_sse_handlers.py.
Translates LabletSession domain events into lightweight SSE messages
consumed by frontend components for real-time UI updates.

Event types follow the convention:
- ``lablet.session.created`` — Initial creation
- ``lablet.session.status.changed`` — All lifecycle transitions (with ``status`` field)
- ``lablet.session.score.recorded`` — Score report finalized
- ``lablet.session.ports.released`` — Ports returned to worker pool
- ``lablet.session.timeslot.extended`` — Timeslot extended
- ``lablet.session.terminated`` — Terminal state reached

ADR-013 Phase 5: Client-side SSE event type filtering.
ADR-020: Session Entity Model — renamed from lablet.instance.* to lablet.session.*
"""

from __future__ import annotations

import logging
from datetime import datetime

from neuroglia.mediation import DomainEventHandler

from application.services.sse_event_relay import SSEEventRelay
from domain.events.lablet_session_events import (
    LabletSessionArchivedDomainEvent,
    LabletSessionCollectingDomainEvent,
    LabletSessionCreatedDomainEvent,
    LabletSessionDesiredStatusUpdatedDomainEvent,
    LabletSessionGradingDomainEvent,
    LabletSessionInstantiatingDomainEvent,
    LabletSessionPipelineProgressUpdatedDomainEvent,
    LabletSessionPortsReleasedDomainEvent,
    LabletSessionReadyDomainEvent,
    LabletSessionRunningDomainEvent,
    LabletSessionScheduledDomainEvent,
    LabletSessionScoreRecordedDomainEvent,
    LabletSessionStoppedDomainEvent,
    LabletSessionStoppingDomainEvent,
    LabletSessionTerminatedDomainEvent,
    LabletSessionTimeslotExtendedDomainEvent,
)

log = logging.getLogger(__name__)


def _utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat() + "Z"


# ---------------------------------------------------------------------------
# 1. Created
# ---------------------------------------------------------------------------


class LabletSessionCreatedDomainEventHandler(DomainEventHandler[LabletSessionCreatedDomainEvent]):
    """SSE handler for lablet session created events (ADR-013).

    AD-SSE-RACE-001 Fix 4: Enriched payload to include status, timeslot,
    and definition metadata so SSE-only clients (e.g. other browser tabs)
    can render a complete table row without an HTTP refetch.
    """

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletSessionCreatedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.session.created",
            data={
                "session_id": notification.aggregate_id,
                "status": "pending",
                "definition_id": notification.definition_id,
                "definition_name": notification.definition_name,
                "definition_version": notification.definition_version,
                "owner_id": notification.owner_id,
                "timeslot_start": _utc_iso(notification.timeslot_start),
                "timeslot_end": _utc_iso(notification.timeslot_end),
                "reservation_id": notification.reservation_id,
                "created_at": _utc_iso(notification.created_at),
            },
            source="domain.lablet_session",
        )
        log.info("Broadcasted lablet.session.created for %s", notification.aggregate_id)
        return None


# ---------------------------------------------------------------------------
# 2. Scheduled
# ---------------------------------------------------------------------------


class LabletSessionScheduledDomainEventHandler(DomainEventHandler[LabletSessionScheduledDomainEvent]):
    """SSE handler for lablet session scheduled events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletSessionScheduledDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.session.status.changed",
            data={
                "session_id": notification.aggregate_id,
                "status": "scheduled",
                "worker_id": notification.worker_id,
                "scheduled_at": _utc_iso(notification.scheduled_at),
            },
            source="domain.lablet_session",
        )
        log.info("Broadcasted lablet.session.status.changed (scheduled) for %s", notification.aggregate_id)
        return None


# ---------------------------------------------------------------------------
# 3. Instantiating
# ---------------------------------------------------------------------------


class LabletSessionInstantiatingDomainEventHandler(DomainEventHandler[LabletSessionInstantiatingDomainEvent]):
    """SSE handler for lablet session instantiating events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletSessionInstantiatingDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.session.status.changed",
            data={
                "session_id": notification.aggregate_id,
                "status": "instantiating",
                "instantiation_started_at": _utc_iso(notification.instantiation_started_at),
            },
            source="domain.lablet_session",
        )
        log.info("Broadcasted lablet.session.status.changed (instantiating) for %s", notification.aggregate_id)
        return None


# ---------------------------------------------------------------------------
# 4. Ready
# ---------------------------------------------------------------------------


class LabletSessionReadyDomainEventHandler(DomainEventHandler[LabletSessionReadyDomainEvent]):
    """SSE handler for lablet session ready events (ADR-013).

    Broadcasts READY status with UserSession FK reference so the frontend
    can fetch the user session for the "Open Lab" button.
    """

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletSessionReadyDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.session.status.changed",
            data={
                "session_id": notification.aggregate_id,
                "status": "ready",
                "user_session_id": notification.user_session_id,
                "cml_lab_id": notification.cml_lab_id,
                "ready_at": _utc_iso(notification.ready_at),
            },
            source="domain.lablet_session",
        )
        log.info("Broadcasted lablet.session.status.changed (ready) for %s", notification.aggregate_id)
        return None


# ---------------------------------------------------------------------------
# 5. Running
# ---------------------------------------------------------------------------


class LabletSessionRunningDomainEventHandler(DomainEventHandler[LabletSessionRunningDomainEvent]):
    """SSE handler for lablet session running events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletSessionRunningDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.session.status.changed",
            data={
                "session_id": notification.aggregate_id,
                "status": "running",
                "started_at": _utc_iso(notification.started_at),
            },
            source="domain.lablet_session",
        )
        log.info("Broadcasted lablet.session.status.changed (running) for %s", notification.aggregate_id)
        return None


# ---------------------------------------------------------------------------
# 6. Collecting
# ---------------------------------------------------------------------------


class LabletSessionCollectingDomainEventHandler(DomainEventHandler[LabletSessionCollectingDomainEvent]):
    """SSE handler for lablet session collecting events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletSessionCollectingDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.session.status.changed",
            data={
                "session_id": notification.aggregate_id,
                "status": "collecting",
                "collection_started_at": _utc_iso(notification.collection_started_at),
            },
            source="domain.lablet_session",
        )
        log.info("Broadcasted lablet.session.status.changed (collecting) for %s", notification.aggregate_id)
        return None


# ---------------------------------------------------------------------------
# 7. Grading
# ---------------------------------------------------------------------------


class LabletSessionGradingDomainEventHandler(DomainEventHandler[LabletSessionGradingDomainEvent]):
    """SSE handler for lablet session grading events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletSessionGradingDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.session.status.changed",
            data={
                "session_id": notification.aggregate_id,
                "status": "grading",
                "grading_session_id": notification.grading_session_id,
                "grading_started_at": _utc_iso(notification.grading_started_at),
            },
            source="domain.lablet_session",
        )
        log.info("Broadcasted lablet.session.status.changed (grading) for %s", notification.aggregate_id)
        return None


# ---------------------------------------------------------------------------
# 8. ScoreRecorded
# ---------------------------------------------------------------------------


class LabletSessionScoreRecordedDomainEventHandler(DomainEventHandler[LabletSessionScoreRecordedDomainEvent]):
    """SSE handler for score recorded events (ADR-013).

    This does NOT change session status — it broadcasts separately
    so the UI can show the score independently.
    """

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletSessionScoreRecordedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.session.score.recorded",
            data={
                "session_id": notification.aggregate_id,
                "score_report_id": notification.score_report_id,
                "grade_result": notification.grade_result,
                "scored_at": _utc_iso(notification.scored_at),
            },
            source="domain.lablet_session",
        )
        log.info("Broadcasted lablet.session.score.recorded for %s", notification.aggregate_id)
        return None


# ---------------------------------------------------------------------------
# 9. Stopping
# ---------------------------------------------------------------------------


class LabletSessionStoppingDomainEventHandler(DomainEventHandler[LabletSessionStoppingDomainEvent]):
    """SSE handler for lablet session stopping events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletSessionStoppingDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.session.status.changed",
            data={
                "session_id": notification.aggregate_id,
                "status": "stopping",
                "stopping_started_at": _utc_iso(notification.stopping_started_at),
                "reason": notification.reason,
            },
            source="domain.lablet_session",
        )
        log.info("Broadcasted lablet.session.status.changed (stopping) for %s", notification.aggregate_id)
        return None


# ---------------------------------------------------------------------------
# 10. Stopped
# ---------------------------------------------------------------------------


class LabletSessionStoppedDomainEventHandler(DomainEventHandler[LabletSessionStoppedDomainEvent]):
    """SSE handler for lablet session stopped events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletSessionStoppedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.session.status.changed",
            data={
                "session_id": notification.aggregate_id,
                "status": "stopped",
                "stopped_at": _utc_iso(notification.stopped_at),
                "duration_seconds": notification.duration_seconds,
            },
            source="domain.lablet_session",
        )
        log.info("Broadcasted lablet.session.status.changed (stopped) for %s", notification.aggregate_id)
        return None


# ---------------------------------------------------------------------------
# 11. Archived
# ---------------------------------------------------------------------------


class LabletSessionArchivedDomainEventHandler(DomainEventHandler[LabletSessionArchivedDomainEvent]):
    """SSE handler for lablet session archived events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletSessionArchivedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.session.status.changed",
            data={
                "session_id": notification.aggregate_id,
                "status": "archived",
                "archived_at": _utc_iso(notification.archived_at),
                "archived_by": notification.archived_by,
            },
            source="domain.lablet_session",
        )
        log.info("Broadcasted lablet.session.status.changed (archived) for %s", notification.aggregate_id)
        return None


# ---------------------------------------------------------------------------
# 12. Terminated
# ---------------------------------------------------------------------------


class LabletSessionTerminatedDomainEventHandler(DomainEventHandler[LabletSessionTerminatedDomainEvent]):
    """SSE handler for lablet session terminated events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletSessionTerminatedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.session.terminated",
            data={
                "session_id": notification.aggregate_id,
                "terminated_at": _utc_iso(notification.terminated_at),
                "terminated_by": notification.terminated_by,
                "reason": notification.reason,
                "from_state": notification.from_state,
            },
            source="domain.lablet_session",
        )
        log.info("Broadcasted lablet.session.terminated for %s", notification.aggregate_id)
        return None


# ---------------------------------------------------------------------------
# 13. PortsReleased
# ---------------------------------------------------------------------------


class LabletSessionPortsReleasedDomainEventHandler(DomainEventHandler[LabletSessionPortsReleasedDomainEvent]):
    """SSE handler for ports released events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletSessionPortsReleasedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.session.ports.released",
            data={
                "session_id": notification.aggregate_id,
                "worker_id": notification.worker_id,
                "released_ports": notification.released_ports,
                "released_at": _utc_iso(notification.released_at),
            },
            source="domain.lablet_session",
        )
        log.info("Broadcasted lablet.session.ports.released for %s", notification.aggregate_id)
        return None


# ---------------------------------------------------------------------------
# 14. TimeslotExtended
# ---------------------------------------------------------------------------


class LabletSessionTimeslotExtendedDomainEventHandler(DomainEventHandler[LabletSessionTimeslotExtendedDomainEvent]):
    """SSE handler for timeslot extended events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletSessionTimeslotExtendedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.session.timeslot.extended",
            data={
                "session_id": notification.aggregate_id,
                "old_timeslot_end": _utc_iso(notification.old_timeslot_end),
                "new_timeslot_end": _utc_iso(notification.new_timeslot_end),
                "extended_by": notification.extended_by,
                "extended_at": _utc_iso(notification.extended_at),
            },
            source="domain.lablet_session",
        )
        log.info("Broadcasted lablet.session.timeslot.extended for %s", notification.aggregate_id)
        return None


# ---------------------------------------------------------------------------
# 15. InstantiationProgressUpdated (ADR-031) — DEPRECATED
# Removed: Superseded by LabletSessionPipelineProgressUpdatedSSEHandler
# which handles all pipeline types including "instantiate".
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 16. PipelineProgressUpdated — Generic (ADR-034 Sprint E)
# ---------------------------------------------------------------------------


class LabletSessionPipelineProgressUpdatedSSEHandler(DomainEventHandler[LabletSessionPipelineProgressUpdatedDomainEvent]):
    """SSE handler for generic pipeline progress events (ADR-034 Sprint E).

    Broadcasts step-level progress updates for all pipeline types
    (instantiate, teardown, collect_evidence, compute_grading).
    """

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletSessionPipelineProgressUpdatedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.session.pipeline.progress",
            data={
                "session_id": notification.aggregate_id,
                "pipeline_name": notification.pipeline_name,
                "step_name": notification.step_name,
                "step_status": notification.step_status,
                "progress": notification.progress_data,
                "updated_at": _utc_iso(notification.updated_at),
            },
            source="domain.lablet_session",
        )
        log.info(
            "Broadcasted lablet.session.pipeline.progress (%s/%s) for %s",
            notification.pipeline_name,
            notification.step_name,
            notification.aggregate_id,
        )
        return None


# ---------------------------------------------------------------------------
# 17. DesiredStatusUpdated — Spec change for reconciliation (ADR-034 Sprint E)
# ---------------------------------------------------------------------------


class LabletSessionDesiredStatusUpdatedSSEHandler(DomainEventHandler[LabletSessionDesiredStatusUpdatedDomainEvent]):
    """SSE handler for desired_status changes (ADR-034 Sprint E / ADR-015).

    Broadcasts desired_status updates so the UI can show the reconciliation
    target alongside the current status.
    """

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletSessionDesiredStatusUpdatedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.session.desired_status.changed",
            data={
                "session_id": notification.aggregate_id,
                "old_desired_status": notification.old_desired_status,
                "new_desired_status": notification.new_desired_status,
                "requested_by": notification.requested_by,
                "reason": notification.reason,
                "updated_at": _utc_iso(notification.updated_at),
            },
            source="domain.lablet_session",
        )
        log.info(
            "Broadcasted lablet.session.desired_status.changed for %s: %s → %s",
            notification.aggregate_id,
            notification.old_desired_status,
            notification.new_desired_status,
        )
        return None
