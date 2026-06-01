"""Domain event handlers for Lablet Definition events that broadcast SSE updates (ADR-013).

These handlers translate LabletDefinition domain events into lightweight SSE messages
consumed by frontend components for real-time UI updates.
"""

from __future__ import annotations

import logging
from datetime import datetime

from neuroglia.mediation import DomainEventHandler

from application.services.sse_event_relay import SSEEventRelay
from domain.events.lablet_definition_events import (
    LabletDefinitionActivatedDomainEvent,
    LabletDefinitionContentSyncedDomainEvent,
    LabletDefinitionCreatedDomainEvent,
    LabletDefinitionDeactivatedDomainEvent,
    LabletDefinitionDeletedDomainEvent,
    LabletDefinitionDeprecatedDomainEvent,
    LabletDefinitionSyncRequestedDomainEvent,
    LabletDefinitionUpdatedDomainEvent,
    LabletDefinitionVersionCreatedDomainEvent,
    LabletDefinitionWarmPoolUpdatedDomainEvent,
)

log = logging.getLogger(__name__)


def _utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat() + "Z"


class LabletDefinitionCreatedDomainEventHandler(DomainEventHandler[LabletDefinitionCreatedDomainEvent]):
    """SSE handler for lablet definition created events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletDefinitionCreatedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.definition.created",
            data={
                "definition_id": notification.aggregate_id,
                "name": notification.name,
                "version": notification.version,
                "node_count": notification.node_count,
                "max_duration_minutes": notification.max_duration_minutes,
                "created_by": notification.created_by,
                "created_at": _utc_iso(notification.created_at),
            },
            source="domain.lablet_definition",
        )
        log.info("Broadcasted lablet.definition.created for %s", notification.aggregate_id)
        return None


class LabletDefinitionUpdatedDomainEventHandler(DomainEventHandler[LabletDefinitionUpdatedDomainEvent]):
    """SSE handler for lablet definition updated events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletDefinitionUpdatedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.definition.updated",
            data={
                "definition_id": notification.aggregate_id,
                "changes": notification.changes,
                "updated_by": notification.updated_by,
                "updated_at": _utc_iso(notification.updated_at),
            },
            source="domain.lablet_definition",
        )
        log.info("Broadcasted lablet.definition.updated for %s", notification.aggregate_id)
        return None


class LabletDefinitionActivatedDomainEventHandler(DomainEventHandler[LabletDefinitionActivatedDomainEvent]):
    """SSE handler for lablet definition activated events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletDefinitionActivatedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.definition.activated",
            data={
                "definition_id": notification.aggregate_id,
                "activated_by": notification.activated_by,
                "activated_at": _utc_iso(notification.activated_at),
            },
            source="domain.lablet_definition",
        )
        log.info("Broadcasted lablet.definition.activated for %s", notification.aggregate_id)
        return None


class LabletDefinitionDeactivatedDomainEventHandler(DomainEventHandler[LabletDefinitionDeactivatedDomainEvent]):
    """SSE handler for lablet definition deactivated events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletDefinitionDeactivatedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.definition.deactivated",
            data={
                "definition_id": notification.aggregate_id,
                "deactivated_by": notification.deactivated_by,
                "deactivated_at": _utc_iso(notification.deactivated_at),
            },
            source="domain.lablet_definition",
        )
        log.info("Broadcasted lablet.definition.deactivated for %s", notification.aggregate_id)
        return None


