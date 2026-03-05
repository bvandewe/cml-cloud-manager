"""Drain CML Worker command with handler.

Sets a worker to DRAINING status, which signals the worker-controller
to gracefully stop the worker after active workloads complete.

Phase 3 - Auto-Scaling: Used during scale-down to gracefully drain
workloads before stopping/terminating a worker.

Flow:
1. Scale-down detection identifies worker to drain
2. This command sets status=DRAINING, desired_status=STOPPED
3. Worker-controller observes state change → drains workloads → stops instance
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from domain.entities.cml_worker import CMLWorker
from domain.enums import CMLWorkerStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from infrastructure.observability import record_scaling_event
from infrastructure.observability.logging import get_logger
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator
from opentelemetry import trace

from ..command_handler_base import CommandHandlerBase

audit_log = get_logger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class DrainWorkerCommand(Command[OperationResult[dict]]):
    """Command to initiate graceful drain of a worker.

    Sets the worker to DRAINING status and desired_status=STOPPED.
    Worker-controller will:
    1. Stop accepting new lab assignments
    2. Wait for active labs to complete or be migrated
    3. Transition to STOPPING → STOPPED

    Attributes:
        worker_id: ID of the worker to drain
        reason: Reason for draining (e.g., "scale_down", "maintenance")
        requested_by: System or user requesting the drain
    """

    worker_id: str
    reason: str = "scale_down"
    requested_by: str = "worker-controller"


class DrainWorkerCommandHandler(
    CommandHandlerBase,
    CommandHandler[DrainWorkerCommand, OperationResult[dict]],
):
    """Handle worker drain by setting status to DRAINING.

    Only workers in RUNNING status can be drained.
    """

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
        self._worker_repository = cml_worker_repository

    async def handle_async(self, request: DrainWorkerCommand) -> OperationResult[dict]:
        """Handle drain worker command.

        Args:
            request: Drain command with worker ID and reason.

        Returns:
            OperationResult with drain status.
        """
        try:
            with tracer.start_as_current_span("drain_worker") as span:
                span.set_attribute("cml_worker.id", request.worker_id)
                span.set_attribute("drain.reason", request.reason)

                # Fetch worker
                worker = await self._worker_repository.get_by_id_async(request.worker_id)
                if not worker:
                    return self.not_found(CMLWorker, request.worker_id)

                # Validate current status - only RUNNING workers can be drained
                if worker.state.status != CMLWorkerStatus.RUNNING:
                    return self.conflict(f"Cannot drain worker in status '{worker.state.status.value}'. Only RUNNING workers can be drained.")

                # Set status to DRAINING
                worker.update_status(CMLWorkerStatus.DRAINING)
                # Set desired status to STOPPED (final target after drain completes)
                worker.update_desired_status(
                    CMLWorkerStatus.STOPPED,
                    requested_by=request.requested_by,
                    reason=request.reason,
                )

                await self._worker_repository.update_async(worker)

                # Scaling audit: record accepted drain
                record_scaling_event(
                    action="drain_accepted",
                    worker_id=request.worker_id,
                    reason=request.reason,
                    requested_by=request.requested_by,
                )
                audit_log.log_scaling_event(
                    action="drain_accepted",
                    worker_id=request.worker_id,
                    reason=request.reason,
                    requested_by=request.requested_by,
                )

                return self.ok(
                    {
                        "worker_id": request.worker_id,
                        "status": "draining",
                        "desired_status": "stopped",
                        "reason": request.reason,
                        "requested_by": request.requested_by,
                        "drained_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

        except Exception as e:
            record_scaling_event(
                action="drain_rejected",
                worker_id=request.worker_id,
                reason=f"error: {e}",
                requested_by=request.requested_by,
                success=False,
            )
            audit_log.error(f"Error draining worker {request.worker_id}: {e}", exc_info=True)
            return self.internal_server_error(f"Failed to drain worker: {str(e)}")
