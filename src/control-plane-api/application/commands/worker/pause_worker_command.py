"""Command for pausing (stopping) a CML worker.

DEPRECATED: Use StopCMLWorkerCommand with is_auto_pause=True for auto-pause
and is_auto_pause=False for manual pause. This command is kept for backward
compatibility with the idle detection system.
"""

import logging
from dataclasses import dataclass

from infrastructure.observability.cqrs_instrumentation import instrumented
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler, Mediator
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .stop_cml_worker_command import StopCMLWorkerCommand

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class PauseWorkerCommand(Command[OperationResult[None]]):
    """Command to pause (stop) a CML worker.

    DEPRECATED: Use StopCMLWorkerCommand directly.

    Attributes:
        worker_id: Worker identifier
        is_auto_pause: Whether this is an automatic pause (True) or manual (False)
        reason: Optional reason for pausing
    """

    worker_id: str
    is_auto_pause: bool = True
    reason: str | None = None


@instrumented
class PauseWorkerCommandHandler(CommandHandler[PauseWorkerCommand, OperationResult[None]]):
    """Handler for PauseWorkerCommand.

    DEPRECATED: Delegates to StopCMLWorkerCommand for unified stop/pause handling.
    """

    def __init__(self, mediator: Mediator):
        """Initialize the handler.

        Args:
            mediator: Mediator for executing commands
        """
        self._mediator = mediator

    async def handle_async(self, command: PauseWorkerCommand) -> OperationResult[None]:
        """Execute the command by delegating to StopCMLWorkerCommand.

        Args:
            command: Command parameters

        Returns:
            OperationResult indicating success or failure
        """
        with tracer.start_as_current_span("PauseWorkerCommandHandler.handle_async") as span:
            span.set_attribute("worker_id", command.worker_id)
            span.set_attribute("is_auto_pause", command.is_auto_pause)

            log.info(f"PauseWorkerCommand delegating to StopCMLWorkerCommand: " f"worker_id={command.worker_id}, is_auto_pause={command.is_auto_pause}")

            # Delegate to unified StopCMLWorkerCommand
            stop_command = StopCMLWorkerCommand(
                worker_id=command.worker_id,
                stopped_by="system" if command.is_auto_pause else None,
                is_auto_pause=command.is_auto_pause,
                reason=command.reason,
            )

            result = await self._mediator.execute_async(stop_command)

            if result.is_success:
                span.set_status(Status(StatusCode.OK))
                return self.no_content()
            else:
                span.set_status(Status(StatusCode.ERROR, result.error_message or "Unknown error"))
                return self.bad_request(result.error_message or "Failed to pause worker")
