"""MongoDB implementation of ``PodDefinitionReadRepository``.

ADR-044 / G-12 — direct Motor collection access (read-model pattern, same
as :class:`MongoPipelineExecutionRepository`).
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from domain.read_models.pod_definition_read_model import PodDefinitionReadModel
from domain.repositories.pod_definition_read_repository import PodDefinitionReadRepository
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

logger = logging.getLogger(__name__)


class MotorPodDefinitionReadRepository(PodDefinitionReadRepository):
    """Motor-backed implementation of the PodDefinition read-model repository."""

    def __init__(
        self,
        client: AsyncIOMotorClient,
        database_name: str,
        collection_name: str = "pod_definitions_read",
    ) -> None:
        self._client = client
        self._collection: AsyncIOMotorCollection = client[database_name][collection_name]
        self._indexes_initialized = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_doc(model: PodDefinitionReadModel) -> dict[str, Any]:
        doc = asdict(model)
        doc["_id"] = model.id
        return doc

    @staticmethod
    def _from_doc(doc: dict[str, Any]) -> PodDefinitionReadModel:
        # Coerce datetimes back from the BSON / dict form.
        last_event_at = doc.get("last_event_at")
        if isinstance(last_event_at, str):
            try:
                last_event_at = datetime.fromisoformat(last_event_at)
            except ValueError:
                last_event_at = None
        projected_at = doc.get("projected_at")
        if isinstance(projected_at, str):
            try:
                projected_at = datetime.fromisoformat(projected_at)
            except ValueError:
                projected_at = datetime.now(timezone.utc)
        elif not isinstance(projected_at, datetime):
            projected_at = datetime.now(timezone.utc)

        return PodDefinitionReadModel(
            id=doc.get("id") or doc.get("_id"),
            name=doc.get("name", ""),
            version=doc.get("version", ""),
            pod_type=doc.get("pod_type", ""),
            status=doc.get("status", ""),
            content_hash=doc.get("content_hash", ""),
            source_uri=doc.get("source_uri"),
            error_message=doc.get("error_message"),
            error_detail=doc.get("error_detail"),
            last_event_at=last_event_at if isinstance(last_event_at, datetime) else None,
            projected_at=projected_at,
            raw_event=doc.get("raw_event", {}) or {},
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_async(self, definition_id: str) -> PodDefinitionReadModel | None:
        doc = await self._collection.find_one({"_id": definition_id})
        if doc is None:
            return None
        return self._from_doc(doc)

    async def list_by_name_pod_type_async(self, name: str, pod_type: str) -> list[PodDefinitionReadModel]:
        cursor = self._collection.find({"name": name, "pod_type": pod_type})
        return [self._from_doc(doc) async for doc in cursor]

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def upsert_async(self, model: PodDefinitionReadModel) -> None:
        doc = self._to_doc(model)
        await self._collection.replace_one({"_id": model.id}, doc, upsert=True)

    async def mark_superseded_async(self, definition_ids: list[str], superseded_at: str) -> int:
        if not definition_ids:
            return 0
        result = await self._collection.update_many(
            {"_id": {"$in": list(definition_ids)}},
            {
                "$set": {
                    "status": "SUPERSEDED",
                    "raw_event.superseded_at": superseded_at,
                    "projected_at": datetime.now(timezone.utc).isoformat(),
                }
            },
        )
        return result.modified_count

    # ------------------------------------------------------------------
    # Indexes
    # ------------------------------------------------------------------

    async def ensure_indexes_async(self) -> None:
        if self._indexes_initialized:
            return
        try:
            await self._collection.create_index(
                [("name", 1), ("pod_type", 1)],
                name="idx_name_pod_type",
            )
            await self._collection.create_index(
                "status",
                name="idx_status",
            )
            logger.debug("PodDefinitionReadModel indexes created successfully")
        except Exception:  # pragma: no cover — defensive
            logger.warning("Failed to create PodDefinitionReadModel indexes", exc_info=True)
        finally:
            self._indexes_initialized = True
