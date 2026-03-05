"""Domain event handlers for Worker Template events that broadcast SSE updates (ADR-013).

These handlers translate WorkerTemplate domain events into lightweight SSE messages
consumed by frontend components for real-time UI updates.
"""

from __future__ import annotations

import logging
from datetime import datetime

from application.services.sse_event_relay import SSEEventRelay
from domain.events.worker_template_events import (
    WorkerTemplateCreatedDomainEvent,
    WorkerTemplateDeletedDomainEvent,
    WorkerTemplateDisabledDomainEvent,
    WorkerTemplateEnabledDomainEvent,
    WorkerTemplateUpdatedDomainEvent,
)
from neuroglia.mediation import DomainEventHandler

log = logging.getLogger(__name__)


def _utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat() + "Z"


class WorkerTemplateCreatedDomainEventHandler(DomainEventHandler[WorkerTemplateCreatedDomainEvent]):
    """SSE handler for worker template created events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: WorkerTemplateCreatedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="worker.template.created",
            data={
                "template_id": notification.aggregate_id,
                "name": notification.name,
                "instance_type": notification.instance_type,
                "capacity": notification.capacity,
                "cost_per_hour_usd": notification.cost_per_hour_usd,
                "created_at": _utc_iso(notification.created_at),
            },
            source="domain.worker_template",
        )
        log.info("Broadcasted worker.template.created for %s", notification.aggregate_id)
        return None


class WorkerTemplateUpdatedDomainEventHandler(DomainEventHandler[WorkerTemplateUpdatedDomainEvent]):
    """SSE handler for worker template updated events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: WorkerTemplateUpdatedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="worker.template.updated",
            data={
                "template_id": notification.aggregate_id,
                "name": notification.name,
                "changes": notification.changes,
                "updated_at": _utc_iso(notification.updated_at),
            },
            source="domain.worker_template",
        )
        log.info("Broadcasted worker.template.updated for %s", notification.aggregate_id)
        return None


class WorkerTemplateDeletedDomainEventHandler(DomainEventHandler[WorkerTemplateDeletedDomainEvent]):
    """SSE handler for worker template deleted events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: WorkerTemplateDeletedDomainEvent) -> None:  # type: ignore[override]
        await self._sse_relay.broadcast_event(
            event_type="worker.template.deleted",
            data={
                "template_id": notification.aggregate_id,
                "name": notification.name,
                "deleted_at": _utc_iso(notification.deleted_at),
            },
            source="domain.worker_template",
        )
        log.info("Broadcasted worker.template.deleted for %s", notification.aggregate_id)
        return None


class WorkerTemplateEnabledDomainEventHandler(DomainEventHandler[WorkerTemplateEnabledDomainEvent]):
    """SSE handler for worker template enabled events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: WorkerTemplateEnabledDomainEvent) -> None:
        await self._sse_relay.broadcast_event(
            event_type="worker.template.enabled",
            data={
                "template_id": notification.aggregate_id,
                "name": notification.name,
                "enabled_at": _utc_iso(notification.enabled_at),
            },
            source="domain.worker_template",
        )
        log.info("Broadcasted worker.template.enabled for %s", notification.aggregate_id)
        return None


class WorkerTemplateDisabledDomainEventHandler(DomainEventHandler[WorkerTemplateDisabledDomainEvent]):
    """SSE handler for worker template disabled events (ADR-013)."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification: WorkerTemplateDisabledDomainEvent) -> None:
        await self._sse_relay.broadcast_event(
            event_type="worker.template.disabled",
            data={
                "template_id": notification.aggregate_id,
                "name": notification.name,
                "disabled_at": _utc_iso(notification.disabled_at),
            },
            source="domain.worker_template",
        )
        log.info("Broadcasted worker.template.disabled for %s", notification.aggregate_id)
        return None
