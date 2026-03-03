"""Domain event handlers for CML Worker events that broadcast SSE updates.

These handlers translate domain events into lightweight SSE messages consumed by
frontend components for real-time UI updates.
"""

from __future__ import annotations

import logging
from datetime import datetime

from neuroglia.mediation import DomainEventHandler
from neuroglia.serialization.json import JsonSerializer

from application.mappers import map_worker_to_dto, worker_dto_to_dict
from application.services.sse_event_relay import SSEEventRelay
from domain.events.cml_worker import (
    CMLWorkerCreatedDomainEvent,
    CMLWorkerEndpointUpdatedDomainEvent,
    CMLWorkerImportedDomainEvent,
    CMLWorkerStatusUpdatedDomainEvent,
    CMLWorkerTelemetryUpdatedDomainEvent,
    CMLWorkerTerminatedDomainEvent,
)
from domain.events.worker_metrics_events import (
    CMLMetricsUpdatedDomainEvent,
    EC2InstanceDetailsUpdatedDomainEvent,
)
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.lab_record_repository import LabRecordRepository

log = logging.getLogger(__name__)


def _utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat() + "Z"


class CMLWorkerCreatedDomainEventHandler(DomainEventHandler[CMLWorkerCreatedDomainEvent]):
    def __init__(self, sse_relay: SSEEventRelay, repository: CMLWorkerRepository, serializer: JsonSerializer):
        self._sse_relay = sse_relay
        self._repository = repository
        self._serializer = serializer

    async def handle_async(self, notification: CMLWorkerCreatedDomainEvent) -> None:  # type: ignore[override]
        # Original specific event
        await self._sse_relay.broadcast_event(
            event_type="worker.created",
            data={
                "worker_id": notification.aggregate_id,
                "name": notification.name,
                "region": notification.aws_region,
                "status": notification.status.value,
                "instance_type": notification.instance_type,
                "created_at": _utc_iso(notification.created_at),
            },
            source="domain.cml_worker",
        )
        # Snapshot event
        await _broadcast_worker_snapshot(
            self._repository,
            self._sse_relay,
            self._serializer,
            notification.aggregate_id,
            reason="created",
        )
        log.info("Broadcasted worker.created + snapshot for %s", notification.aggregate_id)
        return None


