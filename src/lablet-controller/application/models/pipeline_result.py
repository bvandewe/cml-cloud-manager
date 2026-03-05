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
        status: Terminal status — "completed", "failed", or "partial".
        steps_completed: Number of steps that finished successfully.
        steps_failed: Number of steps that failed (including optional ones).
        steps_skipped: Number of steps skipped via skip_when evaluation.
        duration_seconds: Wall-clock time for the entire pipeline execution.
        outputs: Resolved output expressions from the pipeline's ``outputs`` section.
        error: Human-readable error message if status is "failed".
    """

    pipeline_name: str
    status: str  # "completed" | "failed" | "partial"
    steps_completed: int = 0
    steps_failed: int = 0
    steps_skipped: int = 0
    duration_seconds: float = 0.0
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    max_retries: int = 0  # From pipeline def, 0 = unlimited
