"""Update CML Worker metrics command.

This command updates metrics for a worker, typically called by worker-controller
during periodic metrics collection via the reconciliation loop.

Per ADR-001: All state mutations go through Control Plane API.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from domain.repositories.cml_worker_repository import CMLWorkerRepository
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)


@dataclass
class UpdateCMLWorkerMetricsCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to update CML Worker metrics.

    Called by worker-controller to report metrics collected from
    EC2 CloudWatch and CML System API.

    Accepts the nested structure from WorkerReconciler:
    {
        "collected_at": "2026-01-18T12:00:00Z",
        "ec2": {
            "cpu_utilization": 45.2,
            "network_in_bytes": 1234567,
            "network_out_bytes": 7654321
        },
        "cml": {
            "cpu_percent": 50.0,
            "memory_percent": 60.0,
            "disk_percent": 30.0,
            "uptime_seconds": 86400
        }
    }
    """

    worker_id: str
    collected_at: str | None = None
    ec2: dict[str, Any] | None = field(default=None)
    cml: dict[str, Any] | None = field(default=None)
    poll_interval: int | None = None
    next_refresh_at: str | None = None


class UpdateCMLWorkerMetricsCommandHandler(
    CommandHandlerBase,
    CommandHandler[UpdateCMLWorkerMetricsCommand, OperationResult[dict[str, Any]]],
):
    """Handle updating CML Worker metrics."""

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

    async def handle_async(self, request: UpdateCMLWorkerMetricsCommand) -> OperationResult[dict[str, Any]]:
        """Handle update CML Worker metrics command.

        Args:
            request: Update metrics command with worker ID and metrics data.

        Returns:
            OperationResult with acknowledgment or error.
        """
        log.info(f"Updating metrics for worker {request.worker_id}")

        # Retrieve worker from repository
        worker = await self.cml_worker_repository.get_by_id_async(request.worker_id)

        if not worker:
            return self.not_found("CMLWorker", f"Worker {request.worker_id} not found")

        # Extract metrics from nested structure
        ec2_metrics = request.ec2 or {}
        cml_metrics = request.cml or {}

        # Map to CloudWatch-level metrics for the domain
        cpu_utilization = ec2_metrics.get("cpu_utilization") or cml_metrics.get("cpu_percent")
        memory_utilization = cml_metrics.get("memory_percent")

        # Determine collection timestamp
        if request.collected_at:
            try:
                collected_at = datetime.fromisoformat(request.collected_at.replace("Z", "+00:00"))
            except ValueError:
                collected_at = datetime.now(timezone.utc)
        else:
            collected_at = datetime.now(timezone.utc)

        # Build metrics dict for response
        metrics: dict[str, Any] = {
            "collected_at": collected_at.isoformat(),
            "ec2": ec2_metrics,
            "cml": cml_metrics,
        }

        # Update CloudWatch metrics via the source-specific domain method
        # (disk_utilization and network bytes are not tracked at the domain level;
        # full CML system metrics are synced via update_cml_metrics separately)
        if cpu_utilization is not None or memory_utilization is not None:
            worker.update_cloudwatch_metrics(
                cpu_utilization=cpu_utilization or 0.0,
                memory_utilization=memory_utilization or 0.0,
                collected_at=collected_at,
            )

        # Update poll_interval and next_refresh_at for lifecycle timing display
        if request.poll_interval is not None or request.next_refresh_at is not None:
            try:
                next_refresh = None
                if request.next_refresh_at:
                    try:
                        next_refresh = datetime.fromisoformat(request.next_refresh_at.replace("Z", "+00:00"))
                    except ValueError:
                        pass

                worker.update_telemetry(
                    last_activity_at=collected_at,
                    active_labs_count=0,  # Not changed here
                    poll_interval=request.poll_interval,
                    next_refresh_at=next_refresh,
                )
            except Exception as e:
                log.warning(f"Failed to update telemetry timing for {request.worker_id}: {e}")

        # Persist changes
        await self.cml_worker_repository.update_async(worker)

        return self.ok(
            {
                "worker_id": request.worker_id,
                "metrics_updated": True,
                "collected_at": metrics.get("collected_at"),
            }
        )
