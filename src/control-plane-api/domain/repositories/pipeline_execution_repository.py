"""Abstract repository for PipelineExecutionRecord entities.

Sprint G (G1): Defines the contract for persisting and querying pipeline
execution records — the auditable read model for pipeline runs.

Each record is scoped to a parent LabletSession and pipeline_name,
stored in the ``pipeline_executions`` MongoDB collection.

Pattern: Hand-written ABC (child entity — not AggregateRoot).
"""

from abc import ABC, abstractmethod

from domain.entities.pipeline_execution_record import PipelineExecutionRecord


class PipelineExecutionRepository(ABC):
    """Repository for managing PipelineExecutionRecord persistence.

    Provides CRUD operations and query methods for pipeline execution
    history, scoped by session and pipeline name.
    """

    # --- CRUD ---

    @abstractmethod
    async def get_by_id_async(self, record_id: str) -> PipelineExecutionRecord | None:
        """Retrieve a PipelineExecutionRecord by its entity ID.

        Args:
            record_id: The unique entity identifier.

        Returns:
            The record if found, None otherwise.
        """

    @abstractmethod
    async def add_async(self, entity: PipelineExecutionRecord) -> None:
        """Persist a new PipelineExecutionRecord.

        Args:
            entity: The record to persist.
        """

    @abstractmethod
    async def update_async(self, entity: PipelineExecutionRecord) -> None:
        """Update an existing PipelineExecutionRecord.

        Args:
            entity: The record to update (matched by id).
        """

    @abstractmethod
    async def upsert_async(self, entity: PipelineExecutionRecord) -> None:
        """Insert or update a PipelineExecutionRecord.

        Uses a compound key of (session_id, pipeline_name, attempt) for
        upsert matching. Creates a new record if none exists, otherwise
        updates the existing one.

        Args:
            entity: The record to upsert.
        """

    @abstractmethod
    async def delete_async(self, record_id: str) -> bool:
        """Delete a PipelineExecutionRecord by ID.

        Args:
            record_id: The entity ID to delete.

        Returns:
            True if deleted, False if not found.
        """

    # --- Session Queries ---

    @abstractmethod
    async def get_by_session_async(self, session_id: str) -> list[PipelineExecutionRecord]:
        """Retrieve all execution records for a session.

        Args:
            session_id: FK to parent LabletSession.

        Returns:
            List of records ordered by started_at descending.
        """

    @abstractmethod
    async def get_by_session_and_pipeline_async(self, session_id: str, pipeline_name: str) -> list[PipelineExecutionRecord]:
        """Retrieve execution records for a specific pipeline on a session.

        Args:
            session_id: FK to parent LabletSession.
            pipeline_name: Pipeline type (e.g. "instantiate").

        Returns:
            List of records ordered by started_at descending.
        """

    @abstractmethod
    async def get_latest_by_session_and_pipeline_async(self, session_id: str, pipeline_name: str) -> PipelineExecutionRecord | None:
        """Retrieve the most recent execution for a session+pipeline.

        Args:
            session_id: FK to parent LabletSession.
            pipeline_name: Pipeline type.

        Returns:
            The most recent record, or None if no executions exist.
        """

    @abstractmethod
    async def get_running_by_session_async(self, session_id: str) -> list[PipelineExecutionRecord]:
        """Retrieve all currently running executions for a session.

        Args:
            session_id: FK to parent LabletSession.

        Returns:
            List of records with status="running".
        """
