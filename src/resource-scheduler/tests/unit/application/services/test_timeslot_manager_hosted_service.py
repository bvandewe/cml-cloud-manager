"""Unit tests for TimeslotManagerHostedService (Sprint H).

Tests the leader-elected periodic timeslot management for PENDING sessions:
- Approaching timeslot detection and etcd trigger writes
- Expired timeslot enforcement via CPA expire_session()
- Deduplication of triggers/expirations
- Pruning of dedup sets when sessions leave the response
- Error handling for CPA and etcd failures
- Statistics and admin info
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from application.hosted_services.timeslot_manager_hosted_service import TimeslotManagerHostedService
from application.settings import Settings

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_api_client():
    """Mock ControlPlaneApiClient."""
    client = AsyncMock()
    client.get_sessions_with_imminent_deadlines = AsyncMock(return_value={"approaching_start": [], "past_end": []})
    client.expire_session = AsyncMock(return_value={"session_id": "s-1", "status": "EXPIRED"})
    client.health_check = AsyncMock(return_value=True)
    return client


@pytest.fixture
def mock_etcd_client():
    """Mock EtcdClient with leader election and key operations."""
    client = AsyncMock()
    client.try_acquire_leadership = AsyncMock(return_value=True)
    client.grant_lease = AsyncMock(return_value=MagicMock())
    client.put = AsyncMock()
    return client


@pytest.fixture
def settings():
    """Settings with timeslot manager enabled and short intervals for testing."""
    s = Settings()
    s.timeslot_manager_enabled = True
    s.timeslot_manager_interval_seconds = 60
    s.timeslot_expiry_grace_minutes = 5
    s.timeslot_lead_time_minutes = 35
    s.etcd_key_prefix = "/lcm"
    return s


@pytest.fixture
def timeslot_manager(mock_api_client, mock_etcd_client, settings):
    """Create TimeslotManagerHostedService with mocked dependencies."""
    with patch.object(TimeslotManagerHostedService, "__init__", lambda self, *a, **kw: None):
        svc = TimeslotManagerHostedService.__new__(TimeslotManagerHostedService)

    svc._api = mock_api_client
    svc._etcd = mock_etcd_client
    svc._settings = settings

    from lcm_core.infrastructure.hosted_services import LeaderElectionConfig

    svc._election_config = LeaderElectionConfig(
        etcd_endpoints=["localhost:2379"],
        lease_ttl_seconds=15,
        service_name="timeslot-manager",
    )
    svc._key_prefix = "/lcm"
    svc._is_leader = False
    svc._started = False
    svc._scan_task = None
    svc._leader_task = None
    svc._triggered_session_ids = set()
    svc._expired_session_ids = set()
    svc._scan_count = 0
    svc._triggers = 0
    svc._expirations = 0
    svc._last_scan_at = None
    svc._last_error = None

    return svc


# =============================================================================
# Initialization Tests
# =============================================================================


class TestTimeslotManagerInit:
    """Tests for initialization and configuration."""

    def test_initial_state(self, timeslot_manager):
        """Test initial state after construction."""
        assert timeslot_manager._is_leader is False
        assert timeslot_manager._started is False
        assert timeslot_manager._scan_count == 0
        assert timeslot_manager._triggers == 0
        assert timeslot_manager._expirations == 0
        assert timeslot_manager._last_scan_at is None
        assert timeslot_manager._last_error is None
        assert len(timeslot_manager._triggered_session_ids) == 0
        assert len(timeslot_manager._expired_session_ids) == 0

    def test_stats_property(self, timeslot_manager, settings):
        """Test stats property returns correct structure."""
        stats = timeslot_manager.stats
        assert stats["enabled"] is True
        assert stats["is_leader"] is False
        assert stats["scan_count"] == 0
        assert stats["triggers"] == 0
        assert stats["expirations"] == 0
        assert stats["tracked_triggered"] == 0
        assert stats["tracked_expired"] == 0
        assert stats["last_scan_at"] is None
        assert stats["last_error"] is None
        assert stats["interval_seconds"] == settings.timeslot_manager_interval_seconds
        assert stats["lead_time_minutes"] == settings.timeslot_lead_time_minutes
        assert stats["expiry_grace_minutes"] == settings.timeslot_expiry_grace_minutes


# =============================================================================
# Lifecycle Tests
# =============================================================================


class TestTimeslotManagerLifecycle:
    """Tests for start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_when_disabled(self, timeslot_manager):
        """Test start does nothing when timeslot manager is disabled."""
        timeslot_manager._settings.timeslot_manager_enabled = False

        await timeslot_manager.start_async()

        assert timeslot_manager._started is False
        assert timeslot_manager._leader_task is None

    @pytest.mark.asyncio
    async def test_start_when_enabled(self, timeslot_manager):
        """Test start creates leader loop task when enabled."""
        with patch.object(timeslot_manager, "_leader_loop", new_callable=AsyncMock):
            await timeslot_manager.start_async()

        assert timeslot_manager._started is True
        assert timeslot_manager._leader_task is not None

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self, timeslot_manager):
        """Test stop cancels running tasks and resets state."""
        timeslot_manager._started = True
        timeslot_manager._is_leader = True
        timeslot_manager._scan_task = asyncio.create_task(asyncio.sleep(999))
        timeslot_manager._leader_task = asyncio.create_task(asyncio.sleep(999))

        await timeslot_manager.stop_async()

        assert timeslot_manager._started is False
        assert timeslot_manager._is_leader is False

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self, timeslot_manager):
        """Test stop is safe when service was never started."""
        await timeslot_manager.stop_async()

        assert timeslot_manager._started is False


