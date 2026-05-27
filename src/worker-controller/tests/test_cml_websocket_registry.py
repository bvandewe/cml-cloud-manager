"""Unit tests for CmlWebSocketMonitorRegistry (ADR-041 Phase 5).

Dedicated registry tests covering lifecycle management,
concurrent monitor operations, and status reporting.
"""

from unittest.mock import AsyncMock, patch

import pytest
from integration.services.cml_websocket_monitor import (
    CmlWebSocketMonitor,
    ConnectionStatus,
)
from integration.services.cml_websocket_registry import CmlWebSocketMonitorRegistry

# =============================================================================
# Tests: ensure_monitoring() — creation and idempotency
# =============================================================================


class TestRegistryEnsureMonitoring:
    """Test ensure_monitoring() creates and returns existing monitors."""

    @pytest.mark.asyncio
    async def test_creates_and_starts_new_monitor(self):
        """ensure_monitoring() creates a new monitor when none exists."""
        registry = CmlWebSocketMonitorRegistry(default_username="admin", default_password="pass")

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            monitor = await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")

        assert monitor is not None
        assert monitor.worker_id == "w1"
        assert monitor.host == "10.0.0.1"
        assert registry.get_monitor("w1") is monitor

    @pytest.mark.asyncio
    async def test_returns_existing_when_connected(self):
        """ensure_monitoring() returns existing monitor if CONNECTED."""
        registry = CmlWebSocketMonitorRegistry()

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            monitor1 = await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")
        monitor1._status = ConnectionStatus.CONNECTED

        monitor2 = await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")
        assert monitor2 is monitor1

    @pytest.mark.asyncio
    async def test_returns_existing_when_connecting(self):
        """ensure_monitoring() returns existing monitor if CONNECTING."""
        registry = CmlWebSocketMonitorRegistry()

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            monitor1 = await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")
        monitor1._status = ConnectionStatus.CONNECTING

        monitor2 = await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")
        assert monitor2 is monitor1

    @pytest.mark.asyncio
    async def test_returns_existing_when_reconnecting(self):
        """ensure_monitoring() returns existing monitor if RECONNECTING."""
        registry = CmlWebSocketMonitorRegistry()

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            monitor1 = await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")
        monitor1._status = ConnectionStatus.RECONNECTING

        monitor2 = await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")
        assert monitor2 is monitor1

    @pytest.mark.asyncio
    async def test_recreates_when_failed(self):
        """ensure_monitoring() tears down FAILED monitor and creates new one."""
        registry = CmlWebSocketMonitorRegistry()

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            monitor1 = await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")
        monitor1._status = ConnectionStatus.FAILED

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            with patch.object(CmlWebSocketMonitor, "stop", new_callable=AsyncMock):
                monitor2 = await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")

        assert monitor2 is not monitor1
        assert registry.get_monitor("w1") is monitor2

    @pytest.mark.asyncio
    async def test_starts_disconnected_monitor(self):
        """ensure_monitoring() starts a DISCONNECTED monitor without recreating."""
        registry = CmlWebSocketMonitorRegistry()

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            monitor1 = await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")

        # Monitor is in disconnected state (simulating post-stop but still registered)
        monitor1._status = ConnectionStatus.DISCONNECTED

        with patch.object(monitor1, "start", new_callable=AsyncMock) as mock_restart:
            monitor2 = await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")

        assert monitor2 is monitor1
        mock_restart.assert_called_once()

    @pytest.mark.asyncio
    async def test_passes_callbacks_to_new_monitor(self):
        """ensure_monitoring() passes all callbacks to the created monitor."""
        registry = CmlWebSocketMonitorRegistry(default_username="admin", default_password="secret")
        cb_stats = AsyncMock()
        cb_activity = AsyncMock()
        cb_lab_stats = AsyncMock()
        cb_state_change = AsyncMock()
        cb_connection = AsyncMock()

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            monitor = await registry.ensure_monitoring(
                worker_id="w1",
                host="10.0.0.1",
                on_system_stats=cb_stats,
                on_activity_event=cb_activity,
                on_lab_stats=cb_lab_stats,
                on_lab_state_change=cb_state_change,
                on_connection_change=cb_connection,
            )

        assert monitor._on_system_stats is cb_stats
        assert monitor._on_activity_event is cb_activity
        assert monitor._on_lab_stats is cb_lab_stats
        assert monitor._on_lab_state_change is cb_state_change
        assert monitor._on_connection_change is cb_connection

    @pytest.mark.asyncio
    async def test_uses_custom_credentials(self):
        """ensure_monitoring() uses per-worker credentials when provided."""
        registry = CmlWebSocketMonitorRegistry(default_username="default", default_password="default-pass")

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            monitor = await registry.ensure_monitoring(
                worker_id="w1",
                host="10.0.0.1",
                username="custom-user",
                password="custom-pass",  # pragma: allowlist secret
            )

        assert monitor._username == "custom-user"
        assert monitor._password == "custom-pass"  # pragma: allowlist secret

    @pytest.mark.asyncio
    async def test_recreates_when_host_changes(self):
        """ensure_monitoring() recreates monitor when host IP changes (private→public)."""
        registry = CmlWebSocketMonitorRegistry()

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            monitor1 = await registry.ensure_monitoring(worker_id="w1", host="172.31.38.11")
        monitor1._status = ConnectionStatus.CONNECTING  # Still trying to connect

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            with patch.object(CmlWebSocketMonitor, "stop", new_callable=AsyncMock):
                monitor2 = await registry.ensure_monitoring(worker_id="w1", host="54.80.245.250")

        assert monitor2 is not monitor1
        assert monitor2.host == "54.80.245.250"
        assert registry.get_monitor("w1") is monitor2

    @pytest.mark.asyncio
    async def test_passes_fallback_host_to_monitor(self):
        """ensure_monitoring() passes fallback_host to the created monitor."""
        registry = CmlWebSocketMonitorRegistry(default_username="admin", default_password="secret")

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            monitor = await registry.ensure_monitoring(
                worker_id="w1",
                host="172.31.38.11",
                fallback_host="54.80.245.250",
            )

        assert monitor._fallback_host == "54.80.245.250"


