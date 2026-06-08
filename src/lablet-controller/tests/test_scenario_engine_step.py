"""Unit tests for the Tier-B SE step adapter (`_scenario_engine_step`).

Phase 3 / AD-CSI-008 / AD-CSI-009.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from application.services.step_handlers._scenario_engine_step import (
    ScenarioBinding,
    submit_scenario_engine_job,
)


def _make_context(
    *,
    se_client=None,
    pod_definition_ref=None,
    callback_url="http://lc.local/api/events/cloudevents",
):
    """Build a minimal `PipelineContext`-shaped namespace."""
    definition = SimpleNamespace(id="def-1", pod_definition_ref=pod_definition_ref)
    return SimpleNamespace(
        scenario_engine_client=se_client,
        cloud_event_callback_url=callback_url,
        scenario_engine_enabled=True,
        definition=definition,
    )


def _make_instance(session_id="sess-1"):
    return SimpleNamespace(id=session_id, definition_id="def-1", worker_id="worker-1")


@pytest.mark.asyncio
async def test_submit_scenario_engine_job_returns_suspended_on_success():
    se_client = MagicMock()
    se_client.submit_job = AsyncMock(return_value=SimpleNamespace(job_id="job-xyz"))
    context = _make_context(
        se_client=se_client,
        pod_definition_ref={"definition_id": "pod-def-9", "version": "v1"},
    )
    instance = _make_instance()

    result = await submit_scenario_engine_job(
        binding=ScenarioBinding(scenario_name="lab_resolve", scenario_version="v1"),
        step_name="lab_resolve",
        instance=instance,
        context=context,
        input_data={"session_id": "sess-1", "topology_yaml": "abc"},
    )

    assert result.status == "suspended"
    assert result.external_job_id == "job-xyz"
    assert result.step_correlation_id is not None
    assert result.step_correlation_id.startswith("sess-1:lab_resolve:")

    se_client.submit_job.assert_awaited_once()
    kwargs = se_client.submit_job.await_args.kwargs
    assert kwargs["scenario_name"] == "lab_resolve"
    assert kwargs["scenario_version"] == "v1"
    assert kwargs["pod_definition_id"] == "pod-def-9"
    assert kwargs["callback_url"] == "http://lc.local/api/events/cloudevents"
    assert kwargs["input_data"] == {"session_id": "sess-1", "topology_yaml": "abc"}

    metadata = kwargs["metadata"]
    assert metadata["lablet_session_id"] == "sess-1"
    assert metadata["step_name"] == "lab_resolve"
    assert metadata["step_correlation_id"] == result.step_correlation_id


@pytest.mark.asyncio
async def test_submit_scenario_engine_job_fails_when_client_missing():
    context = _make_context(se_client=None, pod_definition_ref={"definition_id": "p-1"})
    result = await submit_scenario_engine_job(
        binding=ScenarioBinding(scenario_name="lab_start"),
        step_name="lab_start",
        instance=_make_instance(),
        context=context,
        input_data={},
    )
    assert result.status == "failed"
    assert "ScenarioEngineClient not available" in (result.error or "")


@pytest.mark.asyncio
async def test_submit_scenario_engine_job_fails_when_pod_definition_ref_missing():
    se_client = MagicMock()
    se_client.submit_job = AsyncMock()
    context = _make_context(se_client=se_client, pod_definition_ref=None)
    result = await submit_scenario_engine_job(
        binding=ScenarioBinding(scenario_name="lab_resolve"),
        step_name="lab_resolve",
        instance=_make_instance(),
        context=context,
        input_data={},
    )
    assert result.status == "failed"
    assert "pod_definition_ref" in (result.error or "")
    se_client.submit_job.assert_not_called()


@pytest.mark.asyncio
async def test_submit_scenario_engine_job_fails_when_se_raises():
    se_client = MagicMock()
    se_client.submit_job = AsyncMock(side_effect=RuntimeError("boom"))
    context = _make_context(
        se_client=se_client,
        pod_definition_ref={"definition_id": "pod-7"},
    )
    result = await submit_scenario_engine_job(
        binding=ScenarioBinding(scenario_name="lab_start"),
        step_name="lab_start",
        instance=_make_instance(),
        context=context,
        input_data={"session_id": "sess-1"},
    )
    assert result.status == "failed"
    assert "SE submit_job failed: boom" in (result.error or "")


@pytest.mark.asyncio
async def test_submit_scenario_engine_job_accepts_vo_like_pod_ref():
    """`pod_definition_ref` may be a VO object (not just a dict)."""
    se_client = MagicMock()
    se_client.submit_job = AsyncMock(return_value=SimpleNamespace(job_id="job-1"))
    vo_ref = SimpleNamespace(definition_id="pod-vo-5", version="v2")
    context = _make_context(se_client=se_client, pod_definition_ref=vo_ref)

    result = await submit_scenario_engine_job(
        binding=ScenarioBinding(scenario_name="lab_resolve"),
        step_name="lab_resolve",
        instance=_make_instance(),
        context=context,
        input_data={},
    )

    assert result.status == "suspended"
    assert se_client.submit_job.await_args.kwargs["pod_definition_id"] == "pod-vo-5"


@pytest.mark.asyncio
async def test_correlation_ids_are_unique_per_submission():
    se_client = MagicMock()
    se_client.submit_job = AsyncMock(return_value=SimpleNamespace(job_id="job-1"))
    context = _make_context(se_client=se_client, pod_definition_ref={"definition_id": "pod-1"})
    instance = _make_instance()

    r1 = await submit_scenario_engine_job(
        binding=ScenarioBinding(scenario_name="lab_resolve"),
        step_name="lab_resolve",
        instance=instance,
        context=context,
        input_data={},
    )
    r2 = await submit_scenario_engine_job(
        binding=ScenarioBinding(scenario_name="lab_resolve"),
        step_name="lab_resolve",
        instance=instance,
        context=context,
        input_data={},
    )
    assert r1.step_correlation_id != r2.step_correlation_id
