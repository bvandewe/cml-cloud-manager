"""CML WebSocket Monitor for Worker Controller (ADR-041).

Persistent WebSocket client for real-time CML worker monitoring.
Connects to wss://<host>/ws/ui and receives push-based events:
- system_stats: System resource utilization (~3s interval)
- lab_stats: Per-lab node/link statistics (~3s per running lab)
- state_change: Node/interface lifecycle transitions (on occurrence)
- lab_event: Lab-level state changes (on occurrence)

Authentication: Message-based. After WebSocket handshake (101),
send {"token": "<jwt>"} as first message. Token obtained from
existing CML REST API POST /api/v0/authenticate.

References:
- ADR-041: WebSocket-Based CML Worker Monitoring
- Phase 0 validation: scripts/explore_cml_ws.py (2026-05-20)
"""

import asyncio
import json
import logging
import ssl
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import httpx
import websockets
import websockets.exceptions
from websockets.asyncio.client import ClientConnection, connect

from infrastructure.observability import (
    record_ws_connection_closed,
    record_ws_connection_opened,
    record_ws_message,
    record_ws_message_latency,
    record_ws_reconnection,
)
from integration.services.cml_system_spi import CmlSystemStats

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Activity event categories for idle detection
# Must align with control-plane-api/application/utils/telemetry_filter.py
ACTIVITY_LAB_EVENT_STATES = {"STARTED", "STOPPED"}
ACTIVITY_STATE_CHANGE_NODE_EVENTS = {"QUEUED", "STARTED"}

# WebSocket close codes
WS_CLOSE_UNAUTHORIZED = 3000


# =============================================================================
# Enums
# =============================================================================


