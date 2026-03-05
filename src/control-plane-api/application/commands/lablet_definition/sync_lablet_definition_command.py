"""Sync LabletDefinition command — triggers content synchronization (AD-CS-001).

This command does NOT execute the sync — it emits a domain event that triggers
the etcd projector, notifying the lablet-controller's ContentSyncService
via reactive etcd watch. Returns 202 Accepted immediately.
"""

import logging
from dataclasses import dataclass

from application.commands.command_handler_base import CommandHandlerBase
from application.dtos.lablet_definition_dto import LabletDefinitionSyncResultDto
from domain.entities.lablet_definition import LabletDefinition
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

logger = logging.getLogger(__name__)


@dataclass
class SyncLabletDefinitionCommand(Command[OperationResult[LabletDefinitionSyncResultDto]]):
    """Command to request content synchronization for a LabletDefinition.

    This does NOT execute the sync — it emits a domain event that triggers
    the etcd projector, notifying the lablet-controller's ContentSyncService
    via reactive etcd watch (AD-CS-001).
    """

    # Identify the definition (by id or name+version)
    id: str | None = None
    name: str | None = None
    version: str | None = None

    # Who requested the sync
    synced_by: str = ""


class SyncLabletDefinitionCommandHandler(
    CommandHandlerBase,
    CommandHandler[SyncLabletDefinitionCommand, OperationResult[LabletDefinitionSyncResultDto]],
):
    """Handle LabletDefinition sync trigger — request_sync() → 202 Accepted."""

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

    async def handle_async(self, request: SyncLabletDefinitionCommand) -> OperationResult[LabletDefinitionSyncResultDto]:
        """Handle sync LabletDefinition command.

        Finds the definition, calls request_sync() on the aggregate (which emits
        LabletDefinitionSyncRequestedDomainEvent), persists, and returns 202 Accepted.
        The domain event triggers the ContentSyncRequestedEtcdProjector → etcd key
        → lablet-controller ContentSyncService picks it up asynchronously.

        Args:
            request: Sync command with definition identifier

        Returns:
            OperationResult with LabletDefinitionSyncResultDto (202 Accepted)
        """
        command = request

        # Validate: must provide either id or (name + version)
        if not command.id and not (command.name and command.version):
            return self.bad_request("Must provide either 'id' or both 'name' and 'version'")

        try:
            # Find the definition
            definition: LabletDefinition | None = None
            if command.id:
                definition = await self._repository.get_by_id_async(command.id)
                if not definition:
                    return self.not_found(LabletDefinition, command.id)
            else:
                definition = await self._repository.get_by_name_and_version_async(
                    name=command.name,  # type: ignore
                    version=command.version,  # type: ignore
                )
                if not definition:
                    return self.not_found(LabletDefinition, f"{command.name}:{command.version}")

            # Validate: must have a form_qualified_name for content sync
            if not definition.state.form_qualified_name:
                return self.bad_request("Definition has no form_qualified_name — cannot trigger content sync")

            # Request sync via aggregate method → emits LabletDefinitionSyncRequestedDomainEvent
            definition.request_sync(requested_by=command.synced_by)

            # Persist (domain event will be published → etcd projector writes key)
            await self._repository.update_async(definition)

            logger.info(
                f"Sync requested for LabletDefinition: {definition.id()} "
                f"(name={definition.state.name}, version={definition.state.version}, "
                f"fqn='{definition.state.form_qualified_name}', requested_by={command.synced_by})"
            )

            # Return 202 Accepted (sync will happen asynchronously via etcd watch)
            dto = LabletDefinitionSyncResultDto(
                id=definition.id(),
                name=definition.state.name,
                version=definition.state.version,
                sync_status="sync_requested",
                synced_at=None,
                lab_yaml_hash=definition.state.lab_yaml_hash,
                content_changed=False,
            )

            return self.accepted(dto)

        except Exception as e:
            logger.error(f"Error requesting sync for LabletDefinition: {e}", exc_info=True)
            return self.internal_server_error(str(e))
