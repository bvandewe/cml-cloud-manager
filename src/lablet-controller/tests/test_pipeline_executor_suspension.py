"""Tests for PipelineExecutor SUSPENDED handling (Phase 3 / AD-CSI-009).

Verifies that when a step handler returns ``StepResult.suspended(...)``:
- The executor persists status="suspended" with external_job_id/correlation.
- The pipeline halts (no downstream steps dispatched).
- PipelineResult.status == "suspended" and ``external_jobs`` is populated.
- On resume (existing_progress with the suspended step flipped to "completed"),
  execution continues with the downstream steps.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.models.pipeline_context import PipelineContext
from application.models.pipeline_result import PipelineResult
from application.services.pipeline_executor import PipelineExecutor


def _make_context() -> PipelineContext:
    """Minimal PipelineContext for executor tests (mock API + cml)."""
    api = AsyncMock()
    api.update_pipeline_progress = AsyncMock(return_value=None)
    return PipelineContext(
        session=SimpleNamespace(id="sess-1"),
        definition=SimpleNamespace(id="def-1"),
        worker_ip="10.0.0.1",
        worker_cml_username="u",
        worker_cml_password="p",
        api=api,
        cml=AsyncMock(),
        lds=None,
    )


def _pipeline_def(*step_names: str) -> dict:
    """Build a linear pipeline definition for tests."""
    steps = []
    for i, name in enumerate(step_names):
        step: dict = {"name": name, "handler": name}
        if i > 0:
            step["needs"] = [step_names[i - 1]]
        steps.append(step)
    return {"description": "test_pipeline", "steps": steps}


@pytest.mark.asyncio
async def test_suspended_step_halts_pipeline():
    """A SUSPENDED step persists, halts downstream, returns status='suspended'."""
    executor = PipelineExecutor()
    context = _make_context()

    async def dispatcher(handler_name, session, progress, ctx, params):
        if handler_name == "lab_resolve":
            return {
                "status": "suspended",
                "external_job_id": "job-100",
                "step_correlation_id": "sess-1:lab_resolve:abc",
                "reason": "awaiting SE",
            }
        # Downstream steps MUST NOT be called
        raise AssertionError(f"Downstream step '{handler_name}' should not run after suspension")

    result: PipelineResult = await executor.execute(
        pipeline_def=_pipeline_def("lab_resolve", "lab_start", "lab_ready"),
        context=context,
        step_dispatcher=dispatcher,
        pipeline_name="instantiate",
    )

    assert result.status == "suspended"
    assert result.steps_completed == 0
    assert result.steps_suspended == 1
    assert len(result.external_jobs) == 1
    ej = result.external_jobs[0]
    assert ej["step_name"] == "lab_resolve"
    assert ej["external_job_id"] == "job-100"
    assert ej["step_correlation_id"] == "sess-1:lab_resolve:abc"
    assert "suspended_at" in ej

    # Persisted as "suspended" status
    call = context.api.update_pipeline_progress.await_args_list[-1]
    assert call.kwargs["step_status"] == "suspended"
    assert call.kwargs["result_data"]["external_job_id"] == "job-100"


@pytest.mark.asyncio
async def test_resuming_with_completed_progress_runs_downstream():
    """After CloudEvent flips suspended→completed in CPA, resumed execute() runs downstream."""
    executor = PipelineExecutor()
    context = _make_context()

    calls: list[str] = []

    async def dispatcher(handler_name, session, progress, ctx, params):
        calls.append(handler_name)
        return {"status": "completed", "ok": True}

    existing_progress = {
        "lab_resolve": {
            "status": "completed",
            "result_data": {"cml_lab_id": "lab-xyz"},
        }
    }

    result = await executor.execute(
        pipeline_def=_pipeline_def("lab_resolve", "lab_start"),
        context=context,
        step_dispatcher=dispatcher,
        existing_progress=existing_progress,
        pipeline_name="instantiate",
    )

    assert result.status == "completed"
    assert calls == ["lab_start"]  # lab_resolve was restored from progress
    assert result.steps_completed == 2  # 1 restored + 1 newly run


@pytest.mark.asyncio
async def test_resuming_with_still_suspended_step_halts():
    """If existing_progress has a step still 'suspended', executor halts without re-dispatching."""
    executor = PipelineExecutor()
    context = _make_context()

    dispatched: list[str] = []

    async def dispatcher(handler_name, session, progress, ctx, params):
        dispatched.append(handler_name)
        return {"status": "completed"}

    existing_progress = {
        "lab_resolve": {
            "status": "suspended",
            "external_job_id": "job-still-running",
            "step_correlation_id": "sess-1:lab_resolve:zzz",
            "suspended_at": "2026-01-01T00:00:00+00:00",
        }
    }

    result = await executor.execute(
        pipeline_def=_pipeline_def("lab_resolve", "lab_start"),
        context=context,
        step_dispatcher=dispatcher,
        existing_progress=existing_progress,
        pipeline_name="instantiate",
    )

    assert result.status == "suspended"
    assert dispatched == []  # Critical: no re-dispatch (would duplicate SE job)
    assert result.steps_suspended == 1
    assert result.external_jobs[0]["external_job_id"] == "job-still-running"


@pytest.mark.asyncio
async def test_suspended_does_not_count_as_failure():
    """Suspended is a distinct terminal state, not failed/partial."""
    executor = PipelineExecutor()
    context = _make_context()

    async def dispatcher(handler_name, session, progress, ctx, params):
        return {
            "status": "suspended",
            "external_job_id": "j-1",
            "step_correlation_id": "c-1",
        }

    result = await executor.execute(
        pipeline_def=_pipeline_def("only_step"),
        context=context,
        step_dispatcher=dispatcher,
        pipeline_name="instantiate",
    )

    assert result.status == "suspended"
    assert result.steps_failed == 0
    assert result.steps_skipped == 0
    assert result.error is None
