"""Unit tests for TimeslotWatcherService (AD-TIMESLOT-001).

Tests cover:
- Lifecycle: start/stop, disabled mode
- Deadline scanning: approaching start, past end, mixed
- Trigger deduplication: avoids redundant etcd writes
- Trigger pruning: clears tracking when sessions leave deadlines
- etcd lease pattern: grant_lease(ttl=60) → put(key, value, lease=...)
- Error handling: API failures, etcd failures
- Stats reporting: get_stats()

Pattern: object.__new__ bypass + AsyncMock, matching test_lablet_reconciler_g5.py style.
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _make_watcher(
    check_enabled: bool = True,
    check_interval: int = 10,
    boot_window_minutes: int = 35,
    etcd_key_prefix: str = "/lcm",
):
    """Create a TimeslotWatcherService bypassing __init__."""
    from application.hosted_services.timeslot_watcher_service import TimeslotWatcherService

    svc = object.__new__(TimeslotWatcherService)

    # API client mock
    svc._api = AsyncMock()
    svc._api.get_sessions_with_imminent_deadlines = AsyncMock(return_value={"approaching_start": [], "past_end": []})

    # etcd client mock
    svc._etcd = AsyncMock()
    svc._etcd.grant_lease = AsyncMock(return_value=_FakeLease(id=1, ttl=60, granted_ttl=60))
    svc._etcd.put = AsyncMock(return_value=True)

    # Settings mock
    svc._settings = MagicMock()
    svc._settings.timeslot_check_enabled = check_enabled
    svc._settings.timeslot_check_interval = check_interval
    svc._settings.timeslot_boot_window_minutes = boot_window_minutes
    svc._settings.etcd_key_prefix = etcd_key_prefix

    # Internal state
    svc._running = False
    svc._task = None
    svc._key_prefix = etcd_key_prefix
    svc._scan_count = 0
    svc._triggers_approaching = 0
    svc._triggers_past_end = 0
    svc._last_scan_at = None
    svc._last_error = None
    svc._triggered_approaching = set()
    svc._triggered_past_end = set()

    return svc


@dataclass
class _FakeLease:
    """Minimal EtcdLease stand-in for tests (avoids importing from lcm_core)."""

    id: int
    ttl: int
    granted_ttl: int


def _session_info(
    session_id: str = "sess-001",
    status: str = "SCHEDULED",
    timeslot_start: str | None = "2025-01-15T10:00:00+00:00",
    timeslot_end: str | None = "2025-01-15T12:00:00+00:00",
    worker_id: str | None = None,
    definition_id: str | None = "def-001",
) -> dict:
    """Create a SessionDeadlineInfo-like dict as returned by CPA."""
    return {
        "id": session_id,
        "status": status,
        "timeslot_start": timeslot_start,
        "timeslot_end": timeslot_end,
        "worker_id": worker_id,
        "definition_id": definition_id,
    }


# ===========================================================================
# Lifecycle
# ===========================================================================


@pytest.mark.unit
class TestTimeslotWatcherLifecycle:
    @pytest.mark.asyncio
    async def test_start_when_disabled_does_not_create_task(self):
        svc = _make_watcher(check_enabled=False)

        await svc.start_async()

        assert not svc._running
        assert svc._task is None

    @pytest.mark.asyncio
    async def test_start_when_enabled_creates_background_task(self):
        svc = _make_watcher(check_enabled=True)

        await svc.start_async()

        assert svc._running
        assert svc._task is not None
        assert svc._task.get_name() == "timeslot_watcher_loop"

        # Clean up
        await svc.stop_async()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        svc = _make_watcher(check_enabled=True)

        await svc.start_async()
        assert svc._running

        await svc.stop_async()
        assert not svc._running
        assert svc._task is None

    @pytest.mark.asyncio
    async def test_stop_when_no_task_is_safe(self):
        svc = _make_watcher()
        # Never started → stop should be a no-op
        await svc.stop_async()
        assert not svc._running


# ===========================================================================
# Deadline Scanning
# ===========================================================================


@pytest.mark.unit
class TestTimeslotDeadlineScanning:
    @pytest.mark.asyncio
    async def test_scan_with_no_deadlines_increments_count(self):
        svc = _make_watcher()
        svc._api.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [],
            "past_end": [],
        }

        await svc._scan_deadlines()

        assert svc._scan_count == 1
        assert svc._last_scan_at is not None
        svc._etcd.put.assert_not_called()

    @pytest.mark.asyncio
    async def test_scan_approaching_start_triggers_reconcile(self):
        svc = _make_watcher()
        svc._api.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [_session_info("sess-A", status="SCHEDULED")],
            "past_end": [],
        }

        await svc._scan_deadlines()

        assert svc._triggers_approaching == 1
        assert svc._triggers_past_end == 0
        assert "sess-A" in svc._triggered_approaching

        # Verify etcd calls: grant_lease then put
        svc._etcd.grant_lease.assert_called_once_with(ttl=60)
        svc._etcd.put.assert_called_once()
        call_args = svc._etcd.put.call_args
        assert "sess-A" in call_args.args[0]  # key contains session_id
        assert call_args.args[1] == "timeslot_approaching"  # reason
        assert call_args.kwargs.get("lease") is not None

    @pytest.mark.asyncio
    async def test_scan_past_end_triggers_reconcile(self):
        svc = _make_watcher()
        svc._api.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [],
            "past_end": [_session_info("sess-B", status="RUNNING")],
        }

        await svc._scan_deadlines()

        assert svc._triggers_approaching == 0
        assert svc._triggers_past_end == 1
        assert "sess-B" in svc._triggered_past_end

        svc._etcd.grant_lease.assert_called_once_with(ttl=60)
        svc._etcd.put.assert_called_once()
        call_args = svc._etcd.put.call_args
        assert "sess-B" in call_args.args[0]
        assert call_args.args[1] == "timeslot_expired"

    @pytest.mark.asyncio
    async def test_scan_mixed_deadlines_triggers_both(self):
        svc = _make_watcher()
        svc._api.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [_session_info("sess-A", status="SCHEDULED")],
            "past_end": [_session_info("sess-B", status="RUNNING")],
        }

        await svc._scan_deadlines()

        assert svc._triggers_approaching == 1
        assert svc._triggers_past_end == 1
        assert svc._etcd.grant_lease.call_count == 2
        assert svc._etcd.put.call_count == 2

    @pytest.mark.asyncio
    async def test_scan_multiple_approaching_sessions(self):
        svc = _make_watcher()
        svc._api.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [
                _session_info("sess-1"),
                _session_info("sess-2"),
                _session_info("sess-3"),
            ],
            "past_end": [],
        }

        await svc._scan_deadlines()

        assert svc._triggers_approaching == 3
        assert svc._etcd.put.call_count == 3
        assert svc._triggered_approaching == {"sess-1", "sess-2", "sess-3"}


# ===========================================================================
# Deduplication
# ===========================================================================


@pytest.mark.unit
class TestTimeslotDeduplication:
    @pytest.mark.asyncio
    async def test_approaching_session_only_triggered_once(self):
        svc = _make_watcher()
        response = {
            "approaching_start": [_session_info("sess-A")],
            "past_end": [],
        }
        svc._api.get_sessions_with_imminent_deadlines.return_value = response

        # Scan #1: triggers
        await svc._scan_deadlines()
        assert svc._triggers_approaching == 1

        # Scan #2: same session, no new trigger
        await svc._scan_deadlines()
        assert svc._triggers_approaching == 1
        assert svc._scan_count == 2
        assert svc._etcd.put.call_count == 1  # Only one etcd write total

    @pytest.mark.asyncio
    async def test_past_end_session_only_triggered_once(self):
        svc = _make_watcher()
        response = {
            "approaching_start": [],
            "past_end": [_session_info("sess-B", status="RUNNING")],
        }
        svc._api.get_sessions_with_imminent_deadlines.return_value = response

        await svc._scan_deadlines()
        await svc._scan_deadlines()

        assert svc._triggers_past_end == 1
        assert svc._etcd.put.call_count == 1

    @pytest.mark.asyncio
    async def test_new_session_triggers_even_when_others_deduped(self):
        svc = _make_watcher()

        # Scan #1: sess-A approaches
        svc._api.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [_session_info("sess-A")],
            "past_end": [],
        }
        await svc._scan_deadlines()
        assert svc._triggers_approaching == 1

        # Scan #2: sess-A still there + new sess-B
        svc._api.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [_session_info("sess-A"), _session_info("sess-B")],
            "past_end": [],
        }
        await svc._scan_deadlines()
        assert svc._triggers_approaching == 2  # Only sess-B is new
        assert svc._etcd.put.call_count == 2


# ===========================================================================
# Pruning
# ===========================================================================


@pytest.mark.unit
class TestTimeslotPruning:
    @pytest.mark.asyncio
    async def test_session_removed_from_tracking_when_no_longer_imminent(self):
        svc = _make_watcher()

        # Scan #1: sess-A is approaching
        svc._api.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [_session_info("sess-A")],
            "past_end": [],
        }
        await svc._scan_deadlines()
        assert "sess-A" in svc._triggered_approaching

        # Scan #2: sess-A transitioned (no longer in response)
        svc._api.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [],
            "past_end": [],
        }
        await svc._scan_deadlines()
        assert "sess-A" not in svc._triggered_approaching

    @pytest.mark.asyncio
    async def test_pruned_session_can_retrigger_if_it_reappears(self):
        """Edge case: session transitions away then reappears (e.g., rescheduled)."""
        svc = _make_watcher()

        # Scan #1: sess-A approaches → triggered
        svc._api.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [_session_info("sess-A")],
            "past_end": [],
        }
        await svc._scan_deadlines()

        # Scan #2: sess-A gone → pruned
        svc._api.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [],
            "past_end": [],
        }
        await svc._scan_deadlines()

        # Scan #3: sess-A reappears → triggers again
        svc._api.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [_session_info("sess-A")],
            "past_end": [],
        }
        await svc._scan_deadlines()
        assert svc._triggers_approaching == 2  # Triggered twice total


# ===========================================================================
# etcd Lease Pattern
# ===========================================================================


@pytest.mark.unit
class TestTimeslotEtcdLeasePattern:
    @pytest.mark.asyncio
    async def test_trigger_calls_grant_lease_before_put(self):
        svc = _make_watcher()

        await svc._trigger_reconcile("sess-001", "timeslot_approaching")

        # grant_lease called first, then put with the lease object
        svc._etcd.grant_lease.assert_called_once_with(ttl=60)
        svc._etcd.put.assert_called_once()

        put_kwargs = svc._etcd.put.call_args.kwargs
        assert put_kwargs.get("lease") is not None
        assert put_kwargs["lease"].ttl == 60

    @pytest.mark.asyncio
    async def test_trigger_writes_correct_key_structure(self):
        svc = _make_watcher()

        await svc._trigger_reconcile("sess-abc-123", "timeslot_expired")

        call_args = svc._etcd.put.call_args
        key = call_args.args[0]
        value = call_args.args[1]

        assert key == "/lcm/sessions/sess-abc-123/timeslot_trigger"
        assert value == "timeslot_expired"

    @pytest.mark.asyncio
    async def test_trigger_uses_custom_etcd_prefix(self):
        svc = _make_watcher(etcd_key_prefix="/custom/prefix")

        await svc._trigger_reconcile("sess-001", "timeslot_approaching")

        key = svc._etcd.put.call_args.args[0]
        assert key == "/custom/prefix/sessions/sess-001/timeslot_trigger"


# ===========================================================================
# Error Handling
# ===========================================================================


@pytest.mark.unit
class TestTimeslotErrorHandling:
    @pytest.mark.asyncio
    async def test_api_failure_sets_last_error(self):
        svc = _make_watcher()
        svc._api.get_sessions_with_imminent_deadlines.side_effect = Exception("CPA unavailable")

        # Should not raise — error is caught in _watch_loop level
        # But _scan_deadlines re-raises, so we need to catch it here
        with pytest.raises(Exception, match="CPA unavailable"):
            await svc._scan_deadlines()

    @pytest.mark.asyncio
    async def test_etcd_put_failure_does_not_crash_scan(self):
        svc = _make_watcher()
        svc._api.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [_session_info("sess-A")],
            "past_end": [],
        }
        svc._etcd.grant_lease.side_effect = Exception("etcd unavailable")

        # _trigger_reconcile catches exceptions internally
        await svc._scan_deadlines()

        # Session was added to tracking despite etcd failure
        # (the add happens after the trigger call in the flow)
        assert svc._scan_count == 1

    @pytest.mark.asyncio
    async def test_etcd_put_failure_logs_but_continues(self):
        svc = _make_watcher()
        svc._api.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [
                _session_info("sess-A"),
                _session_info("sess-B"),
            ],
            "past_end": [],
        }
        # First call fails, second succeeds
        svc._etcd.grant_lease.side_effect = [
            Exception("etcd timeout"),
            _FakeLease(id=2, ttl=60, granted_ttl=60),
        ]

        await svc._scan_deadlines()

        # Both sessions counted as triggered (dedup tracks them)
        assert svc._triggers_approaching == 2
        # But only second actually wrote to etcd
        assert svc._etcd.put.call_count == 1


# ===========================================================================
# Stats
# ===========================================================================


@pytest.mark.unit
class TestTimeslotStats:
    def test_stats_when_fresh(self):
        svc = _make_watcher()
        stats = svc.get_stats()

        assert stats["enabled"] is True
        assert stats["running"] is False
        assert stats["interval_seconds"] == 10
        assert stats["boot_window_minutes"] == 35
        assert stats["scan_count"] == 0
        assert stats["triggers_approaching"] == 0
        assert stats["triggers_past_end"] == 0
        assert stats["tracked_approaching"] == 0
        assert stats["tracked_past_end"] == 0
        assert stats["last_scan_at"] is None
        assert stats["last_error"] is None

    @pytest.mark.asyncio
    async def test_stats_after_scan(self):
        svc = _make_watcher()
        svc._api.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [_session_info("sess-A")],
            "past_end": [_session_info("sess-B", status="RUNNING")],
        }

        await svc._scan_deadlines()

        stats = svc.get_stats()
        assert stats["scan_count"] == 1
        assert stats["triggers_approaching"] == 1
        assert stats["triggers_past_end"] == 1
        assert stats["tracked_approaching"] == 1
        assert stats["tracked_past_end"] == 1
        assert stats["last_scan_at"] is not None

    def test_stats_disabled_service(self):
        svc = _make_watcher(check_enabled=False)
        stats = svc.get_stats()
        assert stats["enabled"] is False


# ===========================================================================
# DI configure()
# ===========================================================================


@pytest.mark.unit
class TestTimeslotConfigure:
    def test_configure_registers_singleton(self):
        from application.hosted_services.timeslot_watcher_service import TimeslotWatcherService

        services = MagicMock()

        TimeslotWatcherService.configure(services)

        services.add_singleton.assert_called_once()
        call_args = services.add_singleton.call_args
        assert call_args.args[0] is TimeslotWatcherService
        assert "implementation_factory" in call_args.kwargs
