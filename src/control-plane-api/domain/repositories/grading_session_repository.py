"""Abstract repository for GradingSession entities.

Defines the contract for persisting and querying GradingSession child entities.
Each GradingSession is scoped to a parent LabletSession and stored in its own
MongoDB collection (``grading_sessions``).

Phase 7C (ADR-021 §2): New repository for child entity pattern.
"""

from abc import ABC, abstractmethod

from domain.entities.grading_session import GradingSession


class GradingSessionRepository(ABC):
    """Repository for managing GradingSession persistence.

    Provides lookups by parent (lablet_session_id) and by
    Grading-Engine external reference (grading_session_id).

    Standard CRUD operations are declared here since GradingSession
    does NOT use the AggregateRoot MotorRepository base class.
    """

    # --- CRUD ---

    @abstractmethod
    async def get_by_id_async(self, session_id: str) -> GradingSession | None:
        """Retrieve a GradingSession by its entity ID.

        Args:
            session_id: The unique entity identifier.

        Returns:
            The GradingSession if found, None otherwise.
        """

    @abstractmethod
    async def add_async(self, entity: GradingSession) -> None:
        """Persist a new GradingSession.

        Args:
            entity: The GradingSession to persist.
        """

    @abstractmethod
    async def update_async(self, entity: GradingSession) -> None:
        """Update an existing GradingSession.

        Args:
            entity: The GradingSession to update.
        """

    @abstractmethod
    async def delete_async(self, session_id: str) -> bool:
        """Delete a GradingSession by ID.

        Args:
            session_id: The entity ID to delete.

        Returns:
            True if deleted, False if not found.
        """

    # --- Parent Queries ---

    @abstractmethod
    async def get_by_lablet_session_async(self, lablet_session_id: str) -> GradingSession | None:
        """Retrieve the GradingSession for a given LabletSession.

        In the current model, each LabletSession has at most one
        active GradingSession.

        Args:
            lablet_session_id: FK to parent LabletSession.

        Returns:
            The GradingSession if found, None otherwise.
        """

    # --- External Reference Queries ---

    @abstractmethod
    async def get_by_grading_session_id_async(self, grading_session_id: str) -> GradingSession | None:
        """Retrieve a GradingSession by its external Grading-Engine reference.

        Useful for correlating Grading-Engine CloudEvents to the internal entity.

        Args:
            grading_session_id: External grading session identifier.

        Returns:
            The GradingSession if found, None otherwise.
        """

    # --- Bulk Queries ---

    @abstractmethod
    async def list_by_lablet_sessions_async(self, lablet_session_ids: list[str]) -> list[GradingSession]:
        """Retrieve GradingSessions for multiple LabletSessions.

        Useful for batch loading in list views.

        Args:
            lablet_session_ids: List of parent LabletSession IDs.

        Returns:
            List of GradingSessions matching any of the given parents.
        """