# =============================================================================
# Leader Election Tests
# =============================================================================


class TestTimeslotManagerLeaderElection:
    """Tests for leader election behavior."""

    @pytest.mark.asyncio
    async def test_try_become_leader_succeeds(self, timeslot_manager, mock_etcd_client):
        """Test successful leader election."""
        mock_etcd_client.try_acquire_leadership.return_value = True

        result = await timeslot_manager._try_become_leader()

        assert result is True
        mock_etcd_client.try_acquire_leadership.assert_called_once_with(
            key="/lcm/timeslot-manager/leader",
            lease_ttl=15,
        )

    @pytest.mark.asyncio
    async def test_try_become_leader_fails(self, timeslot_manager, mock_etcd_client):
        """Test failed leader election."""
        mock_etcd_client.try_acquire_leadership.return_value = False

        result = await timeslot_manager._try_become_leader()

        assert result is False

    @pytest.mark.asyncio
    async def test_try_become_leader_handles_exception(self, timeslot_manager, mock_etcd_client):
        """Test leader election handles etcd errors gracefully."""
        mock_etcd_client.try_acquire_leadership.side_effect = Exception("etcd unavailable")

        result = await timeslot_manager._try_become_leader()

        assert result is False


# =============================================================================
# Approaching Timeslot Detection Tests
# =============================================================================


class TestTimeslotApproachingDetection:
    """Tests for triggering scheduling for approaching PENDING sessions."""

    @pytest.mark.asyncio
    async def test_triggers_pending_approaching_session(self, timeslot_manager, mock_api_client, mock_etcd_client):
        """Test that PENDING sessions approaching their timeslot get an etcd trigger."""
        mock_api_client.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [
                {"id": "s-1", "status": "PENDING", "timeslot_start": "2026-03-12T10:00:00Z"},
            ],
            "past_end": [],
        }

        await timeslot_manager._run_scan()

        # Should have written etcd trigger key
        mock_etcd_client.grant_lease.assert_called_once_with(ttl=120)
        mock_etcd_client.put.assert_called_once_with("/lcm/sessions/s-1/state", "PENDING", lease=mock_etcd_client.grant_lease.return_value)
        assert timeslot_manager._triggers == 1
        assert "s-1" in timeslot_manager._triggered_session_ids

    @pytest.mark.asyncio
    async def test_skips_non_pending_approaching_session(self, timeslot_manager, mock_api_client, mock_etcd_client):
        """Test that non-PENDING sessions (e.g., SCHEDULED) are NOT triggered."""
        mock_api_client.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [
                {"id": "s-1", "status": "SCHEDULED", "timeslot_start": "2026-03-12T10:00:00Z"},
            ],
            "past_end": [],
        }

        await timeslot_manager._run_scan()

        mock_etcd_client.put.assert_not_called()
        assert timeslot_manager._triggers == 0

    @pytest.mark.asyncio
    async def test_triggers_multiple_pending_sessions(self, timeslot_manager, mock_api_client, mock_etcd_client):
        """Test triggering multiple PENDING sessions in one scan."""
        mock_api_client.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [
                {"id": "s-1", "status": "PENDING", "timeslot_start": "2026-03-12T10:00:00Z"},
                {"id": "s-2", "status": "PENDING", "timeslot_start": "2026-03-12T10:05:00Z"},
                {"id": "s-3", "status": "SCHEDULED", "timeslot_start": "2026-03-12T10:10:00Z"},
            ],
            "past_end": [],
        }

        await timeslot_manager._run_scan()

        assert timeslot_manager._triggers == 2
        assert "s-1" in timeslot_manager._triggered_session_ids
        assert "s-2" in timeslot_manager._triggered_session_ids
        assert "s-3" not in timeslot_manager._triggered_session_ids


