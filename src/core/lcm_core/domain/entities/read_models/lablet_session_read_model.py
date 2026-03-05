"""Read model for LabletSession entities.

Immutable DTO used by controllers, schedulers, and the lablet-controller
to represent the current state of a LabletSession without requiring the
full aggregate reconstruction.

Renamed from LabletInstanceReadModel → LabletSessionReadModel in Phase 7A.
Changes from LabletInstance read model:
  - Renamed: lds_session_id → user_session_id, lds_login_url → user_login_url
  - Added: grading_session_id, score_report_id (child entity FKs per ADR-021)
  - Added: lab_record_id, allocated_ports, started_at, ended_at (absorbed from LabletRecordRun per ADR-020)

Backward-compatible aliases (Phase 7B — will be removed in Phase 7C):
  - lds_session_id: Accepted in constructor, mapped to user_session_id
  - lds_login_url: Accepted in constructor, mapped to user_login_url
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class LabletSessionReadModel:
    """Read model for a LabletSession from the Control Plane API.

    Used by:
    - resource-scheduler: For placement decisions (needs worker_id, status)
    - lablet-controller: For lab lifecycle management (needs CML-related fields)
    - frontend: For session display (needs status, user_login_url)

    All fields are optional except id, name, definition_id, status which are always present.
    """

    # Core identity (always present)
    id: str
    name: str
    definition_id: str
    status: str

    # Worker assignment
    worker_id: str | None = None
    worker_ip: str | None = None
    worker_aws_region: str | None = None  # AWS region for LDS deployment selection
    worker_cml_username: str | None = None
    worker_cml_password: str | None = None

    # Lab binding (absorbed from LabletLabBinding — ADR-020 §2)
    lab_record_id: str | None = None  # Direct 1:1 FK (was via LabletLabBinding)
    cml_lab_id: str | None = None  # CML lab identifier on worker

    # Scheduling (matches domain entity field names)
    timeslot_start: datetime | None = None
    timeslot_end: datetime | None = None

    # Port allocation (absorbed from LabletRecordRun — ADR-020 §2)
    allocated_ports: dict[str, int] = field(default_factory=dict)

    # Instantiation pipeline progress (ADR-031)
    # Serialized InstantiationProgress dict from CPA. Contains:
    #   steps: list[StepResult], started_at, current_step, completed_at, pipeline_version
    # The lablet-controller reads this to resume the pipeline after restart;
    # the frontend reads it to render step-level progress indicators.
    instantiation_progress: dict[str, Any] | None = None

    # Runtime tracking (absorbed from LabletRecordRun — ADR-020 §2)
    started_at: datetime | None = None  # When RUNNING state entered
    ended_at: datetime | None = None  # When session completed

    # Lab topology
    topology_yaml: str | None = None
    metadata: dict[str, Any] | None = None

    # Child entity FKs (ADR-021)
    user_session_id: str | None = None  # → UserSession
    grading_session_id: str | None = None  # → GradingSession
    score_report_id: str | None = None  # → ScoreReport

    # Denormalized from UserSession (write-once, AD-P7-06)
    user_login_url: str | None = None  # URL for user to access the lab

    # Backward-compatible aliases (Phase 7B — will be removed in Phase 7C)
    lds_session_id: str | None = None  # DEPRECATED: use user_session_id
    lds_login_url: str | None = None  # DEPRECATED: use user_login_url

    def __post_init__(self) -> None:
        """Map deprecated field names to their new equivalents."""
        # If old name provided but new name not set, copy old → new
        if self.lds_session_id and not self.user_session_id:
            self.user_session_id = self.lds_session_id
        # If new name set but old name not, copy new → old (for backward compat reads)
        if self.user_session_id and not self.lds_session_id:
            self.lds_session_id = self.user_session_id

        if self.lds_login_url and not self.user_login_url:
            self.user_login_url = self.lds_login_url
        if self.user_login_url and not self.lds_login_url:
            self.lds_login_url = self.user_login_url

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LabletSessionReadModel":
        """Create from API response dictionary.

        Handles nested 'worker' object for worker-related fields.
        """
        # Extract worker info if available
        worker_data = data.get("worker", {}) or {}

        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            definition_id=data.get("definition_id", ""),
            status=data.get("status", ""),
            worker_id=data.get("worker_id"),
            worker_ip=worker_data.get("ip_address") or data.get("worker_ip"),
            worker_aws_region=worker_data.get("aws_region") or data.get("worker_aws_region"),
            worker_cml_username=worker_data.get("cml_username") or data.get("worker_cml_username"),
            worker_cml_password=worker_data.get("cml_password") or data.get("worker_cml_password"),
            lab_record_id=data.get("lab_record_id"),
            cml_lab_id=data.get("cml_lab_id"),
            timeslot_start=data.get("timeslot_start"),
            timeslot_end=data.get("timeslot_end"),
            allocated_ports=data.get("allocated_ports", {}),
            instantiation_progress=data.get("instantiation_progress"),
            started_at=data.get("started_at"),
            ended_at=data.get("ended_at"),
            topology_yaml=data.get("topology_yaml"),
            metadata=data.get("metadata"),
            user_session_id=data.get("user_session_id") or data.get("lds_session_id"),
            grading_session_id=data.get("grading_session_id"),
            score_report_id=data.get("score_report_id"),
            user_login_url=data.get("user_login_url") or data.get("lds_login_url"),
        )
