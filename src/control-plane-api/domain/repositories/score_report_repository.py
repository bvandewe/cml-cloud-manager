"""Abstract repository for ScoreReport entities.

Defines the contract for persisting and querying ScoreReport child entities.
Each ScoreReport is scoped to a parent LabletSession (via GradingSession)
and stored in its own MongoDB collection (``score_reports``).

Phase 7C (ADR-021 §3): New repository for child entity pattern.
ScoreReport is immutable after creation — no ``update_async`` method.
"""

from abc import ABC, abstractmethod

from domain.entities.score_report import ScoreReport


class ScoreReportRepository(ABC):
    """Repository for managing ScoreReport persistence.

    Provides lookups by parent (lablet_session_id), by grading session,
    and aggregate reporting queries.

    ScoreReport is **immutable after creation**: no update_async method.
    Standard CRUD (minus update) is declared here since ScoreReport
    does NOT use the AggregateRoot MotorRepository base class.
    """

    # --- CRUD (minus update — immutable) ---

    @abstractmethod
    async def get_by_id_async(self, report_id: str) -> ScoreReport | None:
        """Retrieve a ScoreReport by its entity ID.

        Args:
            report_id: The unique entity identifier.

        Returns:
            The ScoreReport if found, None otherwise.
        """

    @abstractmethod
    async def add_async(self, entity: ScoreReport) -> None:
        """Persist a new ScoreReport.

        Args:
            entity: The ScoreReport to persist.
        """

    @abstractmethod
    async def delete_async(self, report_id: str) -> bool:
        """Delete a ScoreReport by ID.

        Note: Deletion should be rare — score reports are audit evidence.

        Args:
            report_id: The entity ID to delete.

        Returns:
            True if deleted, False if not found.
        """

    # --- Parent Queries ---

    @abstractmethod
    async def get_by_lablet_session_async(self, lablet_session_id: str) -> ScoreReport | None:
        """Retrieve the ScoreReport for a given LabletSession.

        In the current model, each LabletSession has at most one
        ScoreReport.

        Args:
            lablet_session_id: FK to parent LabletSession.

        Returns:
            The ScoreReport if found, None otherwise.
        """

    @abstractmethod
    async def get_by_grading_session_async(self, grading_session_id: str) -> ScoreReport | None:
        """Retrieve the ScoreReport for a given GradingSession.

        Args:
            grading_session_id: FK to the GradingSession that produced this.

        Returns:
            The ScoreReport if found, None otherwise.
        """

    # --- Bulk Queries ---

    @abstractmethod
    async def list_by_lablet_sessions_async(self, lablet_session_ids: list[str]) -> list[ScoreReport]:
        """Retrieve ScoreReports for multiple LabletSessions.

        Useful for batch loading in list views.

        Args:
            lablet_session_ids: List of parent LabletSession IDs.

        Returns:
            List of ScoreReports matching any of the given parents.
        """

    # --- Reporting Queries ---

    @abstractmethod
    async def list_by_definition_async(self, definition_id: str) -> list[ScoreReport]:
        """Retrieve all ScoreReports for sessions of a given definition.

        Useful for aggregate performance reporting across a lablet definition.

        Note: This requires joining via LabletSession.definition_id.
        Implementation may use an aggregation pipeline.

        Args:
            definition_id: The LabletDefinition ID.

        Returns:
            List of ScoreReports for sessions using that definition.
        """

    @abstractmethod
    async def count_passed_by_definition_async(self, definition_id: str) -> int:
        """Count passed ScoreReports for a given definition.

        Useful for pass-rate metrics on dashboard.

        Args:
            definition_id: The LabletDefinition ID.

        Returns:
            Count of ScoreReports where passed=True.
        """