# =============================================================================
# Expired Timeslot Detection Tests
# =============================================================================


class TestTimeslotExpiredDetection:
    """Tests for expiring PENDING sessions that missed their timeslot."""

    @pytest.mark.asyncio
    async def test_expires_pending_past_end_session(self, timeslot_manager, mock_api_client):
        """Test that PENDING sessions past their timeslot_end get expired."""
        mock_api_client.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [],
            "past_end": [
                {"id": "s-1", "status": "PENDING", "timeslot_start": "2026-03-12T08:00:00Z"},
            ],
        }

        await timeslot_manager._run_scan()

        mock_api_client.expire_session.assert_called_once_with(
            session_id="s-1",
            reason="timeslot_missed",
        )
        assert timeslot_manager._expirations == 1
        assert "s-1" in timeslot_manager._expired_session_ids

    @pytest.mark.asyncio
    async def test_skips_non_pending_past_end_session(self, timeslot_manager, mock_api_client):
        """Test that non-PENDING past_end sessions are NOT expired."""
        mock_api_client.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [],
            "past_end": [
                {"id": "s-1", "status": "RUNNING", "timeslot_start": "2026-03-12T08:00:00Z"},
            ],
        }

        await timeslot_manager._run_scan()

        mock_api_client.expire_session.assert_not_called()
        assert timeslot_manager._expirations == 0

    @pytest.mark.asyncio
    async def test_expires_multiple_pending_sessions(self, timeslot_manager, mock_api_client):
        """Test expiring multiple PENDING sessions in one scan."""
        mock_api_client.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [],
            "past_end": [
                {"id": "s-1", "status": "PENDING", "timeslot_start": "2026-03-12T07:00:00Z"},
                {"id": "s-2", "status": "PENDING", "timeslot_start": "2026-03-12T06:00:00Z"},
            ],
        }

        await timeslot_manager._run_scan()

        assert mock_api_client.expire_session.call_count == 2
        assert timeslot_manager._expirations == 2


# =============================================================================
# Deduplication Tests
# =============================================================================


class TestTimeslotDeduplication:
    """Tests for deduplication — don't re-trigger/re-expire already-processed sessions."""

    @pytest.mark.asyncio
    async def test_does_not_retrigger_already_triggered_session(self, timeslot_manager, mock_api_client, mock_etcd_client):
        """Test that an already-triggered session is not triggered again."""
        timeslot_manager._triggered_session_ids = {"s-1"}
        mock_api_client.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [
                {"id": "s-1", "status": "PENDING", "timeslot_start": "2026-03-12T10:00:00Z"},
            ],
            "past_end": [],
        }

        await timeslot_manager._run_scan()

        mock_etcd_client.put.assert_not_called()
        assert timeslot_manager._triggers == 0

    @pytest.mark.asyncio
    async def test_does_not_re_expire_already_expired_session(self, timeslot_manager, mock_api_client):
        """Test that an already-expired session is not expired again."""
        timeslot_manager._expired_session_ids = {"s-1"}
        mock_api_client.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [],
            "past_end": [
                {"id": "s-1", "status": "PENDING", "timeslot_start": "2026-03-12T08:00:00Z"},
            ],
        }

        await timeslot_manager._run_scan()

        mock_api_client.expire_session.assert_not_called()
        assert timeslot_manager._expirations == 0


# =============================================================================
# Pruning Tests
# =============================================================================


