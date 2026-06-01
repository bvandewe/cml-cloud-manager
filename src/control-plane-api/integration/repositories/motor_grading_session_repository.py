"""MongoDB repository for GradingSession child entities.

Phase 7E: Plain Motor collection repository (not MotorRepository base class).
GradingSession is a child entity of LabletSession stored in its own collection.

Pattern: Direct Motor collection access with manual serialization.
"""

import json
import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from neuroglia.serialization.json import JsonSerializer

from domain.entities.grading_session import GradingSession
from domain.repositories.grading_session_repository import GradingSessionRepository

log = logging.getLogger(__name__)


class MongoGradingSessionRepository(GradingSessionRepository):
    """Motor-based MongoDB repository for GradingSession child entities."""

    def __init__(
        self,
        client: AsyncIOMotorClient,
        database_name: str,
        collection_name: str,
        serializer: JsonSerializer,
    ):
        """Initialize the GradingSession repository.

        Args:
            client: Motor async MongoDB client
            database_name: Name of the MongoDB database
            collection_name: Name of the collection ("grading_sessions")
            serializer: JSON serializer for entity conversion
        """
        self._db = client[database_name]
        self._collection: AsyncIOMotorCollection = self._db[collection_name]
        self._serializer = serializer
        self._indexes_initialized = False

    async def _ensure_indexes(self) -> None:
        """Create indexes for common query patterns."""
        if self._indexes_initialized:
            return
        try:
            await self._collection.create_index("lablet_session_id", name="idx_lablet_session_id")
            await self._collection.create_index("grading_session_id", name="idx_grading_session_id", sparse=True)
            log.debug("GradingSession indexes created successfully")
        except Exception:
            log.warning("Failed to create GradingSession indexes", exc_info=True)
        finally:
            self._indexes_initialized = True

    def _serialize(self, entity: GradingSession) -> dict[str, Any]:
        """Serialize a GradingSession to a MongoDB document."""
        raw = self._serializer.serialize(entity)
        if isinstance(raw, (bytes, bytearray)):
            return json.loads(raw.decode("utf-8"))
        if isinstance(raw, str):
            return json.loads(raw)
        return raw  # type: ignore[return-value]

    def _deserialize(self, document: dict[str, Any]) -> GradingSession:
        """Deserialize a MongoDB document to a GradingSession."""
        doc = {k: v for k, v in document.items() if k != "_id"}
        json_bytes = json.dumps(doc, default=str).encode("utf-8")
        return self._serializer.deserialize(json_bytes, GradingSession)  # type: ignore[return-value]

    # --- CRUD ---

    async def get_by_id_async(self, session_id: str) -> GradingSession | None:
        """Retrieve a GradingSession by its entity ID."""
        document = await self._collection.find_one({"id": session_id})
        if document:
            return self._deserialize(document)
        return None

    async def add_async(self, entity: GradingSession) -> None:
        """Persist a new GradingSession."""
        await self._ensure_indexes()
        doc = self._serialize(entity)
        await self._collection.insert_one(doc)
        log.debug(f"Added GradingSession {entity.id} for session {entity.lablet_session_id}")

    async def update_async(self, entity: GradingSession) -> None:
        """Update an existing GradingSession."""
        doc = self._serialize(entity)
        await self._collection.replace_one({"id": entity.id}, doc)

    async def delete_async(self, session_id: str) -> bool:
        """Delete a GradingSession by ID."""
        result = await self._collection.delete_one({"id": session_id})
        return result.deleted_count > 0

    # --- Parent Queries ---

    async def get_by_lablet_session_async(self, lablet_session_id: str) -> GradingSession | None:
        """Retrieve the GradingSession for a given LabletSession."""
        document = await self._collection.find_one({"lablet_session_id": lablet_session_id})
        if document:
            return self._deserialize(document)
        return None

    # --- External Reference Queries ---

    async def get_by_grading_session_id_async(self, grading_session_id: str) -> GradingSession | None:
        """Retrieve a GradingSession by its external Grading-Engine reference."""
        document = await self._collection.find_one({"grading_session_id": grading_session_id})
        if document:
            return self._deserialize(document)
        return None

    # --- Bulk Queries ---

    async def list_by_lablet_sessions_async(self, lablet_session_ids: list[str]) -> list[GradingSession]:
        """Retrieve GradingSessions for multiple LabletSessions."""
        cursor = self._collection.find({"lablet_session_id": {"$in": lablet_session_ids}})
        return [self._deserialize(doc) async for doc in cursor]
