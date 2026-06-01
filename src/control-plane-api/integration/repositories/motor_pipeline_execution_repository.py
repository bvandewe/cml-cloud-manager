"""MongoDB repository for PipelineExecutionRecord child entities.

Sprint G (G1): Plain Motor collection repository (not MotorRepository base class).
PipelineExecutionRecord is a mutable read model stored in its own collection.

Pattern: Direct Motor collection access with manual serialization.
Matches MongoScoreReportRepository pattern.
"""

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from neuroglia.serialization.json import JsonSerializer

from domain.entities.pipeline_execution_record import PipelineExecutionRecord
from domain.repositories.pipeline_execution_repository import PipelineExecutionRepository

log = logging.getLogger(__name__)


class MongoPipelineExecutionRepository(PipelineExecutionRepository):
    """Motor-based MongoDB repository for PipelineExecutionRecord entities."""

    def __init__(
        self,
        client: AsyncIOMotorClient,
        database_name: str,
        collection_name: str,
        serializer: JsonSerializer,
    ):
        """Initialize the PipelineExecutionRecord repository.

        Args:
            client: Motor async MongoDB client.
            database_name: Name of the MongoDB database.
            collection_name: Name of the collection ("pipeline_executions").
            serializer: JSON serializer for entity conversion.
        """
        self._db = client[database_name]
        self._collection: AsyncIOMotorCollection = self._db[collection_name]
        self._serializer = serializer
        self._indexes_initialized = False

    async def _ensure_indexes(self) -> None:
        """Create indexes for common query patterns.

        Indexes:
        - (session_id, pipeline_name): Primary lookup pattern
        - (session_id, started_at): Execution history ordered by time
        - status: Filter running/completed/failed
        """
        if self._indexes_initialized:
            return
        try:
            await self._collection.create_index(
                [("session_id", 1), ("pipeline_name", 1)],
                name="idx_session_pipeline",
            )
            await self._collection.create_index(
                [("session_id", 1), ("started_at", -1)],
                name="idx_session_started",
            )
            await self._collection.create_index("status", name="idx_status", sparse=True)
            log.debug("PipelineExecutionRecord indexes created successfully")
        except Exception:
            log.warning("Failed to create PipelineExecutionRecord indexes", exc_info=True)
        finally:
            self._indexes_initialized = True

    def _serialize(self, entity: PipelineExecutionRecord) -> dict[str, Any]:
        """Serialize a PipelineExecutionRecord to a MongoDB document."""
        raw = self._serializer.serialize(entity)
        if isinstance(raw, (bytes, bytearray)):
            import json

            return json.loads(raw.decode("utf-8"))
        if isinstance(raw, str):
            import json

            return json.loads(raw)
        return raw  # type: ignore[return-value]

    def _deserialize(self, document: dict[str, Any]) -> PipelineExecutionRecord:
        """Deserialize a MongoDB document to a PipelineExecutionRecord."""
        return self._serializer.deserialize(document, PipelineExecutionRecord)  # type: ignore[return-value]

    # --- CRUD ---

    async def get_by_id_async(self, record_id: str) -> PipelineExecutionRecord | None:
        """Retrieve a PipelineExecutionRecord by its entity ID."""
        document = await self._collection.find_one({"id": record_id})
        if document:
            return self._deserialize(document)
        return None

    async def add_async(self, entity: PipelineExecutionRecord) -> None:
        """Persist a new PipelineExecutionRecord."""
        await self._ensure_indexes()
        doc = self._serialize(entity)
        await self._collection.insert_one(doc)
        log.debug(
            "Added PipelineExecutionRecord %s for session %s pipeline %s",
            entity.id,
            entity.session_id,
            entity.pipeline_name,
        )

    async def update_async(self, entity: PipelineExecutionRecord) -> None:
        """Update an existing PipelineExecutionRecord."""
        doc = self._serialize(entity)
        doc.pop("_id", None)
        await self._collection.replace_one({"id": entity.id}, doc)
        log.debug(
            "Updated PipelineExecutionRecord %s (status=%s)",
            entity.id,
            entity.status,
        )

    async def upsert_async(self, entity: PipelineExecutionRecord) -> None:
        """Insert or update a PipelineExecutionRecord.

        Uses compound key (session_id, pipeline_name, attempt) for matching.
        """
        await self._ensure_indexes()
        doc = self._serialize(entity)
        doc.pop("_id", None)
        await self._collection.update_one(
            {
                "session_id": entity.session_id,
                "pipeline_name": entity.pipeline_name,
                "attempt": entity.attempt,
            },
            {"$set": doc},
            upsert=True,
        )
        log.debug(
            "Upserted PipelineExecutionRecord for session %s pipeline %s attempt %d",
            entity.session_id,
            entity.pipeline_name,
            entity.attempt,
        )

    async def delete_async(self, record_id: str) -> bool:
        """Delete a PipelineExecutionRecord by ID."""
        result = await self._collection.delete_one({"id": record_id})
        return result.deleted_count > 0

    # --- Session Queries ---

    async def get_by_session_async(self, session_id: str) -> list[PipelineExecutionRecord]:
        """Retrieve all execution records for a session, ordered by started_at desc."""
        cursor = self._collection.find({"session_id": session_id}).sort("started_at", -1)
        return [self._deserialize(doc) async for doc in cursor]

    async def get_by_session_and_pipeline_async(self, session_id: str, pipeline_name: str) -> list[PipelineExecutionRecord]:
        """Retrieve execution records for a specific pipeline on a session."""
        cursor = self._collection.find({"session_id": session_id, "pipeline_name": pipeline_name}).sort("started_at", -1)
        return [self._deserialize(doc) async for doc in cursor]

    async def get_latest_by_session_and_pipeline_async(self, session_id: str, pipeline_name: str) -> PipelineExecutionRecord | None:
        """Retrieve the most recent execution for a session+pipeline."""
        document = await self._collection.find_one(
            {"session_id": session_id, "pipeline_name": pipeline_name},
            sort=[("started_at", -1)],
        )
        if document:
            return self._deserialize(document)
        return None

    async def get_running_by_session_async(self, session_id: str) -> list[PipelineExecutionRecord]:
        """Retrieve all currently running executions for a session."""
        cursor = self._collection.find({"session_id": session_id, "status": "running"})
        return [self._deserialize(doc) async for doc in cursor]
