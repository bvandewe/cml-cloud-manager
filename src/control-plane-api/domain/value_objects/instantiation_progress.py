"""InstantiationProgress value object — checkpoint-based pipeline state.

ADR-031: Checkpoint-Based Instantiation Pipeline.
Tracks the progress of a LabletSession through its instantiation pipeline.

Each step declares its prerequisites (DAG, not flat list). The
``next_executable_step()`` method resolves the next step whose
prerequisites are all satisfied (completed or skipped).

Pipeline steps (9 total):
  content_sync → variables → lab_resolve → ports_alloc → tags_sync →
  lab_binding → lab_start → lds_provision → mark_ready

See docs/implementation/instantiation-pipeline.md §2.2 for the full
step dependency graph and gate conditions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class StepResult:
    """Result of a single pipeline step.

    Each step tracks its own status, prerequisites, timing, and
    retry count. ``result_data`` carries step-specific evidence
    (e.g., ``{"cml_lab_id": "..."}`` for lab_resolve).
    """

    step: str
    status: str = "pending"  # "pending" | "completed" | "failed" | "skipped"
    requires: list[str] = field(default_factory=list)
    completed_at: datetime | None = None
    result_data: dict[str, Any] | None = None
    error: str | None = None
    attempt_count: int = 0

    # ── Serialization ───────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for MongoDB / JSON."""
        return {
            "step": self.step,
            "status": self.status,
            "requires": list(self.requires),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result_data": self.result_data,
            "error": self.error,
            "attempt_count": self.attempt_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StepResult:
        """Deserialize from a dict."""
        completed_at = data.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at)
        return cls(
            step=data["step"],
            status=data.get("status", "pending"),
            requires=data.get("requires", []),
            completed_at=completed_at,
            result_data=data.get("result_data"),
            error=data.get("error"),
            attempt_count=data.get("attempt_count", 0),
        )


