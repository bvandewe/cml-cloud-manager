"""Deactivate LabletDefinition command — transitions from ACTIVE to INACTIVE."""

import logging
from dataclasses import dataclass

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.lablet_definition import LabletDefinition
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

logger = logging.getLogger(__name__)


@dataclass
class DeactivateLabletDefinitionCommand(Command[OperationResult[dict]]):
    """Command to deactivate a LabletDefinition (temporarily remove from scheduling)."""

    definition_id: str = ""
    deactivated_by: str = ""
    reason: str | None = None


class DeactivateLabletDefinitionCommandHandler(
    CommandHandlerBase,
    CommandHandler[DeactivateLabletDefinitionCommand, OperationResult[dict]],
):
    """Handle LabletDefinition deactivation."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        lablet_definition_repository: LabletDefinitionRepository,
    ):
        super().__init__(
            mediator,
            mapper,
            cloud_event_bus,
            cloud_event_publishing_options,
        )
        self._repository = lablet_definition_repository

    async def handle_async(self, request: DeactivateLabletDefinitionCommand) -> OperationResult[dict]:
        """Deactivate a LabletDefinition.

        Transitions the definition from ACTIVE to INACTIVE,
        temporarily removing it from scheduling availability.
        """
        if not request.definition_id:
            return self.bad_request("definition_id is required")

        definition: LabletDefinition | None = await self._repository.get_by_id_async(request.definition_id)
        if not definition:
            return self.not_found(LabletDefinition, request.definition_id)

        try:
            definition.deactivate(deactivated_by=request.deactivated_by, reason=request.reason)
        except ValueError as e:
            return self.bad_request(str(e))

        await self._repository.update_async(definition)

        logger.info(
            "LabletDefinition deactivated: %s (name=%s, version=%s, by=%s, reason=%s)",
            definition.id(),
            definition.state.name,
            definition.state.version,
            request.deactivated_by,
            request.reason,
        )

        return self.ok(
            {
                "definition_id": definition.id(),
                "name": definition.state.name,
                "version": definition.state.version,
                "status": definition.state.status.value,
            }
        )
