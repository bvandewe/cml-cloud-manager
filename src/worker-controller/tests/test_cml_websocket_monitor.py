"""Unit tests for CML WebSocket Monitor (ADR-041).

Tests the CmlWebSocketMonitor and CmlWebSocketMonitorRegistry classes
including connection lifecycle, message parsing, callbacks, and reconnection.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import websockets.exceptions
from integration.services.cml_system_spi import CmlSystemStats
from integration.services.cml_websocket_monitor import (
    ACTIVITY_LAB_EVENT_STATES,
    ACTIVITY_STATE_CHANGE_NODE_EVENTS,
    CmlWebSocketMonitor,
    ConnectionStatus,
)
from integration.services.cml_websocket_registry import CmlWebSocketMonitorRegistry

# =============================================================================
# Test Fixtures — Real CML WebSocket Event Samples (from Phase 0 validation)
# =============================================================================

SAMPLE_SYSTEM_STATS_EVENT = {
    "event_type": "system_stats",
    "data": {
        "computes": {
            "435a7bac-882a-4edd-a8f3-f4ea9307cb52": {
                "hostname": "ip-172-31-38-11",
                "is_controller": True,
                "stats": {
                    "cpu": {"count": 48, "percent": 0.49},
                    "memory": {"total": 202422902784, "free": 199086161920, "used": 2033487872},
                    "disk": {"total": 266206101504, "free": 128413523968, "used": 137792577536},
                    "dominfo": {
                        "allocated_cpus": 4,
                        "allocated_memory": 8589934592,
                        "total_nodes": 5,
                        "total_orphans": 0,
                        "running_nodes": 3,
                        "running_orphans": 0,
                    },
                },
            }
        },
        "all": {
            "cpu": {"count": 48, "percent": 0.49},
            "memory": {"total": 202422902784, "free": 199086161920, "used": 2033487872},
            "disk": {"total": 266206101504, "free": 128413523968, "used": 137792577536},
        },
        "controller": {"disk": {"total": 266206101504, "free": 128413519872, "used": 137775804416}},
    },
}

SAMPLE_LAB_STATS_EVENT = {
    "event_type": "lab_stats",
    "lab_id": "lab-123-abc",
    "data": {
        "nodes": {"node1": {"cpu": 25.0, "memory": 512000000}},
        "links": {"link1": {"tx_bytes": 1024, "rx_bytes": 2048}},
    },
}

SAMPLE_STATE_CHANGE_NODE_STARTED = {
    "event_type": "state_change",
    "element_type": "node",
    "element_id": "node-001",
    "event": "STARTED",
    "lab_id": "lab-123-abc",
}

SAMPLE_STATE_CHANGE_NODE_BOOTED = {
    "event_type": "state_change",
    "element_type": "node",
    "element_id": "node-001",
    "event": "BOOTED",
    "lab_id": "lab-123-abc",
}

SAMPLE_STATE_CHANGE_INTERFACE = {
    "event_type": "state_change",
    "element_type": "interface",
    "element_id": "iface-001",
    "event": "STARTED",
    "lab_id": "lab-123-abc",
}

SAMPLE_LAB_EVENT_STARTED = {
    "event_type": "lab_event",
    "event": "state",
    "lab_id": "lab-123-abc",
    "data": {"state": "STARTED", "lab_title": "Test Lab"},
}

SAMPLE_LAB_EVENT_STOPPED = {
    "event_type": "lab_event",
    "event": "state",
    "lab_id": "lab-123-abc",
    "data": {"state": "STOPPED", "lab_title": "Test Lab"},
}

SAMPLE_LAB_EVENT_OTHER = {
    "event_type": "lab_event",
    "event": "topology",
    "lab_id": "lab-123-abc",
    "data": {"nodes_count": 5},
}


# =============================================================================
# Helper: Create monitor with defaults
# =============================================================================


def create_monitor(**kwargs) -> CmlWebSocketMonitor:
    """Create a CmlWebSocketMonitor with test defaults."""
    defaults = {
        "worker_id": "worker-001",
        "host": "192.168.1.100",
        "username": "admin",
        "password": "secret",  # pragma: allowlist secret
        "verify_ssl": False,
        "metrics_report_interval": 0,  # No throttling in tests
        "reconnect_max_interval": 1,
        "max_reconnect_attempts": 3,
    }
    defaults.update(kwargs)
    return CmlWebSocketMonitor(**defaults)


# =============================================================================
# Tests: CmlWebSocketMonitor — Initialization
# =============================================================================


class TestCmlWebSocketMonitorInit:
    """Test monitor initialization and properties."""

    def test_initial_status_is_disconnected(self):
        monitor = create_monitor()
        assert monitor.status == ConnectionStatus.DISCONNECTED

    def test_is_connected_false_initially(self):
        monitor = create_monitor()
        assert monitor.is_connected is False

    def test_worker_id_property(self):
        monitor = create_monitor(worker_id="my-worker")
        assert monitor.worker_id == "my-worker"

    def test_host_property(self):
        monitor = create_monitor(host="10.0.0.1")
        assert monitor.host == "10.0.0.1"

    def test_last_message_at_none_initially(self):
        monitor = create_monitor()
        assert monitor.last_message_at is None

    def test_latest_system_stats_none_initially(self):
        monitor = create_monitor()
        assert monitor.latest_system_stats is None

    def test_recent_activity_events_empty_initially(self):
        monitor = create_monitor()
        assert monitor.recent_activity_events == []


# =============================================================================
# Tests: CmlWebSocketMonitor — Message Handling
# =============================================================================


class TestCmlWebSocketMonitorMessageHandling:
    """Test message parsing and routing."""

    @pytest.mark.asyncio
    async def test_handle_system_stats_parses_dto(self):
        monitor = create_monitor()
        await monitor._handle_message(json.dumps(SAMPLE_SYSTEM_STATS_EVENT))

        assert monitor.latest_system_stats is not None
        assert monitor.latest_system_stats.cpu.percent == 0.49
        assert monitor.latest_system_stats.memory.total == 202422902784
        assert len(monitor.latest_system_stats.computes) == 1

    @pytest.mark.asyncio
    async def test_handle_system_stats_invokes_callback(self):
        callback = AsyncMock()
        monitor = create_monitor(on_system_stats=callback)
        await monitor._handle_message(json.dumps(SAMPLE_SYSTEM_STATS_EVENT))

        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "worker-001"
        assert isinstance(args[1], CmlSystemStats)

    @pytest.mark.asyncio
    async def test_handle_system_stats_throttles_callback(self):
        callback = AsyncMock()
        monitor = create_monitor(on_system_stats=callback, metrics_report_interval=10)

        # First call goes through
        await monitor._handle_message(json.dumps(SAMPLE_SYSTEM_STATS_EVENT))
        assert callback.call_count == 1

        # Second call within interval is throttled
        await monitor._handle_message(json.dumps(SAMPLE_SYSTEM_STATS_EVENT))
        assert callback.call_count == 1  # Still 1

    @pytest.mark.asyncio
    async def test_handle_system_stats_unthrottles_after_interval(self):
        """Callback fires again after metrics_report_interval elapses."""
        callback = AsyncMock()
        monitor = create_monitor(on_system_stats=callback, metrics_report_interval=1)

        # First call goes through
        await monitor._handle_message(json.dumps(SAMPLE_SYSTEM_STATS_EVENT))
        assert callback.call_count == 1

        # Simulate time passing beyond the interval
        monitor._last_metrics_report_at -= 2  # 2 seconds before now
        await monitor._handle_message(json.dumps(SAMPLE_SYSTEM_STATS_EVENT))
        assert callback.call_count == 2  # Now goes through

    @pytest.mark.asyncio
    async def test_handle_lab_stats_invokes_callback(self):
        callback = AsyncMock()
        monitor = create_monitor(on_lab_stats=callback)
        await monitor._handle_message(json.dumps(SAMPLE_LAB_STATS_EVENT))

        callback.assert_called_once_with(
            "worker-001",
            "lab-123-abc",
            SAMPLE_LAB_STATS_EVENT["data"],
        )

    @pytest.mark.asyncio
    async def test_handle_lab_stats_no_lab_id_skipped(self):
        callback = AsyncMock()
        monitor = create_monitor(on_lab_stats=callback)
        msg = {**SAMPLE_LAB_STATS_EVENT, "lab_id": ""}
        await monitor._handle_message(json.dumps(msg))

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_state_change_node_started_tracked_as_activity(self):
        monitor = create_monitor()
        await monitor._handle_message(json.dumps(SAMPLE_STATE_CHANGE_NODE_STARTED))

        events = monitor.recent_activity_events
        assert len(events) == 1
        assert events[0]["event_type"] == "state_change"
        assert events[0]["element_type"] == "node"
        assert events[0]["event"] == "STARTED"

    @pytest.mark.asyncio
    async def test_handle_state_change_node_booted_not_tracked(self):
        """BOOTED is not in ACTIVITY_STATE_CHANGE_NODE_EVENTS."""
        monitor = create_monitor()
        await monitor._handle_message(json.dumps(SAMPLE_STATE_CHANGE_NODE_BOOTED))

        assert len(monitor.recent_activity_events) == 0

    @pytest.mark.asyncio
    async def test_handle_state_change_interface_not_tracked(self):
        """Only element_type=='node' is tracked for activity."""
        monitor = create_monitor()
        await monitor._handle_message(json.dumps(SAMPLE_STATE_CHANGE_INTERFACE))

        assert len(monitor.recent_activity_events) == 0

    @pytest.mark.asyncio
    async def test_handle_state_change_invokes_callback(self):
        callback = AsyncMock()
        monitor = create_monitor(on_lab_state_change=callback)
        await monitor._handle_message(json.dumps(SAMPLE_STATE_CHANGE_NODE_STARTED))

        callback.assert_called_once_with("worker-001", SAMPLE_STATE_CHANGE_NODE_STARTED)

    @pytest.mark.asyncio
    async def test_handle_lab_event_started_tracked_as_activity(self):
        monitor = create_monitor()
        await monitor._handle_message(json.dumps(SAMPLE_LAB_EVENT_STARTED))

        events = monitor.recent_activity_events
        assert len(events) == 1
        assert events[0]["event_type"] == "lab_event"
        assert events[0]["state"] == "STARTED"

    @pytest.mark.asyncio
    async def test_handle_lab_event_stopped_tracked_as_activity(self):
        monitor = create_monitor()
        await monitor._handle_message(json.dumps(SAMPLE_LAB_EVENT_STOPPED))

        events = monitor.recent_activity_events
        assert len(events) == 1
        assert events[0]["state"] == "STOPPED"

    @pytest.mark.asyncio
    async def test_handle_lab_event_other_not_tracked(self):
        """Non-state lab_events are not tracked as activity."""
        monitor = create_monitor()
        await monitor._handle_message(json.dumps(SAMPLE_LAB_EVENT_OTHER))

        assert len(monitor.recent_activity_events) == 0

    @pytest.mark.asyncio
    async def test_handle_lab_event_invokes_activity_callback(self):
        callback = AsyncMock()
        monitor = create_monitor(on_activity_event=callback)
        await monitor._handle_message(json.dumps(SAMPLE_LAB_EVENT_STARTED))

        callback.assert_called_once_with("worker-001", SAMPLE_LAB_EVENT_STARTED)

    @pytest.mark.asyncio
    async def test_handle_lab_event_state_invokes_lab_state_change_callback(self):
        """lab_event with event=state routes through on_lab_state_change for LabRecord update."""
        callback = AsyncMock()
        monitor = create_monitor(on_lab_state_change=callback)
        await monitor._handle_message(json.dumps(SAMPLE_LAB_EVENT_STOPPED))

        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "worker-001"
        event = args[1]
        assert event["event"] == "STOPPED"
        assert event["element_type"] == "lab"
        assert event["lab_id"] == "lab-123-abc"
        assert event["element_id"] == "lab-123-abc"

    @pytest.mark.asyncio
    async def test_handle_lab_event_non_state_does_not_invoke_lab_state_change(self):
        """Non-state lab_events (e.g. topology) do not route through on_lab_state_change."""
        callback = AsyncMock()
        monitor = create_monitor(on_lab_state_change=callback)
        await monitor._handle_message(json.dumps(SAMPLE_LAB_EVENT_OTHER))

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_unknown_event_type_no_error(self):
        """Unknown event types are silently ignored."""
        monitor = create_monitor()
        msg = {"event_type": "unknown_future_event", "data": {}}
        await monitor._handle_message(json.dumps(msg))
        # No exception raised

    @pytest.mark.asyncio
    async def test_handle_invalid_json_no_error(self):
        """Non-JSON messages are silently logged and ignored."""
        monitor = create_monitor()
        await monitor._handle_message("not json at all {{{")
        # No exception raised

    @pytest.mark.asyncio
    async def test_handle_message_without_event_type(self):
        """Messages without event_type are ignored."""
        monitor = create_monitor()
        await monitor._handle_message(json.dumps({"data": "something"}))
        # No exception raised

    @pytest.mark.asyncio
    async def test_handle_bytes_message(self):
        """Binary (bytes) messages are decoded and handled."""
        callback = AsyncMock()
        monitor = create_monitor(on_system_stats=callback)
        raw_bytes = json.dumps(SAMPLE_SYSTEM_STATS_EVENT).encode("utf-8")
        await monitor._handle_message(raw_bytes)

        callback.assert_called_once()


# =============================================================================
# Tests: CmlWebSocketMonitor — Activity Event Drain
# =============================================================================


class TestCmlWebSocketMonitorDrain:
    """Test drain_activity_events behavior."""

    @pytest.mark.asyncio
    async def test_drain_returns_and_clears_events(self):
        monitor = create_monitor()
        await monitor._handle_message(json.dumps(SAMPLE_STATE_CHANGE_NODE_STARTED))
        await monitor._handle_message(json.dumps(SAMPLE_LAB_EVENT_STARTED))

        assert len(monitor.recent_activity_events) == 2

        drained = monitor.drain_activity_events()
        assert len(drained) == 2
        assert len(monitor.recent_activity_events) == 0

    @pytest.mark.asyncio
    async def test_drain_empty_returns_empty_list(self):
        monitor = create_monitor()
        drained = monitor.drain_activity_events()
        assert drained == []


# =============================================================================
# Tests: CmlWebSocketMonitor — Authentication
# =============================================================================


class TestCmlWebSocketMonitorAuth:
    """Test token acquisition."""

    @pytest.mark.asyncio
    async def test_get_token_calls_authenticate_endpoint(self):
        monitor = create_monitor(host="10.0.0.1", username="admin", password="pass123")  # pragma: allowlist secret

        mock_response = MagicMock()
        mock_response.json.return_value = "jwt-token-value"
        mock_response.raise_for_status = MagicMock()

        with patch("integration.services.cml_websocket_monitor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            token = await monitor._get_token()

        assert token == "jwt-token-value"
        mock_client.post.assert_called_once_with(
            "https://10.0.0.1/api/v0/authenticate",
            json={"username": "admin", "password": "pass123"},  # pragma: allowlist secret
        )

    @pytest.mark.asyncio
    async def test_get_token_caches_result(self):
        monitor = create_monitor()

        mock_response = MagicMock()
        mock_response.json.return_value = "cached-token"
        mock_response.raise_for_status = MagicMock()

        with patch("integration.services.cml_websocket_monitor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            token1 = await monitor._get_token()
            token2 = await monitor._get_token()

        assert token1 == token2 == "cached-token"
        # Only called once due to caching
        assert mock_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_token_cache_cleared_on_unauthorized_close(self):
        """Token cache is invalidated when CML sends close code 3000 (Unauthorized)."""
        monitor = create_monitor()
        monitor._token_cache = "stale-token"

        # Simulate ConnectionClosedError with unauthorized code
        from integration.services.cml_websocket_monitor import WS_CLOSE_UNAUTHORIZED

        close_exc = websockets.exceptions.ConnectionClosedError(MagicMock(code=WS_CLOSE_UNAUTHORIZED, reason="Unauthorized"), None)

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=close_exc)

        monitor._stop_event = asyncio.Event()
        with pytest.raises(ConnectionError, match="CML closed connection"):
            await monitor._read_loop(mock_ws)

        # Token cache should be cleared for re-authentication
        assert monitor._token_cache is None

    @pytest.mark.asyncio
    async def test_token_refreshed_after_reconnect(self):
        """After token cache is cleared, next _get_token() fetches a new token."""
        monitor = create_monitor()
        monitor._token_cache = "old-token"

        # Clear cache (simulating what happens on 3000 close)
        monitor._token_cache = None

        mock_response = MagicMock()
        mock_response.json.return_value = "fresh-token"
        mock_response.raise_for_status = MagicMock()

        with patch("integration.services.cml_websocket_monitor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            token = await monitor._get_token()

        assert token == "fresh-token"
        mock_client.post.assert_called_once()


# =============================================================================
# Tests: CmlWebSocketMonitor — Connection Lifecycle
# =============================================================================


class TestCmlWebSocketMonitorLifecycle:
    """Test start/stop and status transitions."""

    @pytest.mark.asyncio
    async def test_start_sets_read_task(self):
        monitor = create_monitor()

        with patch.object(monitor, "_connection_loop", new_callable=AsyncMock) as mock_loop:
            # Make the loop return immediately
            mock_loop.return_value = None
            await monitor.start()

            assert monitor._read_task is not None
            # Give the task a moment to start
            await asyncio.sleep(0.01)

        # Cleanup
        await monitor.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task_and_sets_disconnected(self):
        monitor = create_monitor()

        async def fake_loop():
            await asyncio.sleep(100)  # Block indefinitely

        with patch.object(monitor, "_connection_loop", side_effect=fake_loop):
            await monitor.start()
            await asyncio.sleep(0.01)  # Let task start

        await monitor.stop()
        assert monitor.status == ConnectionStatus.DISCONNECTED
        assert monitor._read_task is None

    @pytest.mark.asyncio
    async def test_start_when_already_running_is_noop(self):
        monitor = create_monitor()

        async def fake_loop():
            await asyncio.sleep(100)

        with patch.object(monitor, "_connection_loop", side_effect=fake_loop):
            await monitor.start()
            await asyncio.sleep(0.01)

            task1 = monitor._read_task
            await monitor.start()  # Should be no-op
            assert monitor._read_task is task1

        await monitor.stop()

    @pytest.mark.asyncio
    async def test_connection_loop_enters_failed_after_max_attempts(self):
        monitor = create_monitor(max_reconnect_attempts=2)
        connection_changes = []

        async def track_connection(wid, status, reason):
            connection_changes.append((status, reason))

        monitor._on_connection_change = track_connection

        # Make _connect_and_listen always fail
        with patch.object(monitor, "_connect_and_listen", side_effect=ConnectionError("refused")):
            await monitor._connection_loop()

        assert monitor.status == ConnectionStatus.FAILED
        # Should have reconnecting statuses then failed
        statuses = [s for s, _ in connection_changes]
        assert ConnectionStatus.FAILED in statuses

    @pytest.mark.asyncio
    async def test_connection_loop_tries_fallback_host_before_failing(self):
        """When primary host exhausts retries, switches to fallback_host."""
        monitor = create_monitor(
            host="172.31.38.11",
            fallback_host="54.80.245.250",
            max_reconnect_attempts=2,
        )
        connection_changes = []
        hosts_tried = []

        async def track_connection(wid, status, reason):
            connection_changes.append((status, reason))

        monitor._on_connection_change = track_connection

        async def fail_then_succeed(*args, **kwargs):
            hosts_tried.append(monitor._host)
            if monitor._host == "172.31.38.11":
                raise ConnectionError("ConnectTimeout")
            # Simulate success for fallback host by not raising
            # but we need to exit the loop cleanly
            monitor._stop_event.set()

        with patch.object(monitor, "_connect_and_listen", side_effect=fail_then_succeed):
            await monitor._connection_loop()

        # Should have tried private IP twice, then switched to public IP
        assert "172.31.38.11" in hosts_tried
        assert "54.80.245.250" in hosts_tried
        # After switching to fallback, host should be updated
        assert monitor._host == "54.80.245.250"
        assert monitor._fallback_host is None  # Consumed

    @pytest.mark.asyncio
    async def test_connection_loop_fails_if_no_fallback(self):
        """Without fallback_host, enters FAILED state after max attempts."""
        monitor = create_monitor(
            host="172.31.38.11",
            max_reconnect_attempts=2,
        )

        with patch.object(monitor, "_connect_and_listen", side_effect=ConnectionError("refused")):
            await monitor._connection_loop()

        assert monitor.status == ConnectionStatus.FAILED
        assert monitor._host == "172.31.38.11"  # Unchanged

    @pytest.mark.asyncio
    async def test_connection_loop_fallback_same_as_primary_skipped(self):
        """If fallback_host equals primary host, don't retry — enter FAILED."""
        monitor = create_monitor(
            host="172.31.38.11",
            fallback_host="172.31.38.11",  # Same as primary
            max_reconnect_attempts=2,
        )

        with patch.object(monitor, "_connect_and_listen", side_effect=ConnectionError("refused")):
            await monitor._connection_loop()

        assert monitor.status == ConnectionStatus.FAILED


