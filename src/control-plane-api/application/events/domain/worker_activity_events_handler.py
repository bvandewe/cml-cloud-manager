"""Domain event handlers for Worker Activity events that broadcast SSE updates.

These handlers translate worker activity/pause/resume/idle detection domain events
into lightweight SSE messages consumed by frontend components for real-time UI updates.

NOTE: These handlers send MINIMAL event data only. Full worker snapshots are broadcast
by cml_worker_events.py handlers using proper DTO mapping via Neuroglia Mapper.
"""

import logging
from datetime import datetime

from neuroglia.mediation import DomainEventHandler

from application.services.sse_event_relay import SSEEventRelay
from domain.events.worker_activity_events import (
    IdleDetectionToggledDomainEvent,
    WorkerActivityUpdatedDomainEvent,
    WorkerPausedDomainEvent,
    WorkerResumedDomainEvent,
)

log = logging.getLogger(__name__)


def _utc_iso(dt: datetime | None) -> str | None:
    """Convert datetime to ISO 8601 string with Z suffix."""
    if dt is None:
        return None
    return dt.isoformat() + "Z"


class IdleDetectionToggledDomainEventHandler(DomainEventHandler[IdleDetectionToggledDomainEvent]):
    """Handle idle detection toggled events by broadcasting SSE updates."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: IdleDetectionToggledDomainEvent) -> None:  # type: ignore[override]
        """Broadcast idle detection toggle event via SSE."""
        await self._sse_relay.broadcast_event(
            event_type="worker.idle_detection.toggled",
            data={
                "worker_id": notification.aggregate_id,
                "is_enabled": notification.is_enabled,
                "toggled_by": notification.toggled_by,
                "toggled_at": _utc_iso(notification.toggled_at),
            },
            source="domain.worker_activity",
        )

        log.info(f"Broadcasted idle detection toggle for worker {notification.aggregate_id}: " f"{'enabled' if notification.is_enabled else 'disabled'}")
        return None


class WorkerActivityUpdatedDomainEventHandler(DomainEventHandler[WorkerActivityUpdatedDomainEvent]):
    """Handle worker activity updates by broadcasting SSE updates."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: WorkerActivityUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast worker activity update event via SSE."""
        await self._sse_relay.broadcast_event(
            event_type="worker.activity.updated",
            data={
                "worker_id": notification.aggregate_id,
                "last_activity_at": _utc_iso(notification.last_activity_at),
                "last_activity_check_at": _utc_iso(notification.last_activity_check_at),
                "next_idle_check_at": _utc_iso(notification.next_idle_check_at),
                "target_pause_at": _utc_iso(notification.target_pause_at),
                "updated_at": _utc_iso(notification.updated_at),
            },
            source="domain.worker_activity",
        )

        log.debug(f"Broadcasted activity update for worker {notification.aggregate_id}")
        return None


class WorkerPausedDomainEventHandler(DomainEventHandler[WorkerPausedDomainEvent]):
    """Handle worker paused events by broadcasting SSE updates."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: WorkerPausedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast worker paused event via SSE."""
        await self._sse_relay.broadcast_event(
            event_type="worker.paused",
            data={
                "worker_id": notification.aggregate_id,
                "pause_reason": notification.pause_reason,
                "paused_by": notification.paused_by,
                "paused_at": _utc_iso(notification.paused_at),
                "auto_pause_count": notification.auto_pause_count,
                "manual_pause_count": notification.manual_pause_count,
                "idle_duration_minutes": notification.idle_duration_minutes,
            },
            source="domain.worker_activity",
        )

        log.info(f"Broadcasted worker paused event for {notification.aggregate_id}: " f"reason={notification.pause_reason}, by={notification.paused_by}")
        return None


class WorkerResumedDomainEventHandler(DomainEventHandler[WorkerResumedDomainEvent]):
    """Handle worker resumed events by broadcasting SSE updates."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: WorkerResumedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast worker resumed event via SSE."""
        await self._sse_relay.broadcast_event(
            event_type="worker.resumed",
            data={
                "worker_id": notification.aggregate_id,
                "resume_reason": notification.resume_reason,
                "resumed_by": notification.resumed_by,
                "resumed_at": _utc_iso(notification.resumed_at),
                "auto_resume_count": notification.auto_resume_count,
                "manual_resume_count": notification.manual_resume_count,
                "was_auto_paused": notification.was_auto_paused,
            },
            source="domain.worker_activity",
        )

        log.info(f"Broadcasted worker resumed event for {notification.aggregate_id}: " f"reason={notification.resume_reason}, by={notification.resumed_by}")
        return None
