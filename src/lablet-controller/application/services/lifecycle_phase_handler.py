"""Lifecycle Phase Handler — managed asyncio.Task wrapper for pipeline execution.

ADR-034 §2: Each lifecycle phase that involves multi-step work gets a
LifecyclePhaseHandler — a managed asyncio.Task that self-drives the pipeline
for a specific session.

Key design decisions (AD-PIPELINE-007):
- Handler does NOT auto-terminate on pipeline failure — it stores the result
  and lets the reconciler decide (retry or terminate based on max_retries).
- _on_complete handles success/partial by triggering status transition.
- _on_error logs the exception at ERROR level but does not auto-terminate.

Usage::

    handler = LifecyclePhaseHandler(
        session_id="sess-001",
        pipeline_name="instantiate",
        pipeline_def=pipeline_def,
        context=pipeline_context,
        executor=pipeline_executor,
        step_dispatcher=reconciler_dispatch_fn,
    )
    await handler.start()
    # ... later, in reconciler ...
    if not handler.is_running:
        result = handler.result  # PipelineResult or None
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from application.models.pipeline_context import PipelineContext
    from application.models.pipeline_result import PipelineResult
    from application.services.pipeline_executor import PipelineExecutor, StepDispatcher

logger = logging.getLogger(__name__)


class LifecyclePhaseHandler:
    """Manages pipeline execution for one session in one lifecycle phase.

    Wraps an asyncio.Task that runs PipelineExecutor.execute() to completion.
    The reconciler manages handler instances via a dict[str, LifecyclePhaseHandler]
    and checks is_running / result on each reconciliation cycle.

    Attributes:
        session_id: The session being processed.
        pipeline_name: Name of the pipeline (e.g. "instantiate", "teardown").

    Class attributes:
        _registry: AD-CSI-016 — in-process registry keyed by ``session_id`` so
            the ``events_controller`` can route CloudEvent callbacks back to the
            handler whose pipeline has a suspended step. Only one active handler
            per session is supported today (a session participates in at most
            one pipeline at a time).
    """

    _registry: ClassVar[dict[str, LifecyclePhaseHandler]] = {}

    # ------------------------------------------------------------------
    # Class-level registry (AD-CSI-016)
    # ------------------------------------------------------------------

    @classmethod
    def lookup(cls, session_id: str) -> LifecyclePhaseHandler | None:
        """Return the registered handler for ``session_id`` (or None).

        Used by ``events_controller`` to route SE CloudEvent callbacks to the
        correct in-process handler when its pipeline is suspended.
        """
        return cls._registry.get(session_id)

    @classmethod
    def _register(cls, handler: LifecyclePhaseHandler) -> None:
        cls._registry[handler.session_id] = handler
        logger.debug(
            "LifecyclePhaseHandler registered for session=%s pipeline=%s (registry_size=%d)",
            handler.session_id,
            handler.pipeline_name,
            len(cls._registry),
        )

    @classmethod
    def _unregister(cls, session_id: str) -> None:
        if cls._registry.pop(session_id, None) is not None:
            logger.debug(
                "LifecyclePhaseHandler unregistered for session=%s (registry_size=%d)",
                session_id,
                len(cls._registry),
            )

    def __init__(
        self,
        session_id: str,
        pipeline_name: str,
        pipeline_def: dict[str, Any],
        context: PipelineContext,
        executor: PipelineExecutor,
        step_dispatcher: StepDispatcher,
        existing_progress: dict[str, Any] | None = None,
        on_complete: Callable[[PipelineResult], Any] | None = None,
        on_error: Callable[[Exception], Any] | None = None,
    ) -> None:
        """Initialize the lifecycle phase handler.

        Args:
            session_id: ID of the session being processed.
            pipeline_name: Name of the pipeline (e.g. "instantiate").
            pipeline_def: Pipeline definition dict from YAML.
            context: PipelineContext with session, definition, services.
            executor: PipelineExecutor instance to run the DAG.
            step_dispatcher: Async callable mapping handler names to step functions.
            existing_progress: Optional progress from a previous run for resumability.
            on_complete: Optional callback invoked with PipelineResult on success/failure.
            on_error: Optional callback invoked with Exception on unhandled errors.
        """
        self.session_id = session_id
        self.pipeline_name = pipeline_name
        self._pipeline_def = pipeline_def
        self._context = context
        self._executor = executor
        self._step_dispatcher = step_dispatcher
        self._existing_progress = existing_progress
        self._on_complete_cb = on_complete
        self._on_error_cb = on_error
        self._task: asyncio.Task | None = None
        self._result: PipelineResult | None = None
        self._error: Exception | None = None
        self._pipeline_attempt: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the handler as a background asyncio.Task.

        Idempotent — if a task is already running, this is a no-op.
        Increments the pipeline_attempt counter on each start. Also registers
        the handler in the class-level registry (AD-CSI-016) so SE CloudEvent
        callbacks can route resumption signals back to this instance.
        """
        if self._task and not self._task.done():
            return  # Already running — idempotent
        self._pipeline_attempt += 1
        self._result = None
        self._error = None
        self._register(self)
        self._task = asyncio.create_task(
            self._run(),
            name=f"pipeline:{self.pipeline_name}:{self.session_id}",
        )

    async def stop(self) -> None:
        """Cancel the handler gracefully.

        Cancels the asyncio.Task and awaits its completion. Catches
        CancelledError to ensure clean shutdown.
        """
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._unregister(self.session_id)

    @property
    def is_running(self) -> bool:
        """True if the background task exists and has not finished."""
        return self._task is not None and not self._task.done()

    @property
    def result(self) -> PipelineResult | None:
        """Pipeline result if the task completed, else None."""
        return self._result

    @property
    def error(self) -> Exception | None:
        """Unhandled exception if the task crashed, else None."""
        return self._error

    @property
    def pipeline_attempt(self) -> int:
        """Number of times start() has been called on this handler."""
        return self._pipeline_attempt

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        """Execute the pipeline, handle completion/failure.

        AD-PIPELINE-007: Pipeline failures do NOT auto-trigger teardown.
        The handler stores the result and lets the reconciler decide.
        """
        try:
            result = await self._executor.execute(
                pipeline_def=self._pipeline_def,
                context=self._context,
                step_dispatcher=self._step_dispatcher,
                existing_progress=self._existing_progress,
                pipeline_name=self.pipeline_name,
            )
            self._result = result
            await self._on_complete(result)
        except asyncio.CancelledError:
            logger.info("Pipeline '%s' cancelled for session %s", self.pipeline_name, self.session_id)
            raise
        except Exception as e:
            self._error = e
            logger.error("Pipeline '%s' crashed for session %s: %s", self.pipeline_name, self.session_id, e)
            await self._on_error(e)

    async def _on_complete(self, result: PipelineResult) -> None:
        """Handle pipeline completion — success, partial, suspended, or failure.

        - completed/partial → trigger status transition (e.g. mark_session_ready)
        - suspended (Phase 3 / AD-CSI-009) → graceful pause, KEEP registration
        - failed → log and let reconciler handle on next cycle

        AD-PIPELINE-007: No auto-terminate on failure.
        AD-CSI-016: SUSPENDED keeps the handler registered so the
        events_controller can resume it on the next CloudEvent.
        """
        if result.status == "suspended":
            # Persist suspension state for resumption. Handler exits Task
            # gracefully but remains in the registry until either
            # ``resume_after_external_completion`` or ``stop()`` is called.
            logger.info(
                "Pipeline '%s' suspended for session %s — %d step(s) awaiting external completion (%s)",
                self.pipeline_name,
                self.session_id,
                result.steps_suspended,
                [j.get("external_job_id") for j in result.external_jobs],
            )
            # Invoke external callback if provided (best-effort)
            if self._on_complete_cb:
                try:
                    cb_result = self._on_complete_cb(result)
                    if asyncio.iscoroutine(cb_result):
                        await cb_result
                except Exception as e:
                    logger.error("on_complete callback failed for session %s: %s", self.session_id, e)
            return  # Do NOT unregister; events_controller needs to find us

        if result.status in ("completed", "partial"):
            if self.pipeline_name == "instantiate":
                try:
                    # For instantiate pipeline, mark_session_ready is the last step
                    # and handles its own transition. The handler just logs success.
                    logger.info(
                        "Pipeline '%s' completed for session %s (steps: %d completed, %d skipped, %d failed, %.1fs)",
                        self.pipeline_name,
                        self.session_id,
                        result.steps_completed,
                        result.steps_skipped,
                        result.steps_failed,
                        result.duration_seconds,
                    )
                except Exception as e:
                    logger.error("Error in _on_complete callback for session %s: %s", self.session_id, e)
            else:
                logger.info(
                    "Pipeline '%s' completed for session %s (%s)",
                    self.pipeline_name,
                    self.session_id,
                    result.status,
                )
        elif result.status == "failed":
            logger.warning(
                "Pipeline '%s' failed for session %s: %s (attempt %d)",
                self.pipeline_name,
                self.session_id,
                result.error,
                self._pipeline_attempt,
            )

        # Invoke external callback if provided
        if self._on_complete_cb:
            try:
                cb_result = self._on_complete_cb(result)
                if asyncio.iscoroutine(cb_result):
                    await cb_result
            except Exception as e:
                logger.error("on_complete callback failed for session %s: %s", self.session_id, e)

        # Terminal completion (not suspended) — remove from registry
        self._unregister(self.session_id)

    async def _on_error(self, exc: Exception) -> None:
        """Handle unhandled exception in executor.

        AD-PIPELINE-007: Logs at ERROR level but does NOT auto-terminate.
        The reconciler will detect handler.is_running == False on next cycle.
        """
        logger.error(
            "Unhandled error in pipeline '%s' for session %s: %s",
            self.pipeline_name,
            self.session_id,
            exc,
        )

        # Invoke external callback if provided
        if self._on_error_cb:
            try:
                cb_result = self._on_error_cb(exc)
                if asyncio.iscoroutine(cb_result):
                    await cb_result
            except Exception as e:
                logger.error("on_error callback failed for session %s: %s", self.session_id, e)

        # Terminal error path — remove from registry
        self._unregister(self.session_id)

    # ------------------------------------------------------------------
    # Phase 3 / AD-CSI-016: Resumption signal from CloudEvent callbacks
    # ------------------------------------------------------------------

    async def resume_after_external_completion(
        self,
        updated_progress: dict[str, Any],
    ) -> None:
        """Resume the pipeline after a SE CloudEvent flipped a suspended step to completed.

        Called by ``events_controller`` after it has successfully posted
        ``ResumePipelineStepCommand`` to CPA and received back the refreshed
        ``pipeline_progress`` dict.

        Replaces ``self._existing_progress`` and re-invokes ``start()`` — the
        executor's resumability logic will skip already-completed steps and
        dispatch the previously-blocked downstream steps.

        Args:
            updated_progress: Fresh per-step progress dict from CPA, with the
                resumed step's status flipped to "completed".
        """
        if self.is_running:
            logger.warning(
                "resume_after_external_completion called while handler still running for session %s — ignoring",
                self.session_id,
            )
            return
        self._existing_progress = updated_progress
        logger.info(
            "Resuming pipeline '%s' for session %s after external completion",
            self.pipeline_name,
            self.session_id,
        )
        await self.start()

    async def fail_after_external_completion(
        self,
        updated_progress: dict[str, Any],
    ) -> None:
        """Resume after a SE CloudEvent flipped a suspended step to failed.

        Identical mechanism to ``resume_after_external_completion`` — the
        executor will see the step as "failed" in existing_progress (depending
        on resumability semantics, it may either re-run or treat it as a
        terminal failure based on retry config). The pipeline outcome is then
        determined by ``pipeline_failure_strategy`` on the session.
        """
        if self.is_running:
            logger.warning(
                "fail_after_external_completion called while handler still running for session %s — ignoring",
                self.session_id,
            )
            return
        self._existing_progress = updated_progress
        logger.info(
            "Resuming pipeline '%s' for session %s after external failure",
            self.pipeline_name,
            self.session_id,
        )
        await self.start()
