"""MongoDB repository for PendingLabImport entities.

ADR-017: Stores queued lab imports in MongoDB for the reconciliation pattern.
Lablet-controller polls for pending imports and reconciles them via CML API.

Extends Neuroglia's MotorRepository to provide custom queries while
inheriting standard CRUD operations. Same pattern as MongoLabletLabBindingRepository.
"""

import logging
from typing import TYPE_CHECKING, Optional, cast

from motor.motor_asyncio import AsyncIOMotorClient
from neuroglia.data.infrastructure.mongo import MotorRepository
from neuroglia.data.infrastructure.tracing_mixin import TracedRepositoryMixin
from neuroglia.serialization.json import JsonSerializer

from domain.entities.pending_lab_import import PendingLabImport, PendingLabImportStatus
from domain.repositories.pending_lab_import_repository import PendingLabImportRepository

if TYPE_CHECKING:
    from neuroglia.mediation.mediator import Mediator

logger = logging.getLogger(__name__)


class MongoPendingLabImportRepository(TracedRepositoryMixin, MotorRepository[PendingLabImport, str], PendingLabImportRepository):  # type: ignore[misc]
    """Motor-based async MongoDB repository for PendingLabImport entities.

    Extends Neuroglia's MotorRepository to inherit standard CRUD operations
    and adds import-specific queries for worker-scoped lookups and
    status filtering.

    Collection: ``pending_lab_imports``
    Indexes: worker_id, status, compound (worker_id + status).
    """

    def __init__(
        self,
        client: AsyncIOMotorClient,
        database_name: str,
        collection_name: str,
        serializer: JsonSerializer,
        entity_type: type[PendingLabImport] | None = None,
        mediator: Optional["Mediator"] = None,
    ):
        """Initialize the PendingLabImport repository.

        Args:
            client: Motor async MongoDB client.
            database_name: Name of the MongoDB database.
            collection_name: Name of the collection.
            serializer: JSON serializer for entity conversion.
            entity_type: Optional entity type (PendingLabImport).
            mediator: Optional Mediator for domain event publishing.
        """
        super().__init__(
            client=client,
            database_name=database_name,
            collection_name=collection_name,
            serializer=serializer,
            entity_type=entity_type,
            mediator=mediator,
        )

    # =========================================================================
    # Custom queries — inherited CRUD: add_async, update_async, remove_async,
    # get_async, contains_async are provided by MotorRepository base.
    # =========================================================================

    async def get_by_id_async(self, import_id: str) -> PendingLabImport | None:
        """Get a pending lab import by its ID."""
        return cast(PendingLabImport | None, await self.get_async(import_id))

    async def remove_by_id_async(self, import_id: str) -> None:
        """Remove a pending lab import by ID."""
        await self.collection.delete_one({"id": import_id})

    # =========================================================================
    # QUERIES — by worker
    # =========================================================================

    async def get_by_worker_id_async(self, worker_id: str) -> list[PendingLabImport]:
        """Get all pending lab imports for a specific worker."""
        cursor = self.collection.find({"worker_id": worker_id})
        return [self._deserialize_entity(doc) async for doc in cursor]

    async def get_pending_by_worker_id_async(self, worker_id: str) -> list[PendingLabImport]:
        """Get only pending (not yet started) imports for a worker."""
        cursor = self.collection.find(
            {
                "worker_id": worker_id,
                "status": PendingLabImportStatus.PENDING,
            }
        )
        return [self._deserialize_entity(doc) async for doc in cursor]

    # =========================================================================
    # QUERIES — global
    # =========================================================================

    async def get_all_pending_async(self) -> list[PendingLabImport]:
        """Get all pending imports across all workers."""
        cursor = self.collection.find({"status": PendingLabImportStatus.PENDING})
        return [self._deserialize_entity(doc) async for doc in cursor]
