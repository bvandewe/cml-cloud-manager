"""Delete (soft) WorkerTemplate command with handler.

Performs a soft delete: marks the template as deleted and disabled.
The record is kept in the database for audit purposes.
"""

import logging
from dataclasses import dataclass

from application.commands.command_handler_base import CommandHandlerBase
from domain.repositories.worker_template_repository import WorkerTemplateRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

logger = logging.getLogger(__name__)


@dataclass
class DeleteWorkerTemplateCommand(Command[OperationResult[dict]]):
    """Command to soft-delete a WorkerTemplate.

    Sets deleted=True and enabled=False. The record remains in the DB.
    """

    template_id: str = ""


class DeleteWorkerTemplateCommandHandler(
    CommandHandlerBase,
    CommandHandler[DeleteWorkerTemplateCommand, OperationResult[dict]],
):
    """Handle WorkerTemplate soft delete."""

    def __init__(self, worker_template_repository: WorkerTemplateRepository):
        self._repository = worker_template_repository

    async def handle_async(self, request: DeleteWorkerTemplateCommand) -> OperationResult[dict]:
        """Handle delete WorkerTemplate command."""
        command = request

        if not command.template_id or not command.template_id.strip():
            return self.bad_request("Template ID is required")

        template = await self._repository.get_by_id_async(command.template_id)
        if not template:
            return self.not_found("WorkerTemplate", f"WorkerTemplate '{command.template_id}' not found")

        if template.state.deleted:
            return self.bad_request("Template is already deleted")

        try:
            # Soft delete via aggregate method
            template.delete()

            # Persist
            await self._repository.update_async(template)

            logger.info("Soft-deleted WorkerTemplate: %s (name=%s)", template.id(), template.state.name)

            return self.ok(
                {
                    "id": template.id(),
                    "name": template.state.name,
                    "deleted": True,
                    "message": "Template has been soft-deleted",
                }
            )

        except Exception as e:
            logger.error("Error deleting WorkerTemplate: %s", e, exc_info=True)
            return self.internal_server_error(str(e))
