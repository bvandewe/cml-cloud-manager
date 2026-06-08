"""Phase 3 / AD-CSI-008: verify lab_resolve and lab_start delegate to SE
when ``context.scenario_engine_enabled`` is True.

These tests do NOT exercise the legacy in-process path (covered by
existing test_instantiation_pipeline / test_phase9_lab_discovery suites);
they only assert the flag-gated branch returns SUSPENDED via the SE adapter.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from application.services.step_handlers.lab_resolve_step import step_lab_resolve
from application.services.step_handlers.lab_start_step import step_lab_start


def _make_context(*, se_client, topology_yaml="topology"):
    definition = SimpleNamespace(
        id="def-1",
        pod_definition_ref={"definition_id": "pod-99"},
        cml_yaml_content=topology_yaml,
        topology_yaml=topology_yaml,
    )
    return SimpleNamespace(
        scenario_engine_client=se_client,
        cloud_event_callback_url="http://lc/api/events",
        scenario_engine_enabled=True,
        definition=definition,
        # legacy-path-only fields — must NOT be touched in flag-on tests
        cml=MagicMock(),
        worker_ip="10.0.0.1",
        worker_cml_username="u",
        worker_cml_password="p",
        resolve_lab_for_instance=None,
        resolved_lab_ids={},
        freshly_imported_sessions=set(),
        find_lab_record_id=None,
        register_lab_record=None,
        api=MagicMock(),
        update_lab_record_status=None,
    )


def _make_instance(*, cml_lab_id=None):
    return SimpleNamespace(
        id="sess-9",
        definition_id="def-1",
        worker_id="w-1",
        topology_yaml=None,
        cml_lab_id=cml_lab_id,
    )


@pytest.mark.asyncio
async def test_lab_resolve_delegates_to_se_when_flag_on():
    se_client = MagicMock()
    se_client.submit_job = AsyncMock(return_value=SimpleNamespace(job_id="job-100"))
    context = _make_context(se_client=se_client)
    instance = _make_instance()

    result = await step_lab_resolve(instance, progress={}, context=context, params=None)

    assert result.status == "suspended"
    assert result.external_job_id == "job-100"
    assert result.step_correlation_id.startswith("sess-9:lab_resolve:")
    se_client.submit_job.assert_awaited_once()
    kwargs = se_client.submit_job.await_args.kwargs
    assert kwargs["scenario_name"] == "lab_resolve"
    assert kwargs["input_data"]["session_id"] == "sess-9"
    assert kwargs["input_data"]["topology_yaml"] == "topology"
    # Legacy CML client must NOT be touched in the SE branch
    context.cml.import_lab.assert_not_called()


@pytest.mark.asyncio
async def test_lab_resolve_returns_failed_when_topology_missing():
    se_client = MagicMock()
    se_client.submit_job = AsyncMock()
    context = _make_context(se_client=se_client, topology_yaml=None)
    instance = _make_instance()

    result = await step_lab_resolve(instance, progress={}, context=context, params=None)

    assert result.status == "failed"
    assert "No topology YAML" in (result.error or "")
    se_client.submit_job.assert_not_called()


@pytest.mark.asyncio
async def test_lab_start_delegates_to_se_when_flag_on():
    se_client = MagicMock()
    se_client.submit_job = AsyncMock(return_value=SimpleNamespace(job_id="job-200"))
    context = _make_context(se_client=se_client)
    instance = _make_instance(cml_lab_id="cml-abc")
    progress = {"lab_resolve": {"status": "completed", "result_data": {"cml_lab_id": "cml-abc"}}}

    result = await step_lab_start(instance, progress=progress, context=context, params=None)

    assert result.status == "suspended"
    assert result.external_job_id == "job-200"
    assert result.step_correlation_id.startswith("sess-9:lab_start:")
    se_client.submit_job.assert_awaited_once()
    kwargs = se_client.submit_job.await_args.kwargs
    assert kwargs["scenario_name"] == "lab_start"
    assert kwargs["input_data"] == {"session_id": "sess-9", "cml_lab_id": "cml-abc"}
    # Legacy CML calls must NOT happen on the SE branch
    context.cml.get_lab_state.assert_not_called()
    context.cml.start_lab.assert_not_called()


@pytest.mark.asyncio
async def test_lab_start_returns_failed_when_resolve_data_missing():
    se_client = MagicMock()
    se_client.submit_job = AsyncMock()
    context = _make_context(se_client=se_client)
    instance = _make_instance()

    result = await step_lab_start(instance, progress={}, context=context, params=None)

    assert result.status == "failed"
    assert "No cml_lab_id" in (result.error or "")
    se_client.submit_job.assert_not_called()
