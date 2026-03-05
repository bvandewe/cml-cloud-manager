"""LabRunRecord value object for LabRecord aggregate.

Records a single start→stop execution cycle of a lab.
Maintained as a bounded list on LabRecordState for quick access.

Architecture ref: §4.1 Value Objects.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class LabRunRecord:
    """A single execution cycle (start → stop) of a lab.

    Attributes:
        run_id: Unique identifier for this run (UUID).
        started_at: When the lab was started.
        stopped_at: When the lab was stopped (None if still running).
        duration_seconds: Calculated duration (None if still running).
        started_by: Who/what started the lab (e.g., "reconciler", "user:admin").
        stop_reason: Why the lab was stopped (e.g., "timeslot_end", "user_request", "error").
        lablet_session_id: The LabletSession that triggered this run (if any).
        final_state: The lab state at the end of the run (e.g., "stopped", "wiped").
    """

    run_id: str
    started_at: datetime
    stopped_at: datetime | None = None
    duration_seconds: int | None = None
    started_by: str = "system"
    stop_reason: str | None = None
    lablet_session_id: str | None = None
    final_state: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id cannot be empty")

    @property
    def is_running(self) -> bool:
        """Return True if this run is still active (no stop time)."""
        return self.stopped_at is None

    @property
    def calculated_duration_seconds(self) -> int:
        """Calculate duration, using current time if still running."""
        end_time = self.stopped_at or datetime.now(timezone.utc)
        return int((end_time - self.started_at).total_seconds())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
            "duration_seconds": self.duration_seconds,
            "started_by": self.started_by,
            "stop_reason": self.stop_reason,
            "lablet_session_id": self.lablet_session_id,
            "final_state": self.final_state,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "LabRunRecord":
        """Create from dictionary."""
        started_at_raw = data.get("started_at")
        if isinstance(started_at_raw, str):
            started_at = datetime.fromisoformat(started_at_raw)
        elif isinstance(started_at_raw, datetime):
            started_at = started_at_raw
        else:
            started_at = datetime.now(timezone.utc)

        stopped_at_raw = data.get("stopped_at")
        stopped_at = None
        if isinstance(stopped_at_raw, str):
            stopped_at = datetime.fromisoformat(stopped_at_raw)
        elif isinstance(stopped_at_raw, datetime):
            stopped_at = stopped_at_raw

        return LabRunRecord(
            run_id=data["run_id"],
            started_at=started_at,
            stopped_at=stopped_at,
            duration_seconds=data.get("duration_seconds"),
            started_by=data.get("started_by", "system"),
            stop_reason=data.get("stop_reason"),
            lablet_session_id=data.get("lablet_session_id", data.get("lablet_instance_id")),
            final_state=data.get("final_state"),
        )
