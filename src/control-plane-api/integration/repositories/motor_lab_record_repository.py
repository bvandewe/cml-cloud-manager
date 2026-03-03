"""MongoDB repository for LabRecord entities using Neuroglia's MotorRepository."""

import logging
from typing import TYPE_CHECKING, Optional, cast

from motor.motor_asyncio import AsyncIOMotorClient
from neuroglia.data.infrastructure.mongo import MotorRepository
from neuroglia.data.infrastructure.tracing_mixin import TracedRepositoryMixin
from neuroglia.serialization.json import JsonSerializer

from domain.entities.lab_record import LabRecord
from domain.repositories.lab_record_repository import LabRecordRepository

if TYPE_CHECKING:
    from neuroglia.mediation.mediator import Mediator

logger = logging.getLogger(__name__)


class MongoLabRecordRepository(TracedRepositoryMixin, MotorRepository[LabRecord, str], LabRecordRepository):  # type: ignore[misc]
    """Motor-based async MongoDB repository for LabRecord entities."""

    def __init__(
        self,
        client: AsyncIOMotorClient,
        database_name: str,
        collection_name: str,
        serializer: JsonSerializer,
        entity_type: type[LabRecord] | None = None,
        mediator: Optional["Mediator"] = None,
    ):
        """Initialize the LabRecord repository.

        Args:
            client: Motor async MongoDB client
            database_name: Name of the MongoDB database
            collection_name: Name of the collection
            serializer: JSON serializer for entity conversion
            entity_type: Optional entity type (LabRecord)
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

    async def get_by_id_async(self, record_id: str) -> LabRecord | None:
        """Get a lab record by its ID."""
        return cast(LabRecord | None, await self.get_async(record_id))

    async def get_by_lab_id_async(self, worker_id: str, lab_id: str) -> LabRecord | None:
        """Get a lab record by worker ID and CML lab ID."""
        document = await self.collection.find_one({"worker_id": worker_id, "lab_id": lab_id})
        if document:
            return self._deserialize_entity(document)
        return None

    async def get_all_by_worker_async(self, worker_id: str) -> list[LabRecord]:
        """Get all lab records for a specific worker."""
        cursor = self.collection.find({"worker_id": worker_id})
        records = []
        async for document in cursor:
            record = self._deserialize_entity(document)
            records.append(record)
        return records

    async def get_all_async(self) -> list[LabRecord]:
        """Get all lab records."""
        cursor = self.collection.find({})
        records = []
        async for document in cursor:
            record = self._deserialize_entity(document)
            records.append(record)
        return records

    async def remove_by_id_async(self, record_id: str) -> None:
        """Remove a lab record by ID."""
        await self.collection.delete_one({"id": record_id})

    async def add_many_async(self, lab_records: list[LabRecord]) -> int:
        """Add multiple lab records in a batch operation.

        Uses MongoDB's insert_many for efficient batch inserts.

        Args:
            lab_records: List of LabRecord entities to add

        Returns:
            Number of records inserted
        """
        if not lab_records:
            return 0

        import json

        documents = []
        for record in lab_records:
            # Serialize the entity state to bytes/bytearray
            serialized_bytes = self._serializer.serialize(record.state)

            # Convert bytes to dict for MongoDB
            serialized_dict = json.loads(serialized_bytes)

            documents.append(serialized_dict)

        # Execute bulk insert using Motor's async insert_many
        result = await self.collection.insert_many(documents, ordered=False)

        # Publish domain events for each entity (if mediator configured)
        if self._mediator:
            for record in lab_records:
                # Use the _pending_events attribute from AggregateRoot
                if hasattr(record, "_pending_events") and record._pending_events:
                    for event in record._pending_events:
                        await self._mediator.publish_async(event)
                    record.clear_pending_events()

        return len(result.inserted_ids)

    async def update_many_async(self, lab_records: list[LabRecord]) -> int:
        """Update multiple lab records in a batch operation with optimistic concurrency.

        Uses MongoDB's bulk_write with state_version checks to prevent
        concurrent overwrites (R1 resilience hardening).

        Each update atomically checks {id, state_version} and increments
        the version. Records that fail the version check are skipped
        (another process updated them first) and logged as warnings.

        Args:
            lab_records: List of LabRecord entities to update

        Returns:
            Number of records successfully updated
        """
        if not lab_records:
            return 0

        import json

        from pymongo import UpdateOne

        operations = []
        record_map: dict[int, LabRecord] = {}  # index → record for conflict tracking
        for idx, record in enumerate(lab_records):
            # Serialize the entity state to bytes/bytearray
            serialized_bytes = self._serializer.serialize(record.state)

            # Convert bytes to dict for MongoDB
            serialized_dict = json.loads(serialized_bytes)

            # Read current state_version (Neuroglia AggregateState tracks this)
            current_version = getattr(record.state, "state_version", 0) or 0
            next_version = current_version + 1

            # Set the new version in the update payload
            serialized_dict["state_version"] = next_version

            # OCC: filter by id AND current state_version
            operations.append(
                UpdateOne(
                    {"id": record.id(), "state_version": current_version},
                    {"$set": serialized_dict},
                )
            )
            record_map[idx] = record

        # Execute bulk write using Motor's async bulk_write (ordered=False for parallelism)
        result = await self.collection.bulk_write(operations, ordered=False)

        modified = result.modified_count
        total = len(lab_records)
        skipped = total - modified

        if skipped > 0:
            logger.warning(
                "update_many_async: %d/%d records skipped due to version conflict (OCC)",
                skipped,
                total,
            )

        # Publish domain events only for successfully updated entities
        if self._mediator and modified > 0:
            for record in lab_records:
                if hasattr(record, "_pending_events") and record._pending_events:
                    for event in record._pending_events:
                        await self._mediator.publish_async(event)
                    record.clear_pending_events()

        return modified

    async def remove_by_lab_id_async(self, worker_id: str, lab_id: str) -> bool:
        """Remove a lab record by worker ID and CML lab ID.

        Args:
            worker_id: Worker ID hosting the lab
            lab_id: CML lab ID to remove

        Returns:
            True if record was deleted, False if not found
        """
        result = await self.collection.delete_one({"worker_id": worker_id, "lab_id": lab_id})
        return result.deleted_count > 0

    async def remove_by_worker_async(self, worker_id: str) -> None:
        """Remove all lab records for a worker."""
        await self.collection.delete_many({"worker_id": worker_id})

    async def get_with_pending_actions_async(self) -> list[LabRecord]:
        """Get all lab records with pending actions.

        ADR-017: Used by lablet-controller to find labs needing reconciliation.

        Returns:
            List of LabRecord entities with pending_action != None.
        """
        cursor = self.collection.find({"pending_action": {"$ne": None}})
        records = []
        async for document in cursor:
            record = self._deserialize_entity(document)
            records.append(record)
        return records

    async def get_with_pending_actions_by_worker_async(self, worker_id: str) -> list[LabRecord]:
        """Get lab records with pending actions for a specific worker.

        Args:
            worker_id: Worker ID to filter by.

        Returns:
            List of LabRecord entities with pending_action != None.
        """
        cursor = self.collection.find({"worker_id": worker_id, "pending_action": {"$ne": None}})
        records = []
        async for document in cursor:
            record = self._deserialize_entity(document)
            records.append(record)
        return records

    async def ensure_indexes_async(self) -> None:
        """Create indexes for efficient querying."""
        # Index on worker_id for quick worker-specific queries
        await self.collection.create_index("worker_id")

        # Compound index on worker_id + lab_id for unique lookup
        await self.collection.create_index([("worker_id", 1), ("lab_id", 1)], unique=True)

        # Index on last_synced_at for cleanup operations
        await self.collection.create_index("last_synced_at")

        # Index on pending_action for ADR-017 reconciliation queries
        await self.collection.create_index("pending_action")
