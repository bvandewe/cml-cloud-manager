"""Start CML Worker command with handler.

Sets the worker's desired_status to RUNNING (spec update).
The worker-controller will reconcile by starting the EC2 instance.

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
class StartCMLWorkerCommand(Command[OperationResult[dict]]):
    """Command to request starting a stopped CML Worker (spec update).

    This command sets desired_status=RUNNING. The worker-controller
    will observe this change and reconcile by starting the EC2 instance.

    Pattern: spec (desired_status) vs state (status) reconciliation

    Attributes:
        worker_id: Worker identifier
        started_by: User ID who initiated the start (None for auto-resume)
        is_auto_resume: Whether this is an automatic resume (future feature)
        reason: Optional reason for starting (e.g., "manual", "auto")
    """

    worker_id: str
    started_by: str | None = None
    is_auto_resume: bool = False
    reason: str | None = None


class StartCMLWorkerCommandHandler(
    CommandHandlerBase,
    CommandHandler[StartCMLWorkerCommand, OperationResult[dict]],
):
    """Handle starting a CML Worker by updating desired_status (spec).

    ADR-015: This handler does NOT call AWS EC2. It only updates the
    desired_status field. Worker-controller reconciles actual state.
    """

    def __init__(self, cml_worker_repository: CMLWorkerRepository):
        self.cml_worker_repository = cml_worker_repository

    async def handle_async(self, request: StartCMLWorkerCommand) -> OperationResult[dict]:
        """Handle start CML Worker command by updating desired_status.

        Args:
            request: Start command with worker ID

        Returns:
            OperationResult with worker status details
        """
        command = request

        # Add tracing context
        add_span_attributes(
            {
                "cml_worker.id": command.worker_id,
                "cml_worker.has_started_by": command.started_by is not None,
                "cml_worker.is_auto_resume": command.is_auto_resume,
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
                error_msg = f"Cannot start terminated CML Worker {command.worker_id}"
                log.error(error_msg)
                return self.bad_request(error_msg)

            # Check if already at desired state
            if worker.state.desired_status == CMLWorkerStatus.RUNNING:
                log.info(f"CML Worker {command.worker_id} already has desired_status=RUNNING")
                return self.ok(
                    {
                        "id": worker.id(),
                        "status": worker.state.status.value,
                        "desired_status": worker.state.desired_status.value,
                        "message": "Already has desired_status=RUNNING",
                    }
                )

            with tracer.start_as_current_span("update_desired_status") as span:
                # Update desired_status (spec) - worker-controller will reconcile
                resume_reason = command.reason or ("auto" if command.is_auto_resume else "manual")
                requested_by = None if command.is_auto_resume else command.started_by

                worker.update_desired_status(
                    new_desired_status=CMLWorkerStatus.RUNNING,
                    requested_by=requested_by,
                    reason=resume_reason,
                )

                # Record resume metrics (auto vs manual) for tracking
                worker.resume(
                    reason=resume_reason,
                    resumed_by=requested_by,
                )

                span.set_attribute("cml_worker.new_desired_status", CMLWorkerStatus.RUNNING.value)
                span.set_attribute("cml_worker.resume_reason", resume_reason)

            # Save worker (will publish domain events)
            await self.cml_worker_repository.update_async(worker)

            log.info(f"CML Worker desired_status updated to RUNNING: id={worker.id()}, current_status={worker.state.status.value}, reason={resume_reason}, is_auto_resume={command.is_auto_resume}")

            return self.ok(
                {
                    "id": worker.id(),
                    "status": worker.state.status.value,
                    "desired_status": worker.state.desired_status.value,
                    "message": "Start requested - worker-controller will reconcile",
                }
            )

        except Exception as e:
            log.error(f"Unexpected error updating CML Worker desired_status: {e}", exc_info=True)
            return self.internal_server_error(f"Unexpected error: {str(e)}")
