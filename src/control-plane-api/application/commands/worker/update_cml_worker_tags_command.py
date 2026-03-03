"""Update CML Worker tags command with handler.

ADR-015: This command is DB-only. It stores desired tags in MongoDB.
The worker-controller watches etcd for state changes and syncs tags to EC2.
"""

import logging
from dataclasses import dataclass

from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator
from neuroglia.observability.tracing import add_span_attributes
from opentelemetry import trace

from domain.repositories.cml_worker_repository import CMLWorkerRepository

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class UpdateCMLWorkerTagsCommand(Command[OperationResult[dict[str, str]]]):
    """Command to update tags on a CML Worker.

    ADR-015: This command is DB-only. It does NOT make EC2 API calls.

    This command:
    1. Retrieves the worker from repository
    2. Updates tags in the worker state (MongoDB)
    3. Worker-controller watches etcd and syncs tags to EC2

    Tags are key-value pairs that help organize and identify resources.
    """

    worker_id: str
    tags: dict[str, str]
    updated_by: str | None = None


class UpdateCMLWorkerTagsCommandHandler(
    CommandHandlerBase,
    CommandHandler[UpdateCMLWorkerTagsCommand, OperationResult[dict[str, str]]],
):
    """Handle updating tags on a CML Worker (DB-only per ADR-015).

    Does NOT make EC2 API calls. Worker-controller handles actual
    EC2 tag synchronization by watching etcd for state changes.
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
        self.cml_worker_repository = cml_worker_repository

    async def handle_async(self, request: UpdateCMLWorkerTagsCommand) -> OperationResult[dict[str, str]]:
        """Handle update CML Worker tags command.

        ADR-015: DB-only operation. No EC2 calls.

        Args:
            request: Update tags command with worker ID and tags

        Returns:
            OperationResult with updated tags dict
        """
        command = request

        # Add tracing context
        add_span_attributes(
            {
                "cml_worker.id": command.worker_id,
                "cml_worker.tags_count": len(command.tags),
                "cml_worker.has_updated_by": command.updated_by is not None,
            }
        )

        if not command.tags:
            error_msg = "No tags provided to update"
            log.error(error_msg)
            return self.bad_request(error_msg)

        try:
            with tracer.start_as_current_span("retrieve_cml_worker") as span:
                # Retrieve worker from repository
                worker = await self.cml_worker_repository.get_by_id_async(command.worker_id)

                if not worker:
                    error_msg = f"CML Worker not found: {command.worker_id}"
                    log.error(error_msg)
                    return self.not_found("CMLWorker", error_msg)

                span.set_attribute("ec2.instance_id", worker.state.aws_instance_id or "none")

            with tracer.start_as_current_span("update_tags_in_db") as span:
                # Update tags in worker state (DB-only)
                # Merge with existing tags
                current_tags = worker.state.tags or {}
                updated_tags = {**current_tags, **command.tags}

                # Use aggregate method if available, otherwise update state directly
                # For now, update the state directly since tags is a simple dict
                worker.state.tags = updated_tags

                await self.cml_worker_repository.update_async(worker)

                span.set_attribute("cml_worker.total_tags", len(updated_tags))
                span.set_attribute("cml_worker.new_tags_count", len(command.tags))

            log.info(
                f"CML Worker tags updated in DB: id={worker.id()}, "
                f"aws_instance_id={worker.state.aws_instance_id or 'none'}, "
                f"updated_tags={list(command.tags.keys())}. "
                f"Worker-controller will sync to EC2 via etcd watch."
            )

            return self.ok(updated_tags)

        except Exception as e:
            log.exception(f"Unexpected error updating tags for CML Worker {command.worker_id}")
            return self.internal_server_error(f"Unexpected error: {str(e)}")
