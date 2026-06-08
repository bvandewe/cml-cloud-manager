"""Step Handler Registry — decorator-based registration for pipeline step handlers.

ADR-038: Replaces ``getattr(reconciler, f"_step_{handler_name}")`` with a
module-level registry populated via ``@step_handler`` decorator side-effects.

Step handlers are standalone async functions that follow a uniform protocol:

    @step_handler("content_sync")
    async def step_content_sync(
        instance: LabletSessionReadModel,
        progress: dict[str, Any],
        context: PipelineContext,
        params: dict[str, Any] | None = None,
    ) -> StepResult:
        ...

The registry is populated when handler modules are imported. The reconciler
imports the ``step_handlers`` package to trigger registration, then builds
a dispatcher that resolves handlers from the registry.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# StepResult — standardized return type for step handlers
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    """Standardized result from a pipeline step handler.

    Replaces the ad-hoc ``{"step": ..., "status": ..., "result_data": {...}}``
    dicts that step handlers currently return. The executor unwraps this
    into the existing progress format.

    Attributes:
        status: Step outcome — "completed", "skipped", "failed", or "suspended".
        result_data: Payload available to downstream steps via ``context.steps_data``.
        error: Human-readable error message (when status="failed").
        reason: Explanation for skip / suspension.
        external_job_id: SE Job id when status="suspended" (AD-CSI-009 / Phase 3).
        step_correlation_id: Echo identifier used to match the CloudEvent
            callback back to this suspended step (AD-CSI-016 / Phase 3).
    """

    status: str  # "completed" | "skipped" | "failed" | "suspended"
    result_data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    reason: str | None = None
    external_job_id: str | None = None
    step_correlation_id: str | None = None

    @staticmethod
    def completed(result_data: dict[str, Any] | None = None) -> StepResult:
        """Create a successful step result."""
        return StepResult(status="completed", result_data=result_data or {})

    @staticmethod
    def skipped(reason: str = "") -> StepResult:
        """Create a skipped step result."""
        return StepResult(status="skipped", reason=reason)

    @staticmethod
    def failed(error: str) -> StepResult:
        """Create a failed step result."""
        return StepResult(status="failed", error=error)

    @staticmethod
    def suspended(
        *,
        external_job_id: str,
        step_correlation_id: str,
        reason: str | None = None,
    ) -> StepResult:
        """Create a suspended step result — pipeline pauses awaiting external completion.

        AD-CSI-009 / Phase 3: Tier-B step handlers (those that delegate to the
        Scenario Engine) return ``StepResult.suspended(...)`` after submitting an
        SE Job. The :class:`PipelineExecutor` persists progress and halts dispatch;
        resumption is driven by a CloudEvent callback received by
        ``lablet-controller``'s ``events_controller`` (AD-CSI-016).

        Args:
            external_job_id: SE Job id used by the events_controller to locate
                the suspended step on the ``PipelineExecutionRecord``.
            step_correlation_id: Stable per-suspension identifier echoed on the
                CloudEvent to defend against duplicate or misrouted callbacks.
            reason: Optional human-readable note (defaults to a templated string).
        """
        return StepResult(
            status="suspended",
            external_job_id=external_job_id,
            step_correlation_id=step_correlation_id,
            reason=reason or f"awaiting external job {external_job_id}",
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to the legacy dict format expected by the executor.

        Returns the same shape as the old _step_* methods:
        ``{"step": <name>, "status": ..., "result_data": {...}, "error": ...}``

        Note: ``step`` name is NOT set here — the caller (dispatcher) adds it.

        Suspended results also carry ``external_job_id`` and
        ``step_correlation_id`` so the executor can persist them on the
        progress record.
        """
        result: dict[str, Any] = {"status": self.status}
        if self.result_data:
            result["result_data"] = self.result_data
        if self.error:
            result["error"] = self.error
        if self.reason:
            result["reason"] = self.reason
        if self.external_job_id:
            result["external_job_id"] = self.external_job_id
        if self.step_correlation_id:
            result["step_correlation_id"] = self.step_correlation_id
        return result


# ---------------------------------------------------------------------------
# Handler type alias
# ---------------------------------------------------------------------------

StepHandlerFn = Callable[
    [LabletSessionReadModel, dict[str, Any], PipelineContext, dict[str, Any] | None],
    Awaitable[StepResult],
]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, StepHandlerFn] = {}


def step_handler(name: str) -> Callable[[StepHandlerFn], StepHandlerFn]:
    """Decorator to register a step handler function by name.

    Usage::

        @step_handler("content_sync")
        async def step_content_sync(instance, progress, context, params=None):
            ...
            return StepResult.completed({"key": "value"})

    Args:
        name: The handler name as referenced in pipeline YAML ``handler`` fields.

    Returns:
        Decorator that registers the function and returns it unchanged.
    """

    def decorator(fn: StepHandlerFn) -> StepHandlerFn:
        if name in _HANDLERS:
            logger.warning("Step handler '%s' registered twice — overwriting previous registration", name)
        _HANDLERS[name] = fn
        return fn

    return decorator


def get_handler(name: str) -> StepHandlerFn | None:
    """Look up a registered step handler by name.

    Args:
        name: Handler name (e.g. "content_sync", "lab_start").

    Returns:
        The handler function, or None if not registered.
    """
    return _HANDLERS.get(name)


def get_all_handlers() -> dict[str, StepHandlerFn]:
    """Return a copy of the full handler registry (for introspection/testing)."""
    return dict(_HANDLERS)


def clear_registry() -> None:
    """Clear all registered handlers (for testing only)."""
    _HANDLERS.clear()
