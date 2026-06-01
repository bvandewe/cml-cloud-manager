"""Disable WorkerTemplate command with handler.

Disables a WorkerTemplate so it cannot be used for new worker provisioning.
"""

import logging
from dataclasses import dataclass

from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

from application.commands.command_handler_base import CommandHandlerBase
from application.dtos.worker_template_dto import WorkerTemplateDto, map_worker_template_to_dto
from domain.repositories.worker_template_repository import WorkerTemplateRepository

logger = logging.getLogger(__name__)


@dataclass
class DisableWorkerTemplateCommand(Command[OperationResult[WorkerTemplateDto]]):
    """Command to disable a WorkerTemplate."""

    template_id: str = ""


class DisableWorkerTemplateCommandHandler(
    CommandHandlerBase,
    CommandHandler[DisableWorkerTemplateCommand, OperationResult[WorkerTemplateDto]],
):
    """Handle disabling a WorkerTemplate."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        worker_template_repository: WorkerTemplateRepository,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._repository = worker_template_repository

    async def handle_async(self, request: DisableWorkerTemplateCommand) -> OperationResult[WorkerTemplateDto]:
        """Handle disable WorkerTemplate command."""
        if not request.template_id or not request.template_id.strip():
            return self.bad_request("Template ID is required")

        template = await self._repository.get_by_id_async(request.template_id)
        if not template:
            return self.not_found("WorkerTemplate", f"WorkerTemplate '{request.template_id}' not found")

        if template.state.deleted:
            return self.bad_request("Cannot disable a deleted template")

        if not template.state.enabled:
            # Already disabled — return current state
            dto = map_worker_template_to_dto(template)
            return self.ok(dto)

        try:
            template.disable()
            await self._repository.update_async(template)

            logger.info("Disabled WorkerTemplate: %s (name=%s)", template.id(), template.state.name)

            dto = map_worker_template_to_dto(template)
            return self.ok(dto)

        except Exception as e:
            logger.error("Error disabling WorkerTemplate: %s", e, exc_info=True)
            return self.internal_server_error(str(e))
