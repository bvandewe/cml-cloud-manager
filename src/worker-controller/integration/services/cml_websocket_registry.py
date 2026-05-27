"""CML WebSocket Monitor Registry (ADR-041).

Manages the set of active CmlWebSocketMonitor instances — one per RUNNING worker.
The WorkerReconciler calls ensure_monitoring()/stop_monitoring() to manage lifecycle.
"""

import logging
import time
from typing import Any

from integration.services.cml_websocket_monitor import (
    ActivityEventCallback,
    CmlWebSocketMonitor,
    ConnectionChangeCallback,
    ConnectionStatus,
    LabStateChangeCallback,
    LabStatsCallback,
    SystemStatsCallback,
)

logger = logging.getLogger(__name__)


class CmlWebSocketMonitorRegistry:
    """Registry of active CmlWebSocketMonitor instances.

    The WorkerReconciler calls ensure_monitoring(worker_id, host) for each
    RUNNING worker, and stop_monitoring(worker_id) when workers leave RUNNING.

    Args:
        default_username: Default CML API username for all monitors.
        default_password: Default CML API password for all monitors.
        verify_ssl: Whether to verify SSL certificates.
        metrics_report_interval: Seconds between metrics callback invocations.
        reconnect_max_interval: Max reconnect backoff interval (seconds).
        max_reconnect_attempts: Max consecutive failures before FAILED state.
    """

    def __init__(
        self,
        default_username: str = "admin",
        default_password: str = "",
        *,
        verify_ssl: bool = False,
        metrics_report_interval: int = 10,
        reconnect_max_interval: int = 30,
        max_reconnect_attempts: int = 3,
        recreation_cooldown: int = 120,
    ):
        self._default_username = default_username
        self._default_password = default_password
        self._verify_ssl = verify_ssl
        self._metrics_report_interval = metrics_report_interval
        self._reconnect_max_interval = reconnect_max_interval
        self._max_reconnect_attempts = max_reconnect_attempts
        self._recreation_cooldown = recreation_cooldown
        self._monitors: dict[str, CmlWebSocketMonitor] = {}
        self._failed_at: dict[str, float] = {}  # worker_id → monotonic time of last FAILED recreation

    # =========================================================================
    # Public Interface
    # =========================================================================

    async def ensure_monitoring(
        self,
        worker_id: str,
        host: str,
        *,
        fallback_host: str | None = None,
        username: str | None = None,
        password: str | None = None,
        on_system_stats: SystemStatsCallback | None = None,
        on_activity_event: ActivityEventCallback | None = None,
        on_lab_stats: LabStatsCallback | None = None,
        on_lab_state_change: LabStateChangeCallback | None = None,
        on_connection_change: ConnectionChangeCallback | None = None,
    ) -> CmlWebSocketMonitor:
        """Ensure a monitor exists and is connected for the given worker.

        If a monitor already exists and is connected (or reconnecting), returns it.
        If the monitor is in FAILED state, stops it and creates a fresh one.
        If no monitor exists, creates and starts a new one.

        Args:
            worker_id: Unique worker identifier.
            host: CML worker host/IP.
            fallback_host: Alternative host to try if primary host is unreachable.
            username: CML API username (defaults to registry default).
            password: CML API password (defaults to registry default).
            on_system_stats: Callback for system_stats events.
            on_activity_event: Callback for activity events (lab_event).
            on_lab_stats: Callback for lab_stats events.
            on_lab_state_change: Callback for state_change events.
            on_connection_change: Callback for connection status changes.

        Returns:
            The active CmlWebSocketMonitor instance.
        """
        existing = self._monitors.get(worker_id)

        if existing:
            # If the host has changed (e.g., private→public IP after start), recreate
            if existing.host != host:
                logger.info(f"[WSRegistry] Host changed for {worker_id}: {existing.host} → {host}, recreating...")
                await self._stop_monitor(worker_id)
                self._failed_at.pop(worker_id, None)  # Reset cooldown on host change
            # If already connected or reconnecting, return as-is
            elif existing.status in (ConnectionStatus.CONNECTED, ConnectionStatus.CONNECTING, ConnectionStatus.AUTHENTICATING, ConnectionStatus.RECONNECTING):
                return existing
            # If failed, tear down and recreate (with cooldown)
            elif existing.status == ConnectionStatus.FAILED:
                last_failed = self._failed_at.get(worker_id, 0)
                elapsed = time.monotonic() - last_failed
                if elapsed < self._recreation_cooldown:
                    logger.debug(f"[WSRegistry] Monitor for {worker_id} is FAILED, cooldown active ({elapsed:.0f}s / {self._recreation_cooldown}s)")
                    return existing
                logger.info(f"[WSRegistry] Monitor for {worker_id} is FAILED, recreating (cooldown expired)...")
                self._failed_at[worker_id] = time.monotonic()
                await self._stop_monitor(worker_id)
            else:
                # DISCONNECTED — start it
                await existing.start()
                return existing

        # Create new monitor
        monitor = CmlWebSocketMonitor(
            worker_id=worker_id,
            host=host,
            username=username or self._default_username,
            password=password or self._default_password,
            fallback_host=fallback_host,
            verify_ssl=self._verify_ssl,
            metrics_report_interval=self._metrics_report_interval,
            reconnect_max_interval=self._reconnect_max_interval,
            max_reconnect_attempts=self._max_reconnect_attempts,
            on_system_stats=on_system_stats,
            on_activity_event=on_activity_event,
            on_lab_stats=on_lab_stats,
            on_lab_state_change=on_lab_state_change,
            on_connection_change=on_connection_change,
        )

        self._monitors[worker_id] = monitor
        await monitor.start()
        logger.info(f"[WSRegistry] Started monitor for worker={worker_id} host={host}")
        return monitor

    async def stop_monitoring(self, worker_id: str) -> None:
        """Stop and remove the monitor for a worker.

        Args:
            worker_id: Worker to stop monitoring.
        """
        self._failed_at.pop(worker_id, None)
        await self._stop_monitor(worker_id)

    async def stop_all(self) -> None:
        """Stop all monitors (used during shutdown)."""
        self._failed_at.clear()
        worker_ids = list(self._monitors.keys())
        for worker_id in worker_ids:
            await self._stop_monitor(worker_id)
        logger.info(f"[WSRegistry] All monitors stopped ({len(worker_ids)} total)")

    def get_monitor(self, worker_id: str) -> CmlWebSocketMonitor | None:
        """Get the monitor for a worker (if exists).

        Args:
            worker_id: Worker to look up.

        Returns:
            Monitor instance or None.
        """
        return self._monitors.get(worker_id)

    @property
    def active_count(self) -> int:
        """Number of active monitors (any status except DISCONNECTED)."""
        return sum(1 for m in self._monitors.values() if m.status != ConnectionStatus.DISCONNECTED)

    @property
    def connected_count(self) -> int:
        """Number of currently connected monitors."""
        return sum(1 for m in self._monitors.values() if m.is_connected)

    def get_status_summary(self) -> dict[str, Any]:
        """Get a summary of all monitors and their statuses."""
        return {
            "total": len(self._monitors),
            "active": self.active_count,
            "connected": self.connected_count,
            "monitors": {
                wid: {
                    "host": m.host,
                    "status": m.status.value,
                    "last_message_at": m.last_message_at.isoformat() if m.last_message_at else None,
                }
                for wid, m in self._monitors.items()
            },
        }

    # =========================================================================
    # Internal
    # =========================================================================

    async def _stop_monitor(self, worker_id: str) -> None:
        """Stop and remove a monitor from the registry."""
        monitor = self._monitors.pop(worker_id, None)
        if monitor:
            await monitor.stop()
            logger.info(f"[WSRegistry] Stopped and removed monitor for worker={worker_id}")
