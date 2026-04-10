"""MongoDB repository for ScoreReport child entities.

Phase 7E: Plain Motor collection repository (not MotorRepository base class).
ScoreReport is an immutable child entity of LabletSession stored in its own collection.

Pattern: Direct Motor collection access with manual serialization.
ScoreReport is immutable after creation — no update_async method.
"""

import json
import logging
from typing import Any

from domain.entities.score_report import ScoreReport
from domain.repositories.score_report_repository import ScoreReportRepository
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from neuroglia.serialization.json import JsonSerializer

log = logging.getLogger(__name__)


class MongoScoreReportRepository(ScoreReportRepository):
    """Motor-based MongoDB repository for ScoreReport child entities."""

    def __init__(
        self,
        client: AsyncIOMotorClient,
        database_name: str,
        collection_name: str,
        serializer: JsonSerializer,
    ):
        """Initialize the ScoreReport repository.

        Args:
            client: Motor async MongoDB client
            database_name: Name of the MongoDB database
            collection_name: Name of the collection ("score_reports")
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
            await self._collection.create_index("definition_id", name="idx_definition_id", sparse=True)
            log.debug("ScoreReport indexes created successfully")
        except Exception:
            log.warning("Failed to create ScoreReport indexes", exc_info=True)
        finally:
            self._indexes_initialized = True

    def _serialize(self, entity: ScoreReport) -> dict[str, Any]:
        """Serialize a ScoreReport to a MongoDB document."""
        raw = self._serializer.serialize(entity)
        if isinstance(raw, (bytes, bytearray)):
            return json.loads(raw.decode("utf-8"))
        if isinstance(raw, str):
            return json.loads(raw)
        return raw  # type: ignore[return-value]

    def _deserialize(self, document: dict[str, Any]) -> ScoreReport:
        """Deserialize a MongoDB document to a ScoreReport."""
        doc = {k: v for k, v in document.items() if k != "_id"}
        json_bytes = json.dumps(doc, default=str).encode("utf-8")
        return self._serializer.deserialize(json_bytes, ScoreReport)  # type: ignore[return-value]

    # --- CRUD (minus update — immutable) ---

    async def get_by_id_async(self, report_id: str) -> ScoreReport | None:
        """Retrieve a ScoreReport by its entity ID."""
        document = await self._collection.find_one({"id": report_id})
        if document:
            return self._deserialize(document)
        return None

    async def add_async(self, entity: ScoreReport) -> None:
        """Persist a new ScoreReport."""
        await self._ensure_indexes()
        doc = self._serialize(entity)
        await self._collection.insert_one(doc)
        log.debug(f"Added ScoreReport {entity.id} for session {entity.lablet_session_id}")

    async def delete_async(self, report_id: str) -> bool:
        """Delete a ScoreReport by ID."""
        result = await self._collection.delete_one({"id": report_id})
        return result.deleted_count > 0

    # --- Parent Queries ---

    async def get_by_lablet_session_async(self, lablet_session_id: str) -> ScoreReport | None:
        """Retrieve the ScoreReport for a given LabletSession."""
        document = await self._collection.find_one({"lablet_session_id": lablet_session_id})
        if document:
            return self._deserialize(document)
        return None

    async def get_by_grading_session_async(self, grading_session_id: str) -> ScoreReport | None:
        """Retrieve the ScoreReport for a given GradingSession."""
        document = await self._collection.find_one({"grading_session_id": grading_session_id})
        if document:
            return self._deserialize(document)
        return None

    # --- Bulk Queries ---

    async def list_by_lablet_sessions_async(self, lablet_session_ids: list[str]) -> list[ScoreReport]:
        """Retrieve ScoreReports for multiple LabletSessions."""
        cursor = self._collection.find({"lablet_session_id": {"$in": lablet_session_ids}})
        return [self._deserialize(doc) async for doc in cursor]

    # --- Reporting Queries ---

    async def list_by_definition_async(self, definition_id: str) -> list[ScoreReport]:
        """Retrieve all ScoreReports for sessions of a given definition."""
        cursor = self._collection.find({"definition_id": definition_id})
        return [self._deserialize(doc) async for doc in cursor]

    async def count_passed_by_definition_async(self, definition_id: str) -> int:
        """Count passed ScoreReports for a given definition."""
        return await self._collection.count_documents({"definition_id": definition_id, "passed": True})
