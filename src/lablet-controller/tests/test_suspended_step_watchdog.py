"""Tests for :class:`SuspendedStepWatchdogService` (Phase 3 / Q-10).

Exercises the scan logic directly (``scan_once``) without driving the
asyncio loop. Validates:

- Idempotency guard prevents repeat fails inside one leader term.
- Steps within budget are left alone.
- Stale suspended steps trigger ``fail_pipeline_step`` and signal the
  in-process :class:`LifecyclePhaseHandler` when one is registered.
- Missing ``step_correlation_id`` skips gracefully (cannot fail without it).
- Missing/unparseable ``suspended_at`` skips gracefully (marked failed-key
  to avoid log spam).
- CPA 404 swallowed and marked failed-key (idempotent ack).
- Multiple active statuses are queried via fan-out.
- ``start_async`` / ``stop_async`` lifecycle is idempotent.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from application.hosted_services.suspended_step_watchdog_service import (
    _ACTIVE_STATUS_VALUES,
    SuspendedStepWatchdogService,
)
from application.services.lifecycle_phase_handler import LifecyclePhaseHandler
from lcm_core.integration.clients.control_plane_client import ControlPlaneApiClientError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_lifecycle_registry():
    LifecyclePhaseHandler._registry.clear()
    yield
    LifecyclePhaseHandler._registry.clear()


@pytest.fixture
def settings_mock() -> MagicMock:
    s = MagicMock()
    s.suspended_step_watchdog_enabled = True
    s.suspended_step_watchdog_interval_seconds = 60
    s.pipeline_external_step_default_timeout_seconds = 1800
    return s


@pytest.fixture
def cpa_mock() -> MagicMock:
    mock = MagicMock()
    mock.get_lablet_sessions = AsyncMock(return_value=[])
    mock.fail_pipeline_step = AsyncMock(
        return_value={
            "session_id": "sess-1",
            "pipeline_name": "instantiate",
            "step_name": "lab_resolve",
            "pipeline_progress": {"instantiate": {"lab_resolve": {"status": "failed"}}},
        }
    )
    return mock


def _make_session(
    *,
    session_id: str = "sess-1",
    pipeline_name: str = "instantiate",
    step_name: str = "lab_resolve",
    suspended_at: str | None = None,
    correlation_id: str | None = "corr-1",
    extra_step: dict[str, Any] | None = None,
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "status": "suspended",
        "external_job_id": "job-1",
    }
    if suspended_at is not None:
        step["suspended_at"] = suspended_at
    if correlation_id is not None:
        step["step_correlation_id"] = correlation_id
    if extra_step:
        step.update(extra_step)
    progress = {pipeline_name: {step_name: step}}
    if extra_step is None:
        # Add a completed step alongside to ensure non-suspended steps are skipped.
        progress[pipeline_name]["bootstrap"] = {"status": "completed"}
    return {"id": session_id, "pipeline_progress": progress}


def _make_service(cpa_mock: MagicMock, settings_mock: MagicMock) -> SuspendedStepWatchdogService:
    return SuspendedStepWatchdogService(api_client=cpa_mock, settings=settings_mock)


# ---------------------------------------------------------------------------
# scan_once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_active_sessions_is_noop(cpa_mock: MagicMock, settings_mock: MagicMock):
    service = _make_service(cpa_mock, settings_mock)
    await service.scan_once()
    # Should fan out one query per active status.
    assert cpa_mock.get_lablet_sessions.await_count == len(_ACTIVE_STATUS_VALUES)
    cpa_mock.fail_pipeline_step.assert_not_awaited()


@pytest.mark.asyncio
async def test_suspended_step_within_budget_skipped(cpa_mock: MagicMock, settings_mock: MagicMock):
    # suspended 10 seconds ago, timeout is 1800s → still in budget
    recent = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    session = _make_session(suspended_at=recent)
    # Only the first status returns the session; the rest are empty.
    cpa_mock.get_lablet_sessions.side_effect = [[session]] + [[] for _ in range(len(_ACTIVE_STATUS_VALUES) - 1)]

    service = _make_service(cpa_mock, settings_mock)
    await service.scan_once()
    cpa_mock.fail_pipeline_step.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_suspended_step_is_failed(cpa_mock: MagicMock, settings_mock: MagicMock):
    # 2 hours ago, timeout 30min → way past
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    session = _make_session(suspended_at=stale)
    cpa_mock.get_lablet_sessions.side_effect = [[session]] + [[] for _ in range(len(_ACTIVE_STATUS_VALUES) - 1)]

    service = _make_service(cpa_mock, settings_mock)
    await service.scan_once()

    cpa_mock.fail_pipeline_step.assert_awaited_once()
    kwargs = cpa_mock.fail_pipeline_step.await_args.kwargs
    assert kwargs["session_id"] == "sess-1"
    assert kwargs["pipeline_name"] == "instantiate"
    assert kwargs["step_correlation_id"] == "corr-1"
    assert "timeout" in kwargs["error"].lower()
    assert kwargs["details"]["watchdog"] is True
    assert kwargs["details"]["external_job_id"] == "job-1"


@pytest.mark.asyncio
async def test_idempotent_within_leader_term(cpa_mock: MagicMock, settings_mock: MagicMock):
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    session = _make_session(suspended_at=stale)
    cpa_mock.get_lablet_sessions.side_effect = ([[session]] + [[] for _ in range(len(_ACTIVE_STATUS_VALUES) - 1)]) * 2  # two full scan cycles

    service = _make_service(cpa_mock, settings_mock)
    await service.scan_once()
    await service.scan_once()

    # Second scan must NOT re-fail the same step.
    assert cpa_mock.fail_pipeline_step.await_count == 1


@pytest.mark.asyncio
async def test_signals_in_process_handler_when_registered(cpa_mock: MagicMock, settings_mock: MagicMock):
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    session = _make_session(suspended_at=stale)
    cpa_mock.get_lablet_sessions.side_effect = [[session]] + [[] for _ in range(len(_ACTIVE_STATUS_VALUES) - 1)]

    handler_mock = MagicMock()
    handler_mock.fail_after_external_completion = AsyncMock()
    LifecyclePhaseHandler._registry["sess-1"] = handler_mock

    service = _make_service(cpa_mock, settings_mock)
    await service.scan_once()

    handler_mock.fail_after_external_completion.assert_awaited_once()
    assert service.get_stats()["handler_signals"] == 1


@pytest.mark.asyncio
async def test_no_registered_handler_is_silent(cpa_mock: MagicMock, settings_mock: MagicMock):
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    session = _make_session(suspended_at=stale)
    cpa_mock.get_lablet_sessions.side_effect = [[session]] + [[] for _ in range(len(_ACTIVE_STATUS_VALUES) - 1)]

    service = _make_service(cpa_mock, settings_mock)
    await service.scan_once()

    # No handler registered → no exception, no signal counted.
    assert service.get_stats()["handler_signals"] == 0
    assert service.get_stats()["steps_failed"] == 1


@pytest.mark.asyncio
async def test_missing_correlation_id_is_skipped(cpa_mock: MagicMock, settings_mock: MagicMock):
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    session = _make_session(suspended_at=stale, correlation_id=None)
    cpa_mock.get_lablet_sessions.side_effect = [[session]] + [[] for _ in range(len(_ACTIVE_STATUS_VALUES) - 1)]

    service = _make_service(cpa_mock, settings_mock)
    await service.scan_once()
    cpa_mock.fail_pipeline_step.assert_not_awaited()


@pytest.mark.asyncio
async def test_unparseable_suspended_at_is_marked_handled(cpa_mock: MagicMock, settings_mock: MagicMock):
    session = _make_session(suspended_at="not-a-timestamp")
    cpa_mock.get_lablet_sessions.side_effect = [[session]] + [[] for _ in range(len(_ACTIVE_STATUS_VALUES) - 1)]

    service = _make_service(cpa_mock, settings_mock)
    await service.scan_once()

    cpa_mock.fail_pipeline_step.assert_not_awaited()
    # Re-scan should still skip silently (key tracked).
    cpa_mock.get_lablet_sessions.side_effect = [[session]] + [[] for _ in range(len(_ACTIVE_STATUS_VALUES) - 1)]
    await service.scan_once()
    cpa_mock.fail_pipeline_step.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_suspended_at_is_skipped(cpa_mock: MagicMock, settings_mock: MagicMock):
    session = _make_session(suspended_at=None)
    cpa_mock.get_lablet_sessions.side_effect = [[session]] + [[] for _ in range(len(_ACTIVE_STATUS_VALUES) - 1)]

    service = _make_service(cpa_mock, settings_mock)
    await service.scan_once()
    cpa_mock.fail_pipeline_step.assert_not_awaited()


@pytest.mark.asyncio
async def test_cpa_404_is_swallowed_and_marked_handled(cpa_mock: MagicMock, settings_mock: MagicMock):
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    session = _make_session(suspended_at=stale)
    cpa_mock.get_lablet_sessions.side_effect = [[session]] + [[] for _ in range(len(_ACTIVE_STATUS_VALUES) - 1)]

    err = ControlPlaneApiClientError("not found", status_code=404)
    cpa_mock.fail_pipeline_step.side_effect = err

    service = _make_service(cpa_mock, settings_mock)
    await service.scan_once()  # must not raise

    # Re-scan: 404 path marks the key handled.
    cpa_mock.get_lablet_sessions.side_effect = [[session]] + [[] for _ in range(len(_ACTIVE_STATUS_VALUES) - 1)]
    await service.scan_once()
    # Only one fail attempt should have been issued.
    assert cpa_mock.fail_pipeline_step.await_count == 1


@pytest.mark.asyncio
async def test_cpa_non_404_error_retries_next_scan(cpa_mock: MagicMock, settings_mock: MagicMock):
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    session = _make_session(suspended_at=stale)
    cpa_mock.get_lablet_sessions.side_effect = [[session]] + [[] for _ in range(len(_ACTIVE_STATUS_VALUES) - 1)]
    cpa_mock.fail_pipeline_step.side_effect = ControlPlaneApiClientError("500", status_code=500)

    service = _make_service(cpa_mock, settings_mock)
    # scan_once swallows the per-step exception via the loop's try/except,
    # but the helper re-raises. Verify the exception propagates so the loop's
    # outer handler records it.
    with pytest.raises(ControlPlaneApiClientError):
        await service.scan_once()
    # Key NOT marked → retry next scan.
    cpa_mock.fail_pipeline_step.side_effect = None
    cpa_mock.fail_pipeline_step.return_value = {"pipeline_progress": {}}
    cpa_mock.get_lablet_sessions.side_effect = [[session]] + [[] for _ in range(len(_ACTIVE_STATUS_VALUES) - 1)]
    await service.scan_once()
    assert cpa_mock.fail_pipeline_step.await_count == 2


@pytest.mark.asyncio
async def test_dedup_across_active_status_queries(cpa_mock: MagicMock, settings_mock: MagicMock):
    """Same session id returned from two status queries → counted once."""
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    session = _make_session(suspended_at=stale)
    # First two queries return the same session; rest empty.
    cpa_mock.get_lablet_sessions.side_effect = [[session], [session]] + [[] for _ in range(len(_ACTIVE_STATUS_VALUES) - 2)]

    service = _make_service(cpa_mock, settings_mock)
    await service.scan_once()

    cpa_mock.fail_pipeline_step.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_sessions_error_does_not_stall_scan(cpa_mock: MagicMock, settings_mock: MagicMock):
    """One status fan-out raising should not abort the whole scan."""
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    session = _make_session(suspended_at=stale)
    # Status #1 raises, #2 returns the session, rest empty.
    side_effects: list[Any] = [Exception("CPA hiccup"), [session]] + [[] for _ in range(len(_ACTIVE_STATUS_VALUES) - 2)]
    cpa_mock.get_lablet_sessions.side_effect = side_effects

    service = _make_service(cpa_mock, settings_mock)
    await service.scan_once()

    cpa_mock.fail_pipeline_step.assert_awaited_once()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_async_disabled_does_not_create_task(cpa_mock: MagicMock, settings_mock: MagicMock):
    settings_mock.suspended_step_watchdog_enabled = False
    service = _make_service(cpa_mock, settings_mock)
    await service.start_async()
    assert service._task is None
    await service.stop_async()  # must not raise


@pytest.mark.asyncio
async def test_start_async_zero_interval_disables(cpa_mock: MagicMock, settings_mock: MagicMock):
    settings_mock.suspended_step_watchdog_interval_seconds = 0
    service = _make_service(cpa_mock, settings_mock)
    await service.start_async()
    assert service._task is None


@pytest.mark.asyncio
async def test_start_stop_lifecycle_is_idempotent(cpa_mock: MagicMock, settings_mock: MagicMock):
    service = _make_service(cpa_mock, settings_mock)
    await service.start_async()
    assert service._task is not None
    # Second start is a noop (already running).
    await service.start_async()
    await service.stop_async()
    assert service._task is None
    # Second stop is a noop.
    await service.stop_async()
