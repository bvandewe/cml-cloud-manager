"""Tests for LifecyclePhaseHandler registry + SUSPENDED handling (AD-CSI-016).

Verifies Phase 3 additions:
- Handler registers itself on start() and unregisters on terminal completion.
- SUSPENDED outcome KEEPS the handler registered (so events_controller can
  route CloudEvent callbacks back to it).
- ``resume_after_external_completion(updated_progress)`` replaces the
  existing_progress and re-invokes start() — executor resumes downstream
  steps.
- ``fail_after_external_completion`` follows the same mechanism.
- ``stop()`` always unregisters.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from application.models.pipeline_result import PipelineResult
from application.services.lifecycle_phase_handler import LifecyclePhaseHandler


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure the class-level registry is empty before each test."""
    LifecyclePhaseHandler._registry.clear()
    yield
    LifecyclePhaseHandler._registry.clear()


def _make_handler(
    session_id: str = "sess-1",
    pipeline_result: PipelineResult | None = None,
    pipeline_name: str = "instantiate",
) -> LifecyclePhaseHandler:
    """Build a handler with a mocked executor that returns a configurable result."""
    executor = MagicMock()
    if pipeline_result is None:
        pipeline_result = PipelineResult(
            pipeline_name=pipeline_name,
            status="completed",
            steps_completed=1,
            duration_seconds=0.1,
        )
    executor.execute = AsyncMock(return_value=pipeline_result)
    context = SimpleNamespace()
    return LifecyclePhaseHandler(
        session_id=session_id,
        pipeline_name=pipeline_name,
        pipeline_def={"steps": []},
        context=context,
        executor=executor,
        step_dispatcher=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_handler_registers_on_start_and_unregisters_on_completion():
    handler = _make_handler(session_id="sess-A")

    assert LifecyclePhaseHandler.lookup("sess-A") is None

    await handler.start()
    # Registered immediately at start
    assert LifecyclePhaseHandler.lookup("sess-A") is handler

    # Wait for completion
    assert handler._task is not None
    await handler._task

    # Unregistered after terminal completion
    assert LifecyclePhaseHandler.lookup("sess-A") is None


@pytest.mark.asyncio
async def test_suspended_outcome_keeps_handler_registered():
    suspended_result = PipelineResult(
        pipeline_name="instantiate",
        status="suspended",
        steps_completed=0,
        steps_skipped=0,
        steps_failed=0,
        steps_suspended=1,
        duration_seconds=0.05,
        external_jobs=[
            {
                "step_name": "lab_resolve",
                "external_job_id": "job-123",
                "step_correlation_id": "sess-B:lab_resolve:abc",
                "suspended_at": "2026-01-01T00:00:00+00:00",
            }
        ],
    )
    handler = _make_handler(session_id="sess-B", pipeline_result=suspended_result)

    await handler.start()
    assert handler._task is not None
    await handler._task

    # CRITICAL: still registered so events_controller can find it
    assert LifecyclePhaseHandler.lookup("sess-B") is handler
    assert handler.result is not None
    assert handler.result.status == "suspended"


@pytest.mark.asyncio
async def test_resume_after_external_completion_replaces_progress_and_restarts():
    # First run: suspended
    suspended_result = PipelineResult(
        pipeline_name="instantiate",
        status="suspended",
        steps_completed=0,
        steps_suspended=1,
        external_jobs=[{"step_name": "lab_resolve", "external_job_id": "j-1", "step_correlation_id": "c-1"}],
    )
    handler = _make_handler(session_id="sess-C", pipeline_result=suspended_result)

    await handler.start()
    assert handler._task is not None
    await handler._task
    assert handler.result is not None and handler.result.status == "suspended"

    # Now arrange a second run that returns completed
    completed_result = PipelineResult(
        pipeline_name="instantiate",
        status="completed",
        steps_completed=2,
        duration_seconds=0.2,
    )
    handler._executor.execute = AsyncMock(return_value=completed_result)  # type: ignore[attr-defined]

    updated_progress: dict[str, Any] = {"lab_resolve": {"status": "completed", "result_data": {"cml_lab_id": "lab-xyz"}}}

    await handler.resume_after_external_completion(updated_progress)
    assert handler._task is not None
    await handler._task

    # Verify executor was re-invoked with the refreshed progress
    last_call = handler._executor.execute.await_args_list[-1]  # type: ignore[attr-defined]
    assert last_call.kwargs["existing_progress"] == updated_progress
    # Pipeline attempt counter incremented
    assert handler.pipeline_attempt == 2
    # Terminal completion → unregistered
    assert LifecyclePhaseHandler.lookup("sess-C") is None
    assert handler.result is not None and handler.result.status == "completed"


@pytest.mark.asyncio
async def test_resume_while_running_is_a_noop():
    """Guard: resume must not race against an in-flight task."""
    handler = _make_handler(session_id="sess-D")
    # Don't await the task — pretend it's still running

    # Manually inject a sentinel "still-running" task
    async def _never():
        await __import__("asyncio").sleep(10)

    handler._task = __import__("asyncio").create_task(_never())

    await handler.resume_after_external_completion({"x": {"status": "completed"}})
    # Existing progress NOT replaced because handler ignored the call
    assert handler._existing_progress != {"x": {"status": "completed"}}
    handler._task.cancel()


@pytest.mark.asyncio
async def test_fail_after_external_completion_restarts_with_failed_progress():
    suspended_result = PipelineResult(
        pipeline_name="instantiate",
        status="suspended",
        steps_suspended=1,
        external_jobs=[{"step_name": "lab_resolve", "external_job_id": "j-2", "step_correlation_id": "c-2"}],
    )
    handler = _make_handler(session_id="sess-E", pipeline_result=suspended_result)

    await handler.start()
    assert handler._task is not None
    await handler._task

    failed_after_resume = PipelineResult(
        pipeline_name="instantiate",
        status="failed",
        steps_failed=1,
        error="external job failed",
    )
    handler._executor.execute = AsyncMock(return_value=failed_after_resume)  # type: ignore[attr-defined]

    updated = {"lab_resolve": {"status": "failed", "error": "SE timeout"}}
    await handler.fail_after_external_completion(updated)
    assert handler._task is not None
    await handler._task

    last_call = handler._executor.execute.await_args_list[-1]  # type: ignore[attr-defined]
    assert last_call.kwargs["existing_progress"] == updated
    # Failed terminal → unregistered
    assert LifecyclePhaseHandler.lookup("sess-E") is None


@pytest.mark.asyncio
async def test_stop_unregisters():
    handler = _make_handler(session_id="sess-F")
    await handler.start()
    assert LifecyclePhaseHandler.lookup("sess-F") is handler
    await handler.stop()
    assert LifecyclePhaseHandler.lookup("sess-F") is None
