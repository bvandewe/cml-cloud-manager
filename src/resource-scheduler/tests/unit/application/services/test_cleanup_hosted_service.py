"""Unit tests for CleanupHostedService.

Tests the leader-elected periodic cleanup of terminated worker records.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from application.hosted_services.cleanup_hosted_service import CleanupHostedService
from application.settings import Settings


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_api_client():
    """Mock ControlPlaneApiClient."""
    client = AsyncMock()
    client.cleanup_terminated_workers = AsyncMock(return_value={"deleted_count": 0, "total_checked": 0})
    client.health_check = AsyncMock(return_value=True)
    return client


@pytest.fixture
def mock_etcd_client():
    """Mock EtcdClient with leader election support."""
    client = AsyncMock()
    client.try_acquire_leadership = AsyncMock(return_value=True)
    return client


@pytest.fixture
def settings():
    """Settings with cleanup enabled and short intervals for testing."""
    s = Settings()
    s.cleanup_enabled = True
    s.cleanup_interval_seconds = 3600
    s.cleanup_retention_days = 30
    return s


@pytest.fixture
def cleanup_service(mock_api_client, mock_etcd_client, settings):
    """Create CleanupHostedService with mocked dependencies."""
    with patch.object(CleanupHostedService, "__init__", lambda self, *a, **kw: None):
        svc = CleanupHostedService.__new__(CleanupHostedService)

    svc._api = mock_api_client
    svc._etcd = mock_etcd_client
    svc._settings = settings

    from lcm_core.infrastructure.hosted_services import LeaderElectionConfig

    svc._election_config = LeaderElectionConfig(
        etcd_endpoints=["localhost:2379"],
        lease_ttl_seconds=15,
        service_name="cleanup-service",
    )
    svc._is_leader = False
    svc._started = False
    svc._cleanup_task = None
    svc._leader_task = None
    svc._cleanup_runs = 0
    svc._last_cleanup_at = None
    svc._last_cleanup_result = None

    return svc


# =============================================================================
# Initialization Tests
# =============================================================================


class TestCleanupServiceInit:
    """Tests for initialization and configuration."""

    def test_initial_state(self, cleanup_service):
        """Test initial state after construction."""
        assert cleanup_service._is_leader is False
        assert cleanup_service._started is False
        assert cleanup_service._cleanup_runs == 0
        assert cleanup_service._last_cleanup_at is None
        assert cleanup_service._last_cleanup_result is None

    def test_stats_property(self, cleanup_service, settings):
        """Test stats property returns correct structure."""
        stats = cleanup_service.stats
        assert stats["enabled"] is True
        assert stats["is_leader"] is False
        assert stats["cleanup_runs"] == 0
        assert stats["last_cleanup_at"] is None
        assert stats["last_cleanup_result"] is None
        assert stats["interval_seconds"] == settings.cleanup_interval_seconds
        assert stats["retention_days"] == settings.cleanup_retention_days


# =============================================================================
# Start/Stop Tests
# =============================================================================


class TestCleanupServiceLifecycle:
    """Tests for start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_when_disabled(self, cleanup_service):
        """Test start does nothing when cleanup is disabled."""
        cleanup_service._settings.cleanup_enabled = False

        await cleanup_service.start_async()

        assert cleanup_service._started is False
        assert cleanup_service._leader_task is None

    @pytest.mark.asyncio
    async def test_start_when_enabled(self, cleanup_service):
        """Test start creates leader loop task when enabled."""
        # Patch _leader_loop to prevent it from running forever
        with patch.object(cleanup_service, "_leader_loop", new_callable=AsyncMock):
            await cleanup_service.start_async()

        assert cleanup_service._started is True
        assert cleanup_service._leader_task is not None

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self, cleanup_service):
        """Test stop cancels running tasks and resets state."""
        # Simulate running tasks
        cleanup_service._started = True
        cleanup_service._is_leader = True
        cleanup_service._cleanup_task = asyncio.create_task(asyncio.sleep(999))
        cleanup_service._leader_task = asyncio.create_task(asyncio.sleep(999))

        await cleanup_service.stop_async()

        assert cleanup_service._started is False
        assert cleanup_service._is_leader is False

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self, cleanup_service):
        """Test stop is safe when service was never started."""
        await cleanup_service.stop_async()

        assert cleanup_service._started is False


# =============================================================================
# Leader Election Tests
# =============================================================================


