"""SyncContentCommand — Trigger content sync from BlobStorage for a PodDefinition.

Self-contained CQRS command: request class + handler in same file.
"""

import logging
from dataclasses import dataclass
from typing import Any

from domain.entities.pod_definition import PodDefinition
from domain.repositories.pod_definition_repository import PodDefinitionRepository
from lcm_core.domain.enums import PodDefinitionStatus, PodType
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

logger = logging.getLogger(__name__)


@dataclass
class SyncContentCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to trigger content synchronization from BlobStorage.

    Attributes:
        definition_id: The PodDefinition identifier to sync.
        name: Content package name (used for creation if new).
        version: Content version (used for creation if new).
        source_uri: BlobStorage URI for the content package.
        force: Force re-sync even if content is already READY.
    """

    definition_id: str = ""
    name: str = ""
    version: str = "v1"
    source_uri: str = ""
    force: bool = False


class SyncContentCommandHandler(CommandHandler[SyncContentCommand, OperationResult[dict[str, Any]]]):
    """Handler for SyncContentCommand.

    Validates input, finds or creates PodDefinition, transitions to SYNCHRONIZING.
    """

    def __init__(self, pod_definition_repository: PodDefinitionRepository):
        self._repository = pod_definition_repository

    async def handle_async(self, request: SyncContentCommand) -> OperationResult[dict[str, Any]]:
        """Handle content sync request."""
        if not request.source_uri:
            return self.bad_request("source_uri is required")

        # Look up existing PodDefinition or create new
        pod_def: PodDefinition | None = None
        if request.definition_id:
            pod_def = await self._repository.get_by_id_async(request.definition_id)

        if pod_def is None:
            # Create a new PodDefinition
            if not request.name:
                return self.bad_request("name is required when creating a new PodDefinition")
            pod_def = PodDefinition.create(
                name=request.name,
                version=request.version,
                pod_type=PodType.CML_ON_AWS,
                source_uri=request.source_uri,
                definition_id=request.definition_id or None,
            )
            await self._repository.add_async(pod_def)
        else:
            # Check if re-sync is allowed
            if pod_def.state.status == PodDefinitionStatus.READY and not request.force:
                return self.conflict("PodDefinition is already READY. Use force=true to re-sync.")

        # Transition to SYNCHRONIZING
        pod_def.start_sync()
        await self._repository.update_async(pod_def)

        return self.accepted(
            {
                "definition_id": pod_def.id(),
                "status": "synchronizing",
            }
        )
