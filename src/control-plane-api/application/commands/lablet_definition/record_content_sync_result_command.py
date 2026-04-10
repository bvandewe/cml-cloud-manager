"""Record content sync result command — called by lablet-controller (AD-CS-001).

This command is invoked via the CPA internal API when the lablet-controller's
ContentSyncService completes the sync pipeline. It records sync metadata on the
aggregate and, on success, transitions the definition from PENDING_SYNC to ACTIVE.

If the content hash changed on an already-ACTIVE definition, implements the
version-bump flow per AD-CS-005 (ADR-027).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from application.commands.command_handler_base import CommandHandlerBase
from application.dtos.lablet_definition_dto import LabletDefinitionSyncResultDto
from domain.entities.lablet_definition import LabletDefinition
from domain.enums import LabletDefinitionStatus
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.value_objects.port_template import PortTemplate
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

logger = logging.getLogger(__name__)


@dataclass
class RecordContentSyncResultCommand(Command[OperationResult[LabletDefinitionSyncResultDto]]):
    """Command to record the result of a content sync operation (from lablet-controller).

    Called via POST /api/internal/lablet-definitions/{id}/content-synced.
    """

    definition_id: str = ""
    sync_status: str = ""  # "success" | "failed"
    error_message: str | None = None

    # Content metadata (populated on success)
    lab_yaml_hash: str = ""
    content_package_hash: str | None = None
    upstream_version: str | None = None
    upstream_date_published: str | None = None
    upstream_instance_name: str | None = None
    upstream_form_id: str | None = None
    grade_xml_path: str | None = None
    cml_yaml_path: str | None = None
    cml_yaml_content: str | None = None
    devices_json: str | None = None
    upstream_sync_status: dict[str, Any] | None = None

    # Port template extracted from CML YAML nodes (ADR-029)
    port_template: dict[str, Any] | None = None

    # Topology metadata auto-derived from CML YAML (AD-SEED-001)
    node_count: int | None = None
    node_definitions_required: list[str] | None = None


class RecordContentSyncResultCommandHandler(
    CommandHandlerBase,
    CommandHandler[RecordContentSyncResultCommand, OperationResult[LabletDefinitionSyncResultDto]],
):
    """Handle content sync result recording from lablet-controller.

    Flow:
    1. Find definition by ID
    2. Detect content change (hash comparison)
    3. If content changed AND definition was already ACTIVE → version bump (AD-CS-005)
    4. Otherwise → record sync result on existing definition
    5. Emits LabletDefinitionContentSyncedDomainEvent → triggers etcd cleanup projector
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

    async def handle_async(self, request: RecordContentSyncResultCommand) -> OperationResult[LabletDefinitionSyncResultDto]:
        """Handle record content sync result command.

        Args:
            request: Command with sync results from lablet-controller

        Returns:
            OperationResult with LabletDefinitionSyncResultDto or error
        """
        command = request

        # Validate required fields
        if not command.definition_id:
            return self.bad_request("definition_id is required")

        if not command.sync_status or command.sync_status not in ("success", "failed"):
            return self.bad_request("sync_status must be 'success' or 'failed'")

        try:
            # 1. Find definition by ID
            definition = await self._repository.get_by_id_async(command.definition_id)
            if not definition:
                return self.not_found(LabletDefinition, command.definition_id)

            # 2. Detect content change (hash comparison)
            content_changed = command.content_package_hash is not None and definition.state.content_package_hash is not None and command.content_package_hash != definition.state.content_package_hash

            # 3. Version bump flow (AD-CS-005 / ADR-027):
            #    If content changed AND definition was already ACTIVE → deprecate + create new version
            if content_changed and definition.state.status == LabletDefinitionStatus.ACTIVE:
                return await self._handle_version_bump(definition, command)

            # 4. Normal sync (first sync or no content change)
            #    Build port template from dict if provided
            port_template = PortTemplate.from_dict(command.port_template) if command.port_template else None

            definition.record_content_sync(
                lab_yaml_hash=command.lab_yaml_hash,
                sync_status=command.sync_status,
                error_message=command.error_message,
                content_package_hash=command.content_package_hash,
                upstream_version=command.upstream_version,
                upstream_date_published=command.upstream_date_published,
                upstream_instance_name=command.upstream_instance_name,
                upstream_form_id=command.upstream_form_id,
                grade_xml_path=command.grade_xml_path,
                cml_yaml_path=command.cml_yaml_path,
                cml_yaml_content=command.cml_yaml_content,
                devices_json=command.devices_json,
                upstream_sync_status=command.upstream_sync_status,
                port_template=port_template,
                node_count=command.node_count,
                node_definitions_required=command.node_definitions_required,
            )
            await self._repository.update_async(definition)

            synced_at = datetime.now(timezone.utc)
            logger.info(
                f"Recorded content sync result for LabletDefinition: {definition.id()} "
                f"(name={definition.state.name}, version={definition.state.version}, "
                f"sync_status={command.sync_status}, content_changed={content_changed})"
            )

            dto = LabletDefinitionSyncResultDto(
                id=definition.id(),
                name=definition.state.name,
                version=definition.state.version,
                sync_status=command.sync_status,
                synced_at=synced_at.isoformat(),
                lab_yaml_hash=command.lab_yaml_hash,
                content_changed=content_changed,
            )

            return self.ok(dto)

        except Exception as e:
            logger.error(f"Error recording content sync result: {e}", exc_info=True)
            return self.internal_server_error(str(e))

    async def _handle_version_bump(
        self,
        definition: LabletDefinition,
        command: RecordContentSyncResultCommand,
    ) -> OperationResult[LabletDefinitionSyncResultDto]:
        """Handle version bump when content changes on an ACTIVE definition (AD-CS-005).

        1. Deprecate the current definition
        2. Create a new version with patch-incremented version string
        3. Record sync result on the new definition

        Args:
            definition: The existing ACTIVE definition
            command: The sync result command

        Returns:
            OperationResult with the new definition's DTO
        """
        old_version = definition.state.version
        new_version = _increment_patch_version(old_version)
        hash_preview = command.content_package_hash[:12] if command.content_package_hash else "unknown"

        # 1. Deprecate current definition
        definition.deprecate(
            deprecated_by="content-sync-service",
            deprecation_reason=f"Content updated (new hash: {hash_preview}...)",
            replacement_version=new_version,
        )
        await self._repository.update_async(definition)

        # 2. Create new version (auto-increment patch)
        new_definition = LabletDefinition.create_version(
            name=definition.state.name,
            version=new_version,
            previous_version=old_version,
            lab_artifact_uri=definition.state.lab_artifact_uri,
            lab_yaml_hash=command.lab_yaml_hash,
            resource_requirements=definition.state.resource_requirements,
            node_count=definition.state.node_count,
            port_template=definition.state.port_template,
            created_by="content-sync-service",
        )

        # 3. Record sync result on the NEW definition
        port_template = PortTemplate.from_dict(command.port_template) if command.port_template else None
        new_definition.record_content_sync(
            lab_yaml_hash=command.lab_yaml_hash,
            sync_status=command.sync_status,
            content_package_hash=command.content_package_hash,
            upstream_version=command.upstream_version,
            upstream_date_published=command.upstream_date_published,
            upstream_instance_name=command.upstream_instance_name,
            upstream_form_id=command.upstream_form_id,
            grade_xml_path=command.grade_xml_path,
            cml_yaml_path=command.cml_yaml_path,
            cml_yaml_content=command.cml_yaml_content,
            devices_json=command.devices_json,
            upstream_sync_status=command.upstream_sync_status,
            port_template=port_template,
            node_count=command.node_count,
            node_definitions_required=command.node_definitions_required,
        )

        await self._repository.add_async(new_definition)

        synced_at = datetime.now(timezone.utc)
        logger.info(f"Version bump for LabletDefinition: {definition.id()} (name={definition.state.name}, {old_version} → {new_version}, new_id={new_definition.id()}, hash={hash_preview}...)")

        dto = LabletDefinitionSyncResultDto(
            id=new_definition.id(),
            name=new_definition.state.name,
            version=new_version,
            sync_status=command.sync_status,
            synced_at=synced_at.isoformat(),
            lab_yaml_hash=command.lab_yaml_hash,
            content_changed=True,
        )

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
