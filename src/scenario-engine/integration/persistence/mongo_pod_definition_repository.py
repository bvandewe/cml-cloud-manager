"""MongoPodDefinitionRepository — MongoDB implementation of PodDefinitionRepository.

Uses Neuroglia's MotorRepository with TracedRepositoryMixin for automatic
OpenTelemetry instrumentation and domain event publishing.
"""

import logging
from typing import cast

from domain.entities.pod_definition import PodDefinition
from domain.repositories.pod_definition_repository import PodDefinitionRepository
from lcm_core.domain.enums.pod_definition_status import PodDefinitionStatus
from lcm_core.domain.enums.pod_type import PodType
from motor.motor_asyncio import AsyncIOMotorClient
from neuroglia.data.infrastructure.mongo import MotorRepository
from neuroglia.data.infrastructure.tracing_mixin import TracedRepositoryMixin
from neuroglia.mediation.mediator import Mediator
from neuroglia.serialization.json import JsonSerializer

log = logging.getLogger(__name__)


class MongoPodDefinitionRepository(TracedRepositoryMixin, MotorRepository[PodDefinition, str], PodDefinitionRepository):  # type: ignore[misc]
    """Motor-based async MongoDB repository for PodDefinition entities with automatic
    tracing and domain event publishing.

    Extends Neuroglia's MotorRepository to inherit standard CRUD operations with
    automatic event publishing and adds PodDefinition-specific queries.
    """

    def __init__(
        self,
        client: AsyncIOMotorClient,
        database_name: str,
        collection_name: str,
        serializer: JsonSerializer,
        entity_type: type[PodDefinition] | None = None,
        mediator: Mediator | None = None,
    ):
        super().__init__(
            client=client,
            database_name=database_name,
            collection_name=collection_name,
            serializer=serializer,
            entity_type=entity_type,
            mediator=mediator,
        )

    async def get_by_id_async(self, definition_id: str) -> PodDefinition | None:
        """Retrieve a PodDefinition by its aggregate ID."""
        return cast(PodDefinition | None, await self.get_async(definition_id))

    async def add_async(self, pod_definition: PodDefinition) -> PodDefinition:  # type: ignore[override]
        """Add a new PodDefinition."""
        return cast(PodDefinition, await super().add_async(pod_definition))

    async def update_async(self, pod_definition: PodDefinition) -> PodDefinition:  # type: ignore[override]
        """Update an existing PodDefinition."""
        return cast(PodDefinition, await super().update_async(pod_definition))

    async def get_by_name_version_async(self, name: str, version: str) -> PodDefinition | None:
        """Retrieve a PodDefinition by name and version."""
        document = await self.collection.find_one({"name": name, "version": version})
        if document:
            return self._deserialize_entity(document)
        return None

    async def expire_superseded_definitions_async(
        self,
        name: str,
        pod_type: PodType,
        current_definition_id: str,
        current_content_hash: str,
    ) -> list[str]:
        """Transition stale READY PodDefinitions matching (name, pod_type) to SUPERSEDED.

        Idempotent. Skips the current definition and any READY definitions that
        already share ``current_content_hash``. Each superseded aggregate is
        persisted via ``update_async`` so its ``PodDefinitionSupersededDomainEvent``
        is published through the standard pipeline.
        """
        query = {
            "name": name,
            "pod_type": pod_type.value,
            "status": PodDefinitionStatus.READY.value,
            "content_hash": {"$ne": current_content_hash},
            "_id": {"$ne": current_definition_id},
        }
        superseded_ids: list[str] = []
        cursor = self.collection.find(query)
        async for document in cursor:
            stale = self._deserialize_entity(document)
            if stale is None:
                continue
            stale.supersede(superseded_by=current_definition_id)
            await self.update_async(stale)
            superseded_ids.append(stale.state.id)
        if superseded_ids:
            log.info(
                "Superseded %d stale PodDefinitions for (name=%s, pod_type=%s) by %s",
                len(superseded_ids),
                name,
                pod_type.value,
                current_definition_id,
            )
        return superseded_ids
