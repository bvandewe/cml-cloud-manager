"""Create LabletDefinition command with handler.

Creates a new LabletDefinition in PENDING_SYNC status (ADR-028).
The form_qualified_name is required and auto-derives bucket_name + lab_artifact_uri.
"""

import logging
from dataclasses import dataclass
from typing import Any

from application.commands.command_handler_base import CommandHandlerBase
from application.dtos.lablet_definition_dto import LabletDefinitionCreatedDto
from domain.entities.lablet_definition import LabletDefinition, NotificationConfig
from domain.enums import LicenseType
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.utils import slugify_fqn
from domain.value_objects.port_template import PortDefinition, PortTemplate
from domain.value_objects.resource_requirements import ResourceRequirements
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

logger = logging.getLogger(__name__)


@dataclass
class CreateLabletDefinitionCommand(Command[OperationResult[LabletDefinitionCreatedDto]]):
    """Command to create a new LabletDefinition in PENDING_SYNC status.

    A LabletDefinition defines a versioned template for creating lab instances
    on CML workers. The form_qualified_name is required and auto-derives
    bucket_name and lab_artifact_uri (ADR-028).
    """

    # Required fields
    name: str = ""
    version: str = ""
    form_qualified_name: str = ""  # REQUIRED: FQN replaces lab_artifact_uri as primary input
    created_by: str = ""

    # Resource requirements
    cpu_cores: int = 2
    memory_gb: int = 4
    storage_gb: int = 20
    nested_virt: bool = True

    # License affinity
    license_affinity: list[str] | None = None  # ["personal", "enterprise", "evaluation"]

    # Lab topology
    node_count: int = 1

    # Port template - list of port definitions
    port_definitions: list[dict[str, Any]] | None = None  # [{"name": "ssh", "protocol": "tcp", "description": "SSH"}]

    # Content package configuration (AD-CS-002)
    user_session_package_name: str = "SVN.zip"
    grading_ruleset_package_name: str = "SVN.zip"
    user_session_type: str = "LDS"
    user_session_default_region: str | None = None

    # Optional fields (may be populated later by sync or manually)
    lab_artifact_uri: str | None = None  # Auto-derived from FQN if not provided
    lab_yaml_hash: str = ""  # Empty until sync populates it
    lab_yaml_cached: str | None = None
    grading_rules_uri: str | None = None
    max_duration_minutes: int = 60
    warm_pool_depth: int = 0

    # Instantiation timing (AD-P10-01)
    boot_lead_time_minutes: int | None = None

    # Notification config
    owner_notification: dict[str, Any] | None = None


class CreateLabletDefinitionCommandHandler(
    CommandHandlerBase,
    CommandHandler[CreateLabletDefinitionCommand, OperationResult[LabletDefinitionCreatedDto]],
):
    """Handle LabletDefinition creation."""

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

    async def handle_async(self, request: CreateLabletDefinitionCommand) -> OperationResult[LabletDefinitionCreatedDto]:
        """Handle create LabletDefinition command.

        Validates inputs, auto-derives bucket_name and lab_artifact_uri from
        form_qualified_name, then creates the aggregate in PENDING_SYNC status.

        Args:
            request: Create command with definition specifications

        Returns:
            OperationResult with LabletDefinitionCreatedDto or error
        """
        command = request

        # Validate required fields
        if not command.name or not command.name.strip():
            return self.bad_request("Name is required")

        if not command.version or not command.version.strip():
            return self.bad_request("Version is required")

        if not command.form_qualified_name or not command.form_qualified_name.strip():
            return self.bad_request("Form Qualified Name is required")

        if not command.created_by or not command.created_by.strip():
            return self.bad_request("Created by is required")

        # Validate FQN format (must slugify successfully)
        try:
            slugify_fqn(command.form_qualified_name.strip())
        except ValueError as e:
            return self.bad_request(f"Invalid form_qualified_name: {e}")

        # Check for duplicate name+version
        existing = await self._repository.get_by_name_and_version_async(
            name=command.name.strip(),
            version=command.version.strip(),
        )
        if existing:
            return self.conflict(f"LabletDefinition with name '{command.name}' and version '{command.version}' already exists")

        try:
            # Build resource requirements
            resource_requirements = ResourceRequirements(
                cpu_cores=command.cpu_cores,
                memory_gb=command.memory_gb,
                storage_gb=command.storage_gb,
                nested_virt=command.nested_virt,
            )

            # Build license affinity
            license_affinity: list[LicenseType] = []
            if command.license_affinity:
                for lt_str in command.license_affinity:
                    try:
                        license_affinity.append(LicenseType(lt_str))
                    except ValueError:
                        valid_types = ", ".join(lt.value for lt in LicenseType)
                        return self.bad_request(f"Invalid license type '{lt_str}'. Must be one of: {valid_types}")
            else:
                # Default to all license types
                license_affinity = [LicenseType.PERSONAL, LicenseType.ENTERPRISE, LicenseType.EVALUATION]

            # Build port template
            if command.port_definitions:
                ports = tuple(
                    PortDefinition(
                        name=pd["name"],
                        protocol=pd.get("protocol", "tcp"),
                        description=pd.get("description"),
                    )
                    for pd in command.port_definitions
                )
                port_template = PortTemplate(ports=ports)
            else:
                port_template = PortTemplate.empty()

            # Build notification config if provided
            owner_notification = None
            if command.owner_notification:
                owner_notification = NotificationConfig.from_dict(command.owner_notification)

            # Create the aggregate (PENDING_SYNC status — ADR-028)
            # bucket_name and lab_artifact_uri are auto-derived from form_qualified_name
            definition = LabletDefinition.create(
                name=command.name.strip(),
                version=command.version.strip(),
                form_qualified_name=command.form_qualified_name.strip(),
                resource_requirements=resource_requirements,
                license_affinity=license_affinity,
                node_count=command.node_count,
                port_template=port_template,
                created_by=command.created_by.strip(),
                user_session_package_name=command.user_session_package_name,
                grading_ruleset_package_name=command.grading_ruleset_package_name,
                user_session_type=command.user_session_type,
                user_session_default_region=command.user_session_default_region,
                lab_yaml_hash=command.lab_yaml_hash,
                lab_yaml_cached=command.lab_yaml_cached,
                grading_rules_uri=command.grading_rules_uri,
                max_duration_minutes=command.max_duration_minutes,
                warm_pool_depth=command.warm_pool_depth,
                owner_notification=owner_notification,
                boot_lead_time_minutes=command.boot_lead_time_minutes,
            )

            # Save to repository
            await self._repository.add_async(definition)

            logger.info(
                f"Created LabletDefinition: {definition.id()} "
                f"(name={definition.state.name}, version={definition.state.version}, "
                f"fqn='{definition.state.form_qualified_name}', bucket='{definition.state.bucket_name}', "
                f"status={definition.state.status.value})"
            )

            # Build response DTO
            dto = LabletDefinitionCreatedDto(
                id=definition.id(),
                name=definition.state.name,
                version=definition.state.version,
                lab_artifact_uri=definition.state.lab_artifact_uri,
                status=definition.state.status.value,
                created_by=definition.state.created_by,
                created_at=definition.state.created_at.isoformat(),
            )

            return self.created(dto)

        except ValueError as e:
            # Validation errors from value objects
            logger.warning(f"Validation error creating LabletDefinition: {e}")
            return self.bad_request(str(e))

        except Exception as e:
            logger.error(f"Error creating LabletDefinition: {e}", exc_info=True)
            return self.internal_server_error(str(e))
