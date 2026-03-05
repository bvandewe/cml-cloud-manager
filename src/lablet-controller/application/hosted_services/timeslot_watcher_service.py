"""Timeslot Watcher Service (AD-TIMESLOT-001).

Independent leader-gated background service that proactively detects
sessions with imminent timeslot deadlines and triggers their reconciliation.

Problem Solved:
    In watch-only mode (ADR-015), no external actor writes to etcd when a
    clock-based deadline approaches or expires. This service fills that gap
    by periodically scanning for sessions with imminent deadlines and
    triggering reconciliation via etcd write (which the watch stream picks up).

Architecture:
    - Runs as an independent asyncio loop under leader election
    - Started/stopped by LabletReconciler in _become_leader()/_step_down()
    - Follows the same pattern as LabDiscoveryService, metrics loop, discovery loop
    - Calls CPA's GET /api/internal/lablet-sessions/imminent-deadlines
      (server-side MongoDB filtering using idx_timeslot_start/idx_timeslot_end)
    - For each session with an imminent deadline, writes an etcd key to
      trigger the watch → reconcile_single() flow

Two Deadline Types:
    1. Approaching Start: SCHEDULED sessions within the boot window
       → triggers _handle_scheduled() → INSTANTIATING transition
    2. Past End: Non-terminal sessions past their timeslot_end
       → triggers _handle_running()/_reconcile_inner() → STOPPING/EXPIRED

All state reads go through CPA (ADR-001).
No direct MongoDB access — uses ControlPlaneApiClient.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from lcm_core.integration.clients import ControlPlaneApiClient, EtcdClient

from application.settings import Settings

if TYPE_CHECKING:
    from neuroglia.dependency_injection import ServiceCollection

logger = logging.getLogger(__name__)


class TimeslotWatcherService:
    """Background service that scans for sessions with imminent timeslot deadlines.

    Runs a lightweight loop every timeslot_check_interval seconds (default 10s).
    For each session with an imminent deadline, writes a trigger key to etcd
    so the watch-based reconciliation picks it up immediately.

    Configuration:
        TIMESLOT_CHECK_ENABLED: Enable/disable the watcher (default: true)
        TIMESLOT_CHECK_INTERVAL: Seconds between scans (default: 10)
        TIMESLOT_BOOT_WINDOW_MINUTES: Look-ahead for approaching starts (default: 35)

    Lifecycle: Managed by LabletReconciler via start_async()/stop_async().
    """

    def __init__(
        self,
        api_client: ControlPlaneApiClient,
        etcd_client: EtcdClient,
        settings: Settings,
    ) -> None:
        """Initialize the timeslot watcher service.

        Args:
            api_client: Client for Control Plane API (imminent-deadlines query).
            etcd_client: Client for etcd (trigger key writes).
            settings: Application settings.
        """
        self._api = api_client
        self._etcd = etcd_client
        self._settings = settings
        self._running = False
        self._task: asyncio.Task | None = None

        # etcd key prefix for trigger writes
        self._key_prefix = getattr(settings, "etcd_key_prefix", "/lcm").rstrip("/")

        # Statistics
        self._scan_count = 0
        self._triggers_approaching = 0
        self._triggers_past_end = 0
        self._last_scan_at: datetime | None = None
        self._last_error: str | None = None

        # Track already-triggered sessions to avoid redundant etcd writes.
        # Cleared when the session disappears from the imminent-deadlines response
        # (meaning it transitioned and no longer matches the query).
        self._triggered_approaching: set[str] = set()
        self._triggered_past_end: set[str] = set()

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start_async(self) -> None:
        """Start the timeslot watcher service."""
        if not self._settings.timeslot_check_enabled:
            logger.info("⏭️ TimeslotWatcherService is disabled (TIMESLOT_CHECK_ENABLED=false)")
            return

        logger.info(
            "🚀 Starting TimeslotWatcherService (interval=%ds, boot_window=%dmin)",
            self._settings.timeslot_check_interval,
            self._settings.timeslot_boot_window_minutes,
        )
        self._running = True
        self._task = asyncio.create_task(
            self._watch_loop(),
            name="timeslot_watcher_loop",
        )

    async def stop_async(self) -> None:
        """Stop the timeslot watcher service."""
        logger.info("🛑 Stopping TimeslotWatcherService...")
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info(
            "✅ TimeslotWatcherService stopped (scans=%d, approaching=%d, past_end=%d)",
            self._scan_count,
            self._triggers_approaching,
            self._triggers_past_end,
        )

    # =========================================================================
    # Watch loop
    # =========================================================================

    async def _watch_loop(self) -> None:
        """Main watch loop — scans for imminent deadlines at configured interval."""
        # Brief initial delay to let reconciliation settle
        await asyncio.sleep(5)

        while self._running:
            loop_start = datetime.now(timezone.utc)
            try:
                await self._scan_deadlines()
            except asyncio.CancelledError:
                logger.info("TimeslotWatcherService loop cancelled")
                raise
            except Exception as e:
                self._last_error = str(e)
                logger.error("TimeslotWatcherService scan failed: %s", e, exc_info=True)

            # Sleep for the configured interval, accounting for scan duration
            elapsed = (datetime.now(timezone.utc) - loop_start).total_seconds()
            sleep_time = max(0, self._settings.timeslot_check_interval - elapsed)
            await asyncio.sleep(sleep_time)

    async def _scan_deadlines(self) -> None:
        """Execute a single deadline scan and trigger reconciliation for matches."""
        self._scan_count += 1
        self._last_scan_at = datetime.now(timezone.utc)

        # Query CPA for sessions with imminent deadlines (server-side filtered)
        result = await self._api.get_sessions_with_imminent_deadlines(
            boot_window_minutes=self._settings.timeslot_boot_window_minutes,
        )

        approaching = result.get("approaching_start", [])
        past_end = result.get("past_end", [])

        # Prune triggered sets — remove sessions no longer in the response
        current_approaching_ids = {s["id"] for s in approaching}
        current_past_end_ids = {s["id"] for s in past_end}
        self._triggered_approaching -= self._triggered_approaching - current_approaching_ids
        self._triggered_past_end -= self._triggered_past_end - current_past_end_ids

        # Trigger reconciliation for NEW approaching sessions
        for session in approaching:
            session_id = session["id"]
            if session_id not in self._triggered_approaching:
                await self._trigger_reconcile(session_id, reason="timeslot_approaching")
                self._triggered_approaching.add(session_id)
                self._triggers_approaching += 1
                logger.info(
                    "⏰ Timeslot approaching: session %s (start=%s, status=%s)",
                    session_id,
                    session.get("timeslot_start"),
                    session.get("status"),
                )

        # Trigger reconciliation for NEW past-end sessions
        for session in past_end:
            session_id = session["id"]
            if session_id not in self._triggered_past_end:
                await self._trigger_reconcile(session_id, reason="timeslot_expired")
                self._triggered_past_end.add(session_id)
                self._triggers_past_end += 1
                logger.info(
                    "⏰ Timeslot expired: session %s (end=%s, status=%s)",
                    session_id,
                    session.get("timeslot_end"),
                    session.get("status"),
                )

    async def _trigger_reconcile(self, session_id: str, reason: str) -> None:
        """Write an etcd key to trigger watch-based reconciliation for a session.

        Writes to /lcm/sessions/{session_id}/timeslot_trigger which the
        lablet-controller's watch on /lcm/sessions/ will pick up, causing
        on_watch_event() → reconcile_single() for this specific session.

        The key is written with a 60s TTL lease so it auto-cleans up.

        Args:
            session_id: The session ID to trigger reconciliation for.
            reason: Trigger reason (timeslot_approaching or timeslot_expired).
        """
        key = f"{self._key_prefix}/sessions/{session_id}/timeslot_trigger"
        try:
            lease = await self._etcd.grant_lease(ttl=60)
            await self._etcd.put(key, reason, lease=lease)
            logger.debug("Wrote etcd trigger key: %s = %s (lease_ttl=60s)", key, reason)
        except Exception as e:
            logger.warning("Failed to write etcd trigger for session %s: %s", session_id, e)

    # =========================================================================
    # Stats (for admin endpoint)
    # =========================================================================

    def get_stats(self) -> dict:
        """Get operational statistics for the admin /info endpoint."""
        return {
            "enabled": self._settings.timeslot_check_enabled,
            "running": self._running,
            "interval_seconds": self._settings.timeslot_check_interval,
            "boot_window_minutes": self._settings.timeslot_boot_window_minutes,
            "scan_count": self._scan_count,
            "triggers_approaching": self._triggers_approaching,
            "triggers_past_end": self._triggers_past_end,
            "tracked_approaching": len(self._triggered_approaching),
            "tracked_past_end": len(self._triggered_past_end),
            "last_scan_at": self._last_scan_at.isoformat() if self._last_scan_at else None,
            "last_error": self._last_error,
        }

    # =========================================================================
    # DI Registration
    # =========================================================================

    @classmethod
    def configure(cls, services: "ServiceCollection") -> None:
        """Register TimeslotWatcherService as a singleton.

        Lifecycle is managed by LabletReconciler (start in _become_leader,
        stop in _step_down) — not as a HostedService.

        Args:
            services: Neuroglia service collection.
        """

        def factory(sp):
            return cls(
                api_client=sp.get_required_service(ControlPlaneApiClient),
                etcd_client=sp.get_required_service(EtcdClient),
                settings=sp.get_required_service(Settings),
            )

        services.add_singleton(cls, implementation_factory=factory)
