"""PodDefinitionRepository — abstract repository interface for PodDefinition aggregates."""

from abc import ABC, abstractmethod

from lcm_core.domain.enums.pod_type import PodType

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

    @abstractmethod
    async def expire_superseded_definitions_async(
        self,
        name: str,
        pod_type: PodType,
        current_definition_id: str,
        current_content_hash: str,
    ) -> list[str]:
        """Transition stale READY PodDefinitions with same (name, pod_type) to SUPERSEDED.

        Matches all READY definitions sharing ``name`` + ``pod_type`` whose
        ``content_hash`` differs from ``current_content_hash`` and whose id is
        not ``current_definition_id``. Each matched aggregate is loaded,
        ``supersede(superseded_by=current_definition_id)`` is invoked, and the
        aggregate is persisted via :meth:`update_async`.

        Idempotent: re-running with no stale definitions returns ``[]``.

        Returns:
            List of aggregate ids transitioned to SUPERSEDED (may be empty).
        """
        ...
