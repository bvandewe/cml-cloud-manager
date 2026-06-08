"""Abstract repository for ``PodDefinitionReadModel`` projections.

ADR-044 / G-12 / AD-CSI-007 — CPA owns this read model; only projection
handlers may write through it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain.read_models.pod_definition_read_model import PodDefinitionReadModel


class PodDefinitionReadRepository(ABC):
    """Repository for the ``pod_definitions_read`` MongoDB collection."""

    @abstractmethod
    async def get_async(self, definition_id: str) -> PodDefinitionReadModel | None:
        """Fetch a read model by its SE PodDefinition id."""

    @abstractmethod
    async def upsert_async(self, model: PodDefinitionReadModel) -> None:
        """Insert or replace the read model document keyed by ``model.id``.

        Projection handlers must perform their own staleness check against
        ``last_event_at`` before calling this method (AD-CSI-015).
        """

    @abstractmethod
    async def list_by_name_pod_type_async(self, name: str, pod_type: str) -> list[PodDefinitionReadModel]:
        """List every read model with the given ``(name, pod_type)``."""

    @abstractmethod
    async def mark_superseded_async(self, definition_ids: list[str], superseded_at: str) -> int:
        """Bulk-flip status to ``SUPERSEDED`` for the given ids.

        Args:
            definition_ids: SE PodDefinition ids to mark superseded.
            superseded_at: ISO-8601 timestamp of the supersession (kept in
                ``raw_event.superseded_at`` for audit).

        Returns:
            Number of documents actually updated.
        """

    @abstractmethod
    async def ensure_indexes_async(self) -> None:
        """Create indexes for the supported query patterns.

        Indexes:
            - ``(name, pod_type)`` compound.
            - ``status`` single field.
        """