class TestTimeslotPruning:
    """Tests for pruning dedup sets when sessions leave the response."""

    @pytest.mark.asyncio
    async def test_prunes_triggered_set_when_session_leaves_response(self, timeslot_manager, mock_api_client):
        """Test that sessions removed from approaching_start are pruned from triggered set."""
        timeslot_manager._triggered_session_ids = {"s-1", "s-2"}
        mock_api_client.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [
                # s-1 still present, s-2 is gone (transitioned to SCHEDULED)
                {"id": "s-1", "status": "PENDING", "timeslot_start": "2026-03-12T10:00:00Z"},
            ],
            "past_end": [],
        }

        await timeslot_manager._run_scan()

        assert "s-1" in timeslot_manager._triggered_session_ids
        assert "s-2" not in timeslot_manager._triggered_session_ids

    @pytest.mark.asyncio
    async def test_prunes_expired_set_when_session_leaves_response(self, timeslot_manager, mock_api_client):
        """Test that sessions removed from past_end are pruned from expired set."""
        timeslot_manager._expired_session_ids = {"s-1", "s-2"}
        mock_api_client.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [],
            "past_end": [
                # s-1 still present, s-2 is gone (cleanup completed)
                {"id": "s-1", "status": "PENDING", "timeslot_start": "2026-03-12T08:00:00Z"},
            ],
        }

        await timeslot_manager._run_scan()

        assert "s-1" in timeslot_manager._expired_session_ids
        assert "s-2" not in timeslot_manager._expired_session_ids


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestTimeslotErrorHandling:
    """Tests for error handling in scan operations."""

    @pytest.mark.asyncio
    async def test_cpa_unavailable_records_error(self, timeslot_manager, mock_api_client):
        """Test that CPA errors are recorded in last_error."""
        mock_api_client.get_sessions_with_imminent_deadlines.side_effect = Exception("CPA timeout")

        with pytest.raises(Exception, match="CPA timeout"):
            await timeslot_manager._run_scan()

        # Scan count should still increment (scan was attempted)
        assert timeslot_manager._scan_count == 1

    @pytest.mark.asyncio
    async def test_etcd_write_failure_does_not_crash(self, timeslot_manager, mock_api_client, mock_etcd_client):
        """Test that etcd write failure is handled gracefully."""
        mock_api_client.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [
                {"id": "s-1", "status": "PENDING", "timeslot_start": "2026-03-12T10:00:00Z"},
            ],
            "past_end": [],
        }
        mock_etcd_client.grant_lease.side_effect = Exception("etcd unavailable")

        # Should not raise — error is logged and swallowed
        await timeslot_manager._run_scan()

        # Trigger count still increments (the trigger was attempted)
        assert timeslot_manager._triggers == 1

    @pytest.mark.asyncio
    async def test_expire_failure_removes_from_expired_set(self, timeslot_manager, mock_api_client):
        """Test that a failed expiration removes the session from expired set for retry."""
        mock_api_client.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [],
            "past_end": [
                {"id": "s-1", "status": "PENDING", "timeslot_start": "2026-03-12T08:00:00Z"},
            ],
        }
        mock_api_client.expire_session.side_effect = Exception("API error")

        await timeslot_manager._run_scan()

        # Session should NOT be in expired set (removed for retry)
        assert "s-1" not in timeslot_manager._expired_session_ids
        # Expiration count should not be incremented
        assert timeslot_manager._expirations == 0


# =============================================================================
# Stats Tests
# =============================================================================


class TestTimeslotStats:
    """Tests for statistics tracking."""

    @pytest.mark.asyncio
    async def test_stats_update_after_scan(self, timeslot_manager, mock_api_client, mock_etcd_client):
        """Test that stats reflect scan results."""
        mock_api_client.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [
                {"id": "s-1", "status": "PENDING", "timeslot_start": "2026-03-12T10:00:00Z"},
            ],
            "past_end": [
                {"id": "s-2", "status": "PENDING", "timeslot_start": "2026-03-12T08:00:00Z"},
            ],
        }

        await timeslot_manager._run_scan()

        stats = timeslot_manager.stats
        assert stats["scan_count"] == 1
        assert stats["triggers"] == 1
        assert stats["expirations"] == 1
        assert stats["tracked_triggered"] == 1
        assert stats["tracked_expired"] == 1
        assert stats["last_scan_at"] is not None
        assert stats["last_error"] is None

    def test_stats_format_complete(self, timeslot_manager, settings):
        """Test that stats dict has all required keys."""
        stats = timeslot_manager.stats
        expected_keys = {
            "enabled",
            "is_leader",
            "scan_count",
            "triggers",
            "expirations",
            "tracked_triggered",
            "tracked_expired",
            "last_scan_at",
            "last_error",
            "interval_seconds",
            "lead_time_minutes",
            "expiry_grace_minutes",
        }
        assert set(stats.keys()) == expected_keys


