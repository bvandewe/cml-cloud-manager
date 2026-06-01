"""MongoDB repository for UserSession child entities.

Phase 7E: Plain Motor collection repository (not MotorRepository base class).
UserSession is a child entity of LabletSession stored in its own collection.

Pattern: Direct Motor collection access with manual serialization,
following the same approach used for other child entities.
"""

import json
import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from neuroglia.serialization.json import JsonSerializer

from domain.entities.user_session import UserSession
from domain.repositories.user_session_repository import UserSessionRepository

log = logging.getLogger(__name__)


class MongoUserSessionRepository(UserSessionRepository):
    """Motor-based MongoDB repository for UserSession child entities."""

    def __init__(
        self,
        client: AsyncIOMotorClient,
        database_name: str,
        collection_name: str,
        serializer: JsonSerializer,
    ):
        """Initialize the UserSession repository.

        Args:
            client: Motor async MongoDB client
            database_name: Name of the MongoDB database
            collection_name: Name of the collection ("user_sessions")
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
            await self._collection.create_index("lds_session_id", name="idx_lds_session_id", sparse=True)
            log.debug("UserSession indexes created successfully")
        except Exception:
            log.warning("Failed to create UserSession indexes", exc_info=True)
        finally:
            self._indexes_initialized = True

    def _serialize(self, entity: UserSession) -> dict[str, Any]:
        """Serialize a UserSession to a MongoDB document."""
        raw = self._serializer.serialize(entity)
        if isinstance(raw, (bytes, bytearray)):
            return json.loads(raw.decode("utf-8"))
        if isinstance(raw, str):
            return json.loads(raw)
        return raw  # type: ignore[return-value]

    def _deserialize(self, document: dict[str, Any]) -> UserSession:
        """Deserialize a MongoDB document to a UserSession."""
        doc = {k: v for k, v in document.items() if k != "_id"}
        json_bytes = json.dumps(doc, default=str).encode("utf-8")
        return self._serializer.deserialize(json_bytes, UserSession)  # type: ignore[return-value]

    # --- CRUD ---

    async def get_by_id_async(self, session_id: str) -> UserSession | None:
        """Retrieve a UserSession by its entity ID."""
        document = await self._collection.find_one({"id": session_id})
        if document:
            return self._deserialize(document)
        return None

    async def add_async(self, entity: UserSession) -> None:
        """Persist a new UserSession."""
        await self._ensure_indexes()
        doc = self._serialize(entity)
        await self._collection.insert_one(doc)
        log.debug(f"Added UserSession {entity.id} for session {entity.lablet_session_id}")

    async def update_async(self, entity: UserSession) -> None:
        """Update an existing UserSession."""
        doc = self._serialize(entity)
        await self._collection.replace_one({"id": entity.id}, doc)

    async def delete_async(self, session_id: str) -> bool:
        """Delete a UserSession by ID."""
        result = await self._collection.delete_one({"id": session_id})
        return result.deleted_count > 0

    # --- Parent Queries ---

    async def get_by_lablet_session_async(self, lablet_session_id: str) -> UserSession | None:
        """Retrieve the UserSession for a given LabletSession."""
        document = await self._collection.find_one({"lablet_session_id": lablet_session_id})
        if document:
            return self._deserialize(document)
        return None

    # --- External Reference Queries ---

    async def get_by_lds_session_async(self, lds_session_id: str) -> UserSession | None:
        """Retrieve a UserSession by its LDS session reference."""
        document = await self._collection.find_one({"lds_session_id": lds_session_id})
        if document:
            return self._deserialize(document)
        return None

    # --- Bulk Queries ---

    async def list_by_lablet_sessions_async(self, lablet_session_ids: list[str]) -> list[UserSession]:
        """Retrieve UserSessions for multiple LabletSessions."""
        cursor = self._collection.find({"lablet_session_id": {"$in": lablet_session_ids}})
        return [self._deserialize(doc) async for doc in cursor]
