"""Command for enabling idle detection on a CML worker."""

import logging
from dataclasses import dataclass

from domain.repositories import CMLWorkerRepository
from infrastructure.observability.cqrs_instrumentation import instrumented
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class EnableIdleDetectionCommand(Command[OperationResult[dict]]):
    """Command to enable idle detection for a CML worker.

    When idle detection is enabled, the worker will be automatically stopped
    after a configured idle timeout period to save costs.

    Attributes:
        worker_id: Worker identifier
        enabled_by: Optional user ID who enabled idle detection
    """

    worker_id: str
    enabled_by: str | None = None


@instrumented
class EnableIdleDetectionCommandHandler(CommandHandler[EnableIdleDetectionCommand, OperationResult[dict]]):
    """Handler for EnableIdleDetectionCommand.

    Updates the worker aggregate to enable idle detection.
    """

    def __init__(self, worker_repository: CMLWorkerRepository):
        """Initialize the handler.

        Args:
            worker_repository: Repository for CML worker aggregates
        """
        self._repository = worker_repository

    async def handle_async(self, request: EnableIdleDetectionCommand) -> OperationResult[dict]:
        """Execute the command.

        Args:
            request: Command parameters

        Returns:
            OperationResult with idle detection status
        """
        with tracer.start_as_current_span("EnableIdleDetectionCommandHandler.handle_async") as span:
            span.set_attribute("worker_id", request.worker_id)
            span.set_attribute("enabled_by", request.enabled_by or "system")

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

                # Check if already enabled
                if worker.state.is_idle_detection_enabled:
                    log.info(f"Idle detection already enabled for worker {request.worker_id}")
                    return self.ok(
                        {
                            "worker_id": request.worker_id,
                            "idle_detection_enabled": True,
                            "message": "Idle detection already enabled",
                        }
                    )

                # Enable idle detection
                log.info(f"Enabling idle detection for worker {request.worker_id}")
                worker.enable_idle_detection(enabled_by=request.enabled_by)

                # Save worker
                await self._repository.update_async(worker)

                log.info(f"Successfully enabled idle detection for worker {request.worker_id}")
                span.set_status(Status(StatusCode.OK))

                return self.ok(
                    {
                        "worker_id": request.worker_id,
                        "idle_detection_enabled": True,
                        "message": "Idle detection enabled successfully",
                    }
                )

            except Exception as e:
                log.exception(f"Error enabling idle detection for worker {request.worker_id}: {e}")
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return self.internal_server_error(f"Failed to enable idle detection: {e}")
