"""Stop CML Worker command with handler.

Sets the worker's desired_status to STOPPED (spec update).
The worker-controller will reconcile by stopping the EC2 instance.

ADR-015: Control-plane-api MUST NOT call AWS EC2 directly.
This follows the Kubernetes-like reconciliation pattern:
- desired_status = spec (what user wants)
- status = state (actual EC2 state)
"""

import logging
from dataclasses import dataclass

from domain.enums import CMLWorkerStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler
from neuroglia.observability.tracing import add_span_attributes
from opentelemetry import trace

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class StopCMLWorkerCommand(Command[OperationResult[dict]]):
    """Command to request stopping a running CML Worker (spec update).

    This command sets desired_status=STOPPED. The worker-controller
    will observe this change and reconcile by stopping the EC2 instance.

    Pattern: spec (desired_status) vs state (status) reconciliation

    Attributes:
        worker_id: Worker identifier
        stopped_by: User ID who initiated the stop (None for auto-pause)
        is_auto_pause: Whether this is an automatic pause from idle detection
        reason: Optional reason for stopping (e.g., "idle_timeout", "manual")
    """

    worker_id: str
    stopped_by: str | None = None
    is_auto_pause: bool = False
    reason: str | None = None


class StopCMLWorkerCommandHandler(
    CommandHandlerBase,
    CommandHandler[StopCMLWorkerCommand, OperationResult[dict]],
):
    """Handle stopping a CML Worker by updating desired_status (spec).

    ADR-015: This handler does NOT call AWS EC2. It only updates the
    desired_status field. Worker-controller reconciles actual state.
    """

    def __init__(self, cml_worker_repository: CMLWorkerRepository):
        self.cml_worker_repository = cml_worker_repository

    async def handle_async(self, request: StopCMLWorkerCommand) -> OperationResult[dict]:
        """Handle stop CML Worker command by updating desired_status.

        Args:
            request: Stop command with worker ID

        Returns:
            OperationResult with worker status details
        """
        command = request

        # Add tracing context
        add_span_attributes(
            {
                "cml_worker.id": command.worker_id,
                "cml_worker.has_stopped_by": command.stopped_by is not None,
                "cml_worker.is_auto_pause": command.is_auto_pause,
            }
        )

        try:
            with tracer.start_as_current_span("retrieve_cml_worker") as span:
                # Retrieve worker from repository
                worker = await self.cml_worker_repository.get_by_id_async(command.worker_id)

                if not worker:
                    error_msg = f"CML Worker not found: {command.worker_id}"
                    log.error(error_msg)
                    return self.not_found("CMLWorker", error_msg)

                span.set_attribute("cml_worker.current_status", worker.state.status.value)
                span.set_attribute("cml_worker.current_desired_status", worker.state.desired_status.value)

            # Validate current state
            if worker.state.status == CMLWorkerStatus.TERMINATED:
                error_msg = f"Cannot stop terminated CML Worker {command.worker_id}"
                log.error(error_msg)
                return self.bad_request(error_msg)

            # Check if already at desired state
            if worker.state.desired_status == CMLWorkerStatus.STOPPED:
                log.info(f"CML Worker {command.worker_id} already has desired_status=STOPPED")
                return self.ok(
                    {
                        "id": worker.id(),
                        "status": worker.state.status.value,
                        "desired_status": worker.state.desired_status.value,
                        "message": "Already has desired_status=STOPPED",
                    }
                )

            with tracer.start_as_current_span("update_desired_status") as span:
                # Update desired_status (spec) - worker-controller will reconcile
                pause_reason = command.reason or ("idle_timeout" if command.is_auto_pause else "manual")
                requested_by = None if command.is_auto_pause else command.stopped_by

                worker.update_desired_status(
                    new_desired_status=CMLWorkerStatus.STOPPED,
                    requested_by=requested_by,
                    reason=pause_reason,
                )

                # Record pause metrics (auto vs manual) for tracking
                worker.pause(
                    reason=pause_reason,
                    paused_by=requested_by,
                )

                span.set_attribute("cml_worker.new_desired_status", CMLWorkerStatus.STOPPED.value)
                span.set_attribute("cml_worker.pause_reason", pause_reason)

            # Save worker (will publish domain events)
            await self.cml_worker_repository.update_async(worker)

            log.info(f"CML Worker desired_status updated to STOPPED: id={worker.id()}, current_status={worker.state.status.value}, reason={pause_reason}, is_auto_pause={command.is_auto_pause}")

            return self.ok(
                {
                    "id": worker.id(),
                    "status": worker.state.status.value,
                    "desired_status": worker.state.desired_status.value,
                    "message": "Stop requested - worker-controller will reconcile",
                }
            )

        except Exception as e:
            log.error(f"Unexpected error updating CML Worker desired_status: {e}", exc_info=True)
            return self.internal_server_error(f"Unexpected error: {str(e)}")
