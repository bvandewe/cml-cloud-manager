"""Command for disabling idle detection on a CML worker."""

import logging
from dataclasses import dataclass

from application.commands.command_handler_base import CommandHandlerBase
from domain.repositories import CMLWorkerRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class DisableIdleDetectionCommand(Command[OperationResult[dict]]):
    """Command to disable idle detection for a CML worker.

    When idle detection is disabled, the worker will not be automatically stopped
    due to inactivity, even if the idle timeout threshold is reached.

    Attributes:
        worker_id: Worker identifier
        disabled_by: Optional user ID who disabled idle detection
    """

    worker_id: str
    disabled_by: str | None = None


class DisableIdleDetectionCommandHandler(CommandHandlerBase, CommandHandler[DisableIdleDetectionCommand, OperationResult[dict]]):
    """Handler for DisableIdleDetectionCommand.

    Updates the worker aggregate to disable idle detection.
    """

    def __init__(self, worker_repository: CMLWorkerRepository):
        """Initialize the handler.

        Args:
            worker_repository: Repository for CML worker aggregates
        """
        self._repository = worker_repository

    async def handle_async(self, request: DisableIdleDetectionCommand) -> OperationResult[dict]:
        """Execute the command.

        Args:
            request: Command parameters

        Returns:
            OperationResult with idle detection status
        """
        with tracer.start_as_current_span("DisableIdleDetectionCommandHandler.handle_async") as span:
            span.set_attribute("worker_id", request.worker_id)
            span.set_attribute("disabled_by", request.disabled_by or "system")

            try:
                # Retrieve worker
                worker = await self._repository.get_by_id_async(request.worker_id)

                if not worker:
                    log.warning(f"Worker {request.worker_id} not found")
                    span.set_status(Status(StatusCode.ERROR, "Worker not found"))
                    return self.not_found(
                        f"Worker {request.worker_id}",
                        f"Worker {request.worker_id} not found",
                    )

                # Check if already disabled
                if not worker.state.is_idle_detection_enabled:
                    log.info(f"Idle detection already disabled for worker {request.worker_id}")
                    return self.ok(
                        {
                            "worker_id": request.worker_id,
                            "idle_detection_enabled": False,
                            "message": "Idle detection already disabled",
                        }
                    )

                # Disable idle detection
                log.info(f"Disabling idle detection for worker {request.worker_id}")
                worker.disable_idle_detection(disabled_by=request.disabled_by)

                # Save worker
                await self._repository.update_async(worker)

                log.info(f"Successfully disabled idle detection for worker {request.worker_id}")
                span.set_status(Status(StatusCode.OK))

                return self.ok(
                    {
                        "worker_id": request.worker_id,
                        "idle_detection_enabled": False,
                        "message": "Idle detection disabled successfully",
                    }
                )

            except Exception as e:
                log.exception(f"Error disabling idle detection for worker {request.worker_id}: {e}")
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return self.internal_server_error(f"Failed to disable idle detection: {e}")
