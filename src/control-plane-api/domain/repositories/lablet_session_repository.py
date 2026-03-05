"""Abstract repository for LabletSession aggregates.

Defines the contract for persisting and querying LabletSession aggregates.
Implementations must handle proper serialization of nested value objects
(StateTransition) and optimistic concurrency via state_version.

Phase 7C: Replaces LabletInstanceRepository with Session-based naming
and updated type references per ADR-020.
"""

from abc import ABC, abstractmethod
from datetime import datetime

from domain.entities.lablet_session import LabletSession
from domain.enums import LabletSessionStatus


class LabletSessionRepository(ABC):
    """Abstract repository for LabletSession aggregates.

    LabletSessions represent runtime lab sessions with full lifecycle
    tracking. The repository supports queries by status, worker, owner,
    definition, timeslot, and lab record for scheduling and management.
    """

    # --- Basic CRUD ---

    @abstractmethod
    async def get_by_id_async(self, session_id: str) -> LabletSession | None:
        """Retrieve a LabletSession by its aggregate ID.

        Args:
            session_id: The unique aggregate identifier.

        Returns:
            The LabletSession if found, None otherwise.
        """

    @abstractmethod
    async def add_async(self, entity: LabletSession) -> LabletSession:
        """Add a new LabletSession.

        Args:
            entity: The LabletSession to persist.

        Returns:
            The persisted entity with any server-generated fields.

        Raises:
            RepositoryError: If the entity already exists.
        """

    @abstractmethod
    async def update_async(self, entity: LabletSession) -> LabletSession:
        """Update an existing LabletSession.

        Uses optimistic concurrency via state_version to detect conflicts.

        Args:
            entity: The LabletSession to update.

        Returns:
            The updated entity.

        Raises:
            RepositoryError: If the entity doesn't exist or version conflict.
        """

    @abstractmethod
    async def delete_async(self, session_id: str) -> bool:
        """Delete a LabletSession by ID.

        Note: Prefer archiving/terminating over deletion for audit trail.

        Args:
            session_id: The aggregate ID to delete.

        Returns:
            True if deleted, False if not found.
        """

    # --- Status Queries ---

    @abstractmethod
    async def list_by_status_async(self, status: LabletSessionStatus) -> list[LabletSession]:
        """Retrieve LabletSessions by status.

        Args:
            status: The status to filter by.

        Returns:
            List of LabletSessions with the specified status.
        """

    @abstractmethod
    async def list_by_statuses_async(self, statuses: list[LabletSessionStatus]) -> list[LabletSession]:
        """Retrieve LabletSessions matching any of the given statuses.

        Useful for querying multiple lifecycle phases (e.g., all active states).

        Args:
            statuses: List of statuses to match.

        Returns:
            List of LabletSessions matching any of the specified statuses.
        """

    @abstractmethod
    async def list_active_async(self) -> list[LabletSession]:
        """Retrieve all active (non-terminal) LabletSessions.

        Active states: RUNNING, COLLECTING, GRADING.

        Returns:
            List of active LabletSessions.
        """

    @abstractmethod
    async def list_pending_async(self) -> list[LabletSession]:
        """Retrieve LabletSessions pending execution.

        Pending states: PENDING, SCHEDULED, INSTANTIATING.

        Returns:
            List of pending LabletSessions.
        """

    # --- Worker Queries ---

    @abstractmethod
    async def list_by_worker_async(self, worker_id: str) -> list[LabletSession]:
        """Retrieve all LabletSessions assigned to a worker.

        Args:
            worker_id: The CMLWorker ID.

        Returns:
            List of LabletSessions assigned to the worker.
        """

    @abstractmethod
    async def list_active_by_worker_async(self, worker_id: str) -> list[LabletSession]:
        """Retrieve active LabletSessions for a specific worker.

        Useful for capacity planning and resource management.

        Args:
            worker_id: The CMLWorker ID.

        Returns:
            List of active LabletSessions on the worker.
        """

    @abstractmethod
    async def count_by_worker_async(self, worker_id: str) -> int:
        """Count non-terminal LabletSessions on a worker.

        Useful for load balancing and scheduling decisions.

        Args:
            worker_id: The CMLWorker ID.

        Returns:
            Count of non-terminal sessions.
        """

    # --- Owner Queries ---

    @abstractmethod
    async def list_by_owner_async(self, owner_id: str) -> list[LabletSession]:
        """Retrieve all LabletSessions owned by a user.

        Args:
            owner_id: The user ID.

        Returns:
            List of LabletSessions owned by the user.
        """

    @abstractmethod
    async def list_active_by_owner_async(self, owner_id: str) -> list[LabletSession]:
        """Retrieve active LabletSessions for a specific owner.

        Args:
            owner_id: The user ID.

        Returns:
            List of active LabletSessions owned by the user.
        """

    # --- Definition Queries ---

    @abstractmethod
    async def list_by_definition_async(self, definition_id: str) -> list[LabletSession]:
        """Retrieve all LabletSessions for a specific definition.

        Args:
            definition_id: The LabletDefinition ID.

        Returns:
            List of LabletSessions using the definition.
        """

    @abstractmethod
    async def count_by_definition_async(self, definition_id: str) -> int:
        """Count LabletSessions using a specific definition.

        Useful for impact analysis before deprecating a definition.

        Args:
            definition_id: The LabletDefinition ID.

        Returns:
            Count of sessions using the definition.
        """

    # --- Lab Record Query (absorbed from LabletLabBinding — ADR-020 §2) ---

    @abstractmethod
    async def get_by_lab_record_async(self, lab_record_id: str) -> LabletSession | None:
        """Retrieve the LabletSession bound to a lab record.

        In the new 1:1 model (ADR-020), each LabletSession is bound to
        exactly one LabRecord at schedule time.

        Args:
            lab_record_id: The LabRecord ID.

        Returns:
            The LabletSession if found, None otherwise.
        """

    # --- Timeslot Queries ---

    @abstractmethod
    async def list_by_timeslot_overlap_async(
        self,
        start: datetime,
        end: datetime,
        worker_id: str | None = None,
    ) -> list[LabletSession]:
        """Find LabletSessions with overlapping timeslots.

        Useful for scheduling and conflict detection.

        Args:
            start: Start of the time window.
            end: End of the time window.
            worker_id: Optional worker filter.

        Returns:
            List of LabletSessions overlapping the time window.
        """

    @abstractmethod
    async def list_expiring_soon_async(self, within_minutes: int = 15) -> list[LabletSession]:
        """Find active LabletSessions expiring within the given window.

        Useful for proactive cleanup and notification.

        Args:
            within_minutes: Minutes until expiration (default 15).

        Returns:
            List of LabletSessions expiring soon.
        """

    @abstractmethod
    async def list_approaching_start_async(self, before: datetime) -> list[LabletSession]:
        """Find SCHEDULED sessions whose timeslot_start is before the given time.

        Used by TimeslotWatcherService to detect sessions that should begin
        instantiation (boot window has opened or will open imminently).

        Args:
            before: Upper bound for timeslot_start (UTC).

        Returns:
            List of SCHEDULED LabletSessions with timeslot_start <= before.
        """

    @abstractmethod
    async def list_past_end_async(self, as_of: datetime) -> list[LabletSession]:
        """Find non-terminal sessions whose timeslot_end has passed.

        Used by TimeslotWatcherService to detect sessions that should
        transition to STOPPING or EXPIRED.

        Args:
            as_of: Reference time (UTC). Sessions with timeslot_end <= as_of
                   are considered past their deadline.

        Returns:
            List of non-terminal LabletSessions past their timeslot_end.
        """

    # --- Reservation Queries ---

    @abstractmethod
    async def get_by_reservation_id_async(self, reservation_id: str) -> LabletSession | None:
        """Retrieve a LabletSession by external reservation ID.

        Args:
            reservation_id: The external reservation reference.

        Returns:
            The LabletSession if found, None otherwise.
        """

    # --- Aggregate Queries ---

    @abstractmethod
    async def count_by_status_async(self, status: LabletSessionStatus) -> int:
        """Count LabletSessions by status.

        Args:
            status: The status to count.

        Returns:
            Count of sessions with the specified status.
        """

    @abstractmethod
    async def get_status_counts_async(self) -> dict[LabletSessionStatus, int]:
        """Get counts for all statuses.

        Useful for dashboard metrics and monitoring.

        Returns:
            Dictionary mapping each status to its count.
        """

    # --- Resource Observation Queries (ADR-030) ---

    @abstractmethod
    async def find_with_observations_async(self, definition_id: str, limit: int = 20) -> list[LabletSession]:
        """Find sessions with resource observations for a given definition.

        Returns sessions that have non-null observed_resources, sorted by
        observed_at descending. Used for aggregating observation data
        across sessions to inform definition resource requirement updates.

        Args:
            definition_id: The LabletDefinition ID to filter by.
            limit: Maximum number of sessions to return (default 20).

        Returns:
            List of LabletSessions with recorded observations.
        """