class LabletDefinitionDeletedDomainEventHandler(DomainEventHandler[LabletDefinitionDeletedDomainEvent]):
    """SSE handler for lablet definition deleted events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletDefinitionDeletedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.definition.deleted",
            data={
                "definition_id": notification.aggregate_id,
                "deleted_by": notification.deleted_by,
                "deleted_at": _utc_iso(notification.deleted_at),
            },
            source="domain.lablet_definition",
        )
        log.info("Broadcasted lablet.definition.deleted for %s", notification.aggregate_id)
        return None


class LabletDefinitionContentSyncedDomainEventHandler(DomainEventHandler[LabletDefinitionContentSyncedDomainEvent]):
    """SSE handler for lablet definition content sync completed events.

    Broadcasts when the lablet-controller reports sync results (success or failure).
    This is the critical event that transitions a definition from PENDING_SYNC → ACTIVE.
    """

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletDefinitionContentSyncedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.definition.content_synced",
            data={
                "definition_id": notification.aggregate_id,
                "sync_status": notification.sync_status,
                "error_message": notification.error_message,
                "lab_yaml_hash": notification.lab_yaml_hash,
                "content_package_hash": notification.content_package_hash,
                "synced_at": _utc_iso(notification.synced_at),
            },
            source="domain.lablet_definition",
        )
        log.info(
            "Broadcasted lablet.definition.content_synced for %s (status=%s)",
            notification.aggregate_id,
            notification.sync_status,
        )
        return None


class LabletDefinitionDeprecatedDomainEventHandler(DomainEventHandler[LabletDefinitionDeprecatedDomainEvent]):
    """SSE handler for lablet definition deprecated events.

    Broadcasts when a definition is deprecated (e.g., superseded by a new version).
    """

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletDefinitionDeprecatedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.definition.deprecated",
            data={
                "definition_id": notification.aggregate_id,
                "name": notification.name,
                "version": notification.version,
                "deprecated_by": notification.deprecated_by,
                "deprecated_at": _utc_iso(notification.deprecated_at),
                "deprecation_reason": notification.deprecation_reason,
                "replacement_version": notification.replacement_version,
            },
            source="domain.lablet_definition",
        )
        log.info("Broadcasted lablet.definition.deprecated for %s", notification.aggregate_id)
        return None


class LabletDefinitionSyncRequestedDomainEventHandler(DomainEventHandler[LabletDefinitionSyncRequestedDomainEvent]):
    """SSE handler for lablet definition sync requested events.

    Broadcasts when a user requests content synchronization for a definition.
    Used by the frontend to show immediate feedback (sync in progress indicator).
    """

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletDefinitionSyncRequestedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.definition.sync_requested",
            data={
                "definition_id": notification.aggregate_id,
                "form_qualified_name": notification.form_qualified_name,
                "bucket_name": notification.bucket_name,
                "requested_by": notification.requested_by,
                "requested_at": notification.requested_at,
            },
            source="domain.lablet_definition",
        )
        log.info("Broadcasted lablet.definition.sync_requested for %s", notification.aggregate_id)
        return None


class LabletDefinitionVersionCreatedDomainEventHandler(DomainEventHandler[LabletDefinitionVersionCreatedDomainEvent]):
    """SSE handler for lablet definition version created events.

    Broadcasts when a new version of a definition is created (version bump).
    Used by the frontend to update definition cards with new version info.
    """

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletDefinitionVersionCreatedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.definition.version_created",
            data={
                "definition_id": notification.aggregate_id,
                "name": notification.name,
                "version": notification.version,
                "previous_version": notification.previous_version,
                "node_count": notification.node_count,
                "created_by": notification.created_by,
                "created_at": _utc_iso(notification.created_at),
            },
            source="domain.lablet_definition",
        )
        log.info("Broadcasted lablet.definition.version_created for %s (v%s)", notification.aggregate_id, notification.version)
        return None


class LabletDefinitionWarmPoolUpdatedDomainEventHandler(DomainEventHandler[LabletDefinitionWarmPoolUpdatedDomainEvent]):
    """SSE handler for lablet definition warm pool updated events.

    Broadcasts when a definition's warm pool depth is changed.
    Used by the frontend to reflect warm pool configuration changes.
    """

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: LabletDefinitionWarmPoolUpdatedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="lablet.definition.warm_pool_updated",
            data={
                "definition_id": notification.aggregate_id,
                "old_warm_pool_depth": notification.old_warm_pool_depth,
                "new_warm_pool_depth": notification.new_warm_pool_depth,
                "updated_by": notification.updated_by,
                "updated_at": _utc_iso(notification.updated_at),
            },
            source="domain.lablet_definition",
        )
        log.info("Broadcasted lablet.definition.warm_pool_updated for %s", notification.aggregate_id)
        return None