class CMLWorkerImportedDomainEventHandler(DomainEventHandler[CMLWorkerImportedDomainEvent]):
    """Handle worker imported event by notifying UI and triggering initial data refresh.

    Note: APScheduler job scheduling removed per ADR-011. Initial data collection
    is now triggered via mediator command. Background refresh is handled by the
    WorkerReconciler in worker-controller.
    """

    def __init__(
        self,
        sse_relay: SSEEventRelay,
        repository: CMLWorkerRepository,
        mediator,
        serializer: JsonSerializer,
    ):
        from neuroglia.mediation import Mediator

        self._sse_relay = sse_relay
        self._repository = repository
        self._mediator: Mediator = mediator
        self._serializer = serializer

    async def handle_async(self, notification: CMLWorkerImportedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast worker.imported SSE event and trigger initial data collection."""

        # Map EC2 instance_state to CMLWorkerStatus for consistency
        status_str = notification.instance_state
        if notification.instance_state == "running":
            status_str = "running"
        elif notification.instance_state == "stopped":
            status_str = "stopped"
        elif notification.instance_state == "stopping":
            status_str = "stopping"
        elif notification.instance_state == "pending":
            status_str = "pending"
        else:
            status_str = "unknown"

        # Broadcast imported event to UI
        await self._sse_relay.broadcast_event(
            event_type="worker.imported",
            data={
                "worker_id": notification.aggregate_id,
                "name": notification.name,
                "region": notification.aws_region,
                "status": status_str,
                "instance_type": notification.instance_type,
                "aws_instance_id": notification.aws_instance_id,
                "imported_at": _utc_iso(notification.created_at),
            },
            source="domain.cml_worker",
        )

        # Broadcast snapshot for full worker data
        await _broadcast_worker_snapshot(
            self._repository,
            self._sse_relay,
            self._serializer,
            notification.aggregate_id,
            reason="imported",
        )

        log.info(f"Broadcasted worker.imported + snapshot for {notification.aggregate_id}")

        # ADR-015: Initial data collection is handled by worker-controller
        # via etcd watch. Control-plane-api does NOT call EC2/CloudWatch/CML.
        # The worker-controller will detect the new worker and fetch metrics.
        log.info(f"Worker {notification.aggregate_id} imported. Worker-controller will handle initial data collection via etcd watch.")

        return None


class CMLWorkerStatusUpdatedDomainEventHandler(DomainEventHandler[CMLWorkerStatusUpdatedDomainEvent]):
    def __init__(self, sse_relay: SSEEventRelay, repository: CMLWorkerRepository, serializer: JsonSerializer):
        self._sse_relay = sse_relay
        self._repository = repository
        self._serializer = serializer

    async def handle_async(self, notification: CMLWorkerStatusUpdatedDomainEvent) -> None:  # type: ignore[override]
        # Include transition initiation timestamp if present so UI can start elapsed timer immediately
        event_data = {
            "worker_id": notification.aggregate_id,
            "old_status": notification.old_status.value,
            "new_status": notification.new_status.value,
            "updated_at": _utc_iso(notification.updated_at),
        }
        if getattr(notification, "transition_initiated_at", None):
            # type: ignore[arg-type]
            event_data["transition_initiated_at"] = _utc_iso(notification.transition_initiated_at)
        await self._sse_relay.broadcast_event(
            event_type="worker.status.updated",
            data=event_data,
            source="domain.cml_worker",
        )
        await _broadcast_worker_snapshot(
            self._repository,
            self._sse_relay,
            self._serializer,
            notification.aggregate_id,
            reason="status_updated",
        )
        log.info(
            "Broadcasted worker.status.updated + snapshot for %s",
            notification.aggregate_id,
        )
        return None


class CMLWorkerTerminatedDomainEventHandler(DomainEventHandler[CMLWorkerTerminatedDomainEvent]):
    """Handle worker termination: broadcast SSE and cascade-orphan all lab records.

    When a worker is terminated, all its non-terminal lab records become
    unreachable and must be marked ORPHANED. This is a force-majeure
    transition — the state machine allows ANY non-terminal state → ORPHANED.
    """

    def __init__(
        self,
        sse_relay: SSEEventRelay,
        repository: CMLWorkerRepository,
        serializer: JsonSerializer,
        lab_record_repository: LabRecordRepository,
    ):
        self._sse_relay = sse_relay
        self._repository = repository
        self._serializer = serializer
        self._lab_record_repository = lab_record_repository

    async def handle_async(self, notification: CMLWorkerTerminatedDomainEvent) -> None:  # type: ignore[override]
        # 1. Broadcast SSE events
        await self._sse_relay.broadcast_event(
            event_type="worker.terminated",
            data={
                "worker_id": notification.aggregate_id,
                "name": notification.name,
                "terminated_at": _utc_iso(notification.terminated_at),
            },
            source="domain.cml_worker",
        )
        await _broadcast_worker_snapshot(
            self._repository,
            self._sse_relay,
            self._serializer,
            notification.aggregate_id,
            reason="terminated",
        )
        log.info("Broadcasted worker.terminated + snapshot for %s", notification.aggregate_id)

        # 2. Cascade-orphan all lab records for this worker
        orphaned_count = await self._orphan_worker_labs(notification.aggregate_id)
        if orphaned_count > 0:
            log.info(
                "Cascade-orphaned %d lab records for terminated worker %s",
                orphaned_count,
                notification.aggregate_id,
            )

        return None

    async def _orphan_worker_labs(self, worker_id: str) -> int:
        """Mark all non-terminal lab records for this worker as ORPHANED.

        Returns:
            Number of lab records orphaned.
        """
        orphaned = 0
        try:
            records = await self._lab_record_repository.get_all_by_worker_async(worker_id)
            for record in records:
                if record.is_terminal or record.is_orphaned:
                    continue
                try:
                    record.mark_orphaned()
                    await self._lab_record_repository.update_async(record)
                    orphaned += 1
                except Exception as e:
                    log.warning(
                        "Failed to orphan lab %s (status=%s) for worker %s: %s",
                        record.state.lab_id,
                        record.state.status.value,
                        worker_id,
                        e,
                    )
        except Exception as e:
            log.error("Failed to fetch lab records for worker %s during orphan cascade: %s", worker_id, e)

        return orphaned


class CMLWorkerTelemetryUpdatedDomainEventHandler(DomainEventHandler[CMLWorkerTelemetryUpdatedDomainEvent]):
    def __init__(self, sse_relay: SSEEventRelay, repository: CMLWorkerRepository, serializer: JsonSerializer):
        self._sse_relay = sse_relay
        self._repository = repository
        self._serializer = serializer

    async def handle_async(self, notification: CMLWorkerTelemetryUpdatedDomainEvent) -> None:  # type: ignore[override]
        event_data = {
            "worker_id": notification.aggregate_id,
            "last_activity_at": _utc_iso(notification.last_activity_at),
            "active_labs_count": notification.active_labs_count,
            "cpu_utilization": notification.cpu_utilization,
            "memory_utilization": notification.memory_utilization,
            "updated_at": _utc_iso(notification.updated_at),
        }
        if notification.poll_interval is not None:
            event_data["poll_interval"] = notification.poll_interval
        if notification.next_refresh_at is not None:
            event_data["next_refresh_at"] = _utc_iso(notification.next_refresh_at)

        await self._sse_relay.broadcast_event(
            event_type="worker.metrics.updated",
            data=event_data,
            source="domain.cml_worker",
        )
        await _broadcast_worker_snapshot(
            self._repository,
            self._sse_relay,
            self._serializer,
            notification.aggregate_id,
            reason="telemetry_updated",
        )
        log.debug(
            "Broadcasted worker.metrics.updated + snapshot for %s",
            notification.aggregate_id,
        )
        return None


class CMLMetricsUpdatedDomainEventHandler(DomainEventHandler[CMLMetricsUpdatedDomainEvent]):
    """Broadcast SSE events when CML metrics (system stats) are updated.

    Domain already suppresses insignificant changes; this handler simply
    derives utilization from current state and broadcasts the event plus snapshot.
    """

    def __init__(self, sse_relay: SSEEventRelay, repository: CMLWorkerRepository):
        self._sse_relay = sse_relay
        self._repository = repository

    async def handle_async(self, notification: CMLMetricsUpdatedDomainEvent) -> None:  # type: ignore[override]
        worker = await self._repository.get_by_id_async(notification.aggregate_id)
        cpu_util = None
        mem_util = None
        storage_util = None
        poll_interval = None
        next_refresh_at_iso = None
        if worker:
            s = worker.state
            poll_interval = s.poll_interval
            if s.next_refresh_at:
                next_refresh_at_iso = s.next_refresh_at.isoformat() + "Z"

            # Use helper method on metrics VO
            cpu_util, mem_util, storage_util = s.metrics.get_utilization()

            # Fallback to CloudWatch if CML metrics are missing
            if cpu_util is None and s.cloudwatch_cpu_utilization is not None:
                cpu_util = s.cloudwatch_cpu_utilization
            if mem_util is None and s.cloudwatch_memory_utilization is not None:
                mem_util = s.cloudwatch_memory_utilization

        payload = {
            "worker_id": notification.aggregate_id,
            "cml_version": notification.cml_version,
            "labs_count": notification.labs_count,
            "cpu_utilization": cpu_util,
            "memory_utilization": mem_util,
            "storage_utilization": storage_util,
            "updated_at": _utc_iso(notification.updated_at),
        }
        if poll_interval is not None:
            payload["poll_interval"] = poll_interval
        if next_refresh_at_iso:
            payload["next_refresh_at"] = next_refresh_at_iso

        await self._sse_relay.broadcast_event(
            event_type="worker.metrics.updated",
            data=payload,
            source="domain.cml_worker.cml_metrics",
        )
        # Note: Snapshot broadcast removed - metrics event already contains relevant data
        # Snapshots are only broadcast for significant state changes (status, license, etc.)
        log.debug(
            "Broadcasted worker.metrics.updated (CML metrics) for %s",
            notification.aggregate_id,
        )
        return None


class CMLWorkerEndpointUpdatedDomainEventHandler(DomainEventHandler[CMLWorkerEndpointUpdatedDomainEvent]):
    """Broadcast SSE events when worker HTTPS endpoint is updated.

    This handler is critical for notifying the UI when a worker's endpoint changes,
    particularly after a worker is resumed (started after being stopped) and receives
    a new public IP address from AWS EC2.
    """

    def __init__(self, sse_relay: SSEEventRelay, repository: CMLWorkerRepository, serializer: JsonSerializer):
        self._sse_relay = sse_relay
        self._repository = repository
        self._serializer = serializer

    async def handle_async(self, notification: CMLWorkerEndpointUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast endpoint updated event and worker snapshot."""
        await self._sse_relay.broadcast_event(
            event_type="worker.endpoint.updated",
            data={
                "worker_id": notification.aggregate_id,
                "https_endpoint": notification.https_endpoint,
                "public_ip": notification.public_ip,
                "updated_at": _utc_iso(notification.updated_at),
            },
            source="domain.cml_worker",
        )
        await _broadcast_worker_snapshot(
            self._repository,
            self._sse_relay,
            self._serializer,
            notification.aggregate_id,
            reason="endpoint_updated",
        )
        log.info(
            "Broadcasted worker.endpoint.updated + snapshot for %s: endpoint=%s",
            notification.aggregate_id,
            notification.https_endpoint,
        )
        return None


class EC2InstanceDetailsUpdatedDomainEventHandler(DomainEventHandler[EC2InstanceDetailsUpdatedDomainEvent]):
    """Broadcast SSE events when EC2 instance details (IPs, type, AMI) are updated.

    This handler ensures the UI is updated when EC2 instance details change,
    such as when a stopped instance is started and receives new IP addresses.
    """

    def __init__(self, sse_relay: SSEEventRelay, repository: CMLWorkerRepository, serializer: JsonSerializer):
        self._sse_relay = sse_relay
        self._repository = repository
        self._serializer = serializer

    async def handle_async(self, notification: EC2InstanceDetailsUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Broadcast EC2 instance details updated event and worker snapshot."""
        await self._sse_relay.broadcast_event(
            event_type="worker.ec2_details.updated",
            data={
                "worker_id": notification.aggregate_id,
                "public_ip": notification.public_ip,
                "private_ip": notification.private_ip,
                "instance_type": notification.instance_type,
                "ami_id": notification.ami_id,
                "ami_name": notification.ami_name,
                "updated_at": _utc_iso(notification.updated_at),
            },
            source="domain.cml_worker",
        )
        await _broadcast_worker_snapshot(
            self._repository,
            self._sse_relay,
            self._serializer,
            notification.aggregate_id,
            reason="ec2_details_updated",
        )
        log.debug(
            "Broadcasted worker.ec2_details.updated + snapshot for %s: public_ip=%s, private_ip=%s",
            notification.aggregate_id,
            notification.public_ip,
            notification.private_ip,
        )
        return None


# --- Snapshot Helper & Additional Event Handlers ---


async def _broadcast_worker_snapshot(
    repository: CMLWorkerRepository,
    relay: SSEEventRelay,
    serializer: JsonSerializer,
    worker_id: str,
    reason: str | None = None,
) -> None:
    """Broadcast worker snapshot using DTO mapper for consistent format.

    This function uses the centralized CMLWorkerDto mapper to ensure consistent
    data structure across API responses and SSE events.
    """
    try:
        worker = await repository.get_by_id_async(worker_id)
        if not worker:
            return

        # Use DTO mapper for consistent transformation
        dto = map_worker_to_dto(worker)
        snapshot = worker_dto_to_dict(dto)

        # Add optional reason field
        if reason:
            snapshot["_reason"] = reason

        await relay.broadcast_event(
            event_type="worker.snapshot",
            data=snapshot,
            source="domain.cml_worker.snapshot",
        )
    except Exception as e:
        log.warning("Failed to broadcast worker snapshot for %s: %s", worker_id, e, exc_info=True)
