"""Create WorkerTemplate command with handler.

Creates a new WorkerTemplate aggregate for worker provisioning.
ADR-007: Templates are managed as configuration, seeded from YAML + API managed at runtime.
"""

import logging
from dataclasses import dataclass

from application.commands.command_handler_base import CommandHandlerBase
from application.dtos.worker_template_dto import WorkerTemplateCreatedDto
from domain.entities.worker_template import WorkerTemplate
from domain.repositories.worker_template_repository import WorkerTemplateRepository
from domain.value_objects.worker_capacity import WorkerCapacity
from integration.enums import Ec2InstanceType
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

logger = logging.getLogger(__name__)


@dataclass
class CreateWorkerTemplateCommand(Command[OperationResult[WorkerTemplateCreatedDto]]):
    """Command to create a new WorkerTemplate.

    Validates inputs, checks for duplicate names, then creates the aggregate.
    """

    name: str = ""
    description: str = ""
    instance_type: str = ""

    # Capacity configuration
    cpu_cores: int = 4
    memory_gb: int = 8
    storage_gb: int = 100
    max_nodes: int | None = 50

    # Configuration
    ami_name_pattern: str = "cisco-cml2.9*"
    cost_per_hour_usd: float = 0.0
    enabled: bool = True


class CreateWorkerTemplateCommandHandler(
    CommandHandlerBase,
    CommandHandler[CreateWorkerTemplateCommand, OperationResult[WorkerTemplateCreatedDto]],
):
    """Handle WorkerTemplate creation."""

    def __init__(self, worker_template_repository: WorkerTemplateRepository):
        self._repository = worker_template_repository

    async def handle_async(self, request: CreateWorkerTemplateCommand) -> OperationResult[WorkerTemplateCreatedDto]:
        """Handle create WorkerTemplate command."""
        command = request

        # Validate required fields
        if not command.name or not command.name.strip():
            return self.bad_request("Name is required")
        if not command.description or not command.description.strip():
            return self.bad_request("Description is required")
        if not command.instance_type or not command.instance_type.strip():
            return self.bad_request("Instance type is required")

        # Validate instance type enum
        try:
            instance_type = Ec2InstanceType(command.instance_type)
        except ValueError:
            valid_types = ", ".join(it.value for it in Ec2InstanceType)
            return self.bad_request(f"Invalid instance type '{command.instance_type}'. Must be one of: {valid_types}")

        # Check for duplicate name
        existing = await self._repository.get_by_name_async(command.name.strip())
        if existing:
            return self.conflict(f"WorkerTemplate with name '{command.name}' already exists")

        try:
            # Build capacity
            capacity = WorkerCapacity(
                cpu_cores=command.cpu_cores,
                memory_gb=command.memory_gb,
                storage_gb=command.storage_gb,
                max_nodes=command.max_nodes,
            )

            # Create aggregate
            template = WorkerTemplate.create(
                name=command.name.strip(),
                description=command.description.strip(),
                instance_type=instance_type,
                capacity=capacity,
                ami_name_pattern=command.ami_name_pattern,
                cost_per_hour_usd=command.cost_per_hour_usd,
                enabled=command.enabled,
            )

            # Persist
            await self._repository.add_async(template)

            logger.info("Created WorkerTemplate: %s (name=%s, type=%s)", template.id(), template.state.name, instance_type.value)

            dto = WorkerTemplateCreatedDto(
                id=template.id(),
                name=template.state.name,
                description=template.state.description,
                instance_type=template.state.instance_type.value,
                enabled=template.state.enabled,
                created_at=template.state.created_at.isoformat(),
            )
            return self.created(dto)

        except ValueError as e:
            logger.warning("Validation error creating WorkerTemplate: %s", e)
            return self.bad_request(str(e))

        except Exception as e:
            logger.error("Error creating WorkerTemplate: %s", e, exc_info=True)
            return self.internal_server_error(str(e))
