"""PodDefinitionRepository — abstract repository interface for PodDefinition aggregates."""

from abc import ABC, abstractmethod

from domain.entities.pod_definition import PodDefinition


class PodDefinitionRepository(ABC):
    """Abstract repository for PodDefinition persistence.

    Implementations: MongoPodDefinitionRepository (integration layer).
    """

    @abstractmethod
    async def get_by_id_async(self, definition_id: str) -> PodDefinition | None:
        """Retrieve a PodDefinition by its ID."""
        ...

    @abstractmethod
    async def add_async(self, pod_definition: PodDefinition) -> None:
        """Persist a new PodDefinition."""
        ...

    @abstractmethod
    async def update_async(self, pod_definition: PodDefinition) -> None:
        """Update an existing PodDefinition."""
        ...

    @abstractmethod
    async def get_by_name_version_async(self, name: str, version: str) -> PodDefinition | None:
        """Retrieve a PodDefinition by name and version."""
        ...
