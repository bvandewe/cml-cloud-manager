"""Enable WorkerTemplate command with handler.

Re-enables a previously disabled WorkerTemplate for worker provisioning.
"""

import logging
from dataclasses import dataclass

from application.commands.command_handler_base import CommandHandlerBase
from application.dtos.worker_template_dto import WorkerTemplateDto, map_worker_template_to_dto
from domain.repositories.worker_template_repository import WorkerTemplateRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

logger = logging.getLogger(__name__)


@dataclass
class EnableWorkerTemplateCommand(Command[OperationResult[WorkerTemplateDto]]):
    """Command to enable a WorkerTemplate."""

    template_id: str = ""


class EnableWorkerTemplateCommandHandler(
    CommandHandlerBase,
    CommandHandler[EnableWorkerTemplateCommand, OperationResult[WorkerTemplateDto]],
):
    """Handle enabling a WorkerTemplate."""

    def __init__(self, worker_template_repository: WorkerTemplateRepository):
        self._repository = worker_template_repository

    async def handle_async(self, request: EnableWorkerTemplateCommand) -> OperationResult[WorkerTemplateDto]:
        """Handle enable WorkerTemplate command."""
        if not request.template_id or not request.template_id.strip():
            return self.bad_request("Template ID is required")

        template = await self._repository.get_by_id_async(request.template_id)
        if not template:
            return self.not_found("WorkerTemplate", f"WorkerTemplate '{request.template_id}' not found")

        if template.state.deleted:
            return self.bad_request("Cannot enable a deleted template")

        if template.state.enabled:
            # Already enabled — return current state
            dto = map_worker_template_to_dto(template)
            return self.ok(dto)

        try:
            template.enable()
            await self._repository.update_async(template)

            logger.info("Enabled WorkerTemplate: %s (name=%s)", template.id(), template.state.name)

            dto = map_worker_template_to_dto(template)
            return self.ok(dto)

        except Exception as e:
            logger.error("Error enabling WorkerTemplate: %s", e, exc_info=True)
            return self.internal_server_error(str(e))