# =============================================================================
# Tests: CmlWebSocketMonitor — Status Callback
# =============================================================================


class TestCmlWebSocketMonitorStatusCallback:
    """Test connection status change callbacks."""

    @pytest.mark.asyncio
    async def test_set_status_invokes_callback_on_change(self):
        callback = AsyncMock()
        monitor = create_monitor(on_connection_change=callback)

        await monitor._set_status(ConnectionStatus.CONNECTING)
        callback.assert_called_once_with("worker-001", ConnectionStatus.CONNECTING, None)

    @pytest.mark.asyncio
    async def test_set_status_no_callback_on_same_status(self):
        callback = AsyncMock()
        monitor = create_monitor(on_connection_change=callback)

        # DISCONNECTED → DISCONNECTED (no change)
        await monitor._set_status(ConnectionStatus.DISCONNECTED)
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_status_includes_reason(self):
        callback = AsyncMock()
        monitor = create_monitor(on_connection_change=callback)

        await monitor._set_status(ConnectionStatus.RECONNECTING, reason="connection reset")
        callback.assert_called_once_with("worker-001", ConnectionStatus.RECONNECTING, "connection reset")


# =============================================================================
# Tests: CmlWebSocketMonitorRegistry
# =============================================================================


class TestCmlWebSocketMonitorRegistry:
    """Test the registry for managing multiple monitors."""

    def test_initial_state(self):
        registry = CmlWebSocketMonitorRegistry()
        assert registry.active_count == 0
        assert registry.connected_count == 0

    def test_get_monitor_returns_none_for_unknown(self):
        registry = CmlWebSocketMonitorRegistry()
        assert registry.get_monitor("unknown-worker") is None

    @pytest.mark.asyncio
    async def test_ensure_monitoring_creates_new_monitor(self):
        registry = CmlWebSocketMonitorRegistry(default_username="admin", default_password="pass")  # pragma: allowlist secret

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            monitor = await registry.ensure_monitoring(
                worker_id="worker-001",
                host="10.0.0.1",
            )

        assert monitor is not None
        assert monitor.worker_id == "worker-001"
        assert monitor.host == "10.0.0.1"
        assert registry.get_monitor("worker-001") is monitor

    @pytest.mark.asyncio
    async def test_ensure_monitoring_returns_existing_connected(self):
        registry = CmlWebSocketMonitorRegistry()

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            monitor1 = await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")

        # Simulate connected state
        monitor1._status = ConnectionStatus.CONNECTED

        monitor2 = await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")
        assert monitor2 is monitor1

    @pytest.mark.asyncio
    async def test_ensure_monitoring_recreates_failed_monitor(self):
        registry = CmlWebSocketMonitorRegistry()

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            monitor1 = await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")

        # Simulate failed state
        monitor1._status = ConnectionStatus.FAILED

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            with patch.object(CmlWebSocketMonitor, "stop", new_callable=AsyncMock):
                monitor2 = await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")

        assert monitor2 is not monitor1
        assert registry.get_monitor("w1") is monitor2

    @pytest.mark.asyncio
    async def test_stop_monitoring_removes_monitor(self):
        registry = CmlWebSocketMonitorRegistry()

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")

        with patch.object(CmlWebSocketMonitor, "stop", new_callable=AsyncMock):
            await registry.stop_monitoring("w1")

        assert registry.get_monitor("w1") is None

    @pytest.mark.asyncio
    async def test_stop_monitoring_unknown_worker_is_noop(self):
        registry = CmlWebSocketMonitorRegistry()
        await registry.stop_monitoring("nonexistent")  # No exception

    @pytest.mark.asyncio
    async def test_stop_all_clears_all_monitors(self):
        registry = CmlWebSocketMonitorRegistry()

        with patch.object(CmlWebSocketMonitor, "start", new_callable=AsyncMock):
            await registry.ensure_monitoring(worker_id="w1", host="10.0.0.1")
            await registry.ensure_monitoring(worker_id="w2", host="10.0.0.2")

        with patch.object(CmlWebSocketMonitor, "stop", new_callable=AsyncMock):
            await registry.stop_all()

        assert registry.get_monitor("w1") is None
        assert registry.get_monitor("w2") is None
        assert registry.active_count == 0

    def test_get_status_summary(self):
        registry = CmlWebSocketMonitorRegistry()

        monitor = CmlWebSocketMonitor(worker_id="w1", host="10.0.0.1", username="admin", password="pass")
        monitor._status = ConnectionStatus.CONNECTED
        registry._monitors["w1"] = monitor

        summary = registry.get_status_summary()
        assert summary["total"] == 1
        assert summary["connected"] == 1
        assert "w1" in summary["monitors"]
        assert summary["monitors"]["w1"]["status"] == "connected"


# =============================================================================
# Tests: Activity Category Constants
# =============================================================================


class TestActivityCategories:
    """Verify activity categories match expected values."""

    def test_lab_event_states(self):
        assert "STARTED" in ACTIVITY_LAB_EVENT_STATES
        assert "STOPPED" in ACTIVITY_LAB_EVENT_STATES

    def test_state_change_node_events(self):
        assert "QUEUED" in ACTIVITY_STATE_CHANGE_NODE_EVENTS
        assert "STARTED" in ACTIVITY_STATE_CHANGE_NODE_EVENTS
        # BOOTED is intentionally NOT an activity trigger
        assert "BOOTED" not in ACTIVITY_STATE_CHANGE_NODE_EVENTS
