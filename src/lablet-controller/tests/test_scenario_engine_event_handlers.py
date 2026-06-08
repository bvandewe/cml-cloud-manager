"""Tests for the Scenario Engine IntegrationEventHandlers.

These tests exercise the handlers directly (no FastAPI / TestClient) — the
ingestion path (CloudEventMiddleware → CloudEventBus → CloudEventIngestor →
Mediator) is provided and verified by Neuroglia itself.

Coverage:
- ``started`` / ``progress`` are no-ops against CPA.
- ``completed`` → CPA ``resume_pipeline_step`` with normalised metadata.
- Default ``pipeline_name`` fallback to ``"instantiate"``.
- Missing routing metadata → handler returns silently (no CPA call).
- CPA 404 swallowed (idempotent duplicate-delivery).
- CPA non-404 error swallowed (reconciler is the recovery path).
- ``failed`` and ``cancelled`` invoke CPA ``fail_pipeline_step`` with the
  appropriate error / details payload.
- LifecyclePhaseHandler resumption / fail signalling when one is registered;
  quiet skip when none is registered.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from application.events.integration.scenario_engine_events import (
    ScenarioEngineJobCancelledIntegrationEventV1,
    ScenarioEngineJobCompletedIntegrationEventV1,
    ScenarioEngineJobFailedIntegrationEventV1,
    ScenarioEngineJobProgressIntegrationEventV1,
    ScenarioEngineJobStartedIntegrationEventV1,
)
from application.events.integration.scenario_engine_handler import (
    ScenarioEngineJobCancelledHandler,
    ScenarioEngineJobCompletedHandler,
    ScenarioEngineJobFailedHandler,
    ScenarioEngineJobProgressHandler,
    ScenarioEngineJobStartedHandler,
)
from application.services.lifecycle_phase_handler import LifecyclePhaseHandler
from lcm_core.integration.clients.control_plane_client import ControlPlaneApiClientError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_lifecycle_registry():
    """Ensure the in-process LifecyclePhaseHandler registry is empty per-test."""
    LifecyclePhaseHandler._registry.clear()
    yield
    LifecyclePhaseHandler._registry.clear()


@pytest.fixture
def cpa_mock() -> MagicMock:
    """Mock ControlPlaneApiClient with default successful resume/fail responses."""
    mock = MagicMock()
    mock.resume_pipeline_step = AsyncMock(
        return_value={
            "session_id": "sess-1",
            "pipeline_name": "instantiate",
            "step_name": "lab_resolve",
            "pipeline_progress": {"lab_resolve": {"status": "completed"}},
            "idempotent": False,
        }
    )
    mock.fail_pipeline_step = AsyncMock(
        return_value={
            "session_id": "sess-1",
            "pipeline_name": "instantiate",
            "step_name": "lab_start",
            "pipeline_progress": {"lab_start": {"status": "failed"}},
        }
    )
    return mock


def _make_event(cls: type, **kwargs: Any) -> Any:
    """Construct an event using the same ``__dict__`` assignment that the
    CloudEventIngestor uses at runtime (bypassing ``__init__``)."""
    instance = object.__new__(cls)
    instance.__dict__ = dict(kwargs)
    return instance


# ---------------------------------------------------------------------------
# Informational handlers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_started_handler_is_noop_against_cpa(cpa_mock: MagicMock):
    handler = ScenarioEngineJobStartedHandler()
    event = _make_event(
        ScenarioEngineJobStartedIntegrationEventV1,
        job_id="job-1",
        scenario_name="lab_resolve",
        started_at="2026-01-01T00:00:00Z",
        metadata={"lablet_session_id": "sess-1"},
    )
    await handler.handle_async(event)
    cpa_mock.resume_pipeline_step.assert_not_awaited()
    cpa_mock.fail_pipeline_step.assert_not_awaited()


@pytest.mark.asyncio
async def test_progress_handler_is_noop_against_cpa(cpa_mock: MagicMock):
    handler = ScenarioEngineJobProgressHandler()
    event = _make_event(
        ScenarioEngineJobProgressIntegrationEventV1,
        job_id="job-1",
        percentage=42,
        message="halfway",
        details={},
        metadata={},
    )
    await handler.handle_async(event)
    cpa_mock.resume_pipeline_step.assert_not_awaited()


# ---------------------------------------------------------------------------
# job.completed — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completed_calls_resume_with_normalised_metadata(cpa_mock: MagicMock):
    handler = ScenarioEngineJobCompletedHandler(control_plane_client=cpa_mock)
    event = _make_event(
        ScenarioEngineJobCompletedIntegrationEventV1,
        job_id="job-100",
        output_data={"cml_lab_id": "lab-xyz"},
        completed_at="2026-01-01T00:05:00Z",
        metadata={
            "lablet_session_id": "sess-1",
            "step_correlation_id": "corr-1",
            "step_name": "lab_resolve",
            "pipeline_name": "instantiate",
        },
    )
    await handler.handle_async(event)

    cpa_mock.resume_pipeline_step.assert_awaited_once()
    kwargs = cpa_mock.resume_pipeline_step.await_args.kwargs
    assert kwargs["session_id"] == "sess-1"
    assert kwargs["pipeline_name"] == "instantiate"
    assert kwargs["step_correlation_id"] == "corr-1"
    assert kwargs["output_data"] == {"cml_lab_id": "lab-xyz"}
    # 'Z' normalised to '+00:00'
    assert kwargs["completed_at"].startswith("2026-01-01T00:05:00")


@pytest.mark.asyncio
async def test_completed_defaults_pipeline_name_to_instantiate(cpa_mock: MagicMock):
    handler = ScenarioEngineJobCompletedHandler(control_plane_client=cpa_mock)
    event = _make_event(
        ScenarioEngineJobCompletedIntegrationEventV1,
        job_id="job-100",
        output_data={},
        metadata={
            "lablet_session_id": "sess-1",
            "step_correlation_id": "corr-1",
            # pipeline_name intentionally omitted
        },
    )
    await handler.handle_async(event)
    assert cpa_mock.resume_pipeline_step.await_args.kwargs["pipeline_name"] == "instantiate"


@pytest.mark.asyncio
async def test_completed_missing_metadata_is_dropped(cpa_mock: MagicMock):
    handler = ScenarioEngineJobCompletedHandler(control_plane_client=cpa_mock)
    event = _make_event(
        ScenarioEngineJobCompletedIntegrationEventV1,
        job_id="job-100",
        output_data={},
        metadata={},
    )
    await handler.handle_async(event)
    cpa_mock.resume_pipeline_step.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_no_metadata_attribute_is_dropped(cpa_mock: MagicMock):
    handler = ScenarioEngineJobCompletedHandler(control_plane_client=cpa_mock)
    event = _make_event(
        ScenarioEngineJobCompletedIntegrationEventV1,
        job_id="job-100",
        output_data={},
        # no metadata key at all
    )
    await handler.handle_async(event)
    cpa_mock.resume_pipeline_step.assert_not_awaited()


# ---------------------------------------------------------------------------
# job.failed / job.cancelled — terminal handlers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_calls_fail_with_error_message_alias(cpa_mock: MagicMock):
    handler = ScenarioEngineJobFailedHandler(control_plane_client=cpa_mock)
    event = _make_event(
        ScenarioEngineJobFailedIntegrationEventV1,
        job_id="job-100",
        error_message="external timeout",
        error_details={"timeout_seconds": 1800},
        failed_at="2026-01-01T00:30:00Z",
        metadata={
            "lablet_session_id": "sess-1",
            "step_correlation_id": "corr-2",
            "step_name": "lab_start",
        },
    )
    await handler.handle_async(event)

    cpa_mock.fail_pipeline_step.assert_awaited_once()
    kwargs = cpa_mock.fail_pipeline_step.await_args.kwargs
    assert kwargs["session_id"] == "sess-1"
    assert kwargs["step_correlation_id"] == "corr-2"
    assert kwargs["error"] == "external timeout"
    assert kwargs["details"] == {"timeout_seconds": 1800}


@pytest.mark.asyncio
async def test_failed_with_actual_se_payload_shape(cpa_mock: MagicMock):
    """SE actually emits ``data.error`` (no ``error_message``)."""
    handler = ScenarioEngineJobFailedHandler(control_plane_client=cpa_mock)
    event = _make_event(
        ScenarioEngineJobFailedIntegrationEventV1,
        job_id="job-100",
        error="boom",
        duration=12.5,
        metadata={
            "lablet_session_id": "sess-1",
            "step_correlation_id": "corr-2",
        },
    )
    await handler.handle_async(event)
    kwargs = cpa_mock.fail_pipeline_step.await_args.kwargs
    assert kwargs["error"] == "boom"
    assert kwargs["details"] is None


@pytest.mark.asyncio
async def test_cancelled_calls_fail_with_cancelled_marker(cpa_mock: MagicMock):
    handler = ScenarioEngineJobCancelledHandler(control_plane_client=cpa_mock)
    event = _make_event(
        ScenarioEngineJobCancelledIntegrationEventV1,
        job_id="job-100",
        reason="user_requested",
        cancelled_at="2026-01-01T00:10:00Z",
        metadata={
            "lablet_session_id": "sess-1",
            "step_correlation_id": "corr-3",
        },
    )
    await handler.handle_async(event)

    cpa_mock.fail_pipeline_step.assert_awaited_once()
    kwargs = cpa_mock.fail_pipeline_step.await_args.kwargs
    assert "cancelled" in kwargs["error"]
    assert kwargs["details"]["cancelled"] is True
    assert kwargs["details"]["reason"] == "user_requested"


# ---------------------------------------------------------------------------
# CPA error semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completed_swallows_cpa_404_as_idempotent(cpa_mock: MagicMock):
    cpa_mock.resume_pipeline_step.side_effect = ControlPlaneApiClientError("not found", status_code=404)
    handler = ScenarioEngineJobCompletedHandler(control_plane_client=cpa_mock)
    event = _make_event(
        ScenarioEngineJobCompletedIntegrationEventV1,
        job_id="job-100",
        output_data={},
        metadata={"lablet_session_id": "sess-1", "step_correlation_id": "corr-stale"},
    )
    # Must not raise.
    await handler.handle_async(event)


@pytest.mark.asyncio
async def test_completed_swallows_cpa_500_and_relies_on_reconciler(cpa_mock: MagicMock):
    cpa_mock.resume_pipeline_step.side_effect = ControlPlaneApiClientError("boom", status_code=500)
    handler = ScenarioEngineJobCompletedHandler(control_plane_client=cpa_mock)
    event = _make_event(
        ScenarioEngineJobCompletedIntegrationEventV1,
        job_id="job-100",
        output_data={},
        metadata={"lablet_session_id": "sess-1", "step_correlation_id": "corr-1"},
    )
    # Must not raise — SE delivery is already-acked by the middleware (202)
    # before the handler runs; reconciler is the recovery path.
    await handler.handle_async(event)


@pytest.mark.asyncio
async def test_failed_swallows_cpa_404(cpa_mock: MagicMock):
    cpa_mock.fail_pipeline_step.side_effect = ControlPlaneApiClientError("not found", status_code=404)
    handler = ScenarioEngineJobFailedHandler(control_plane_client=cpa_mock)
    event = _make_event(
        ScenarioEngineJobFailedIntegrationEventV1,
        job_id="job-100",
        error="boom",
        metadata={"lablet_session_id": "sess-1", "step_correlation_id": "corr-1"},
    )
    await handler.handle_async(event)


# ---------------------------------------------------------------------------
# LifecyclePhaseHandler signalling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completed_signals_registered_lifecycle_handler(cpa_mock: MagicMock):
    lifecycle_mock = MagicMock()
    lifecycle_mock.resume_after_external_completion = AsyncMock()
    LifecyclePhaseHandler._registry["sess-1"] = lifecycle_mock

    handler = ScenarioEngineJobCompletedHandler(control_plane_client=cpa_mock)
    event = _make_event(
        ScenarioEngineJobCompletedIntegrationEventV1,
        job_id="job-100",
        output_data={},
        metadata={"lablet_session_id": "sess-1", "step_correlation_id": "corr-1"},
    )
    await handler.handle_async(event)

    lifecycle_mock.resume_after_external_completion.assert_awaited_once_with({"lab_resolve": {"status": "completed"}})


@pytest.mark.asyncio
async def test_completed_quiet_skip_when_no_lifecycle_handler(cpa_mock: MagicMock):
    handler = ScenarioEngineJobCompletedHandler(control_plane_client=cpa_mock)
    event = _make_event(
        ScenarioEngineJobCompletedIntegrationEventV1,
        job_id="job-100",
        output_data={},
        metadata={"lablet_session_id": "sess-unregistered", "step_correlation_id": "corr-1"},
    )
    # Must not raise even though no LifecyclePhaseHandler is registered.
    await handler.handle_async(event)
    cpa_mock.resume_pipeline_step.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_signals_registered_lifecycle_handler(cpa_mock: MagicMock):
    lifecycle_mock = MagicMock()
    lifecycle_mock.fail_after_external_completion = AsyncMock()
    LifecyclePhaseHandler._registry["sess-1"] = lifecycle_mock

    handler = ScenarioEngineJobFailedHandler(control_plane_client=cpa_mock)
    event = _make_event(
        ScenarioEngineJobFailedIntegrationEventV1,
        job_id="job-100",
        error="boom",
        metadata={"lablet_session_id": "sess-1", "step_correlation_id": "corr-1"},
    )
    await handler.handle_async(event)

    lifecycle_mock.fail_after_external_completion.assert_awaited_once_with({"lab_start": {"status": "failed"}})


# ---------------------------------------------------------------------------
# Phase 3 / Q-11 — CloudEvent source allow-list
# ---------------------------------------------------------------------------


def _settings_with_sources(sources: list[str]) -> Any:
    s = MagicMock()
    s.scenario_engine_allowed_sources = sources
    return s


@pytest.mark.asyncio
async def test_q11_disallowed_source_drops_completed_event(cpa_mock: MagicMock):
    """A completed event from an unknown source must be dropped (no CPA call)."""
    handler = ScenarioEngineJobCompletedHandler(
        control_plane_client=cpa_mock,
        settings=_settings_with_sources(["scenario-engine"]),
    )
    event = _make_event(
        ScenarioEngineJobCompletedIntegrationEventV1,
        job_id="job-1",
        output_data={},
        completed_at="2026-01-01T00:00:00Z",
        metadata={"lablet_session_id": "sess-1", "step_correlation_id": "corr-1"},
    )
    event.__cloudevent__source__ = "rogue-injector"
    await handler.handle_async(event)
    cpa_mock.resume_pipeline_step.assert_not_awaited()


@pytest.mark.asyncio
async def test_q11_allowed_source_passes_completed_event(cpa_mock: MagicMock):
    handler = ScenarioEngineJobCompletedHandler(
        control_plane_client=cpa_mock,
        settings=_settings_with_sources(["scenario-engine"]),
    )
    event = _make_event(
        ScenarioEngineJobCompletedIntegrationEventV1,
        job_id="job-1",
        output_data={},
        completed_at="2026-01-01T00:00:00Z",
        metadata={"lablet_session_id": "sess-1", "step_correlation_id": "corr-1"},
    )
    event.__cloudevent__source__ = "scenario-engine"
    await handler.handle_async(event)
    cpa_mock.resume_pipeline_step.assert_awaited_once()


@pytest.mark.asyncio
async def test_q11_source_check_is_case_insensitive(cpa_mock: MagicMock):
    handler = ScenarioEngineJobCompletedHandler(
        control_plane_client=cpa_mock,
        settings=_settings_with_sources(["Scenario-Engine"]),
    )
    event = _make_event(
        ScenarioEngineJobCompletedIntegrationEventV1,
        job_id="job-1",
        output_data={},
        completed_at="2026-01-01T00:00:00Z",
        metadata={"lablet_session_id": "sess-1", "step_correlation_id": "corr-1"},
    )
    event.__cloudevent__source__ = "SCENARIO-ENGINE"
    await handler.handle_async(event)
    cpa_mock.resume_pipeline_step.assert_awaited_once()


@pytest.mark.asyncio
async def test_q11_empty_allow_list_disables_check(cpa_mock: MagicMock):
    """An empty allow-list opts out of source validation entirely."""
    handler = ScenarioEngineJobCompletedHandler(
        control_plane_client=cpa_mock,
        settings=_settings_with_sources([]),
    )
    event = _make_event(
        ScenarioEngineJobCompletedIntegrationEventV1,
        job_id="job-1",
        output_data={},
        completed_at="2026-01-01T00:00:00Z",
        metadata={"lablet_session_id": "sess-1", "step_correlation_id": "corr-1"},
    )
    event.__cloudevent__source__ = "anything"
    await handler.handle_async(event)
    cpa_mock.resume_pipeline_step.assert_awaited_once()


@pytest.mark.asyncio
async def test_q11_missing_source_attribute_is_dropped(cpa_mock: MagicMock):
    """No CloudEvent source attached → drop when allow-list is active."""
    handler = ScenarioEngineJobCompletedHandler(
        control_plane_client=cpa_mock,
        settings=_settings_with_sources(["scenario-engine"]),
    )
    event = _make_event(
        ScenarioEngineJobCompletedIntegrationEventV1,
        job_id="job-1",
        output_data={},
        completed_at="2026-01-01T00:00:00Z",
        metadata={"lablet_session_id": "sess-1", "step_correlation_id": "corr-1"},
    )
    # No event.__cloudevent__source__ set
    await handler.handle_async(event)
    cpa_mock.resume_pipeline_step.assert_not_awaited()


@pytest.mark.asyncio
async def test_q11_failed_handler_drops_disallowed_source(cpa_mock: MagicMock):
    handler = ScenarioEngineJobFailedHandler(
        control_plane_client=cpa_mock,
        settings=_settings_with_sources(["scenario-engine"]),
    )
    event = _make_event(
        ScenarioEngineJobFailedIntegrationEventV1,
        job_id="job-1",
        error="boom",
        failed_at="2026-01-01T00:00:00Z",
        metadata={"lablet_session_id": "sess-1", "step_correlation_id": "corr-1"},
    )
    event.__cloudevent__source__ = "rogue"
    await handler.handle_async(event)
    cpa_mock.fail_pipeline_step.assert_not_awaited()


@pytest.mark.asyncio
async def test_q11_started_handler_drops_disallowed_source(cpa_mock: MagicMock):
    handler = ScenarioEngineJobStartedHandler(
        settings=_settings_with_sources(["scenario-engine"]),
    )
    event = _make_event(
        ScenarioEngineJobStartedIntegrationEventV1,
        job_id="job-1",
        scenario_name="lab_resolve",
        started_at="2026-01-01T00:00:00Z",
        metadata={"lablet_session_id": "sess-1"},
    )
    event.__cloudevent__source__ = "rogue"
    # No exception, no CPA call — handler simply returns.
    await handler.handle_async(event)
    cpa_mock.resume_pipeline_step.assert_not_awaited()
    cpa_mock.fail_pipeline_step.assert_not_awaited()
