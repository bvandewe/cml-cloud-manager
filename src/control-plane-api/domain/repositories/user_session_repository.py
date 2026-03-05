"""Abstract repository for UserSession entities.

Defines the contract for persisting and querying UserSession child entities.
Each UserSession is scoped to a parent LabletSession and stored in its own
MongoDB collection (``user_sessions``).

Phase 7C (ADR-021 §1): New repository for child entity pattern.
"""

from abc import ABC, abstractmethod

from domain.entities.user_session import UserSession


class UserSessionRepository(ABC):
    """Repository for managing UserSession persistence.

    Provides lookups by parent (lablet_session_id) and by
    LDS external reference (lds_session_id).

    Standard CRUD operations are declared here since UserSession
    does NOT use the AggregateRoot MotorRepository base class.
    """

    # --- CRUD ---

    @abstractmethod
    async def get_by_id_async(self, session_id: str) -> UserSession | None:
        """Retrieve a UserSession by its entity ID.

        Args:
            session_id: The unique entity identifier.

        Returns:
            The UserSession if found, None otherwise.
        """

    @abstractmethod
    async def add_async(self, entity: UserSession) -> None:
        """Persist a new UserSession.

        Args:
            entity: The UserSession to persist.
        """

    @abstractmethod
    async def update_async(self, entity: UserSession) -> None:
        """Update an existing UserSession.

        Args:
            entity: The UserSession to update.
        """

    @abstractmethod
    async def delete_async(self, session_id: str) -> bool:
        """Delete a UserSession by ID.

        Args:
            session_id: The entity ID to delete.

        Returns:
            True if deleted, False if not found.
        """

    # --- Parent Queries ---

    @abstractmethod
    async def get_by_lablet_session_async(self, lablet_session_id: str) -> UserSession | None:
        """Retrieve the UserSession for a given LabletSession.

        In the current model, each LabletSession has at most one
        active UserSession.

        Args:
            lablet_session_id: FK to parent LabletSession.

        Returns:
            The UserSession if found, None otherwise.
        """

    # --- External Reference Queries ---

    @abstractmethod
    async def get_by_lds_session_async(self, lds_session_id: str) -> UserSession | None:
        """Retrieve a UserSession by its LDS session reference.

        Useful for correlating LDS CloudEvents to the internal entity.

        Args:
            lds_session_id: External LDS session identifier.

        Returns:
            The UserSession if found, None otherwise.
        """

    # --- Bulk Queries ---

    @abstractmethod
    async def list_by_lablet_sessions_async(self, lablet_session_ids: list[str]) -> list[UserSession]:
        """Retrieve UserSessions for multiple LabletSessions.

        Useful for batch loading in list views.

        Args:
            lablet_session_ids: List of parent LabletSession IDs.

        Returns:
            List of UserSessions matching any of the given parents.
        """
