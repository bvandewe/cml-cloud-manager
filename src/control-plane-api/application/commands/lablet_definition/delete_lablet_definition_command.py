"""Delete LabletDefinition command — soft-deletes the definition."""

import logging
from dataclasses import dataclass

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.lablet_definition import LabletDefinition
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

logger = logging.getLogger(__name__)


@dataclass
class DeleteLabletDefinitionCommand(Command[OperationResult[dict]]):
    """Command to soft-delete a LabletDefinition."""

    definition_id: str = ""
    deleted_by: str = ""


class DeleteLabletDefinitionCommandHandler(
    CommandHandlerBase,
    CommandHandler[DeleteLabletDefinitionCommand, OperationResult[dict]],
):
    """Handle LabletDefinition soft-deletion."""

    def __init__(self, lablet_definition_repository: LabletDefinitionRepository):
        self._repository = lablet_definition_repository

    async def handle_async(self, request: DeleteLabletDefinitionCommand) -> OperationResult[dict]:
        """Soft-delete a LabletDefinition.

        Marks the definition as DELETED. It will be excluded from all listings
        but remains in the database for audit purposes.
        """
        if not request.definition_id:
            return self.bad_request("definition_id is required")

        definition: LabletDefinition | None = await self._repository.get_by_id_async(request.definition_id)
        if not definition:
            return self.not_found(LabletDefinition, request.definition_id)

        try:
            definition.soft_delete(deleted_by=request.deleted_by)
        except ValueError as e:
            return self.bad_request(str(e))

        await self._repository.update_async(definition)

        logger.info(
            "LabletDefinition soft-deleted: %s (name=%s, version=%s, by=%s)",
            definition.id(),
            definition.state.name,
            definition.state.version,
            request.deleted_by,
        )

        return self.no_content()
