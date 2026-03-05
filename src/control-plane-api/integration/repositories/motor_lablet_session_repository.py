"""MongoDB repository for LabletSession aggregates using Neuroglia's MotorRepository.

Phase 7E: Replaces MongoLabletInstanceRepository.
Extends the framework's MotorRepository to provide LabletSession-specific queries
while inheriting all standard CRUD operations with automatic domain event publishing.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional, cast

from domain.entities.lablet_session import LabletSession
from domain.enums import LabletSessionStatus
from domain.repositories.lablet_session_repository import LabletSessionRepository
from motor.motor_asyncio import AsyncIOMotorClient
from neuroglia.data.infrastructure.mongo import MotorRepository
from neuroglia.data.infrastructure.tracing_mixin import TracedRepositoryMixin
from neuroglia.serialization.json import JsonSerializer

if TYPE_CHECKING:
    from neuroglia.mediation.mediator import Mediator

log = logging.getLogger(__name__)

# Status constants for queries
ACTIVE_STATUSES = [
    LabletSessionStatus.RUNNING.value,
    LabletSessionStatus.COLLECTING.value,
    LabletSessionStatus.GRADING.value,
]

PENDING_STATUSES = [
    LabletSessionStatus.PENDING.value,
    LabletSessionStatus.SCHEDULED.value,
    LabletSessionStatus.INSTANTIATING.value,
]

NON_TERMINAL_STATUSES = [
    LabletSessionStatus.PENDING.value,
    LabletSessionStatus.SCHEDULED.value,
    LabletSessionStatus.INSTANTIATING.value,
    LabletSessionStatus.RUNNING.value,
    LabletSessionStatus.COLLECTING.value,
    LabletSessionStatus.GRADING.value,
    LabletSessionStatus.STOPPING.value,
    LabletSessionStatus.STOPPED.value,
    LabletSessionStatus.ARCHIVED.value,
]


class MongoLabletSessionRepository(TracedRepositoryMixin, MotorRepository[LabletSession, str], LabletSessionRepository):  # type: ignore[misc]
    """Motor-based async MongoDB repository for LabletSession aggregates.

    Extends Neuroglia's MotorRepository to inherit standard CRUD operations with
    automatic event publishing and adds LabletSession-specific queries. TracedRepositoryMixin
    provides automatic OpenTelemetry instrumentation for all repository operations.
    """

    def __init__(
        self,
        client: AsyncIOMotorClient,
        database_name: str,
        collection_name: str,
        serializer: JsonSerializer,
        entity_type: type[LabletSession] | None = None,
        mediator: Optional["Mediator"] = None,
    ):
        """Initialize the LabletSession repository.

        Args:
            client: Motor async MongoDB client
            database_name: Name of the MongoDB database
            collection_name: Name of the collection (typically "lablet_sessions")
            serializer: JSON serializer for entity conversion
            entity_type: Optional entity type (LabletSession)
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
        self._indexes_initialized: bool = False

    async def _ensure_indexes(self) -> None:
        """Ensure required indexes exist for the collection.

        Creates indexes for common query patterns:
        - status: Primary lifecycle queries
        - worker_id: Worker assignment and capacity
        - owner_id: User dashboard queries
        - definition_id: Definition usage tracking
        - reservation_id: External reservation lookup (unique, sparse)
        - timeslot_start/end: Scheduling and overlap detection
        - lab_record_id: Absorbed from LabletLabBinding (ADR-020)
        """
        if self._indexes_initialized:
            return

        try:
            await self.collection.create_index("status", name="idx_status")
            await self.collection.create_index("worker_id", name="idx_worker_id", sparse=True)
            await self.collection.create_index("owner_id", name="idx_owner_id")
            await self.collection.create_index("definition_id", name="idx_definition_id")
            await self.collection.create_index("reservation_id", name="idx_reservation_id_unique", unique=True, sparse=True)
            await self.collection.create_index("timeslot_start", name="idx_timeslot_start")
            await self.collection.create_index("timeslot_end", name="idx_timeslot_end")
            await self.collection.create_index("lab_record_id", name="idx_lab_record_id", sparse=True)
            await self.collection.create_index([("worker_id", 1), ("status", 1)], name="idx_worker_status", sparse=True)
            await self.collection.create_index([("owner_id", 1), ("status", 1)], name="idx_owner_status")
            log.debug("LabletSession indexes created successfully")
        except Exception:
            log.warning("Failed to create LabletSession indexes", exc_info=True)
        finally:
            self._indexes_initialized = True

    # --- Basic CRUD ---

    async def get_by_id_async(self, session_id: str) -> LabletSession | None:
        """Retrieve a LabletSession by its aggregate ID."""
        return cast(LabletSession | None, await self.get_async(session_id))

    async def add_async(self, entity: LabletSession) -> LabletSession:  # type: ignore[override]
        """Add a new LabletSession."""
        await self._ensure_indexes()
        return cast(LabletSession, await super().add_async(entity))

    async def update_async(self, entity: LabletSession) -> LabletSession:  # type: ignore[override]
        """Update an existing LabletSession."""
        return cast(LabletSession, await super().update_async(entity))

    async def delete_async(self, session_id: str) -> bool:
        """Delete a LabletSession by ID."""
        await self.remove_async(session_id)
        return True

    # --- Status Queries ---

    async def list_by_status_async(self, status: LabletSessionStatus) -> list[LabletSession]:
        """Retrieve LabletSessions by status."""
        cursor = self.collection.find({"status": status.value})
        return [self._deserialize_entity(doc) async for doc in cursor]

    async def list_by_statuses_async(self, statuses: list[LabletSessionStatus]) -> list[LabletSession]:
        """Retrieve LabletSessions matching any of the given statuses."""
        status_values = [s.value for s in statuses]
        cursor = self.collection.find({"status": {"$in": status_values}})
        return [self._deserialize_entity(doc) async for doc in cursor]

    async def list_active_async(self) -> list[LabletSession]:
        """Retrieve all active (RUNNING, COLLECTING, GRADING) LabletSessions."""
        cursor = self.collection.find({"status": {"$in": ACTIVE_STATUSES}})
        return [self._deserialize_entity(doc) async for doc in cursor]

    async def list_pending_async(self) -> list[LabletSession]:
        """Retrieve LabletSessions pending execution (PENDING, SCHEDULED, INSTANTIATING)."""
        cursor = self.collection.find({"status": {"$in": PENDING_STATUSES}})
        return [self._deserialize_entity(doc) async for doc in cursor]

    # --- Worker Queries ---

    async def list_by_worker_async(self, worker_id: str) -> list[LabletSession]:
        """Retrieve all LabletSessions assigned to a worker."""
        cursor = self.collection.find({"worker_id": worker_id})
        return [self._deserialize_entity(doc) async for doc in cursor]

    async def list_active_by_worker_async(self, worker_id: str) -> list[LabletSession]:
        """Retrieve active LabletSessions for a specific worker."""
        cursor = self.collection.find({"worker_id": worker_id, "status": {"$in": ACTIVE_STATUSES}})
        return [self._deserialize_entity(doc) async for doc in cursor]

    async def count_by_worker_async(self, worker_id: str) -> int:
        """Count non-terminal LabletSessions on a worker."""
        return await self.collection.count_documents({"worker_id": worker_id, "status": {"$in": NON_TERMINAL_STATUSES}})

    # --- Owner Queries ---

    async def list_by_owner_async(self, owner_id: str) -> list[LabletSession]:
        """Retrieve all LabletSessions owned by a user."""
        cursor = self.collection.find({"owner_id": owner_id})
        return [self._deserialize_entity(doc) async for doc in cursor]

    async def list_active_by_owner_async(self, owner_id: str) -> list[LabletSession]:
        """Retrieve active LabletSessions for a specific owner."""
        cursor = self.collection.find({"owner_id": owner_id, "status": {"$in": ACTIVE_STATUSES}})
        return [self._deserialize_entity(doc) async for doc in cursor]

    # --- Definition Queries ---

    async def list_by_definition_async(self, definition_id: str) -> list[LabletSession]:
        """Retrieve all LabletSessions for a specific definition."""
        cursor = self.collection.find({"definition_id": definition_id})
        return [self._deserialize_entity(doc) async for doc in cursor]

    async def count_by_definition_async(self, definition_id: str) -> int:
        """Count LabletSessions using a specific definition."""
        return await self.collection.count_documents({"definition_id": definition_id})

    # --- Lab Record Query (absorbed from LabletLabBinding — ADR-020 §2) ---

    async def get_by_lab_record_async(self, lab_record_id: str) -> LabletSession | None:
        """Retrieve the LabletSession bound to a lab record."""
        document = await self.collection.find_one({"lab_record_id": lab_record_id})
        if document:
            return self._deserialize_entity(document)
        return None

    # --- Timeslot Queries ---

    async def list_by_timeslot_overlap_async(
        self,
        start: datetime,
        end: datetime,
        worker_id: str | None = None,
    ) -> list[LabletSession]:
        """Find LabletSessions with overlapping timeslots."""
        query: dict = {
            "timeslot_start": {"$lt": end},
            "timeslot_end": {"$gt": start},
            "status": {"$in": NON_TERMINAL_STATUSES},
        }
        if worker_id:
            query["worker_id"] = worker_id

        cursor = self.collection.find(query)
        return [self._deserialize_entity(doc) async for doc in cursor]

    async def list_expiring_soon_async(self, within_minutes: int = 15) -> list[LabletSession]:
        """Find active LabletSessions expiring within the given window."""
        now = datetime.now(timezone.utc)
        expiration_threshold = now + timedelta(minutes=within_minutes)

        cursor = self.collection.find(
            {
                "status": {"$in": ACTIVE_STATUSES},
                "timeslot_end": {"$lte": expiration_threshold, "$gt": now},
            }
        )
        return [self._deserialize_entity(doc) async for doc in cursor]

    async def list_approaching_start_async(self, before: datetime) -> list[LabletSession]:
        """Find SCHEDULED sessions whose timeslot_start is before the given time.

        Uses idx_timeslot_start index for efficient querying.
        Only returns SCHEDULED sessions (not yet instantiating).
        """
        cursor = self.collection.find(
            {
                "status": LabletSessionStatus.SCHEDULED.value,
                "timeslot_start": {"$ne": None, "$lte": before},
            }
        )
        return [self._deserialize_entity(doc) async for doc in cursor]

    async def list_past_end_async(self, as_of: datetime) -> list[LabletSession]:
        """Find non-terminal sessions whose timeslot_end has passed.

        Uses idx_timeslot_end index for efficient querying.
        Returns sessions in any non-terminal status where the timeslot
        has ended — the reconciler decides the appropriate transition
        (STOPPING, EXPIRED, etc.) based on current status.
        """
        # Exclude STOPPING and terminal statuses — those are already being handled
        actionable_statuses = [
            LabletSessionStatus.SCHEDULED.value,
            LabletSessionStatus.INSTANTIATING.value,
            LabletSessionStatus.RUNNING.value,
            LabletSessionStatus.COLLECTING.value,
            LabletSessionStatus.GRADING.value,
        ]
        cursor = self.collection.find(
            {
                "status": {"$in": actionable_statuses},
                "timeslot_end": {"$ne": None, "$lte": as_of},
            }
        )
        return [self._deserialize_entity(doc) async for doc in cursor]

    # --- Reservation Queries ---

    async def get_by_reservation_id_async(self, reservation_id: str) -> LabletSession | None:
        """Retrieve a LabletSession by external reservation ID."""
        document = await self.collection.find_one({"reservation_id": reservation_id})
        if document:
            return self._deserialize_entity(document)
        return None

    # --- Aggregate Queries ---

    async def count_by_status_async(self, status: LabletSessionStatus) -> int:
        """Count LabletSessions by status."""
        return await self.collection.count_documents({"status": status.value})

    async def get_status_counts_async(self) -> dict[LabletSessionStatus, int]:
        """Get counts for all statuses."""
        pipeline = [{"$group": {"_id": "$status", "count": {"$sum": 1}}}]
        counts: dict[LabletSessionStatus, int] = {status: 0 for status in LabletSessionStatus}

        async for result in self.collection.aggregate(pipeline):
            status_value = result["_id"]
            count = result["count"]
            try:
                status = LabletSessionStatus(status_value)
                counts[status] = count
            except ValueError:
                log.warning(f"Unknown status value in database: {status_value}")

        return counts

    # --- Resource Observation Queries (ADR-030) ---

    async def find_with_observations_async(self, definition_id: str, limit: int = 20) -> list[LabletSession]:
        """Find sessions with resource observations, sorted by observed_at desc."""
        cursor = (
            self.collection.find(
                {
                    "definition_id": definition_id,
                    "observed_resources": {"$ne": None},
                }
            )
            .sort("observed_at", -1)
            .limit(limit)
        )
        return [self._deserialize_entity(doc) async for doc in cursor]
