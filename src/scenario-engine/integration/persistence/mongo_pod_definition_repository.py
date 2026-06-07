"""MongoPodDefinitionRepository — MongoDB implementation of PodDefinitionRepository.

Uses Neuroglia's MotorRepository with TracedRepositoryMixin for automatic
OpenTelemetry instrumentation and domain event publishing.
"""

import logging
from typing import cast

from domain.entities.pod_definition import PodDefinition
from domain.repositories.pod_definition_repository import PodDefinitionRepository
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
