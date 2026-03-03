"""Domain event handlers for Lab Record events that broadcast SSE updates.

These handlers translate lab record domain events into lightweight SSE messages
consumed by frontend components for real-time UI updates.

Legacy handlers (pre-Phase 8): LabRecordCreated, LabRecordUpdated, LabStateChanged
    → event_type: "worker.labs.updated" (backward compatible)

Phase 8 (P8-26) handlers — Architecture §8.6 SSE event types:
    lab.discovered          → LabRecordDiscoveredDomainEvent
    lab.status.updated      → LabRecordStartedDomainEvent, LabRecordStoppedDomainEvent,
                              LabRecordWipedDomainEvent, LabRecordDeletedDomainEvent,
                              LabRecordArchivedDomainEvent
    lab.topology.updated    → LabRecordRevisionCreatedDomainEvent
    lab.bound               → LabRecordBoundToLabletDomainEvent
    lab.unbound             → LabRecordUnboundFromLabletDomainEvent
    lab.action.requested    → LabActionRequestedDomainEvent
    lab.action.completed    → LabActionCompletedDomainEvent
    lab.action.failed       → LabActionFailedDomainEvent
    lab.run.completed       → (via command handler, not domain event SSE)
    lab.error               → LabRecordErrorDomainEvent, LabRecordOrphanedDomainEvent
    lab.cloned              → LabRecordClonedDomainEvent
"""

from __future__ import annotations

import logging

from neuroglia.mediation import DomainEventHandler

from application.services.sse_event_relay import SSEEventRelay
from domain.events.lab_record_events import (
    LabActionCompletedDomainEvent,
    LabActionFailedDomainEvent,
    LabActionRequestedDomainEvent,
    LabRecordArchivedDomainEvent,
    LabRecordBoundToLabletDomainEvent,
    LabRecordClonedDomainEvent,
    LabRecordCreatedDomainEvent,
    LabRecordDeletedDomainEvent,
    LabRecordDiscoveredDomainEvent,
    LabRecordErrorDomainEvent,
    LabRecordOrphanedDomainEvent,
    LabRecordRevisionCreatedDomainEvent,
    LabRecordStartedDomainEvent,
    LabRecordStoppedDomainEvent,
    LabRecordUnboundFromLabletDomainEvent,
    LabRecordUpdatedDomainEvent,
    LabRecordWipedDomainEvent,
    LabStateChangedDomainEvent,
)
from domain.repositories.lab_record_repository import LabRecordRepository

log = logging.getLogger(__name__)


def _utc_iso(dt) -> str | None:
    """Convert datetime to ISO format with Z suffix."""
    if dt is None:
        return None
    return dt.isoformat() + "Z"


# ==============================================================================
# Legacy SSE Handlers (backward compatible)
# ==============================================================================


