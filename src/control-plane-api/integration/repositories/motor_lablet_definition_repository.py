"""MongoDB repository for LabletDefinition entities using Neuroglia's MotorRepository.

This extends the framework's MotorRepository to provide LabletDefinition-specific queries
while inheriting all standard CRUD operations with automatic domain event publishing.
"""

import logging
from typing import TYPE_CHECKING, Optional, cast

import pymongo.errors
from domain.entities.lablet_definition import LabletDefinition
from domain.enums import LabletDefinitionStatus
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from motor.motor_asyncio import AsyncIOMotorClient
from neuroglia.data.infrastructure.mongo import MotorRepository
from neuroglia.data.infrastructure.tracing_mixin import TracedRepositoryMixin
from neuroglia.serialization.json import JsonSerializer

if TYPE_CHECKING:
    from neuroglia.mediation.mediator import Mediator

log = logging.getLogger(__name__)


class MongoLabletDefinitionRepository(TracedRepositoryMixin, MotorRepository[LabletDefinition, str], LabletDefinitionRepository):  # type: ignore[misc]
    """Motor-based async MongoDB repository for LabletDefinition entities with automatic tracing
    and domain event publishing.

    Extends Neuroglia's MotorRepository to inherit standard CRUD operations with
    automatic event publishing and adds LabletDefinition-specific queries. TracedRepositoryMixin
    provides automatic OpenTelemetry instrumentation for all repository operations
    using Python's MRO to intercept repository calls transparently.
    """

    def __init__(
        self,
        client: AsyncIOMotorClient,
        database_name: str,
        collection_name: str,
        serializer: JsonSerializer,
        entity_type: type[LabletDefinition] | None = None,
        mediator: Optional["Mediator"] = None,
    ):
        """Initialize the LabletDefinition repository.

        Args:
            client: Motor async MongoDB client
            database_name: Name of the MongoDB database
            collection_name: Name of the collection (typically "lablet_definitions")
            serializer: JSON serializer for entity conversion
            entity_type: Optional entity type (LabletDefinition)
            mediator: Optional Mediator for automatic domain event publishing
        """
        super().__init__(
            client=client,
            database_name=database_name,
            collection_name=collection_name,
            serializer=serializer,
            entity_type=entity_type,
            mediator=mediator,
        )

        # Flag to avoid recreating indexes repeatedly
        self._indexes_initialized: bool = False

    async def _ensure_indexes(self) -> None:
        """Ensure required indexes exist for the collection.

        Creates a unique compound index on (name, version) to enforce
        version uniqueness per definition name.
        """
        if self._indexes_initialized:
            return

        try:
            # Unique compound index on name + version
            await self.collection.create_index(
                [("name", 1), ("version", 1)],
                unique=True,
                name="idx_name_version_unique",
            )

            # Index for status queries
            await self.collection.create_index("status", name="idx_status")

            # Index for name queries (version history)
            await self.collection.create_index("name", name="idx_name")

            log.debug("LabletDefinition indexes created successfully")
        except Exception:
            # Index creation failures should not block normal operation
            log.warning("Failed to create LabletDefinition indexes", exc_info=True)
        finally:
            self._indexes_initialized = True

    async def get_by_id_async(self, definition_id: str) -> LabletDefinition | None:
        """Retrieve a LabletDefinition by its aggregate ID."""
        return cast(LabletDefinition | None, await self.get_async(definition_id))

    async def get_by_name_and_version_async(self, name: str, version: str) -> LabletDefinition | None:
        """Retrieve a LabletDefinition by name and version.

        Args:
            name: The definition name (e.g., "ccna-basic-routing")
            version: The semantic version string (e.g., "1.0.0")

        Returns:
            The LabletDefinition if found, None otherwise
        """
        document = await self.collection.find_one({"name": name, "version": version})
        if document:
            return self._deserialize_entity(document)
        return None

    async def list_active_async(self) -> list[LabletDefinition]:
        """Retrieve all active (non-deprecated) LabletDefinitions."""
        cursor = self.collection.find({"status": LabletDefinitionStatus.ACTIVE.value})
        definitions: list[LabletDefinition] = []
        async for document in cursor:
            definition = self._deserialize_entity(document)
            definitions.append(definition)
        return definitions

    async def list_by_status_async(self, status: LabletDefinitionStatus) -> list[LabletDefinition]:
        """Retrieve LabletDefinitions by status.

        Args:
            status: The status to filter by

        Returns:
            List of LabletDefinitions with the specified status
        """
        cursor = self.collection.find({"status": status.value})
        definitions: list[LabletDefinition] = []
        async for document in cursor:
            definition = self._deserialize_entity(document)
            definitions.append(definition)
        return definitions

    async def list_by_name_async(self, name: str) -> list[LabletDefinition]:
        """Retrieve all versions of a LabletDefinition by name.

        Args:
            name: The definition name

        Returns:
            List of all versions for the given name, ordered by version descending
        """
        # Sort by version descending to get latest first
        cursor = self.collection.find({"name": name}).sort("version", -1)
        definitions: list[LabletDefinition] = []
        async for document in cursor:
            definition = self._deserialize_entity(document)
            definitions.append(definition)
        return definitions

    async def get_latest_version_async(self, name: str) -> LabletDefinition | None:
        """Retrieve the latest active version of a LabletDefinition.

        Args:
            name: The definition name

        Returns:
            The latest active version if found, None otherwise
        """
        # Find the latest active version by sorting version descending
        document = await self.collection.find_one(
            {"name": name, "status": LabletDefinitionStatus.ACTIVE.value},
            sort=[("version", -1)],
        )
        if document:
            return self._deserialize_entity(document)
        return None

    async def add_async(self, entity: LabletDefinition) -> LabletDefinition:  # type: ignore[override]
        """Add a new LabletDefinition.

        Ensures the unique index on (name, version) is created before insertion.

        Args:
            entity: The LabletDefinition to add

        Returns:
            The added LabletDefinition

        Raises:
            DuplicateKeyError: If a definition with the same name+version exists
        """
        await self._ensure_indexes()

        name = entity.state.name
        version = entity.state.version

        try:
            return cast(LabletDefinition, await super().add_async(entity))
        except pymongo.errors.DuplicateKeyError:
            # Check if it was a name+version collision
            existing = await self.get_by_name_and_version_async(name, version)
            if existing:
                log.warning(f"Attempted to add duplicate LabletDefinition: name={name}, version={version}")
                raise ValueError(f"LabletDefinition with name '{name}' and version '{version}' already exists")
            raise

    async def update_async(self, entity: LabletDefinition) -> LabletDefinition:  # type: ignore[override]
        """Update an existing LabletDefinition.

        Note: LabletDefinitions are mostly immutable. Updates are limited to:
        - warm_pool_depth (via update_warm_pool_depth)
        - sync_status (via record_artifact_sync)
        - status (via deprecate)

        Args:
            entity: The LabletDefinition to update

        Returns:
            The updated LabletDefinition
        """
        return cast(LabletDefinition, await super().update_async(entity))

    async def delete_async(self, definition_id: str, entity: LabletDefinition | None = None) -> bool:
        """Delete a LabletDefinition by ID.

        In practice, definitions should be deprecated rather than deleted
        to maintain referential integrity with existing instances.

        Args:
            definition_id: The ID of the definition to delete
            entity: Optional entity with pending domain events to publish

        Returns:
            True if deletion was successful, False otherwise
        """
        await self.remove_async(definition_id)
        return True

    async def get_all_async(self) -> list[LabletDefinition]:
        """Retrieve all LabletDefinitions regardless of status.

        Returns:
            List of all LabletDefinitions
        """
        cursor = self.collection.find({})
        definitions: list[LabletDefinition] = []
        async for document in cursor:
            definition = self._deserialize_entity(document)
            definitions.append(definition)
        return definitions

    async def count_by_status_async(self, status: LabletDefinitionStatus) -> int:
        """Count LabletDefinitions by status.

        Args:
            status: The status to filter by

        Returns:
            Count of definitions with the specified status
        """
        return await self.collection.count_documents({"status": status.value})

    async def count_active_async(self) -> int:
        """Count active LabletDefinitions.

        Returns:
            Count of active definitions
        """
        return await self.count_by_status_async(LabletDefinitionStatus.ACTIVE)

    async def list_by_sync_status_async(self, sync_status: str) -> list[LabletDefinition]:
        """Retrieve LabletDefinitions by sync_status.

        Args:
            sync_status: The sync status to filter by
                         (e.g., 'sync_requested', 'success', 'failed')

        Returns:
            List of LabletDefinitions with the specified sync_status
        """
        cursor = self.collection.find({"sync_status": sync_status})
        definitions: list[LabletDefinition] = []
        async for document in cursor:
            definition = self._deserialize_entity(document)
            definitions.append(definition)
        return definitions

    async def search_async(
        self,
        query: str,
        include_deprecated: bool = False,
        limit: int = 10,
    ) -> list[LabletDefinition]:
        """Search LabletDefinitions by name text.

        Performs case-insensitive regex search matching anywhere in the
        name field. Used for autocomplete/typeahead functionality.

        Args:
            query: Search query string
            include_deprecated: Include deprecated definitions (default False)
            limit: Maximum number of results to return (default 10)

        Returns:
            List of matching LabletDefinitions ordered by name
        """
        import re

        # Build the search filter with case-insensitive regex on name
        # Escape special regex characters in the query
        escaped_query = re.escape(query)
        search_filter: dict = {
            "name": {"$regex": escaped_query, "$options": "i"},
        }

        # Optionally exclude deprecated definitions
        if not include_deprecated:
            search_filter["status"] = {
                "$in": [
                    LabletDefinitionStatus.ACTIVE.value,
                ]
            }

        # Execute search with limit
        cursor = self.collection.find(search_filter).sort("name", 1).limit(limit)

        definitions: list[LabletDefinition] = []
        async for document in cursor:
            definition = self._deserialize_entity(document)
            definitions.append(definition)

        return definitions
