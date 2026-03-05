"""Update WorkerTemplate command with handler.

Updates mutable fields of an existing WorkerTemplate.
Only fields present in the request will be updated.
"""

import logging
from dataclasses import dataclass
from typing import Any

from application.commands.command_handler_base import CommandHandlerBase
from application.dtos.worker_template_dto import WorkerTemplateDto, map_worker_template_to_dto
from domain.repositories.worker_template_repository import WorkerTemplateRepository
from domain.value_objects.worker_capacity import WorkerCapacity
from integration.enums import Ec2InstanceType
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

logger = logging.getLogger(__name__)


@dataclass
class UpdateWorkerTemplateCommand(Command[OperationResult[WorkerTemplateDto]]):
    """Command to update mutable fields of a WorkerTemplate.

    Only fields present (non-None) will be updated.
    Name is immutable and cannot be changed.
    """

    template_id: str = ""

    # Mutable fields (all optional — only provided ones are updated)
    description: str | None = None
    instance_type: str | None = None
    ami_name_pattern: str | None = None
    cost_per_hour_usd: float | None = None

    # Capacity fields (if any provided, merges with existing)
    cpu_cores: int | None = None
    memory_gb: int | None = None
    storage_gb: int | None = None
    max_nodes: int | None = None


class UpdateWorkerTemplateCommandHandler(
    CommandHandlerBase,
    CommandHandler[UpdateWorkerTemplateCommand, OperationResult[WorkerTemplateDto]],
):
    """Handle WorkerTemplate update."""

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

    async def handle_async(self, request: UpdateWorkerTemplateCommand) -> OperationResult[WorkerTemplateDto]:
        """Handle update WorkerTemplate command."""
        command = request

        # Validate template_id
        if not command.template_id or not command.template_id.strip():
            return self.bad_request("Template ID is required")

        # Fetch existing template
        template = await self._repository.get_by_id_async(command.template_id)
        if not template:
            return self.not_found("WorkerTemplate", f"WorkerTemplate '{command.template_id}' not found")

        if template.state.deleted:
            return self.bad_request("Cannot update a deleted template")

        try:
            # Resolve optional fields
            update_kwargs: dict[str, Any] = {}

            if command.description is not None:
                update_kwargs["description"] = command.description.strip()

            if command.instance_type is not None:
                try:
                    update_kwargs["instance_type"] = Ec2InstanceType(command.instance_type)
                except ValueError:
                    valid_types = ", ".join(it.value for it in Ec2InstanceType)
                    return self.bad_request(f"Invalid instance type '{command.instance_type}'. Must be one of: {valid_types}")

            if command.ami_name_pattern is not None:
                update_kwargs["ami_name_pattern"] = command.ami_name_pattern.strip()

            if command.cost_per_hour_usd is not None:
                update_kwargs["cost_per_hour_usd"] = command.cost_per_hour_usd

            # Build capacity if any capacity field is provided
            has_capacity_change = any(v is not None for v in [command.cpu_cores, command.memory_gb, command.storage_gb, command.max_nodes])
            if has_capacity_change:
                current = template.state.capacity
                update_kwargs["capacity"] = WorkerCapacity(
                    cpu_cores=command.cpu_cores if command.cpu_cores is not None else current.cpu_cores,
                    memory_gb=command.memory_gb if command.memory_gb is not None else current.memory_gb,
                    storage_gb=command.storage_gb if command.storage_gb is not None else current.storage_gb,
                    max_nodes=command.max_nodes if command.max_nodes is not None else current.max_nodes,
                )

            if not update_kwargs:
                return self.bad_request("No fields to update")

            # Apply update via aggregate method
            template.update(**update_kwargs)

            # Persist
            await self._repository.update_async(template)

            logger.info(
                "Updated WorkerTemplate: %s (fields: %s)",
                template.id(),
                ", ".join(update_kwargs.keys()),
            )

            dto = map_worker_template_to_dto(template)
            return self.ok(dto)

        except ValueError as e:
            logger.warning("Validation error updating WorkerTemplate: %s", e)
            return self.bad_request(str(e))

        except Exception as e:
            logger.error("Error updating WorkerTemplate: %s", e, exc_info=True)
            return self.internal_server_error(str(e))
