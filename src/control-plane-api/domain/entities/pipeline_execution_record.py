"""PipelineExecutionRecord — auditable read model for pipeline runs.

Sprint G (G1): Captures each pipeline execution as a queryable record
for observability and auditing. Stored in the ``pipeline_executions``
MongoDB collection.

Pattern: @dataclass extending Entity[str] — mutable read model (upserted
on pipeline start and updated on completion).

Unlike ScoreReport (immutable), PipelineExecutionRecord is updated during
the pipeline lifecycle: created on start, updated with step progress,
and finalized on completion/failure.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from neuroglia.data import Entity


@dataclass
class PipelineExecutionRecord(Entity[str]):
    """Read model capturing a single pipeline execution run.

    Stored in ``pipeline_executions`` MongoDB collection.
    Upserted by UpdatePipelineProgressCommandHandler on pipeline
    start/completion transitions.

    Attributes — Identity:
        id: Globally unique execution record ID (UUID).
        session_id: FK → parent LabletSession. (Consider renaming to subject_id for more generic read model usage?)
        pipeline_name: Pipeline type (instantiate, teardown, etc.).

    Attributes — Execution State:
        status: Current pipeline status (running, completed, failed, partial).
        steps: Per-step progress snapshots.
        attempt: Pipeline attempt number (incremented on retry).

    Attributes — Timing:
        started_at: When the pipeline execution started.
        completed_at: When the pipeline execution finished (None if running).
        duration_seconds: Wall-clock execution time.

    Attributes — Results:
        outputs: Resolved output expressions from pipeline.
        error: Error message if status is failed.
    """

    # =========================================================================
    # Identity
    # =========================================================================
    id: str = field(default_factory=lambda: str(uuid4()))
    session_id: str = ""
    pipeline_name: str = ""

    # =========================================================================
    # Execution State
    # =========================================================================
    status: str = "running"  # running | completed | failed | partial
    steps: list[dict[str, Any]] = field(default_factory=list)
    attempt: int = 1

    # =========================================================================
    # Timing
    # =========================================================================
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    duration_seconds: float = 0.0

    # =========================================================================
    # Results
    # =========================================================================
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    # =========================================================================
    # Factory
    # =========================================================================

    @staticmethod
    def create(
        session_id: str,
        pipeline_name: str,
        attempt: int = 1,
        steps: list[dict[str, Any]] | None = None,
    ) -> "PipelineExecutionRecord":
        """Create a new PipelineExecutionRecord for a pipeline start.

        Args:
            session_id: FK → parent LabletSession.
            pipeline_name: Pipeline type (e.g. "instantiate").
            attempt: Pipeline attempt number.
            steps: Initial step snapshot (optional).

        Returns:
            A new PipelineExecutionRecord in "running" status.
        """
        return PipelineExecutionRecord(
            id=str(uuid4()),
            session_id=session_id,
            pipeline_name=pipeline_name,
            status="running",
            steps=steps or [],
            attempt=attempt,
            started_at=datetime.now(timezone.utc),
        )

    # =========================================================================
    # Mutations
    # =========================================================================

    def mark_completed(
        self,
        steps: list[dict[str, Any]] | None = None,
        outputs: dict[str, Any] | None = None,
        duration_seconds: float = 0.0,
    ) -> None:
        """Mark the execution as completed.

        Args:
            steps: Final step snapshot.
            outputs: Resolved pipeline outputs.
            duration_seconds: Total execution time.
        """
        self.status = "completed"
        self.completed_at = datetime.now(timezone.utc)
        self.duration_seconds = duration_seconds
        if steps is not None:
            self.steps = steps
        if outputs is not None:
            self.outputs = outputs

    def mark_failed(
        self,
        error: str,
        steps: list[dict[str, Any]] | None = None,
        duration_seconds: float = 0.0,
    ) -> None:
        """Mark the execution as failed.

        Args:
            error: Error message describing the failure.
            steps: Final step snapshot.
            duration_seconds: Total execution time.
        """
        self.status = "failed"
        self.completed_at = datetime.now(timezone.utc)
        self.duration_seconds = duration_seconds
        self.error = error
        if steps is not None:
            self.steps = steps

    def mark_partial(
        self,
        steps: list[dict[str, Any]] | None = None,
        outputs: dict[str, Any] | None = None,
        duration_seconds: float = 0.0,
    ) -> None:
        """Mark the execution as partially completed.

        Args:
            steps: Final step snapshot.
            outputs: Resolved pipeline outputs.
            duration_seconds: Total execution time.
        """
        self.status = "partial"
        self.completed_at = datetime.now(timezone.utc)
        self.duration_seconds = duration_seconds
        if steps is not None:
            self.steps = steps
        if outputs is not None:
            self.outputs = outputs

    def update_steps(self, steps: list[dict[str, Any]]) -> None:
        """Update the step progress snapshot.

        Args:
            steps: Current step progress data.
        """
        self.steps = steps

    # =========================================================================
    # Serialization helpers
    # =========================================================================

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for API responses."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "pipeline_name": self.pipeline_name,
            "status": self.status,
            "steps": self.steps,
            "attempt": self.attempt,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "outputs": self.outputs,
            "error": self.error,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "PipelineExecutionRecord":
        """Deserialize from a dict (e.g. MongoDB document).

        Args:
            data: Dictionary with PipelineExecutionRecord fields.

        Returns:
            A PipelineExecutionRecord instance.
        """
        started_at = data.get("started_at")
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)
        elif not isinstance(started_at, datetime):
            started_at = datetime.now(timezone.utc)

        completed_at = data.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at)
        elif not isinstance(completed_at, datetime):
            completed_at = None

        return PipelineExecutionRecord(
            id=data.get("id", str(uuid4())),
            session_id=data.get("session_id", ""),
            pipeline_name=data.get("pipeline_name", ""),
            status=data.get("status", "running"),
            steps=data.get("steps", []),
            attempt=data.get("attempt", 1),
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=data.get("duration_seconds", 0.0),
            outputs=data.get("outputs", {}),
            error=data.get("error"),
        )
