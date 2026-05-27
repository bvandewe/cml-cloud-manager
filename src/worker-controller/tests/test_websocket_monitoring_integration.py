"""Integration tests for WebSocket Monitoring (ADR-041 Phase 5).

End-to-end flow: Mock CML WS server → CmlWebSocketMonitor → callbacks → CPA reporting.
Graceful degradation: Kill WS → polling resumes → WS reconnects.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from integration.services.cml_websocket_monitor import (
    CmlWebSocketMonitor,
    ConnectionStatus,
)
from integration.services.cml_websocket_registry import CmlWebSocketMonitorRegistry

# =============================================================================
# Sample CML WS Messages (from Phase 0 validation)
# =============================================================================

SYSTEM_STATS_MSG = json.dumps(
    {
        "event_type": "system_stats",
        "data": {
            "computes": {
                "compute-1": {
                    "hostname": "ip-172-31-38-11",
                    "is_controller": True,
                    "stats": {
                        "cpu": {"count": 48, "percent": 5.2},
                        "memory": {"total": 200000000000, "free": 180000000000, "used": 20000000000},
                        "disk": {"total": 300000000000, "free": 200000000000, "used": 100000000000},
                        "dominfo": {
                            "allocated_cpus": 8,
                            "allocated_memory": 16000000000,
                            "total_nodes": 10,
                            "total_orphans": 0,
                            "running_nodes": 6,
                            "running_orphans": 0,
                        },
                    },
                }
            },
            "all": {
                "cpu": {"count": 48, "percent": 5.2},
                "memory": {"total": 200000000000, "free": 180000000000, "used": 20000000000},
                "disk": {"total": 300000000000, "free": 200000000000, "used": 100000000000},
            },
            "controller": {"disk": {"total": 300000000000, "free": 200000000000, "used": 100000000000}},
        },
    }
)

LAB_STATE_CHANGE_MSG = json.dumps(
    {
        "event_type": "state_change",
        "element_type": "node",
        "element_id": "node-001",
        "event": "STARTED",
        "lab_id": "lab-abc-123",
    }
)

LAB_STATS_MSG = json.dumps(
    {
        "event_type": "lab_stats",
        "lab_id": "lab-abc-123",
        "data": {"nodes": {"node-001": {"cpu": 15.0, "memory": 1024000000}}},
    }
)


# =============================================================================
# Tests: Full flow — Monitor receives messages → invokes callbacks
# =============================================================================


class TestWebSocketMonitoringIntegrationFlow:
    """Integration test: WS message flow through monitor to callbacks."""

    @pytest.mark.asyncio
    async def test_system_stats_flow_to_callback(self):
        """system_stats received via WS → parsed → callback invoked with CmlSystemStats."""
        stats_received = []

        async def on_stats(worker_id, stats):
            stats_received.append((worker_id, stats))

        monitor = CmlWebSocketMonitor(
            worker_id="w1",
            host="10.0.0.1",
            username="admin",
            password="pass",  # pragma: allowlist secret
            metrics_report_interval=0,
            on_system_stats=on_stats,
        )

        # Simulate receiving a message (bypass WS connection)
        await monitor._handle_message(SYSTEM_STATS_MSG)

        assert len(stats_received) == 1
        worker_id, stats = stats_received[0]
        assert worker_id == "w1"
        assert stats.cpu.percent == 5.2
        assert stats.memory.total == 200000000000

    @pytest.mark.asyncio
    async def test_state_change_flow_to_callback_and_activity(self):
        """state_change received → invokes on_lab_state_change AND tracks activity."""
        state_changes = []

        async def on_state_change(worker_id, event):
            state_changes.append((worker_id, event))

        monitor = CmlWebSocketMonitor(
            worker_id="w1",
            host="10.0.0.1",
            username="admin",
            password="pass",  # pragma: allowlist secret
            on_lab_state_change=on_state_change,
        )

        await monitor._handle_message(LAB_STATE_CHANGE_MSG)

        # Callback invoked
        assert len(state_changes) == 1
        assert state_changes[0][0] == "w1"
        assert state_changes[0][1]["element_type"] == "node"
        assert state_changes[0][1]["event"] == "STARTED"

        # Activity tracked
        events = monitor.drain_activity_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "state_change"

    @pytest.mark.asyncio
    async def test_lab_stats_flow_to_callback(self):
        """lab_stats received → on_lab_stats callback invoked with parsed data."""
        lab_stats_received = []

        async def on_lab_stats(worker_id, lab_id, data):
            lab_stats_received.append((worker_id, lab_id, data))

        monitor = CmlWebSocketMonitor(
            worker_id="w1",
            host="10.0.0.1",
            username="admin",
            password="pass",  # pragma: allowlist secret
            on_lab_stats=on_lab_stats,
        )

        await monitor._handle_message(LAB_STATS_MSG)

        assert len(lab_stats_received) == 1
        assert lab_stats_received[0][0] == "w1"
        assert lab_stats_received[0][1] == "lab-abc-123"
        assert "nodes" in lab_stats_received[0][2]

    @pytest.mark.asyncio
    async def test_multiple_messages_sequential_processing(self):
        """Multiple messages are processed sequentially, each invoking correct callback."""
        stats_count = []
        state_count = []

        async def on_stats(wid, s):
            stats_count.append(1)

        async def on_state_change(wid, e):
            state_count.append(1)

        monitor = CmlWebSocketMonitor(
            worker_id="w1",
            host="10.0.0.1",
            username="admin",
            password="pass",  # pragma: allowlist secret
            metrics_report_interval=0,
            on_system_stats=on_stats,
            on_lab_state_change=on_state_change,
        )

        # Process a mixed stream of messages
        await monitor._handle_message(SYSTEM_STATS_MSG)
        await monitor._handle_message(LAB_STATE_CHANGE_MSG)
        await monitor._handle_message(SYSTEM_STATS_MSG)
        await monitor._handle_message(LAB_STATE_CHANGE_MSG)

        assert len(stats_count) == 2
        assert len(state_count) == 2


# =============================================================================
# Tests: Registry-mediated flow (ensure → receive → stop)
# =============================================================================


class TestRegistryIntegrationFlow:
    """Integration test: Registry lifecycle with monitor callbacks."""

    @pytest.mark.asyncio
    async def test_ensure_creates_monitor_with_callbacks(self):
        """Registry ensure_monitoring() creates monitor wired to caller's callbacks."""
        received_events = []

        async def on_stats(wid, s):
            received_events.append(("stats", wid))

        registry = CmlWebSocketMonitorRegistry(
            default_username="admin",
            default_password="pass",  # pragma: allowlist secret
            metrics_report_interval=0,
        )

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            monitor = await registry.ensure_monitoring(
                worker_id="w1",
                host="10.0.0.1",
                on_system_stats=on_stats,
            )

        # Directly invoke message handler to verify callback wiring
        await monitor._handle_message(SYSTEM_STATS_MSG)
        assert len(received_events) == 1
        assert received_events[0] == ("stats", "w1")

    @pytest.mark.asyncio
    async def test_stop_monitoring_disconnects_cleanly(self):
        """stop_monitoring() stops the monitor and removes from registry."""
        registry = CmlWebSocketMonitorRegistry(default_username="admin", default_password="pass")  # pragma: allowlist secret

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")

        assert registry.get_monitor("w1") is not None

        with patch.object(CmlWebSocketMonitor, "stop", new_callable=AsyncMock) as mock_stop:
            await registry.stop_monitoring("w1")

        assert registry.get_monitor("w1") is None
        mock_stop.assert_called_once()


