"""Update Worker CML Data command.

This command updates CML application-level data for a worker, including:
- CML version, readiness state
- System information (compute nodes, resource allocation)
- System health checks
- License information

This is separate from utilization metrics (handled by UpdateCMLWorkerMetricsCommand).
Called by worker-controller during reconciliation via the internal API.

Per ADR-001: All state mutations go through Control Plane API.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

from domain.enums import CMLServiceStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)


@dataclass
class UpdateWorkerCmlDataCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to update CML application data for a worker.

    Called by worker-controller to report CML system information,
    health, and license data collected from the CML API.

    This is the full CML application state, not just utilization metrics.
    """

    worker_id: str
    cml_version: str | None = None
    ready: bool = False
    system_info: dict[str, Any] | None = field(default=None)
    system_health: dict[str, Any] | None = field(default=None)
    license_info: dict[str, Any] | None = field(default=None)
    uptime_seconds: int | None = None
    labs_count: int = 0
    collected_at: str | None = None


class UpdateWorkerCmlDataCommandHandler(
    CommandHandlerBase,
    CommandHandler[UpdateWorkerCmlDataCommand, OperationResult[dict[str, Any]]],
):
    """Handle updating CML application data for a worker."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        cml_worker_repository: CMLWorkerRepository,
    ):
        super().__init__(
            mediator,
            mapper,
            cloud_event_bus,
            cloud_event_publishing_options,
        )
        self.cml_worker_repository = cml_worker_repository

    async def handle_async(self, request: UpdateWorkerCmlDataCommand) -> OperationResult[dict[str, Any]]:
        """Handle update worker CML data command.

        Calls the aggregate's update_cml_metrics() method which emits
        CMLMetricsUpdatedDomainEvent, populating system_info, system_health,
        license_info, and compute node details.

        Args:
            request: Command with CML data fields.

        Returns:
            OperationResult with acknowledgment or error.
        """
        log.info(f"Updating CML data for worker {request.worker_id}")

        # Retrieve worker from repository
        worker = await self.cml_worker_repository.get_by_id_async(request.worker_id)

        if not worker:
            return self.not_found("CMLWorker", f"Worker {request.worker_id} not found")

        # Determine collection timestamp
        if request.collected_at:
            try:
                synced_at = datetime.fromisoformat(request.collected_at.replace("Z", "+00:00"))
            except ValueError:
                synced_at = datetime.now(timezone.utc)
        else:
            synced_at = datetime.now(timezone.utc)

        # Update CML metrics via domain method (emits CMLMetricsUpdatedDomainEvent)
        try:
            worker.update_cml_metrics(
                cml_version=request.cml_version,
                system_info=request.system_info or {},
                system_health=request.system_health,
                license_info=request.license_info,
                ready=request.ready,
                uptime_seconds=request.uptime_seconds,
                labs_count=request.labs_count,
                synced_at=synced_at,
            )
        except Exception as e:
            log.error(f"Failed to update CML metrics for worker {request.worker_id}: {e}")
            return self.internal_server_error(f"Failed to update CML data: {e}")

        # Also update service status based on readiness
        try:
            if request.ready:
                worker.update_service_status(
                    new_service_status=CMLServiceStatus.AVAILABLE,
                    https_endpoint=None,
                )
            else:
                worker.update_service_status(
                    new_service_status=CMLServiceStatus.STARTING,
                    https_endpoint=None,
                )
        except Exception as e:
            # Non-fatal: CML data is more important than service status
            log.warning(f"Failed to update service status for worker {request.worker_id}: {e}")

        # Auto-derive declared_capacity from system_info hardware metrics.
        # For discovered workers (no template), this is the only way capacity gets set.
        # For template-provisioned workers, this updates capacity to match actual hardware.
        # Without this, the resource-scheduler sees 0 capacity and rejects all workers.
        try:
            sys_info = request.system_info or {}
            # Worker-controller sends system_stats keys with "all_" prefix
            # (all_cpu_count, all_memory_total, all_disk_total).
            # Try prefixed keys first, fall back to unprefixed for backward compat.
            cpu_count = sys_info.get("all_cpu_count") or sys_info.get("cpu_count")
            memory_total = sys_info.get("all_memory_total") or sys_info.get("memory_total")  # bytes
            disk_total = sys_info.get("all_disk_total") or sys_info.get("disk_total")  # bytes

            if cpu_count and memory_total and disk_total:
                derived_cpu = int(cpu_count)
                derived_memory_gb = int(memory_total / (1024**3))  # bytes → GB
                derived_storage_gb = int(disk_total / (1024**3))  # bytes → GB

                # Extract max_nodes from license info if available
                derived_max_nodes = None
                if request.license_info:
                    product_license = request.license_info.get("product_license", {})
                    if isinstance(product_license, dict):
                        node_limit = product_license.get("node_limit")
                        if node_limit and int(node_limit) > 0:
                            derived_max_nodes = int(node_limit)

                # Check if capacity actually changed before emitting event
                current = worker.state.declared_capacity
                needs_update = (
                    current is None or current.cpu_cores != derived_cpu or current.memory_gb != derived_memory_gb or current.storage_gb != derived_storage_gb or current.max_nodes != derived_max_nodes
                )

                if needs_update:
                    worker.update_capacity(
                        template_name=worker.state.template_name,  # preserve existing template
                        cpu_cores=derived_cpu,
                        memory_gb=derived_memory_gb,
                        storage_gb=derived_storage_gb,
                        max_nodes=derived_max_nodes,
                    )
                    log.info(
                        f"Auto-derived declared_capacity for worker {request.worker_id}: cpu={derived_cpu}, mem={derived_memory_gb}GB, storage={derived_storage_gb}GB, max_nodes={derived_max_nodes}"
                    )
        except Exception as e:
            # Non-fatal: capacity derivation failure shouldn't block CML data update
            log.warning(f"Failed to auto-derive capacity for worker {request.worker_id}: {e}")

        # Clear any pending refresh request (on-demand refresh fulfilled)
        if worker.state.refresh_requested_at is not None:
            worker.clear_refresh_request()
            log.info(f"Cleared refresh request for worker {request.worker_id}")

        # Persist changes
        await self.cml_worker_repository.update_async(worker)

        return self.ok(
            {
                "worker_id": request.worker_id,
                "cml_data_updated": True,
                "cml_version": request.cml_version,
                "ready": request.ready,
                "collected_at": synced_at.isoformat(),
            }
        )