class TestCleanupLeaderElection:
    """Tests for leader election behavior."""

    @pytest.mark.asyncio
    async def test_try_become_leader_succeeds(self, cleanup_service, mock_etcd_client):
        """Test successful leader election."""
        mock_etcd_client.try_acquire_leadership.return_value = True

        result = await cleanup_service._try_become_leader()

        assert result is True
        mock_etcd_client.try_acquire_leadership.assert_called_once()

    @pytest.mark.asyncio
    async def test_try_become_leader_fails(self, cleanup_service, mock_etcd_client):
        """Test failed leader election."""
        mock_etcd_client.try_acquire_leadership.return_value = False

        result = await cleanup_service._try_become_leader()

        assert result is False

    @pytest.mark.asyncio
    async def test_try_become_leader_handles_exception(self, cleanup_service, mock_etcd_client):
        """Test leader election handles etcd errors gracefully."""
        mock_etcd_client.try_acquire_leadership.side_effect = Exception("etcd unavailable")

        result = await cleanup_service._try_become_leader()

        assert result is False


# =============================================================================
# Cleanup Execution Tests
# =============================================================================


class TestCleanupExecution:
    """Tests for the actual cleanup operation."""

    @pytest.mark.asyncio
    async def test_run_cleanup_success_with_deletions(self, cleanup_service, mock_api_client):
        """Test successful cleanup that deletes workers."""
        mock_api_client.cleanup_terminated_workers.return_value = {
            "deleted_count": 3,
            "total_checked": 10,
            "deleted_ids": ["w-1", "w-2", "w-3"],
        }

        await cleanup_service._run_cleanup()

        assert cleanup_service._cleanup_runs == 1
        assert cleanup_service._last_cleanup_at is not None
        assert cleanup_service._last_cleanup_result["deleted_count"] == 3
        mock_api_client.cleanup_terminated_workers.assert_called_once_with(
            retention_days=30,
            dry_run=False,
        )

    @pytest.mark.asyncio
    async def test_run_cleanup_success_with_no_deletions(self, cleanup_service, mock_api_client):
        """Test cleanup that finds nothing to delete."""
        mock_api_client.cleanup_terminated_workers.return_value = {
            "deleted_count": 0,
            "total_checked": 5,
        }

        await cleanup_service._run_cleanup()

        assert cleanup_service._cleanup_runs == 1
        assert cleanup_service._last_cleanup_result["deleted_count"] == 0

    @pytest.mark.asyncio
    async def test_run_cleanup_api_failure(self, cleanup_service, mock_api_client):
        """Test cleanup handles API errors gracefully."""
        mock_api_client.cleanup_terminated_workers.side_effect = Exception("API timeout")

        await cleanup_service._run_cleanup()

        # Should not increment runs on failure
        assert cleanup_service._cleanup_runs == 0
        assert cleanup_service._last_cleanup_result == {"error": "API timeout"}

    @pytest.mark.asyncio
    async def test_run_cleanup_uses_configured_retention(self, cleanup_service, mock_api_client):
        """Test that cleanup uses retention days from settings."""
        cleanup_service._settings.cleanup_retention_days = 60

        await cleanup_service._run_cleanup()

        mock_api_client.cleanup_terminated_workers.assert_called_once_with(
            retention_days=60,
            dry_run=False,
        )

    @pytest.mark.asyncio
    async def test_run_cleanup_increments_count(self, cleanup_service, mock_api_client):
        """Test that multiple cleanup runs increment the counter."""
        await cleanup_service._run_cleanup()
        await cleanup_service._run_cleanup()
        await cleanup_service._run_cleanup()

        assert cleanup_service._cleanup_runs == 3

    @pytest.mark.asyncio
    async def test_run_cleanup_records_timestamp(self, cleanup_service, mock_api_client):
        """Test that cleanup records an ISO timestamp."""
        await cleanup_service._run_cleanup()

        ts = cleanup_service._last_cleanup_at
        assert ts is not None
        # Should be a valid ISO 8601 timestamp
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None  # timezone-aware

    @pytest.mark.asyncio
    async def test_stats_update_after_cleanup(self, cleanup_service, mock_api_client):
        """Test that stats reflect cleanup results."""
        mock_api_client.cleanup_terminated_workers.return_value = {
            "deleted_count": 5,
        }

        cleanup_service._is_leader = True
        await cleanup_service._run_cleanup()

        stats = cleanup_service.stats
        assert stats["cleanup_runs"] == 1
        assert stats["last_cleanup_result"]["deleted_count"] == 5
        assert stats["is_leader"] is True


# =============================================================================
# Configure Tests
# =============================================================================


class TestCleanupServiceConfigure:
    """Tests for DI configuration."""

    def test_configure_registers_singleton(self):
        """Test that configure registers the service as a singleton."""
        from unittest.mock import MagicMock

        mock_services = MagicMock()
        settings = Settings()

        CleanupHostedService.configure(mock_services, settings)

        mock_services.add_singleton.assert_called_once()
        # Verify correct class was registered
        call_args = mock_services.add_singleton.call_args
        assert call_args[0][0] is CleanupHostedService