# =============================================================================
# Tests: Graceful degradation (WS failure → fallback)
# =============================================================================


class TestGracefulDegradation:
    """Test graceful degradation when WebSocket fails."""

    @pytest.mark.asyncio
    async def test_monitor_enters_failed_state_after_max_retries(self):
        """Monitor transitions to FAILED after max reconnect attempts."""
        status_changes = []

        async def on_status(wid, status, reason):
            status_changes.append(status)

        monitor = CmlWebSocketMonitor(
            worker_id="w1",
            host="10.0.0.1",
            username="admin",
            password="pass",  # pragma: allowlist secret
            max_reconnect_attempts=2,
            reconnect_max_interval=0,
            on_connection_change=on_status,
        )

        with patch.object(monitor, "_connect_and_listen", side_effect=ConnectionError("refused")):
            await monitor._connection_loop()

        assert monitor.status == ConnectionStatus.FAILED
        assert ConnectionStatus.FAILED in status_changes

    @pytest.mark.asyncio
    async def test_registry_recreates_failed_monitor_on_next_ensure(self):
        """After FAILED, ensure_monitoring() creates a fresh monitor."""
        registry = CmlWebSocketMonitorRegistry(default_username="admin", default_password="pass")  # pragma: allowlist secret

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            monitor1 = await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")

        # Simulate failure
        monitor1._status = ConnectionStatus.FAILED

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            with patch.object(CmlWebSocketMonitor, "stop", new_callable=AsyncMock):
                monitor2 = await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")

        assert monitor2 is not monitor1
        assert monitor2.status != ConnectionStatus.FAILED

    @pytest.mark.asyncio
    async def test_connection_change_callback_on_disconnect(self):
        """Monitor invokes connection_change callback when losing connection."""
        statuses = []

        async def track(wid, status, reason):
            statuses.append((status, reason))

        monitor = CmlWebSocketMonitor(
            worker_id="w1",
            host="10.0.0.1",
            username="admin",
            password="pass",  # pragma: allowlist secret
            on_connection_change=track,
        )

        # Simulate connection cycle: connecting → connected → reconnecting
        await monitor._set_status(ConnectionStatus.CONNECTING)
        await monitor._set_status(ConnectionStatus.CONNECTED)
        await monitor._set_status(ConnectionStatus.RECONNECTING, reason="network timeout")

        assert statuses[0] == (ConnectionStatus.CONNECTING, None)
        assert statuses[1] == (ConnectionStatus.CONNECTED, None)
        assert statuses[2] == (ConnectionStatus.RECONNECTING, "network timeout")
