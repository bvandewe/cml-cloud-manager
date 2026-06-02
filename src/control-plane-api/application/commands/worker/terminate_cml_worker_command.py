"""Terminate CML Worker command with handler.

Sets the worker's desired_status to TERMINATED (spec update).
The worker-controller will reconcile by terminating the EC2 instance.

ADR-015: Control-plane-api MUST NOT call AWS EC2 directly.
This follows the Kubernetes-like reconciliation pattern:
- desired_status = spec (what user wants)
- status = state (actual EC2 state)

Warning: This is a destructive operation that cannot be undone.
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
class TerminateCMLWorkerCommand(Command[OperationResult[dict]]):
    """Command to request terminating a CML Worker (spec update).

    This command sets desired_status=TERMINATED. The worker-controller
    will observe this change and reconcile by terminating the EC2 instance.

    Pattern: spec (desired_status) vs state (status) reconciliation

    Warning: Termination is permanent and cannot be undone.

    Attributes:
        worker_id: Worker identifier
        terminated_by: User ID who initiated the termination
        reason: Optional reason for termination
    """

    worker_id: str
    terminated_by: str | None = None
    reason: str | None = None


class TerminateCMLWorkerCommandHandler(
    CommandHandlerBase,
    CommandHandler[TerminateCMLWorkerCommand, OperationResult[dict]],
):
    """Handle terminating a CML Worker by updating desired_status (spec).

    ADR-015: This handler does NOT call AWS EC2. It only updates the
    desired_status field. Worker-controller reconciles actual state.
    """

    def __init__(self, cml_worker_repository: CMLWorkerRepository):
        self.cml_worker_repository = cml_worker_repository

    async def handle_async(self, request: TerminateCMLWorkerCommand) -> OperationResult[dict]:
        """Handle terminate CML Worker command by updating desired_status.

        Args:
            request: Terminate command with worker ID

        Returns:
            OperationResult with worker status details
        """
        command = request

        # Add tracing context
        add_span_attributes(
            {
                "cml_worker.id": command.worker_id,
                "cml_worker.has_terminated_by": command.terminated_by is not None,
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
                error_msg = f"CML Worker {command.worker_id} is already terminated"
                log.info(error_msg)
                return self.ok(
                    {
                        "id": worker.id(),
                        "status": worker.state.status.value,
                        "desired_status": worker.state.desired_status.value,
                        "message": "Worker is already terminated",
                    }
                )

            # Check if already at desired state
            if worker.state.desired_status == CMLWorkerStatus.TERMINATED:
                log.info(f"CML Worker {command.worker_id} already has desired_status=TERMINATED")
                return self.ok(
                    {
                        "id": worker.id(),
                        "status": worker.state.status.value,
                        "desired_status": worker.state.desired_status.value,
                        "message": "Already has desired_status=TERMINATED",
                    }
                )

            with tracer.start_as_current_span("update_desired_status") as span:
                # Update desired_status (spec) - worker-controller will reconcile
                terminate_reason = command.reason or "manual"

                worker.update_desired_status(
                    new_desired_status=CMLWorkerStatus.TERMINATED,
                    requested_by=command.terminated_by,
                    reason=terminate_reason,
                )

                # Also call terminate to update domain state markers
                worker.terminate(terminated_by=command.terminated_by)

                span.set_attribute("cml_worker.new_desired_status", CMLWorkerStatus.TERMINATED.value)
                span.set_attribute("cml_worker.terminate_reason", terminate_reason)

            # Save worker (will publish domain events)
            await self.cml_worker_repository.update_async(worker)

            log.info(
                f"CML Worker desired_status updated to TERMINATED: id={worker.id()}, "
                f"current_status={worker.state.status.value}, "
                f"reason={terminate_reason}, "
                f"terminated_by={command.terminated_by or 'system'}"
            )

            return self.ok(
                {
                    "id": worker.id(),
                    "status": worker.state.status.value,
                    "desired_status": worker.state.desired_status.value,
                    "message": "Terminate requested - worker-controller will reconcile",
                }
            )

        except Exception as e:
            log.error(f"Unexpected error updating CML Worker desired_status: {e}", exc_info=True)
            return self.internal_server_error(f"Unexpected error: {str(e)}")
