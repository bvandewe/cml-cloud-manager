"""Update LabletDefinition command with handler.

For ACTIVE definitions, an edit triggers a version bump:
  - Deprecate the current version
  - Create a new version (patch-incremented) in PENDING_SYNC status
  - Apply all requested changes to the new version

For PENDING_SYNC definitions (not yet synced), an in-place update is performed.

This follows the AD-CS-005 pattern established by RecordContentSyncResultCommand.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

from application.commands.command_handler_base import CommandHandlerBase
from application.dtos.lablet_definition_dto import LabletDefinitionDto, map_lablet_definition_to_dto
from domain.entities.lablet_definition import LabletDefinition
from domain.enums import LabletDefinitionStatus, LicenseType
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.utils import slugify_fqn
from domain.value_objects.resource_requirements import ResourceRequirements

logger = logging.getLogger(__name__)


@dataclass
class UpdateLabletDefinitionCommand(Command[OperationResult[LabletDefinitionDto]]):
    """Command to update mutable fields of a LabletDefinition.

    For ACTIVE definitions, this triggers a version bump (deprecate old → create new).
    For PENDING_SYNC definitions, this performs an in-place update.
    """

    definition_id: str = ""
    updated_by: str = ""

    # Content identification
    form_qualified_name: str | None = None

    # Mutable fields (all optional - only provided ones are updated)
    lab_artifact_uri: str | None = None
    lab_yaml_hash: str | None = None
    cpu_cores: int | None = None
    memory_gb: int | None = None
    storage_gb: int | None = None
    nested_virt: bool | None = None
    license_affinity: list[str] | None = None
    node_count: int | None = None
    max_duration_minutes: int | None = None
    warm_pool_depth: int | None = None
    grading_rules_uri: str | None = field(default=None)

    # Content sync settings
    user_session_package_name: str | None = None
    grading_ruleset_package_name: str | None = None
    user_session_type: str | None = None
    user_session_default_region: str | None = None

    # Lab binding options (Phase 7)
    lab_reuse_enabled: bool | None = None

    # Instantiation timing (AD-P10-01)
    boot_lead_time_minutes: int | None = None


class UpdateLabletDefinitionCommandHandler(
    CommandHandlerBase,
    CommandHandler[UpdateLabletDefinitionCommand, OperationResult[LabletDefinitionDto]],
):
    """Handle LabletDefinition update.

    - ACTIVE definitions → version bump (deprecate + create new in PENDING_SYNC)
    - PENDING_SYNC definitions → in-place update
    - DEPRECATED definitions → rejected
    """

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

    async def handle_async(self, request: UpdateLabletDefinitionCommand) -> OperationResult[LabletDefinitionDto]:
        """Handle update LabletDefinition command."""
        command = request

        # Validate definition_id
        if not command.definition_id or not command.definition_id.strip():
            return self.bad_request("Definition ID is required")

        # Fetch existing definition
        definition = await self._repository.get_async(command.definition_id)
        if not definition:
            return self.not_found(LabletDefinition, command.definition_id)

        # Reject deprecated definitions
        if definition.state.status == LabletDefinitionStatus.DEPRECATED:
            return self.bad_request("Cannot update a deprecated definition")

        # Validate license_affinity if provided
        if command.license_affinity is not None:
            for lt_str in command.license_affinity:
                try:
                    LicenseType(lt_str)
                except ValueError:
                    valid_types = ", ".join(lt.value for lt in LicenseType)
                    return self.bad_request(f"Invalid license type '{lt_str}'. Must be one of: {valid_types}")

        try:
            if definition.state.status == LabletDefinitionStatus.ACTIVE:
                return await self._handle_version_bump(definition, command)
            else:
                # PENDING_SYNC — in-place update
                return await self._handle_in_place_update(definition, command)

        except ValueError as e:
            logger.warning("Validation error updating LabletDefinition: %s", e)
            return self.bad_request(str(e))

        except Exception as e:
            logger.error("Error updating LabletDefinition: %s", e, exc_info=True)
            return self.internal_server_error(str(e))

    async def _handle_version_bump(
        self,
        definition: LabletDefinition,
        command: UpdateLabletDefinitionCommand,
    ) -> OperationResult[LabletDefinitionDto]:
        """Handle version bump for an ACTIVE definition.

        1. Merge command fields with existing state
        2. Deprecate the current definition
        3. Create a new version via LabletDefinition.create() (PENDING_SYNC)
        4. Return the new definition DTO
        """
        state = definition.state
        old_version = state.version
        new_version = _increment_patch_version(old_version)

        # Merge fields: use command value if provided, else existing state
        form_qualified_name = command.form_qualified_name or state.form_qualified_name or ""
        cpu_cores = command.cpu_cores if command.cpu_cores is not None else state.resource_requirements.cpu_cores
        memory_gb = command.memory_gb if command.memory_gb is not None else state.resource_requirements.memory_gb
        storage_gb = command.storage_gb if command.storage_gb is not None else state.resource_requirements.storage_gb
        nested_virt = command.nested_virt if command.nested_virt is not None else state.resource_requirements.nested_virt
        node_count = command.node_count if command.node_count is not None else state.node_count
        max_duration_minutes = command.max_duration_minutes if command.max_duration_minutes is not None else state.max_duration_minutes
        warm_pool_depth = command.warm_pool_depth if command.warm_pool_depth is not None else state.warm_pool_depth
        user_session_package_name = command.user_session_package_name or state.user_session_package_name
        grading_ruleset_package_name = command.grading_ruleset_package_name or state.grading_ruleset_package_name
        user_session_type = command.user_session_type or state.user_session_type
        user_session_default_region = command.user_session_default_region if command.user_session_default_region is not None else state.user_session_default_region
        grading_rules_uri = command.grading_rules_uri if command.grading_rules_uri is not None else state.grading_rules_uri
        boot_lead_time_minutes = command.boot_lead_time_minutes if command.boot_lead_time_minutes is not None else getattr(state, "boot_lead_time_minutes", None)
        lab_reuse_enabled = command.lab_reuse_enabled if command.lab_reuse_enabled is not None else getattr(state, "lab_reuse_enabled", False)

        if command.license_affinity is not None:
            license_affinity = [LicenseType(lt) for lt in command.license_affinity]
        else:
            license_affinity = list(state.license_affinity)

        resource_requirements = ResourceRequirements(
            cpu_cores=cpu_cores,
            memory_gb=memory_gb,
            storage_gb=storage_gb,
            nested_virt=nested_virt,
        )

        # 1. Deprecate the current definition
        definition.deprecate(
            deprecated_by=command.updated_by,
            deprecation_reason=f"Superseded by version {new_version} (manual edit)",
            replacement_version=new_version,
        )
        await self._repository.update_async(definition)

        # 2. Create new version via LabletDefinition.create() → PENDING_SYNC
        new_definition = LabletDefinition.create(
            name=state.name,
            version=new_version,
            form_qualified_name=form_qualified_name,
            resource_requirements=resource_requirements,
            license_affinity=license_affinity,
            node_count=node_count,
            port_template=state.port_template,
            created_by=command.updated_by,
            user_session_package_name=user_session_package_name,
            grading_ruleset_package_name=grading_ruleset_package_name,
            user_session_type=user_session_type,
            user_session_default_region=user_session_default_region,
            grading_rules_uri=grading_rules_uri,
            max_duration_minutes=max_duration_minutes,
            warm_pool_depth=warm_pool_depth,
            owner_notification=state.owner_notification,
            boot_lead_time_minutes=boot_lead_time_minutes,
            lab_reuse_enabled=lab_reuse_enabled,
        )

        # 3. Persist the new version
        await self._repository.add_async(new_definition)

        # 4. Request content sync for the new version (ADR-028)
        # This emits LabletDefinitionSyncRequestedDomainEvent → etcd projection
        # → lablet-controller ContentSyncService picks it up for sync.
        new_definition.request_sync(requested_by=command.updated_by)
        await self._repository.update_async(new_definition)

        logger.info(
            "Version bump for LabletDefinition: %s → %s (name=%s, %s → %s, new_id=%s, by=%s)",
            definition.id(),
            new_definition.id(),
            state.name,
            old_version,
            new_version,
            new_definition.id(),
            command.updated_by,
        )

        # 4. Return new definition DTO
        dto = map_lablet_definition_to_dto(new_definition)
        return self.ok(dto)

    async def _handle_in_place_update(
        self,
        definition: LabletDefinition,
        command: UpdateLabletDefinitionCommand,
    ) -> OperationResult[LabletDefinitionDto]:
        """Handle in-place update for a PENDING_SYNC definition.

        Builds a changes dict and applies them to the existing aggregate.
        """
        changes: dict[str, Any] = {}

        if command.form_qualified_name is not None:
            fqn = command.form_qualified_name.strip()
            changes["form_qualified_name"] = fqn
            changes["bucket_name"] = slugify_fqn(fqn)
            # Recalculate lab_artifact_uri from new bucket + package name
            pkg = command.user_session_package_name or definition.state.user_session_package_name
            changes["lab_artifact_uri"] = f"s3://{slugify_fqn(fqn)}/{pkg}"

        if command.lab_artifact_uri is not None and "lab_artifact_uri" not in changes:
            changes["lab_artifact_uri"] = command.lab_artifact_uri.strip()
        if command.lab_yaml_hash is not None:
            changes["lab_yaml_hash"] = command.lab_yaml_hash.strip()

        # Build resource requirements changes
        has_resource_change = any(v is not None for v in [command.cpu_cores, command.memory_gb, command.storage_gb, command.nested_virt])
        if has_resource_change:
            current_rr = definition.state.resource_requirements
            changes["resource_requirements"] = {
                "cpu_cores": command.cpu_cores if command.cpu_cores is not None else current_rr.cpu_cores,
                "memory_gb": command.memory_gb if command.memory_gb is not None else current_rr.memory_gb,
                "storage_gb": command.storage_gb if command.storage_gb is not None else current_rr.storage_gb,
                "nested_virt": command.nested_virt if command.nested_virt is not None else current_rr.nested_virt,
            }

        if command.license_affinity is not None:
            changes["license_affinity"] = command.license_affinity

        if command.node_count is not None:
            changes["node_count"] = command.node_count
        if command.max_duration_minutes is not None:
            changes["max_duration_minutes"] = command.max_duration_minutes
        if command.warm_pool_depth is not None:
            changes["warm_pool_depth"] = command.warm_pool_depth
        if command.grading_rules_uri is not None:
            changes["grading_rules_uri"] = command.grading_rules_uri

        # Content sync settings
        if command.user_session_package_name is not None:
            changes["user_session_package_name"] = command.user_session_package_name
        if command.grading_ruleset_package_name is not None:
            changes["grading_ruleset_package_name"] = command.grading_ruleset_package_name
        if command.user_session_type is not None:
            changes["user_session_type"] = command.user_session_type
        if command.user_session_default_region is not None:
            changes["user_session_default_region"] = command.user_session_default_region
        if command.boot_lead_time_minutes is not None:
            changes["boot_lead_time_minutes"] = command.boot_lead_time_minutes
        if command.lab_reuse_enabled is not None:
            changes["lab_reuse_enabled"] = command.lab_reuse_enabled

        if not changes:
            return self.bad_request("No fields to update")

        # Apply update
        definition.update(changes=changes, updated_by=command.updated_by)

        # Save to repository
        await self._repository.update_async(definition)

        logger.info(
            "Updated LabletDefinition (in-place): %s (fields: %s)",
            definition.id(),
            ", ".join(changes.keys()),
        )

        # Build response DTO
        dto = map_lablet_definition_to_dto(definition)
        return self.ok(dto)


def _increment_patch_version(version: str) -> str:
    """Increment the patch component of a semver string.

    Examples:
        "1.0.0" → "1.0.1"
        "2.3.7" → "2.3.8"
        "1.0" → "1.1" (non-semver fallback)
    """
    parts = version.split(".")
    if len(parts) >= 3:
        try:
            parts[-1] = str(int(parts[-1]) + 1)
        except ValueError:
            parts.append("1")
    elif len(parts) == 2:
        try:
            parts[-1] = str(int(parts[-1]) + 1)
        except ValueError:
            parts.append("1")
    else:
        parts.append("1")
    return ".".join(parts)
