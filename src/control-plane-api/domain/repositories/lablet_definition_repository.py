"""Abstract repository for LabletDefinition entities.

Defines the contract for persisting and querying LabletDefinition aggregates.
Implementations must handle proper serialization of nested value objects
(ResourceRequirements, PortTemplate) and optimistic concurrency via state_version.
"""

from abc import ABC, abstractmethod

from domain.entities.lablet_definition import LabletDefinition
from domain.enums import LabletDefinitionStatus


class LabletDefinitionRepository(ABC):
    """Abstract repository for LabletDefinition entities.

    LabletDefinitions are immutable per version - each version is a separate
    aggregate instance. The repository supports queries by name+version
    for version management and by status for lifecycle queries.
    """

    @abstractmethod
    async def get_by_id_async(self, definition_id: str) -> LabletDefinition | None:
        """Retrieve a LabletDefinition by its aggregate ID.

        Args:
            definition_id: The unique aggregate identifier

        Returns:
            The LabletDefinition if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_by_name_and_version_async(self, name: str, version: str) -> LabletDefinition | None:
        """Retrieve a LabletDefinition by name and version.

        This is the primary lookup method for version management,
        as each name+version combination is unique.

        Args:
            name: The definition name (e.g., "ccna-basic-routing")
            version: The semantic version string (e.g., "1.0.0")

        Returns:
            The LabletDefinition if found, None otherwise
        """
        pass

    @abstractmethod
    async def list_active_async(self) -> list[LabletDefinition]:
        """Retrieve all active (non-deprecated) LabletDefinitions.

        Returns:
            List of active LabletDefinitions
        """
        pass

    @abstractmethod
    async def list_by_status_async(self, status: LabletDefinitionStatus) -> list[LabletDefinition]:
        """Retrieve LabletDefinitions by status.

        Args:
            status: The status to filter by

        Returns:
            List of LabletDefinitions with the specified status
        """
        pass

    @abstractmethod
    async def list_by_name_async(self, name: str) -> list[LabletDefinition]:
        """Retrieve all versions of a LabletDefinition by name.

        Useful for version history and management.

        Args:
            name: The definition name

        Returns:
            List of all versions for the given name, ordered by version
        """
        pass

    @abstractmethod
    async def get_latest_version_async(self, name: str) -> LabletDefinition | None:
        """Retrieve the latest active version of a LabletDefinition.

        Args:
            name: The definition name

        Returns:
            The latest active version if found, None otherwise
        """
        pass

    @abstractmethod
    async def add_async(self, entity: LabletDefinition) -> LabletDefinition:
        """Add a new LabletDefinition.

        Args:
            entity: The LabletDefinition to add

        Returns:
            The added LabletDefinition

        Raises:
            DuplicateKeyError: If a definition with the same name+version exists
        """
        pass

    @abstractmethod
    async def update_async(self, entity: LabletDefinition) -> LabletDefinition:
        """Update an existing LabletDefinition.

        Note: LabletDefinitions are mostly immutable. Updates are limited to:
        - warm_pool_depth (via update_warm_pool_depth)
        - sync_status (via record_artifact_sync)
        - status (via deprecate)

        Args:
            entity: The LabletDefinition to update

        Returns:
            The updated LabletDefinition

        Raises:
            ConcurrencyError: If state_version mismatch (optimistic concurrency)
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    async def list_by_sync_status_async(self, sync_status: str) -> list[LabletDefinition]:
        """Retrieve LabletDefinitions by sync_status.

        Used by the lablet-controller to discover definitions that need
        content synchronization (sync_status='sync_requested').

        Args:
            sync_status: The sync status to filter by
                         (e.g., 'sync_requested', 'success', 'failed')

        Returns:
            List of LabletDefinitions with the specified sync_status
        """
        pass

    @abstractmethod
    async def search_async(
        self,
        query: str,
        include_deprecated: bool = False,
        limit: int = 10,
    ) -> list[LabletDefinition]:
        """Search LabletDefinitions by name or description text.

        Performs case-insensitive text search matching anywhere in the
        name field. Used for autocomplete/typeahead functionality.

        Args:
            query: Search query string
            include_deprecated: Include deprecated definitions (default False)
            limit: Maximum number of results to return (default 10)

        Returns:
            List of matching LabletDefinitions ordered by relevance
        """
        pass
