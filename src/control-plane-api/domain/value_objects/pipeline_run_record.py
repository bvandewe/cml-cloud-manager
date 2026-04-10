"""PipelineRunRecord value object for LabRecord aggregate.

Sprint F (ADR-034): Records a single pipeline execution on a LabRecord.
Appended to LabRecordState.pipeline_run_history as an append-only log.

Each lifecycle phase pipeline (instantiate, teardown, collect_evidence,
compute_grading) that completes produces a PipelineRunRecord capturing
the pipeline outcome, timing, step-level results, and provenance.

Architecture ref: ADR-034-next-steps.md §Sprint F.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class PipelineRunRecord:
    """A single pipeline execution record on a LabRecord.

    Attributes:
        run_id: Unique identifier for this pipeline run (UUID).
        pipeline_name: Name of the pipeline (e.g., "instantiate", "teardown").
        started_at: When the pipeline started.
        completed_at: When the pipeline completed (None if still running).
        status: Terminal status ("completed", "failed", "partial").
        step_results: Per-step outcome dict {step_name: {status, duration_seconds, error}}.
        error_message: Pipeline-level error message if status is "failed".
        triggered_by: Who/what triggered the pipeline (e.g., "lablet-controller", "admin").
        lablet_session_id: The LabletSession that owns this pipeline run.
        duration_seconds: Total pipeline duration in seconds (computed).
        steps_completed: Count of successfully completed steps.
        steps_failed: Count of failed steps.
        steps_skipped: Count of skipped steps.
    """

    run_id: str
    pipeline_name: str
    started_at: datetime
    completed_at: datetime | None = None
    status: str = "completed"
    step_results: dict[str, Any] | None = None
    error_message: str | None = None
    triggered_by: str = "lablet-controller"
    lablet_session_id: str | None = None
    duration_seconds: float | None = None
    steps_completed: int = 0
    steps_failed: int = 0
    steps_skipped: int = 0

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id cannot be empty")
        if not self.pipeline_name:
            raise ValueError("pipeline_name cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "run_id": self.run_id,
            "pipeline_name": self.pipeline_name,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
            "step_results": self.step_results,
            "error_message": self.error_message,
            "triggered_by": self.triggered_by,
            "lablet_session_id": self.lablet_session_id,
            "duration_seconds": self.duration_seconds,
            "steps_completed": self.steps_completed,
            "steps_failed": self.steps_failed,
            "steps_skipped": self.steps_skipped,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "PipelineRunRecord":
        """Create from dictionary."""
        started_at_raw = data.get("started_at")
        if isinstance(started_at_raw, str):
            started_at = datetime.fromisoformat(started_at_raw)
        elif isinstance(started_at_raw, datetime):
            started_at = started_at_raw
        else:
            started_at = datetime.now(timezone.utc)

        completed_at_raw = data.get("completed_at")
        completed_at = None
        if isinstance(completed_at_raw, str):
            completed_at = datetime.fromisoformat(completed_at_raw)
        elif isinstance(completed_at_raw, datetime):
            completed_at = completed_at_raw

        return PipelineRunRecord(
            run_id=data["run_id"],
            pipeline_name=data.get("pipeline_name", "unknown"),
            started_at=started_at,
            completed_at=completed_at,
            status=data.get("status", "completed"),
            step_results=data.get("step_results"),
            error_message=data.get("error_message"),
            triggered_by=data.get("triggered_by", "lablet-controller"),
            lablet_session_id=data.get("lablet_session_id"),
            duration_seconds=data.get("duration_seconds"),
            steps_completed=data.get("steps_completed", 0),
            steps_failed=data.get("steps_failed", 0),
            steps_skipped=data.get("steps_skipped", 0),
        )