# =============================================================================
# Tests: stop_monitoring() and stop_all()
# =============================================================================


class TestRegistryStopMonitoring:
    """Test stop_monitoring() and stop_all()."""

    @pytest.mark.asyncio
    async def test_stop_monitoring_stops_and_removes(self):
        """stop_monitoring() calls stop() and removes from registry."""
        registry = CmlWebSocketMonitorRegistry()

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")

        with patch.object(CmlWebSocketMonitor, "stop", new_callable=AsyncMock) as mock_stop:
            await registry.stop_monitoring("w1")

        assert registry.get_monitor("w1") is None
        mock_stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_monitoring_nonexistent_is_safe(self):
        """stop_monitoring() for unknown worker_id is a no-op."""
        registry = CmlWebSocketMonitorRegistry()
        await registry.stop_monitoring("does-not-exist")
        # No exception raised

    @pytest.mark.asyncio
    async def test_stop_all_stops_all_monitors(self):
        """stop_all() stops and removes all registered monitors."""
        registry = CmlWebSocketMonitorRegistry()

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")
            await registry.ensure_monitoring(worker_id="w2", host="10.0.0.2")
            await registry.ensure_monitoring(worker_id="w3", host="10.0.0.3")

        with patch.object(CmlWebSocketMonitor, "stop", new_callable=AsyncMock) as mock_stop:
            await registry.stop_all()

        assert registry.get_monitor("w1") is None
        assert registry.get_monitor("w2") is None
        assert registry.get_monitor("w3") is None
        assert mock_stop.call_count == 3

    @pytest.mark.asyncio
    async def test_stop_all_on_empty_registry(self):
        """stop_all() on empty registry is a no-op."""
        registry = CmlWebSocketMonitorRegistry()
        await registry.stop_all()
        assert registry.active_count == 0


# =============================================================================
# Tests: Status and properties
# =============================================================================


class TestRegistryStatus:
    """Test status reporting and property accessors."""

    @pytest.mark.asyncio
    async def test_active_count_excludes_disconnected(self):
        """active_count counts monitors in any status except DISCONNECTED."""
        registry = CmlWebSocketMonitorRegistry()

        m1 = CmlWebSocketMonitor(worker_id="w1", host="10.0.0.1", username="a", password="p")
        m2 = CmlWebSocketMonitor(worker_id="w2", host="10.0.0.2", username="a", password="p")
        m3 = CmlWebSocketMonitor(worker_id="w3", host="10.0.0.3", username="a", password="p")

        m1._status = ConnectionStatus.CONNECTED
        m2._status = ConnectionStatus.RECONNECTING
        m3._status = ConnectionStatus.DISCONNECTED

        registry._monitors = {"w1": m1, "w2": m2, "w3": m3}

        assert registry.active_count == 2

    @pytest.mark.asyncio
    async def test_connected_count_only_connected(self):
        """connected_count counts only CONNECTED monitors."""
        registry = CmlWebSocketMonitorRegistry()

        m1 = CmlWebSocketMonitor(worker_id="w1", host="10.0.0.1", username="a", password="p")
        m2 = CmlWebSocketMonitor(worker_id="w2", host="10.0.0.2", username="a", password="p")

        m1._status = ConnectionStatus.CONNECTED
        m2._status = ConnectionStatus.RECONNECTING

        registry._monitors = {"w1": m1, "w2": m2}

        assert registry.connected_count == 1

    def test_get_status_summary_structure(self):
        """get_status_summary() returns expected dict shape."""
        registry = CmlWebSocketMonitorRegistry()

        m1 = CmlWebSocketMonitor(worker_id="w1", host="10.0.0.1", username="a", password="p")
        m1._status = ConnectionStatus.CONNECTED
        registry._monitors = {"w1": m1}

        summary = registry.get_status_summary()
        assert summary["total"] == 1
        assert summary["active"] == 1
        assert summary["connected"] == 1
        assert "w1" in summary["monitors"]
        assert summary["monitors"]["w1"]["host"] == "10.0.0.1"
        assert summary["monitors"]["w1"]["status"] == "connected"