# =============================================================================
# DI Configure Tests
# =============================================================================


class TestTimeslotManagerConfigure:
    """Tests for DI configuration."""

    def test_configure_registers_singleton(self):
        """Test that configure registers the service as a singleton."""
        mock_services = MagicMock()
        settings = Settings()

        TimeslotManagerHostedService.configure(mock_services, settings)

        mock_services.add_singleton.assert_called_once()
        # Verify correct class was registered
        call_args = mock_services.add_singleton.call_args
        assert call_args[0][0] is TimeslotManagerHostedService


# =============================================================================
# Combined Scenario Tests
# =============================================================================


class TestTimeslotManagerScenarios:
    """End-to-end scenario tests combining multiple aspects."""

    @pytest.mark.asyncio
    async def test_mixed_approaching_and_expired(self, timeslot_manager, mock_api_client, mock_etcd_client):
        """Test scan with both approaching and expired sessions."""
        mock_api_client.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [
                {"id": "s-1", "status": "PENDING", "timeslot_start": "2026-03-12T10:00:00Z"},
                {"id": "s-2", "status": "SCHEDULED", "timeslot_start": "2026-03-12T10:05:00Z"},
            ],
            "past_end": [
                {"id": "s-3", "status": "PENDING", "timeslot_start": "2026-03-12T08:00:00Z"},
                {"id": "s-4", "status": "RUNNING", "timeslot_start": "2026-03-12T07:00:00Z"},
            ],
        }

        await timeslot_manager._run_scan()

        # s-1: PENDING + approaching → triggered
        assert "s-1" in timeslot_manager._triggered_session_ids
        # s-2: SCHEDULED → not triggered (not PENDING)
        assert "s-2" not in timeslot_manager._triggered_session_ids
        # s-3: PENDING + past_end → expired
        assert "s-3" in timeslot_manager._expired_session_ids
        # s-4: RUNNING → not expired (not PENDING)
        assert "s-4" not in timeslot_manager._expired_session_ids

        assert timeslot_manager._triggers == 1
        assert timeslot_manager._expirations == 1

    @pytest.mark.asyncio
    async def test_consecutive_scans_with_dedup_and_pruning(self, timeslot_manager, mock_api_client, mock_etcd_client):
        """Test two consecutive scans showing dedup on second scan and pruning."""
        # First scan: s-1 approaching, s-2 expired
        mock_api_client.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [
                {"id": "s-1", "status": "PENDING", "timeslot_start": "2026-03-12T10:00:00Z"},
            ],
            "past_end": [
                {"id": "s-2", "status": "PENDING", "timeslot_start": "2026-03-12T08:00:00Z"},
            ],
        }

        await timeslot_manager._run_scan()
        assert timeslot_manager._triggers == 1
        assert timeslot_manager._expirations == 1

        # Second scan: s-1 still approaching (dedup), s-2 gone (pruned), s-3 new
        mock_api_client.get_sessions_with_imminent_deadlines.return_value = {
            "approaching_start": [
                {"id": "s-1", "status": "PENDING", "timeslot_start": "2026-03-12T10:00:00Z"},
                {"id": "s-3", "status": "PENDING", "timeslot_start": "2026-03-12T10:30:00Z"},
            ],
            "past_end": [],
        }

        mock_etcd_client.put.reset_mock()
        mock_etcd_client.grant_lease.reset_mock()
        await timeslot_manager._run_scan()

        # s-1 should NOT be re-triggered (dedup)
        # s-3 should be triggered (new)
        assert timeslot_manager._triggers == 2  # total across both scans
        assert timeslot_manager._scan_count == 2
        # s-2 should be pruned from expired set
        assert "s-2" not in timeslot_manager._expired_session_ids
        # s-3 should be in triggered set
        assert "s-3" in timeslot_manager._triggered_session_ids
