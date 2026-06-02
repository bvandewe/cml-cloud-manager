"""Update CML Worker status command with handler.

Database-only status query. Does NOT call AWS EC2.
For status updates from EC2, use worker-controller reconciliation.

ADR-015: Control-plane-api MUST NOT call AWS EC2 directly.
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
class UpdateCMLWorkerStatusCommand(Command[OperationResult[dict[str, str]]]):
    """Command to get current CML Worker status (database-only).

    ADR-015: This command does NOT query AWS. It returns current status from database.
    Worker-controller is responsible for syncing status from EC2.

    If a direct status update is needed (e.g., from worker-controller), use:
    - MarkWorkerTerminatedCommand (for termination)
    - Internal status update endpoints

    Attributes:
        worker_id: ID of the worker to get status for
        status: Optional - if provided, updates the status (for internal use only)
        metrics: Optional metrics dict to include in response
    """

    worker_id: str
    status: str | None = None
    ec2_instance_id: str | None = None
    metrics: dict | None = None


class UpdateCMLWorkerStatusCommandHandler(
    CommandHandlerBase,
    CommandHandler[UpdateCMLWorkerStatusCommand, OperationResult[dict[str, str]]],
):
    """Handle getting/updating CML Worker status (database-only).

    ADR-015: This handler does NOT call AWS EC2.
    """

    def __init__(self, cml_worker_repository: CMLWorkerRepository):
        self.cml_worker_repository = cml_worker_repository

    async def handle_async(self, request: UpdateCMLWorkerStatusCommand) -> OperationResult[dict[str, str]]:
        """Handle get/update CML Worker status command (database-only).

        Args:
            request: Command with worker ID and optional status override

        Returns:
            OperationResult with current status information
        """
        command = request

        # Add tracing context
        add_span_attributes(
            {
                "cml_worker.id": command.worker_id,
                "cml_worker.has_status_override": command.status is not None,
            }
        )

        try:
            with tracer.start_as_current_span("retrieve_cml_worker") as span:
                # Retrieve worker from repository (database only, no AWS call)
                worker = await self.cml_worker_repository.get_by_id_async(command.worker_id)

                if not worker:
                    error_msg = f"CML Worker not found: {command.worker_id}"
                    log.error(error_msg)
                    return self.not_found("CMLWorker", error_msg)

                span.set_attribute("cml_worker.current_status", worker.state.status.value)
                span.set_attribute("cml_worker.desired_status", worker.state.desired_status.value)
                span.set_attribute("ec2.instance_id", worker.state.aws_instance_id or "none")

            # If status override is provided, update the worker status
            if command.status:
                with tracer.start_as_current_span("update_worker_status") as span:
                    try:
                        new_status = CMLWorkerStatus(command.status)
                        status_updated = worker.update_status(new_status)

                        if status_updated:
                            await self.cml_worker_repository.update_async(worker)
                            log.info(f"CML Worker status updated: id={worker.id()}, new_status={worker.state.status.value}")

                        span.set_attribute("cml_worker.status_updated", status_updated)
                    except ValueError:
                        return self.bad_request(f"Invalid status value: {command.status}")

            # If EC2 instance ID is provided, assign it to the worker
            if command.ec2_instance_id:
                with tracer.start_as_current_span("assign_instance") as span:
                    worker.assign_instance(aws_instance_id=command.ec2_instance_id)
                    await self.cml_worker_repository.update_async(worker)
                    log.info(f"EC2 instance assigned to worker: id={worker.id()}, ec2_instance_id={command.ec2_instance_id}")
                    span.set_attribute("cml_worker.ec2_instance_id", command.ec2_instance_id)

            # Build response with current status info
            status_info = {
                "worker_id": worker.id(),
                "status": worker.state.status.value,
                "desired_status": worker.state.desired_status.value,
                "instance_state": worker.state.status.value,  # For backward compatibility
                "instance_id": worker.state.aws_instance_id or "none",
                "aws_region": worker.state.aws_region,
            }

            # Add metrics if provided
            if command.metrics:
                status_info.update(command.metrics)

            log.debug(f"CML Worker status query: id={worker.id()}, status={worker.state.status.value}, desired_status={worker.state.desired_status.value}")

            return self.ok(status_info)

        except Exception as e:
            log.error(f"Unexpected error getting CML Worker status: {e}", exc_info=True)
            return self.internal_server_error(f"Unexpected error: {str(e)}")