@dataclass
class InstantiationProgress:
    """Tracks the instantiation pipeline state for a LabletSession.

    The pipeline is a DAG of steps, each with explicit prerequisites.
    ``next_executable_step()`` resolves which step to execute next by
    checking whether all prerequisites are satisfied.

    Stored as ``instantiation_progress`` on ``LabletSessionState``
    (serialized via ``to_dict()``/``from_dict()``).
    """

    steps: list[StepResult] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    current_step: str | None = None
    completed_at: datetime | None = None
    pipeline_version: str = "1.0"

    # ── Pipeline inspection ─────────────────────────────────────────

    @property
    def is_complete(self) -> bool:
        """True when every step is completed or skipped."""
        return bool(self.steps) and all(s.status in ("completed", "skipped") for s in self.steps)

    @property
    def has_failures(self) -> bool:
        """True when at least one step has failed."""
        return any(s.status == "failed" for s in self.steps)

    @property
    def completed_step_count(self) -> int:
        """Number of steps that are completed or skipped."""
        return sum(1 for s in self.steps if s.status in ("completed", "skipped"))

    @property
    def total_step_count(self) -> int:
        """Total number of steps in the pipeline."""
        return len(self.steps)

    def next_executable_step(self) -> StepResult | None:
        """Find the next step whose prerequisites are all satisfied.

        A step is executable when:
        1. Its status is ``"pending"`` (not completed/failed/skipped)
        2. All prerequisite steps are ``"completed"`` or ``"skipped"``

        Returns:
            The next executable ``StepResult``, or ``None`` if no step
            is ready (pipeline complete or blocked by failures).
        """
        satisfied = {s.step for s in self.steps if s.status in ("completed", "skipped")}
        for step in self.steps:
            if step.status == "pending" and all(r in satisfied for r in step.requires):
                return step
        return None

    def get_step(self, name: str) -> StepResult | None:
        """Look up a step by name."""
        return next((s for s in self.steps if s.step == name), None)

    # ── Mutation helpers (called by command handlers) ───────────────

    def complete_step(self, name: str, result_data: dict[str, Any] | None = None) -> None:
        """Mark a step as completed with optional result data."""
        step = self.get_step(name)
        if step:
            step.status = "completed"
            step.completed_at = datetime.now(timezone.utc)
            step.result_data = result_data
            step.attempt_count += 1
            self.current_step = None
            # Check if pipeline is complete
            if self.is_complete:
                self.completed_at = datetime.now(timezone.utc)

    def fail_step(self, name: str, error: str) -> None:
        """Mark a step as failed with an error message."""
        step = self.get_step(name)
        if step:
            step.status = "failed"
            step.error = error
            step.attempt_count += 1
            self.current_step = None

    def skip_step(self, name: str, reason: str | None = None) -> None:
        """Mark a step as skipped."""
        step = self.get_step(name)
        if step:
            step.status = "skipped"
            step.completed_at = datetime.now(timezone.utc)
            step.error = reason
            self.current_step = None

    def reset_step(self, name: str) -> None:
        """Reset a failed step back to pending for retry."""
        step = self.get_step(name)
        if step and step.status == "failed":
            step.status = "pending"
            step.error = None

    def mark_in_progress(self, name: str) -> None:
        """Mark a step as currently executing."""
        self.current_step = name

    # ── Serialization ───────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for MongoDB / JSON."""
        return {
            "steps": [s.to_dict() for s in self.steps],
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "current_step": self.current_step,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "pipeline_version": self.pipeline_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InstantiationProgress:
        """Deserialize from a dict."""
        started_at = data.get("started_at")
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)
        elif started_at is None:
            started_at = datetime.now(timezone.utc)

        completed_at = data.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at)

        return cls(
            steps=[StepResult.from_dict(s) for s in data.get("steps", [])],
            started_at=started_at,
            current_step=data.get("current_step"),
            completed_at=completed_at,
            pipeline_version=data.get("pipeline_version", "1.0"),
        )

    # ── Factory ─────────────────────────────────────────────────────

    @classmethod
    def build_default(
        cls,
        has_port_template: bool = False,
        has_content_sync: bool = False,
        has_lds: bool = False,
    ) -> InstantiationProgress:
        """Build the default 9-step pipeline.

        Steps are pre-skipped based on the definition's capabilities:
        - ``content_sync``: skipped if ``has_content_sync`` is False
        - ``variables``: always skipped (placeholder for future)
        - ``ports_alloc`` / ``tags_sync``: skipped if no port template
        - ``lds_provision``: skipped if no LDS form qualified name

        Args:
            has_port_template: Definition has a port_template.
            has_content_sync: Definition has content_sync_enabled.
            has_lds: Definition has a form_qualified_name.

        Returns:
            A new InstantiationProgress with 9 steps.
        """
        return cls(
            steps=[
                StepResult(
                    step="content_sync",
                    requires=[],
                    status="pending" if has_content_sync else "skipped",
                ),
                StepResult(
                    step="variables",
                    requires=[],
                    status="skipped",  # placeholder
                ),
                StepResult(
                    step="lab_resolve",
                    requires=["content_sync", "variables"],
                    status="pending",
                ),
                StepResult(
                    step="ports_alloc",
                    requires=["lab_resolve"],
                    status="pending" if has_port_template else "skipped",
                ),
                StepResult(
                    step="tags_sync",
                    requires=["ports_alloc"],
                    status="pending" if has_port_template else "skipped",
                ),
                StepResult(
                    step="lab_binding",
                    requires=["lab_resolve", "tags_sync"],
                    status="pending",
                ),
                StepResult(
                    step="lab_start",
                    requires=["lab_binding"],
                    status="pending",
                ),
                StepResult(
                    step="lds_provision",
                    requires=["lab_start"],
                    status="pending" if has_lds else "skipped",
                ),
                StepResult(
                    step="mark_ready",
                    requires=["lds_provision"],
                    status="pending",
                ),
            ],
            started_at=datetime.now(timezone.utc),
            current_step=None,
            completed_at=None,
            pipeline_version="1.0",
        )
