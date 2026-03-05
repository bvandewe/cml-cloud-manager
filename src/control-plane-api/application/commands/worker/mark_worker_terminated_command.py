"""Mark Worker Terminated command with handler.

This command marks a worker as TERMINATED in the database WITHOUT calling AWS EC2.
Used by worker-controller when it detects an EC2 instance is gone (orphan detection).

ADR-015: Control-plane-api MUST NOT call AWS EC2 directly.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from domain.enums import CMLWorkerStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator
from neuroglia.observability.tracing import add_span_attributes
from opentelemetry import trace

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class MarkWorkerTerminatedCommand(Command[OperationResult[dict]]):
    """Command to mark a worker as TERMINATED without calling AWS.

    This is a database-only operation used when:
    - Worker-controller detects an orphaned worker (EC2 instance gone)
    - External system confirms worker termination
    - Manual cleanup of stale worker records

    This command does NOT:
    - Call AWS EC2 API
    - Attempt to terminate any EC2 instance
    - Verify EC2 instance state

    Args:
        worker_id: ID of the worker to mark as terminated
        terminated_by: Optional user/system identifier
        reason: Optional reason for termination (e.g., "orphan_detection", "manual_cleanup")
    """

    worker_id: str
    terminated_by: str | None = None
    reason: str | None = None


class MarkWorkerTerminatedCommandHandler(
    CommandHandlerBase,
    CommandHandler[MarkWorkerTerminatedCommand, OperationResult[dict]],
):
    """Handle marking a worker as terminated (database-only, no AWS calls)."""

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

    async def handle_async(self, request: MarkWorkerTerminatedCommand) -> OperationResult[dict]:
        """Handle mark worker terminated command.

        Args:
            request: Command with worker ID and optional metadata

        Returns:
            OperationResult with worker info if successful, or error
        """
        command = request

        # Add tracing context
        add_span_attributes(
            {
                "cml_worker.id": command.worker_id,
                "cml_worker.terminated_by": command.terminated_by or "system",
                "cml_worker.termination_reason": command.reason or "not_specified",
            }
        )

        try:
            with tracer.start_as_current_span("retrieve_cml_worker") as span:
                # Retrieve worker from repository
                worker = await self.cml_worker_repository.get_by_id_async(command.worker_id)

                if not worker:
                    error_msg = f"CML Worker not found: {command.worker_id}"
                    log.warning(error_msg)
                    return self.not_found("CML Worker", error_msg)

                span.set_attribute("cml_worker.current_status", worker.state.status.value)
                span.set_attribute("cml_worker.name", worker.state.name)

            with tracer.start_as_current_span("mark_worker_terminated") as span:
                # Check if already terminated
                if worker.state.status == CMLWorkerStatus.TERMINATED:
                    log.info(f"Worker {command.worker_id} is already terminated, skipping")
                    return self.ok(
                        {
                            "worker_id": command.worker_id,
                            "name": worker.state.name,
                            "status": "TERMINATED",
                            "already_terminated": True,
                        }
                    )

                old_status = worker.state.status.value

                # Mark as terminated using the entity method
                worker.terminate(terminated_by=command.terminated_by)

                span.set_attribute("cml_worker.old_status", old_status)
                span.set_attribute("cml_worker.new_status", "TERMINATED")

            # Save worker (will publish domain events)
            await self.cml_worker_repository.update_async(worker)

            log.info(
                f"Marked worker as terminated: id={command.worker_id}, "
                f"name={worker.state.name}, "
                f"old_status={old_status}, "
                f"reason={command.reason or 'not_specified'}, "
                f"terminated_by={command.terminated_by or 'system'}"
            )

            return self.ok(
                {
                    "worker_id": command.worker_id,
                    "name": worker.state.name,
                    "old_status": old_status,
                    "status": "TERMINATED",
                    "terminated_at": datetime.now(timezone.utc).isoformat(),
                    "terminated_by": command.terminated_by or "system",
                    "reason": command.reason,
                    "already_terminated": False,
                }
            )

        except Exception as e:
            log.error(f"Failed to mark worker {command.worker_id} as terminated: {e}", exc_info=True)
            return self.internal_server_error(f"Failed to mark worker as terminated: {str(e)}")
