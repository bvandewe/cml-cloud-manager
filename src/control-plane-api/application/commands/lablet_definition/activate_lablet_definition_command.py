"""Activate LabletDefinition command — transitions from INACTIVE/ARCHIVED to ACTIVE."""

import logging
from dataclasses import dataclass

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.lablet_definition import LabletDefinition
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

logger = logging.getLogger(__name__)


@dataclass
class ActivateLabletDefinitionCommand(Command[OperationResult[dict]]):
    """Command to activate a LabletDefinition (make it available for scheduling)."""

    definition_id: str = ""
    activated_by: str = ""


class ActivateLabletDefinitionCommandHandler(
    CommandHandlerBase,
    CommandHandler[ActivateLabletDefinitionCommand, OperationResult[dict]],
):
    """Handle LabletDefinition activation."""

    def __init__(self, lablet_definition_repository: LabletDefinitionRepository):
        self._repository = lablet_definition_repository

    async def handle_async(self, request: ActivateLabletDefinitionCommand) -> OperationResult[dict]:
        """Activate a LabletDefinition.

        Transitions the definition from INACTIVE/ARCHIVED to ACTIVE,
        making it available for scheduling new lablet sessions.
        """
        if not request.definition_id:
            return self.bad_request("definition_id is required")

        definition: LabletDefinition | None = await self._repository.get_by_id_async(request.definition_id)
        if not definition:
            return self.not_found(LabletDefinition, request.definition_id)

        try:
            definition.activate(activated_by=request.activated_by)
        except ValueError as e:
            return self.bad_request(str(e))

        await self._repository.update_async(definition)

        logger.info(
            "LabletDefinition activated: %s (name=%s, version=%s, by=%s)",
            definition.id(),
            definition.state.name,
            definition.state.version,
            request.activated_by,
        )

        return self.ok(
            {
                "definition_id": definition.id(),
                "name": definition.state.name,
                "version": definition.state.version,
                "status": definition.state.status.value,
            }
        )
