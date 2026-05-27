"""Unit tests for WorkerReconciler WebSocket Integration (ADR-041 Phase 5).

Tests cover the reconciler's integration with the CmlWebSocketMonitorRegistry:
- _handle_running() calls ensure_monitoring() when WS enabled
- _handle_stopping() calls stop_monitoring()
- Metrics collection skips CML system_stats when WS connected
- Falls back to polling when WS not connected
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from application.hosted_services.worker_reconciler import WorkerReconciler
from integration.services.cml_websocket_monitor import CmlWebSocketMonitor
from integration.services.cml_websocket_registry import CmlWebSocketMonitorRegistry
from lcm_core.domain.entities import CMLWorkerReadModel

# =============================================================================
# Fixtures
# =============================================================================


def make_worker(
    worker_id: str = "worker-001",
    status: str = "running",
    desired_status: str = "running",
    ip_address: str = "10.0.0.1",
    ec2_instance_id: str = "i-abc123",
    cml_username: str = "admin",
    cml_password: str = "pass",
) -> CMLWorkerReadModel:
    """Create a CMLWorkerReadModel for testing."""
    return CMLWorkerReadModel(
        id=worker_id,
        name=f"cml-{worker_id}",
        status=status,
        desired_status=desired_status,
        ip_address=ip_address,
        ec2_instance_id=ec2_instance_id,
        cml_username=cml_username,
        cml_password=cml_password,
    )


def make_reconciler_with_ws(
    ws_enabled: bool = True,
    ws_registry: CmlWebSocketMonitorRegistry | None = None,
) -> WorkerReconciler:
    """Create a WorkerReconciler with mocked dependencies and WS registry.

    Uses object.__new__ to skip the complex __init__ (requires etcd, AWS, etc.).
    """
    reconciler = object.__new__(WorkerReconciler)

    # Mock settings
    reconciler._settings = MagicMock()
    reconciler._settings.cml_websocket_enabled = ws_enabled
    reconciler._settings.scale_down_enabled = False
    reconciler._settings.min_workers = 1

    # Mock API client
    reconciler._api = MagicMock()
    reconciler._api.update_worker_status = AsyncMock()
    reconciler._api.update_worker_ec2_details = AsyncMock()
    reconciler._api.report_worker_metrics = AsyncMock()

    # Mock EC2 client
    reconciler._ec2 = MagicMock()
    reconciler._ec2.get_instance_state = AsyncMock(return_value=MagicMock(state="running", public_ip="10.0.0.1", private_ip="10.0.0.1"))
    reconciler._ec2.stop_instance = AsyncMock()
    reconciler._ec2.describe_image = AsyncMock(return_value=None)

    # Mock CloudWatch client
    reconciler._cloudwatch = MagicMock()
    reconciler._cloudwatch.get_ec2_metrics = AsyncMock(return_value=MagicMock(cpu_utilization=25.0, network_in_bytes=1000, network_out_bytes=500))

    # Mock CML client
    reconciler._cml = MagicMock()
    reconciler._cml.get_system_stats = AsyncMock()
    reconciler._cml.get_telemetry_events = AsyncMock(return_value=[])
    reconciler._cml.check_health = AsyncMock(return_value=(True, "CML 2.9 ready"))

    # WebSocket registry
    if ws_registry is None and ws_enabled:
        ws_registry = MagicMock(spec=CmlWebSocketMonitorRegistry)
        ws_registry.ensure_monitoring = AsyncMock()
        ws_registry.stop_monitoring = AsyncMock()
        ws_registry.get_monitor = MagicMock(return_value=None)
    reconciler._ws_registry = ws_registry

    # Internal state
    reconciler._running_worker_count = 3
    reconciler._scale_down_count = 0
    reconciler._last_scale_down_at = None
    reconciler._metrics_collected_count = 0
    reconciler._activity_checks_count = 0
    reconciler._auto_pauses_triggered_count = 0
    reconciler._license_registrations_count = 0
    reconciler._license_deregistrations_count = 0

    return reconciler


# =============================================================================
# Tests: _handle_running() — WebSocket Integration
# =============================================================================


class TestHandleRunningWSIntegration:
    """Test _handle_running() calls ensure_monitoring() when WS enabled."""

    @pytest.mark.asyncio
    async def test_calls_ensure_monitoring_when_ws_enabled(self):
        """_handle_running() calls ensure_monitoring() for RUNNING worker with WS enabled."""
        reconciler = make_reconciler_with_ws(ws_enabled=True)
        worker = make_worker()

        # Need to mock helper methods called by _handle_running
        reconciler._reconcile_license = AsyncMock()
        reconciler._handle_on_demand_refresh = AsyncMock()

        await reconciler._handle_running(worker)

        reconciler._ws_registry.ensure_monitoring.assert_called_once()
        call_kwargs = reconciler._ws_registry.ensure_monitoring.call_args
        assert call_kwargs[1]["worker_id"] == "worker-001" or call_kwargs[0][0] == "worker-001"

    @pytest.mark.asyncio
    async def test_does_not_call_ensure_monitoring_when_ws_disabled(self):
        """_handle_running() skips ensure_monitoring when cml_websocket_enabled=False."""
        reconciler = make_reconciler_with_ws(ws_enabled=False, ws_registry=None)
        worker = make_worker()

        reconciler._reconcile_license = AsyncMock()
        reconciler._handle_on_demand_refresh = AsyncMock()

        result = await reconciler._handle_running(worker)

        # No ws_registry → no call
        # Verify no error occurred
        assert result is not None

    @pytest.mark.asyncio
    async def test_does_not_call_ensure_monitoring_when_no_ip(self):
        """_handle_running() skips ensure_monitoring if worker has no IP and EC2 has no IP."""
        reconciler = make_reconciler_with_ws(ws_enabled=True)
        # Worker has no IP AND EC2 returns no public/private IP either
        reconciler._ec2.get_instance_state = AsyncMock(return_value=MagicMock(state="running", public_ip=None, private_ip=None, instance_type="m5zn.metal", image_id=None))
        worker = make_worker(ip_address="")

        reconciler._reconcile_license = AsyncMock()
        reconciler._handle_on_demand_refresh = AsyncMock()

        await reconciler._handle_running(worker)

        reconciler._ws_registry.ensure_monitoring.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_monitoring_error_does_not_block_reconciliation(self):
        """_handle_running() continues if ensure_monitoring() raises."""
        reconciler = make_reconciler_with_ws(ws_enabled=True)
        reconciler._ws_registry.ensure_monitoring = AsyncMock(side_effect=Exception("WS connect failed"))
        worker = make_worker()

        reconciler._reconcile_license = AsyncMock()
        reconciler._handle_on_demand_refresh = AsyncMock()

        # Should not raise — logs warning and continues
        result = await reconciler._handle_running(worker)
        assert result is not None


# =============================================================================
# Tests: _handle_stopping() — WebSocket Teardown
# =============================================================================


class TestHandleStoppingWSIntegration:
    """Test _handle_stopping() calls stop_monitoring()."""

    @pytest.mark.asyncio
    async def test_calls_stop_monitoring_when_ws_enabled(self):
        """_handle_stopping() disconnects WS monitor before stopping EC2."""
        reconciler = make_reconciler_with_ws(ws_enabled=True)
        worker = make_worker(status="stopping")

        await reconciler._handle_stopping(worker)

        reconciler._ws_registry.stop_monitoring.assert_called_once_with("worker-001")

    @pytest.mark.asyncio
    async def test_does_not_call_stop_monitoring_when_ws_disabled(self):
        """_handle_stopping() skips stop_monitoring when WS disabled."""
        reconciler = make_reconciler_with_ws(ws_enabled=False, ws_registry=None)
        worker = make_worker(status="stopping")

        result = await reconciler._handle_stopping(worker)
        # No exception raised; ws_registry is None
        assert result is not None


# =============================================================================
# Tests: Metrics collection — WS-connected skip vs polling fallback
# =============================================================================


class TestMetricsCollectionWSFallback:
    """Test that metrics collection skips CML REST poll when WS is connected."""

    @pytest.mark.asyncio
    async def test_skips_cml_poll_when_ws_connected(self):
        """_collect_and_report_metrics skips CML system_stats when WS monitor is connected."""
        reconciler = make_reconciler_with_ws(ws_enabled=True)
        worker = make_worker()

        # Create a mock WS monitor that is connected with stats
        mock_monitor = MagicMock(spec=CmlWebSocketMonitor)
        mock_monitor.is_connected = True
        mock_monitor.latest_system_stats = MagicMock(
            cpu=MagicMock(percent=12.5),
            memory=MagicMock(total=200000000000, used=50000000000, free=150000000000),
            disk=MagicMock(total=300000000000, used=100000000000, free=200000000000),
        )
        reconciler._ws_registry.get_monitor = MagicMock(return_value=mock_monitor)

        # Mock _collect_and_report_cml_data to avoid deeper calls
        reconciler._collect_and_report_cml_data = AsyncMock()
        reconciler._report_ec2_details = AsyncMock()

        await reconciler._collect_and_report_metrics(worker)

        # CML REST poll should NOT have been called
        reconciler._cml.get_system_stats.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_cml_poll_when_ws_not_connected(self):
        """_collect_and_report_metrics polls CML REST API when WS is not connected."""
        reconciler = make_reconciler_with_ws(ws_enabled=True)
        worker = make_worker()

        # WS monitor not connected
        mock_monitor = MagicMock(spec=CmlWebSocketMonitor)
        mock_monitor.is_connected = False
        mock_monitor.latest_system_stats = None
        reconciler._ws_registry.get_monitor = MagicMock(return_value=mock_monitor)

        # Mock CML stats response
        mock_stats = MagicMock()
        mock_stats.cpu.percent = 5.0
        mock_stats.memory.total = 200000000000
        mock_stats.memory.used = 30000000000
        mock_stats.memory.free = 170000000000
        mock_stats.disk.total = 300000000000
        mock_stats.disk.used = 80000000000
        mock_stats.disk.free = 220000000000
        reconciler._cml.get_system_stats = AsyncMock(return_value=mock_stats)

        reconciler._collect_and_report_cml_data = AsyncMock()
        reconciler._report_ec2_details = AsyncMock()

        await reconciler._collect_and_report_metrics(worker)

        # CML REST poll SHOULD have been called as fallback
        reconciler._cml.get_system_stats.assert_called_once()

    @pytest.mark.asyncio
    async def test_falls_back_to_poll_when_no_ws_registry(self):
        """_collect_and_report_metrics polls CML when ws_registry is None."""
        reconciler = make_reconciler_with_ws(ws_enabled=False, ws_registry=None)
        worker = make_worker()

        mock_stats = MagicMock()
        mock_stats.cpu.percent = 10.0
        mock_stats.memory.total = 200000000000
        mock_stats.memory.used = 40000000000
        mock_stats.memory.free = 160000000000
        mock_stats.disk.total = 300000000000
        mock_stats.disk.used = 90000000000
        mock_stats.disk.free = 210000000000
        reconciler._cml.get_system_stats = AsyncMock(return_value=mock_stats)

        reconciler._collect_and_report_cml_data = AsyncMock()
        reconciler._report_ec2_details = AsyncMock()

        await reconciler._collect_and_report_metrics(worker)

        reconciler._cml.get_system_stats.assert_called_once()

    @pytest.mark.asyncio
    async def test_falls_back_when_ws_connected_but_no_stats_yet(self):
        """Falls back to polling when WS is connected but hasn't received stats yet."""
        reconciler = make_reconciler_with_ws(ws_enabled=True)
        worker = make_worker()

        mock_monitor = MagicMock(spec=CmlWebSocketMonitor)
        mock_monitor.is_connected = True
        mock_monitor.latest_system_stats = None  # No stats received yet
        reconciler._ws_registry.get_monitor = MagicMock(return_value=mock_monitor)

        mock_stats = MagicMock()
        mock_stats.cpu.percent = 8.0
        mock_stats.memory.total = 200000000000
        mock_stats.memory.used = 45000000000
        mock_stats.memory.free = 155000000000
        mock_stats.disk.total = 300000000000
        mock_stats.disk.used = 95000000000
        mock_stats.disk.free = 205000000000
        reconciler._cml.get_system_stats = AsyncMock(return_value=mock_stats)

        reconciler._collect_and_report_cml_data = AsyncMock()
        reconciler._report_ec2_details = AsyncMock()

        await reconciler._collect_and_report_metrics(worker)

        # Should fall back since latest_system_stats is None
        reconciler._cml.get_system_stats.assert_called_once()
