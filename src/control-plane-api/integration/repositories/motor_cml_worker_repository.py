"""
MongoDB repository for CMLWorker entities using Neuroglia's MotorRepository.

This extends the framework's MotorRepository to provide CMLWorker-specific queries
while inheriting all standard CRUD operations with automatic domain event publishing.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional, cast

import pymongo.errors
from motor.motor_asyncio import AsyncIOMotorClient
from neuroglia.data.infrastructure.mongo import MotorRepository
from neuroglia.data.infrastructure.tracing_mixin import TracedRepositoryMixin
from neuroglia.serialization.json import JsonSerializer

from domain.entities.cml_worker import CMLWorker
from domain.enums import CMLWorkerStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository

if TYPE_CHECKING:
    from neuroglia.mediation.mediator import Mediator

log = logging.getLogger(__name__)


class MongoCMLWorkerRepository(TracedRepositoryMixin, MotorRepository[CMLWorker, str], CMLWorkerRepository):  # type: ignore[misc]
    """
    Motor-based async MongoDB repository for CMLWorker entities with automatic tracing
    and domain event publishing.

    Extends Neuroglia's MotorRepository to inherit standard CRUD operations with
    automatic event publishing and adds CMLWorker-specific queries. TracedRepositoryMixin
    provides automatic OpenTelemetry instrumentation for all repository operations
    using Python's MRO to intercept repository calls transparently.
    """

    def __init__(
        self,
        client: AsyncIOMotorClient,
        database_name: str,
        collection_name: str,
        serializer: JsonSerializer,
        entity_type: type[CMLWorker] | None = None,
        mediator: Optional["Mediator"] = None,
    ):
        """
        Initialize the CMLWorker repository.

        Args:
            client: Motor async MongoDB client
            database_name: Name of the MongoDB database
            collection_name: Name of the collection
            serializer: JSON serializer for entity conversion
            entity_type: Optional entity type (CMLWorker)
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

        Creates indexes for common query patterns:
        - status: Primary lifecycle queries
        - aws_instance_id: Unique identifier for EC2 instances (sparse)
        - aws_region: Regional queries
        - last_activity_at: Idle worker detection
        - license status: Worker selection based on license
        """
        if self._indexes_initialized:
            return

        try:
            # Status index - primary query path
            await self.collection.create_index("status", name="idx_status")

            # Unique index on AWS instance ID (sparse to allow None)
            await self.collection.create_index("aws_instance_id", unique=True, sparse=True, name="idx_aws_instance_id_unique")

            # Region queries - worker distribution
            await self.collection.create_index("aws_region", name="idx_aws_region")

            # Idle worker detection - combining status and last activity
            await self.collection.create_index(
                [("status", 1), ("last_activity_at", 1)],
                name="idx_status_last_activity",
            )

            # License status for worker selection
            await self.collection.create_index("license_status", name="idx_license_status")

            # Compound index for available worker queries
            await self.collection.create_index(
                [("status", 1), ("license_status", 1), ("aws_region", 1)],
                name="idx_worker_availability",
            )

            log.debug("CMLWorker indexes created successfully")
        except Exception:
            log.warning("Failed to create CMLWorker indexes", exc_info=True)
        finally:
            self._indexes_initialized = True

    async def get_all_async(self) -> list[CMLWorker]:
        """Retrieve all CML workers."""
        await self._ensure_indexes()
        cursor = self.collection.find({})
        workers = []
        async for document in cursor:
            worker = self._deserialize_entity(document)
            workers.append(worker)
        return workers

    async def get_by_id_async(self, worker_id: str) -> CMLWorker | None:
        """Retrieve a CML worker by ID."""
        return cast(CMLWorker | None, await self.get_async(worker_id))

    async def get_by_aws_instance_id_async(self, aws_instance_id: str) -> CMLWorker | None:
        """Retrieve a CML worker by AWS EC2 instance ID."""
        await self._ensure_indexes()
        document = await self.collection.find_one({"aws_instance_id": aws_instance_id})
        if document:
            return self._deserialize_entity(document)
        return None

    async def get_by_status_async(self, status: CMLWorkerStatus) -> list[CMLWorker]:
        """Retrieve CML workers by status."""
        await self._ensure_indexes()
        cursor = self.collection.find({"status": status.value})
        workers = []
        async for document in cursor:
            worker = self._deserialize_entity(document)
            workers.append(worker)
        return workers

    async def get_active_workers_async(self) -> list[CMLWorker]:
        """Retrieve all active (non-terminated) CML workers."""
        await self._ensure_indexes()
        cursor = self.collection.find({"status": {"$ne": CMLWorkerStatus.TERMINATED.value}})
        workers = []
        async for document in cursor:
            worker = self._deserialize_entity(document)
            workers.append(worker)
        return workers

    async def get_idle_workers_async(self, idle_threshold_minutes: int) -> list[CMLWorker]:
        """Retrieve workers that have been idle beyond the threshold.

        Args:
            idle_threshold_minutes: Idle threshold in minutes

        Returns:
            List of idle workers (running but inactive)
        """
        await self._ensure_indexes()
        threshold_time = datetime.now(timezone.utc) - timedelta(minutes=idle_threshold_minutes)
        cursor = self.collection.find(
            {
                "status": CMLWorkerStatus.RUNNING.value,
                "last_activity_at": {"$lt": threshold_time.isoformat()},
            }
        )
        workers = []
        async for document in cursor:
            worker = self._deserialize_entity(document)
            workers.append(worker)
        return workers

    async def get_workers_by_region_async(self, aws_region: str) -> list[CMLWorker]:
        """Retrieve workers in a specific AWS region.

        Args:
            aws_region: AWS region identifier (e.g., 'us-east-1')

        Returns:
            List of workers in the specified region
        """
        await self._ensure_indexes()
        cursor = self.collection.find({"aws_region": aws_region})
        workers = []
        async for document in cursor:
            worker = self._deserialize_entity(document)
            workers.append(worker)
        return workers

    async def add_async(self, entity: CMLWorker) -> CMLWorker:  # type: ignore[override]
        """Add a new CML worker.

        Args:
            entity: The CML worker entity to add

        Returns:
            The added worker with updated state
        """
        # Ensure all indexes are created (includes unique index on aws_instance_id)
        await self._ensure_indexes()

        instance_id = entity.state.aws_instance_id
        if instance_id:
            # Atomic check to prevent duplicate imports (race condition safe)
            existing = await self.collection.find_one({"aws_instance_id": instance_id})
            if existing:
                # Return existing aggregate rather than creating a duplicate
                return self._deserialize_entity(existing)
        try:
            return cast(CMLWorker, await super().add_async(entity))
        except pymongo.errors.DuplicateKeyError:
            # In rare case of race between check and insert, fetch existing
            existing = await self.collection.find_one({"aws_instance_id": instance_id})
            if existing:
                return self._deserialize_entity(existing)
            raise

    async def update_async(self, entity: CMLWorker) -> CMLWorker:  # type: ignore[override]
        """Update an existing CML worker.

        Args:
            entity: The CML worker entity to update

        Returns:
            The updated worker
        """
        return cast(CMLWorker, await super().update_async(entity))

    async def update_many_async(self, entities: list[CMLWorker]) -> int:
        """Update multiple CML workers in a batch operation.

        Uses MongoDB's bulk_write for efficient batch updates.

        Args:
            entities: List of CMLWorker entities to update

        Returns:
            Number of workers updated
        """
        if not entities:
            return 0

        import json

        from pymongo import UpdateOne

        operations = []
        for entity in entities:
            # Serialize the entity state to bytes/bytearray
            serialized_bytes = self._serializer.serialize(entity.state)

            # Convert bytes to dict for MongoDB
            serialized_dict = json.loads(serialized_bytes)

            # Create update operation using Motor's collection
            operations.append(
                UpdateOne(
                    {"id": entity.id()},
                    {"$set": serialized_dict},
                )
            )

        # Execute bulk write using Motor's async bulk_write
        result = await self.collection.bulk_write(operations, ordered=False)

        # Publish domain events for each entity (if mediator configured)
        if self._mediator:
            for entity in entities:
                # Use the _pending_events attribute from AggregateRoot
                if hasattr(entity, "_pending_events") and entity._pending_events:
                    for event in entity._pending_events:
                        await self._mediator.publish_async(event)
                    entity.clear_pending_events()

        return result.modified_count

    async def delete_async(self, worker_id: str, worker: CMLWorker | None = None) -> bool:
        """Delete a CML worker by ID.

        Args:
            worker_id: The ID of the worker to delete
            worker: Optional worker entity with pending domain events to publish

        Returns:
            True if deletion was successful, False otherwise
        """
        # The base MotorRepository.remove_async will handle event publishing
        # if a mediator is configured and the entity has pending events
        await self.remove_async(worker_id)
        return True
        return True
