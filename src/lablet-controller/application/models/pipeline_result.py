"""Pipeline execution result — returned by PipelineExecutor after a run.

ADR-034: Captures the outcome of executing an entire pipeline DAG,
including per-step completion counts, timing, resolved outputs,
and any terminal error message.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelineResult:
    """Result of executing a single pipeline.

    Attributes:
        pipeline_name: Name of the pipeline that was executed (e.g. "instantiate").
        status: Terminal status — "completed", "failed", "partial", or "suspended".
            "suspended" (Phase 3 / AD-CSI-009) means a Tier-B step delegated to
            the Scenario Engine and the pipeline is paused awaiting a CloudEvent
            callback. ``external_jobs`` carries the outstanding SE job references.
        steps_completed: Number of steps that finished successfully.
        steps_failed: Number of steps that failed (including optional ones).
        steps_skipped: Number of steps skipped via skip_when evaluation.
        steps_suspended: Number of steps that suspended awaiting external completion.
        duration_seconds: Wall-clock time for the entire pipeline execution.
        outputs: Resolved output expressions from the pipeline's ``outputs`` section.
        error: Human-readable error message if status is "failed".
        external_jobs: SE job references created during this run.
            Each entry: ``{"step_name", "external_job_id", "step_correlation_id",
            "suspended_at"}``. Populated when status="suspended".
    """

    pipeline_name: str
    status: str  # "completed" | "failed" | "partial" | "suspended"
    steps_completed: int = 0
    steps_failed: int = 0
    steps_skipped: int = 0
    steps_suspended: int = 0
    duration_seconds: float = 0.0
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    max_retries: int = 0  # From pipeline def, 0 = unlimited
    external_jobs: list[dict[str, Any]] = field(default_factory=list)