class ConnectionStatus(str, Enum):
    """WebSocket connection health status."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    AUTHENTICATING = "authenticating"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


# =============================================================================
# Type Aliases for Callbacks
# =============================================================================

SystemStatsCallback = Callable[[str, CmlSystemStats], Awaitable[None]]
ActivityEventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]
LabStatsCallback = Callable[[str, str, dict[str, Any]], Awaitable[None]]
LabStateChangeCallback = Callable[[str, dict[str, Any]], Awaitable[None]]
ConnectionChangeCallback = Callable[[str, ConnectionStatus, str | None], Awaitable[None]]


# =============================================================================
# CmlWebSocketMonitor
# =============================================================================


class CmlWebSocketMonitor:
    """Persistent WebSocket monitor for a single CML worker.

    Connects to wss://<host>/ws/ui and receives real-time events.
    Lifecycle managed by CmlWebSocketMonitorRegistry:
    - start() when worker transitions to RUNNING
    - stop() when worker transitions to STOPPING/STOPPED/TERMINATED

    Args:
        worker_id: Unique identifier for the CML worker.
        host: CML worker host/IP address.
        username: CML API username for authentication.
        password: CML API password for authentication.
        verify_ssl: Whether to verify SSL certificates (default: False for self-signed).
        metrics_report_interval: Minimum seconds between system_stats callback invocations.
        reconnect_max_interval: Maximum backoff interval for reconnection attempts (seconds).
        max_reconnect_attempts: Max consecutive reconnect failures before entering FAILED state.
        on_system_stats: Callback invoked with (worker_id, CmlSystemStats) on system stats.
        on_activity_event: Callback invoked with (worker_id, event_dict) on activity events.
        on_lab_stats: Callback invoked with (worker_id, lab_id, stats_dict) on lab stats.
        on_lab_state_change: Callback invoked with (worker_id, event_dict) on state changes.
        on_connection_change: Callback invoked with (worker_id, status, reason) on connection changes.
    """

    def __init__(
        self,
        worker_id: str,
        host: str,
        username: str,
        password: str,
        *,
        fallback_host: str | None = None,
        verify_ssl: bool = False,
        metrics_report_interval: int = 10,
        reconnect_max_interval: int = 30,
        max_reconnect_attempts: int = 3,
        on_system_stats: SystemStatsCallback | None = None,
        on_activity_event: ActivityEventCallback | None = None,
        on_lab_stats: LabStatsCallback | None = None,
        on_lab_state_change: LabStateChangeCallback | None = None,
        on_connection_change: ConnectionChangeCallback | None = None,
    ):
        self._worker_id = worker_id
        self._host = host
        self._fallback_host = fallback_host
        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl
        self._metrics_report_interval = metrics_report_interval
        self._reconnect_max_interval = reconnect_max_interval
        self._max_reconnect_attempts = max_reconnect_attempts

        # Callbacks
        self._on_system_stats = on_system_stats
        self._on_activity_event = on_activity_event
        self._on_lab_stats = on_lab_stats
        self._on_lab_state_change = on_lab_state_change
        self._on_connection_change = on_connection_change

        # Internal state
        self._status: ConnectionStatus = ConnectionStatus.DISCONNECTED
        self._ws: ClientConnection | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event = asyncio.Event()
        self._reconnect_count: int = 0
        self._last_message_at: datetime | None = None
        self._last_metrics_report_at: float = 0.0
        self._latest_system_stats: CmlSystemStats | None = None
        self._activity_events: list[dict[str, Any]] = []
        self._token_cache: str | None = None

    # =========================================================================
    # Public Interface
    # =========================================================================

    @property
    def worker_id(self) -> str:
        """Worker ID this monitor is attached to."""
        return self._worker_id

    @property
    def host(self) -> str:
        """CML worker host/IP."""
        return self._host

    @property
    def status(self) -> ConnectionStatus:
        """Current connection status."""
        return self._status

    @property
    def is_connected(self) -> bool:
        """Whether the WebSocket is currently connected and receiving."""
        return self._status == ConnectionStatus.CONNECTED

    @property
    def last_message_at(self) -> datetime | None:
        """Timestamp of the last received message."""
        return self._last_message_at

    @property
    def latest_system_stats(self) -> CmlSystemStats | None:
        """Most recent system_stats received via WebSocket."""
        return self._latest_system_stats

    @property
    def recent_activity_events(self) -> list[dict[str, Any]]:
        """Activity events accumulated since last drain."""
        return list(self._activity_events)

    def drain_activity_events(self) -> list[dict[str, Any]]:
        """Return and clear accumulated activity events for idle detection."""
        events = self._activity_events
        self._activity_events = []
        return events

    async def start(self) -> None:
        """Start the WebSocket connection. Non-blocking; spawns background read task."""
        if self._read_task and not self._read_task.done():
            logger.warning(f"[WS:{self._worker_id}] Monitor already running, ignoring start()")
            return

        self._stop_event.clear()
        self._reconnect_count = 0
        self._read_task = asyncio.create_task(self._connection_loop(), name=f"ws-monitor-{self._worker_id}")
        logger.info(f"[WS:{self._worker_id}] Monitor started for host={self._host}")

    async def stop(self) -> None:
        """Gracefully close the WebSocket connection and stop the read loop."""
        logger.info(f"[WS:{self._worker_id}] Stopping monitor...")
        self._stop_event.set()

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        self._ws = None
        self._read_task = None
        await self._set_status(ConnectionStatus.DISCONNECTED, reason="stopped")
        logger.info(f"[WS:{self._worker_id}] Monitor stopped")

    # =========================================================================
    # Connection Lifecycle
    # =========================================================================

    async def _connection_loop(self) -> None:
        """Main connection loop with auto-reconnect on failure.

        If the primary host exhausts max_reconnect_attempts and a fallback_host
        is configured, switches to the fallback host and resets the retry counter.
        """
        while not self._stop_event.is_set():
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if self._stop_event.is_set():
                    break

                self._reconnect_count += 1
                logger.warning(f"[WS:{self._worker_id}] Connection lost (attempt {self._reconnect_count}): {exc}")

                # OTel: record reconnection attempt (ADR-041 Phase 5)
                record_ws_reconnection(self._worker_id, reason=str(exc)[:100])

                if self._reconnect_count >= self._max_reconnect_attempts:
                    # Before entering FAILED state, try fallback host if available
                    if self._fallback_host and self._fallback_host != self._host:
                        logger.info(f"[WS:{self._worker_id}] Primary host {self._host} exhausted {self._max_reconnect_attempts} attempts, switching to fallback host {self._fallback_host}")
                        self._host = self._fallback_host
                        self._fallback_host = None  # Consume the fallback
                        self._reconnect_count = 0
                        self._token_cache = None  # Invalidate token for new host
                        await self._set_status(ConnectionStatus.RECONNECTING, reason=f"Switching to fallback host {self._host}")
                        continue

                    await self._set_status(ConnectionStatus.FAILED, reason=f"Max reconnect attempts reached ({self._max_reconnect_attempts})")
                    logger.error(f"[WS:{self._worker_id}] Entering FAILED state after {self._reconnect_count} attempts")
                    break

                await self._set_status(ConnectionStatus.RECONNECTING, reason=str(exc))
                backoff = min(2**self._reconnect_count, self._reconnect_max_interval)
                logger.info(f"[WS:{self._worker_id}] Reconnecting in {backoff}s...")

                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                    break  # stop_event was set during backoff
                except asyncio.TimeoutError:
                    pass  # Backoff elapsed, retry

    async def _connect_and_listen(self) -> None:
        """Establish WebSocket connection, authenticate, and run read loop."""
        await self._set_status(ConnectionStatus.CONNECTING)

        # Obtain auth token
        token = await self._get_token()

        # Build SSL context (self-signed certs on CML workers)
        ssl_ctx = ssl.create_default_context()
        if not self._verify_ssl:
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        uri = f"wss://{self._host}/ws/ui"
        logger.debug(f"[WS:{self._worker_id}] Connecting to {uri}")

        async with connect(uri, ssl=ssl_ctx, open_timeout=10, close_timeout=5) as ws:
            self._ws = ws

            # Authenticate via message-based auth
            await self._set_status(ConnectionStatus.AUTHENTICATING)
            await ws.send(json.dumps({"token": token}))
            logger.debug(f"[WS:{self._worker_id}] Auth message sent, awaiting first event...")

            # Wait for first message to confirm auth succeeded
            try:
                first_msg = await asyncio.wait_for(ws.recv(), timeout=15.0)
            except asyncio.TimeoutError:
                raise ConnectionError("No response after auth message (timeout 15s)")

            # Process the first message
            self._last_message_at = datetime.now(timezone.utc)
            await self._handle_message(first_msg)

            # Auth succeeded - reset reconnect counter and mark connected
            self._reconnect_count = 0
            await self._set_status(ConnectionStatus.CONNECTED)
            logger.info(f"[WS:{self._worker_id}] Connected and authenticated")

            # Enter read loop
            await self._read_loop(ws)

    async def _read_loop(self, ws: ClientConnection) -> None:
        """Read messages until connection drops or stop is requested."""
        while not self._stop_event.is_set():
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                self._last_message_at = datetime.now(timezone.utc)
                await self._handle_message(msg)
            except asyncio.TimeoutError:
                # No message in 30s — CML sends system_stats every ~3s
                # Connection might be stale but don't disconnect yet
                logger.debug(f"[WS:{self._worker_id}] No message in 30s (connection may be idle)")
                continue
            except websockets.exceptions.ConnectionClosedError as exc:
                if exc.code == WS_CLOSE_UNAUTHORIZED:
                    # Token expired mid-session — invalidate and let reconnect re-auth
                    self._token_cache = None
                    raise ConnectionError(f"CML closed connection: {exc.reason} (code={exc.code})")
                raise
            except websockets.exceptions.ConnectionClosedOK:
                logger.info(f"[WS:{self._worker_id}] Connection closed gracefully")
                return

    # =========================================================================
    # Message Handling
    # =========================================================================

    async def _handle_message(self, raw: str | bytes) -> None:
        """Parse JSON message and route to appropriate handler."""
        msg_start = time.monotonic()

        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")

        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"[WS:{self._worker_id}] Non-JSON message received: {raw[:100]}")
            return

        event_type = msg.get("event_type")
        if not event_type:
            logger.debug(f"[WS:{self._worker_id}] Message without event_type: {raw[:200]}")
            return

        # OTel: record message count (ADR-041 Phase 5)
        record_ws_message(self._worker_id, event_type)

        if event_type == "system_stats":
            await self._handle_system_stats(msg)
        elif event_type == "lab_stats":
            await self._handle_lab_stats(msg)
        elif event_type == "state_change":
            await self._handle_state_change(msg)
        elif event_type == "lab_event":
            await self._handle_lab_event(msg)
        else:
            logger.debug(f"[WS:{self._worker_id}] Unknown event_type: {event_type}")

        # OTel: record processing latency (ADR-041 Phase 5)
        record_ws_message_latency(event_type, time.monotonic() - msg_start)

    async def _handle_system_stats(self, msg: dict[str, Any]) -> None:
        """Process system_stats event. Throttle outbound callback invocation."""
        data = msg.get("data", msg)

        # Parse into existing DTO (reuse CmlSystemStats.from_api_response)
        try:
            stats = CmlSystemStats.from_api_response(data)
        except Exception as exc:
            logger.warning(f"[WS:{self._worker_id}] Failed to parse system_stats: {exc}")
            return

        self._latest_system_stats = stats

        # Throttle callback invocation to metrics_report_interval
        now = time.monotonic()
        if self._on_system_stats and (now - self._last_metrics_report_at) >= self._metrics_report_interval:
            self._last_metrics_report_at = now
            try:
                await self._on_system_stats(self._worker_id, stats)
            except Exception as exc:
                logger.error(f"[WS:{self._worker_id}] on_system_stats callback error: {exc}")

    async def _handle_lab_stats(self, msg: dict[str, Any]) -> None:
        """Process lab_stats event."""
        lab_id = msg.get("lab_id", "")
        data = msg.get("data") or {}

        if self._on_lab_stats and lab_id and data:
            try:
                await self._on_lab_stats(self._worker_id, lab_id, data)
            except Exception as exc:
                logger.error(f"[WS:{self._worker_id}] on_lab_stats callback error: {exc}")

    async def _handle_state_change(self, msg: dict[str, Any]) -> None:
        """Process state_change event. Track as activity if relevant."""
        element_type = msg.get("element_type", "")
        event = msg.get("event", "")

        # Track node state transitions as user activity for idle detection
        if element_type == "node" and event in ACTIVITY_STATE_CHANGE_NODE_EVENTS:
            self._activity_events.append(
                {
                    "event_type": "state_change",
                    "element_type": element_type,
                    "event": event,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "raw": msg,
                }
            )

        if self._on_lab_state_change:
            try:
                await self._on_lab_state_change(self._worker_id, msg)
            except Exception as exc:
                logger.error(f"[WS:{self._worker_id}] on_lab_state_change callback error: {exc}")

    async def _handle_lab_event(self, msg: dict[str, Any]) -> None:
        """Process lab_event event. Track as activity AND report lab state change."""
        event = msg.get("event", "")
        data = msg.get("data", {})
        lab_id = msg.get("lab_id", "")
        state = data.get("state", "") if isinstance(data, dict) else ""

        # Track lab state transitions as user activity for idle detection
        if event == "state" and state in ACTIVITY_LAB_EVENT_STATES:
            self._activity_events.append(
                {
                    "event_type": "lab_event",
                    "event": event,
                    "state": state,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "raw": msg,
                }
            )

        if self._on_activity_event:
            try:
                await self._on_activity_event(self._worker_id, msg)
            except Exception as exc:
                logger.error(f"[WS:{self._worker_id}] on_activity_event callback error: {exc}")

        # Route lab-level state changes through on_lab_state_change so CPA can
        # update the LabRecord and broadcast SSE to the frontend in real-time.
        if event == "state" and state and lab_id and self._on_lab_state_change:
            lab_state_event = {
                "event_type": "lab_event",
                "event": state,
                "element_type": "lab",
                "element_id": lab_id,
                "lab_id": lab_id,
                "data": data,
            }
            try:
                await self._on_lab_state_change(self._worker_id, lab_state_event)
            except Exception as exc:
                logger.error(f"[WS:{self._worker_id}] on_lab_state_change (lab_event) callback error: {exc}")

    # =========================================================================
    # Authentication
    # =========================================================================

    async def _get_token(self) -> str:
        """Get a valid JWT token for WebSocket authentication.

        Uses the same REST endpoint as CmlSystemSpiClient._authenticate():
        POST /api/v0/authenticate with {"username": ..., "password": ...}
        """
        if self._token_cache:
            return self._token_cache

        url = f"https://{self._host}/api/v0/authenticate"
        ssl_verify = self._verify_ssl

        async with httpx.AsyncClient(verify=ssl_verify, timeout=30.0) as client:
            response = await client.post(
                url,
                json={"username": self._username, "password": self._password},
            )
            response.raise_for_status()
            token = response.json()

        self._token_cache = token
        logger.debug(f"[WS:{self._worker_id}] Obtained auth token ({len(token)} chars)")
        return token

    # =========================================================================
    # Status Management
    # =========================================================================

    async def _set_status(self, status: ConnectionStatus, reason: str | None = None) -> None:
        """Update connection status and invoke callback."""
        previous = self._status
        self._status = status

        if previous != status:
            logger.debug(f"[WS:{self._worker_id}] Status: {previous.value} → {status.value}" + (f" ({reason})" if reason else ""))

            # OTel metrics: track connection gauge (ADR-041 Phase 5)
            if status == ConnectionStatus.CONNECTED:
                record_ws_connection_opened(self._worker_id)
            elif previous == ConnectionStatus.CONNECTED:
                record_ws_connection_closed(self._worker_id)

            if self._on_connection_change:
                try:
                    await self._on_connection_change(self._worker_id, status, reason)
                except Exception as exc:
                    logger.error(f"[WS:{self._worker_id}] on_connection_change callback error: {exc}")