class LabRecordCreatedDomainEventHandler(DomainEventHandler[LabRecordCreatedDomainEvent]):
    """Handle lab record created event by broadcasting SSE update."""

    def __init__(self, sse_relay: SSEEventRelay, repository: LabRecordRepository):
        self._sse_relay = sse_relay
        self._repository = repository

    async def handle_async(self, notification: LabRecordCreatedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast worker.labs.updated SSE event when lab is created."""
        await self._sse_relay.broadcast_event(
            event_type="worker.labs.updated",
            data={
                "worker_id": notification.worker_id,
                "lab_id": notification.lab_id,
                "action": "created",
                "title": notification.title,
                "state": notification.state,
                "node_count": notification.node_count,
                "link_count": notification.link_count,
                "owner_username": notification.owner_username,
                "first_seen_at": _utc_iso(notification.first_seen_at),
            },
            source="domain.lab_record",
        )

        log.debug(f"Broadcasted worker.labs.updated (created) for lab {notification.lab_id} on worker {notification.worker_id}")
        return None


class LabRecordUpdatedDomainEventHandler(DomainEventHandler[LabRecordUpdatedDomainEvent]):
    """Handle lab record updated event by broadcasting SSE update."""

    def __init__(self, sse_relay: SSEEventRelay, repository: LabRecordRepository):
        self._sse_relay = sse_relay
        self._repository = repository

    async def handle_async(self, notification: LabRecordUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast worker.labs.updated SSE event when lab is updated."""
        lab_record = await self._repository.get_by_id_async(notification.aggregate_id)
        if not lab_record:
            log.warning(f"Lab record {notification.aggregate_id} not found for SSE broadcast")
            return None

        await self._sse_relay.broadcast_event(
            event_type="worker.labs.updated",
            data={
                "worker_id": lab_record.state.worker_id,
                "lab_id": notification.lab_id,
                "action": "updated",
                "title": notification.title,
                "state": notification.state,
                "node_count": notification.node_count,
                "link_count": notification.link_count,
                "owner_username": notification.owner_username,
                "synced_at": _utc_iso(notification.synced_at),
            },
            source="domain.lab_record",
        )

        log.debug(f"Broadcasted worker.labs.updated (updated) for lab {notification.lab_id} on worker {lab_record.state.worker_id}")
        return None


class LabStateChangedDomainEventHandler(DomainEventHandler[LabStateChangedDomainEvent]):
    """Handle lab state changed event by broadcasting SSE update."""

    def __init__(self, sse_relay: SSEEventRelay, repository: LabRecordRepository):
        self._sse_relay = sse_relay
        self._repository = repository

    async def handle_async(self, notification: LabStateChangedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast worker.labs.updated SSE event when lab state changes."""
        lab_record = await self._repository.get_by_id_async(notification.aggregate_id)
        if not lab_record:
            log.warning(f"Lab record {notification.aggregate_id} not found for SSE broadcast")
            return None

        await self._sse_relay.broadcast_event(
            event_type="worker.labs.updated",
            data={
                "worker_id": lab_record.state.worker_id,
                "lab_id": notification.lab_id,
                "action": "state_changed",
                "previous_state": notification.previous_state,
                "new_state": notification.new_state,
                "changed_fields": notification.changed_fields,
                "changed_at": _utc_iso(notification.changed_at),
            },
            source="domain.lab_record",
        )

        log.debug(f"Broadcasted worker.labs.updated (state_changed) for lab {notification.lab_id} on worker {lab_record.state.worker_id}: {notification.previous_state} → {notification.new_state}")
        return None


# ==============================================================================
# Phase 8 SSE Handlers — Architecture §8.6
# ==============================================================================


class LabRecordDiscoveredDomainEventHandler(DomainEventHandler[LabRecordDiscoveredDomainEvent]):
    """Handle lab discovered event → SSE 'lab.discovered'."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabRecordDiscoveredDomainEvent) -> None:  # type: ignore[override]
        """Broadcast lab.discovered SSE event when a new lab is found on a worker."""
        await self._sse_relay.broadcast_event(
            event_type="lab.discovered",
            data={
                "lab_record_id": notification.aggregate_id,
                "worker_id": notification.worker_id,
                "lab_id": notification.lab_id,
                "title": notification.title,
                "state": notification.state,
                "owner": notification.owner_username,
                "node_count": notification.node_count,
                "link_count": notification.link_count,
                "discovered_at": _utc_iso(notification.discovered_at),
            },
            source="domain.lab_record",
        )
        log.debug("Broadcasted lab.discovered for lab %s on worker %s", notification.lab_id, notification.worker_id)
        return None


class LabRecordStartedDomainEventHandler(DomainEventHandler[LabRecordStartedDomainEvent]):
    """Handle lab started event → SSE 'lab.status.updated'."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabRecordStartedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast lab.status.updated SSE event when lab is started."""
        await self._sse_relay.broadcast_event(
            event_type="lab.status.updated",
            data={
                "lab_record_id": notification.aggregate_id,
                "lab_id": notification.lab_id,
                "action": "started",
                "status": "booted",
                "started_by": notification.started_by,
                "started_at": _utc_iso(notification.started_at),
            },
            source="domain.lab_record",
        )
        log.debug("Broadcasted lab.status.updated (started) for lab %s", notification.lab_id)
        return None


class LabRecordStoppedDomainEventHandler(DomainEventHandler[LabRecordStoppedDomainEvent]):
    """Handle lab stopped event → SSE 'lab.status.updated'."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabRecordStoppedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast lab.status.updated SSE event when lab is stopped."""
        await self._sse_relay.broadcast_event(
            event_type="lab.status.updated",
            data={
                "lab_record_id": notification.aggregate_id,
                "lab_id": notification.lab_id,
                "action": "stopped",
                "status": "stopped",
                "stop_reason": notification.stop_reason,
                "stopped_at": _utc_iso(notification.stopped_at),
            },
            source="domain.lab_record",
        )
        log.debug("Broadcasted lab.status.updated (stopped) for lab %s", notification.lab_id)
        return None


class LabRecordWipedDomainEventHandler(DomainEventHandler[LabRecordWipedDomainEvent]):
    """Handle lab wiped event → SSE 'lab.status.updated'."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabRecordWipedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast lab.status.updated SSE event when lab is wiped."""
        await self._sse_relay.broadcast_event(
            event_type="lab.status.updated",
            data={
                "lab_record_id": notification.aggregate_id,
                "lab_id": notification.lab_id,
                "action": "wiped",
                "status": "wiped",
                "wiped_at": _utc_iso(notification.wiped_at),
            },
            source="domain.lab_record",
        )
        log.debug("Broadcasted lab.status.updated (wiped) for lab %s", notification.lab_id)
        return None


class LabRecordDeletedDomainEventHandler(DomainEventHandler[LabRecordDeletedDomainEvent]):
    """Handle lab deleted event → SSE 'lab.status.updated'."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabRecordDeletedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast lab.status.updated SSE event when lab is deleted."""
        await self._sse_relay.broadcast_event(
            event_type="lab.status.updated",
            data={
                "lab_record_id": notification.aggregate_id,
                "lab_id": notification.lab_id,
                "action": "deleted",
                "status": "deleted",
                "deleted_by": notification.deleted_by,
                "deleted_at": _utc_iso(notification.deleted_at),
            },
            source="domain.lab_record",
        )
        log.debug("Broadcasted lab.status.updated (deleted) for lab %s", notification.lab_id)
        return None


class LabRecordArchivedDomainEventHandler(DomainEventHandler[LabRecordArchivedDomainEvent]):
    """Handle lab archived event → SSE 'lab.status.updated'."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabRecordArchivedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast lab.status.updated SSE event when lab is archived."""
        await self._sse_relay.broadcast_event(
            event_type="lab.status.updated",
            data={
                "lab_record_id": notification.aggregate_id,
                "lab_id": notification.lab_id,
                "action": "archived",
                "status": "archived",
                "archived_by": notification.archived_by,
                "archived_at": _utc_iso(notification.archived_at),
            },
            source="domain.lab_record",
        )
        log.debug("Broadcasted lab.status.updated (archived) for lab %s", notification.lab_id)
        return None


class LabRecordClonedDomainEventHandler(DomainEventHandler[LabRecordClonedDomainEvent]):
    """Handle lab cloned event → SSE 'lab.cloned'."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabRecordClonedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast lab.cloned SSE event when a lab is cloned."""
        await self._sse_relay.broadcast_event(
            event_type="lab.cloned",
            data={
                "lab_record_id": notification.aggregate_id,
                "lab_id": notification.lab_id,
                "source_lab_record_id": notification.source_lab_record_id,
                "cloned_by": notification.cloned_by,
                "cloned_at": _utc_iso(notification.cloned_at),
            },
            source="domain.lab_record",
        )
        log.debug("Broadcasted lab.cloned for lab %s (source: %s)", notification.lab_id, notification.source_lab_record_id)
        return None


class LabRecordRevisionCreatedDomainEventHandler(DomainEventHandler[LabRecordRevisionCreatedDomainEvent]):
    """Handle topology revision created → SSE 'lab.topology.updated'."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabRecordRevisionCreatedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast lab.topology.updated SSE event when a new revision is created."""
        await self._sse_relay.broadcast_event(
            event_type="lab.topology.updated",
            data={
                "lab_record_id": notification.aggregate_id,
                "lab_id": notification.lab_id,
                "revision": notification.revision,
                "topology_checksum": notification.topology_checksum,
                "previous_checksum": notification.previous_checksum,
                "change_summary": notification.change_summary,
                "node_count": notification.node_count,
                "link_count": notification.link_count,
                "created_at": _utc_iso(notification.created_at),
            },
            source="domain.lab_record",
        )
        log.debug("Broadcasted lab.topology.updated (revision %d) for lab %s", notification.revision, notification.lab_id)
        return None


class LabRecordBoundToLabletDomainEventHandler(DomainEventHandler[LabRecordBoundToLabletDomainEvent]):
    """Handle lab bound to lablet → SSE 'lab.bound'."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabRecordBoundToLabletDomainEvent) -> None:  # type: ignore[override]
        """Broadcast lab.bound SSE event when a lab is bound to a lablet."""
        await self._sse_relay.broadcast_event(
            event_type="lab.bound",
            data={
                "lab_record_id": notification.aggregate_id,
                "lab_id": notification.lab_id,
                "lablet_session_id": notification.lablet_session_id,
                "binding_id": notification.binding_id,
                "binding_role": notification.binding_role,
                "bound_at": _utc_iso(notification.bound_at),
            },
            source="domain.lab_record",
        )
        log.debug("Broadcasted lab.bound for lab %s → session %s", notification.lab_id, notification.lablet_session_id)
        return None


class LabRecordUnboundFromLabletDomainEventHandler(DomainEventHandler[LabRecordUnboundFromLabletDomainEvent]):
    """Handle lab unbound from lablet → SSE 'lab.unbound'."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabRecordUnboundFromLabletDomainEvent) -> None:  # type: ignore[override]
        """Broadcast lab.unbound SSE event when a lab is unbound from a lablet."""
        await self._sse_relay.broadcast_event(
            event_type="lab.unbound",
            data={
                "lab_record_id": notification.aggregate_id,
                "lab_id": notification.lab_id,
                "lablet_session_id": notification.lablet_session_id,
                "binding_id": notification.binding_id,
                "unbound_at": _utc_iso(notification.unbound_at),
            },
            source="domain.lab_record",
        )
        log.debug("Broadcasted lab.unbound for lab %s from session %s", notification.lab_id, notification.lablet_session_id)
        return None


class LabActionRequestedDomainEventHandler(DomainEventHandler[LabActionRequestedDomainEvent]):
    """Handle lab action requested → SSE 'lab.action.requested'."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabActionRequestedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast lab.action.requested SSE event when a pending action is set."""
        await self._sse_relay.broadcast_event(
            event_type="lab.action.requested",
            data={
                "lab_record_id": notification.aggregate_id,
                "lab_id": notification.lab_id,
                "action": notification.action,
                "requested_at": _utc_iso(notification.requested_at),
            },
            source="domain.lab_record",
        )
        log.debug("Broadcasted lab.action.requested (%s) for lab %s", notification.action, notification.lab_id)
        return None


class LabActionCompletedDomainEventHandler(DomainEventHandler[LabActionCompletedDomainEvent]):
    """Handle lab action completed → SSE 'lab.action.completed'."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabActionCompletedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast lab.action.completed SSE event when a pending action succeeds."""
        await self._sse_relay.broadcast_event(
            event_type="lab.action.completed",
            data={
                "lab_record_id": notification.aggregate_id,
                "lab_id": notification.lab_id,
                "action": notification.action,
                "completed_at": _utc_iso(notification.completed_at),
            },
            source="domain.lab_record",
        )
        log.debug("Broadcasted lab.action.completed (%s) for lab %s", notification.action, notification.lab_id)
        return None


class LabActionFailedDomainEventHandler(DomainEventHandler[LabActionFailedDomainEvent]):
    """Handle lab action failed → SSE 'lab.action.failed'."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabActionFailedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast lab.action.failed SSE event when a pending action fails."""
        await self._sse_relay.broadcast_event(
            event_type="lab.action.failed",
            data={
                "lab_record_id": notification.aggregate_id,
                "lab_id": notification.lab_id,
                "action": notification.action,
                "error_message": notification.error_message,
                "failed_at": _utc_iso(notification.failed_at),
            },
            source="domain.lab_record",
        )
        log.debug("Broadcasted lab.action.failed (%s) for lab %s: %s", notification.action, notification.lab_id, notification.error_message)
        return None


class LabRecordErrorDomainEventHandler(DomainEventHandler[LabRecordErrorDomainEvent]):
    """Handle lab error event → SSE 'lab.error'."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabRecordErrorDomainEvent) -> None:  # type: ignore[override]
        """Broadcast lab.error SSE event when a lab transitions to error state."""
        await self._sse_relay.broadcast_event(
            event_type="lab.error",
            data={
                "lab_record_id": notification.aggregate_id,
                "lab_id": notification.lab_id,
                "error_message": notification.error_message,
                "previous_status": notification.previous_status,
                "occurred_at": _utc_iso(notification.occurred_at),
            },
            source="domain.lab_record",
        )
        log.debug("Broadcasted lab.error for lab %s: %s", notification.lab_id, notification.error_message)
        return None


class LabRecordOrphanedDomainEventHandler(DomainEventHandler[LabRecordOrphanedDomainEvent]):
    """Handle lab orphaned event → SSE 'lab.error' (orphaned is an error condition)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabRecordOrphanedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast lab.error SSE event when a lab is marked orphaned."""
        await self._sse_relay.broadcast_event(
            event_type="lab.error",
            data={
                "lab_record_id": notification.aggregate_id,
                "lab_id": notification.lab_id,
                "worker_id": notification.worker_id,
                "action": "orphaned",
                "orphaned_at": _utc_iso(notification.orphaned_at),
            },
            source="domain.lab_record",
        )
        log.debug("Broadcasted lab.error (orphaned) for lab %s on worker %s", notification.lab_id, notification.worker_id)
        return None
