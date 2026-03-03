"""Domain event handlers for CML Worker license events."""

import logging

from neuroglia.mediation import DomainEventHandler
from neuroglia.serialization.json import JsonSerializer

from application.events.domain.cml_worker_events import _broadcast_worker_snapshot
from application.services.sse_event_relay import SSEEventRelay
from domain.events.cml_worker import (
    CMLWorkerLicenseDeregisteredDomainEvent,
    CMLWorkerLicenseRegistrationCompletedDomainEvent,
    CMLWorkerLicenseRegistrationFailedDomainEvent,
    CMLWorkerLicenseRegistrationStartedDomainEvent,
)
from domain.repositories.cml_worker_repository import CMLWorkerRepository

log = logging.getLogger(__name__)


class CMLWorkerLicenseRegistrationStartedEventHandler(DomainEventHandler[CMLWorkerLicenseRegistrationStartedDomainEvent]):
    """Broadcasts SSE event when license registration starts."""

    def __init__(self, sse_relay: SSEEventRelay, worker_repository: CMLWorkerRepository):
        self._sse_relay = sse_relay
        self._repository = worker_repository

    async def handle_async(self, notification: CMLWorkerLicenseRegistrationStartedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast license registration started event via SSE."""
        log.debug(f"📡 Broadcasting license registration started for worker {notification.worker_id}")

        # Fetch worker name for notification
        worker = await self._repository.get_by_id_async(notification.worker_id)
        worker_name = worker.state.name if worker else notification.worker_id

        await self._sse_relay.broadcast_event(
            event_type="worker.license.registration.started",
            data={
                "worker_id": notification.worker_id,
                "worker_name": worker_name,
                "started_at": notification.started_at,
                "initiated_by": notification.initiated_by,
            },
        )


class CMLWorkerLicenseRegistrationCompletedEventHandler(DomainEventHandler[CMLWorkerLicenseRegistrationCompletedDomainEvent]):
    """Broadcasts SSE event when license registration completes."""

    def __init__(self, sse_relay: SSEEventRelay, worker_repository: CMLWorkerRepository, serializer: JsonSerializer):
        self._sse_relay = sse_relay
        self._repository = worker_repository
        self._serializer = serializer

    async def handle_async(self, notification: CMLWorkerLicenseRegistrationCompletedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast license registration completed event via SSE."""
        log.info(f"📡 Broadcasting license registration completed for worker {notification.worker_id}")

        # Fetch worker name for notification
        worker = await self._repository.get_by_id_async(notification.worker_id)
        worker_name = worker.state.name if worker else notification.worker_id

        await self._sse_relay.broadcast_event(
            event_type="worker.license.registration.completed",
            data={
                "worker_id": notification.worker_id,
                "worker_name": worker_name,
                "registration_status": notification.registration_status,
                "smart_account": notification.smart_account,
                "virtual_account": notification.virtual_account,
                "completed_at": notification.completed_at,
            },
        )

        # Broadcast snapshot for full worker data including updated license_status
        await _broadcast_worker_snapshot(
            self._repository,
            self._sse_relay,
            self._serializer,
            notification.worker_id,
            reason="license_registered",
        )
        log.info("Broadcasted license.registration.completed + snapshot for %s", notification.worker_id)


class CMLWorkerLicenseRegistrationFailedEventHandler(DomainEventHandler[CMLWorkerLicenseRegistrationFailedDomainEvent]):
    """Broadcasts SSE event when license registration fails."""

    def __init__(self, sse_relay: SSEEventRelay, worker_repository: CMLWorkerRepository, serializer: JsonSerializer):
        self._sse_relay = sse_relay
        self._repository = worker_repository
        self._serializer = serializer

    async def handle_async(self, notification: CMLWorkerLicenseRegistrationFailedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast license registration failed event via SSE."""
        log.warning(f"📡 Broadcasting license registration failed for worker {notification.worker_id}")

        # Fetch worker name for notification
        worker = await self._repository.get_by_id_async(notification.worker_id)
        worker_name = worker.state.name if worker else notification.worker_id

        await self._sse_relay.broadcast_event(
            event_type="worker.license.registration.failed",
            data={
                "worker_id": notification.worker_id,
                "worker_name": worker_name,
                "error_message": notification.error_message,
                "error_code": notification.error_code,
                "failed_at": notification.failed_at,
            },
        )

        # Broadcast snapshot for full worker data
        await _broadcast_worker_snapshot(
            self._repository,
            self._sse_relay,
            self._serializer,
            notification.worker_id,
            reason="license_registration_failed",
        )
        log.info("Broadcasted license.registration.failed + snapshot for %s", notification.worker_id)


class CMLWorkerLicenseDeregisteredEventHandler(DomainEventHandler[CMLWorkerLicenseDeregisteredDomainEvent]):
    """Broadcasts SSE event when license is deregistered."""

    def __init__(self, sse_relay: SSEEventRelay, worker_repository: CMLWorkerRepository, serializer: JsonSerializer):
        self._sse_relay = sse_relay
        self._repository = worker_repository
        self._serializer = serializer

    async def handle_async(self, notification: CMLWorkerLicenseDeregisteredDomainEvent) -> None:  # type: ignore[override]
        """Broadcast license deregistered event via SSE."""
        log.info(f"📡 Broadcasting license deregistered for worker {notification.worker_id}")

        await self._sse_relay.broadcast_event(
            event_type="worker.license.deregistered",
            data={
                "worker_id": notification.worker_id,
                "deregistered_at": notification.deregistered_at,
                "initiated_by": notification.initiated_by,
            },
        )

        # Broadcast snapshot for full worker data including updated license_status
        await _broadcast_worker_snapshot(
            self._repository,
            self._sse_relay,
            self._serializer,
            notification.worker_id,
            reason="license_deregistered",
        )
        log.info("Broadcasted license.deregistered + snapshot for %s", notification.worker_id)
