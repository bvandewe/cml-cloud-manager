"""Timeslot Manager Hosted Service (Sprint H).

Leader-elected periodic background service that manages timeslot lifecycle
for PENDING LabletSessions in the resource-scheduler:

1. **Approaching timeslot activation** — Detects PENDING sessions within the
   `timeslot_lead_time_minutes` window and writes etcd trigger keys to wake
   the SchedulerHostedService watch for immediate placement.

2. **Expired timeslot enforcement** — Detects PENDING sessions whose
   `timeslot_start + grace_period` has passed and expires them via CPA,
   preventing indefinite PENDING state for missed timeslots.

Architecture:
    - Follows the CleanupHostedService pattern (leader election, asyncio loop)
    - Uses CPA's `get_sessions_with_imminent_deadlines()` for server-side
      MongoDB filtering (reuses existing indexed queries)
    - Writes etcd trigger keys following the TimeslotWatcherService pattern
      from lablet-controller (dedup sets, TTL leases, pruning)
    - Separate election key from SchedulerHostedService — both can be
      leader simultaneously (different concerns)

Gap Filled:
    SchedulerHostedService handles PENDING→SCHEDULED placement but has no
    timeslot awareness. TimeslotWatcherService (lablet-controller) handles
    SCHEDULED→INSTANTIATING and RUNNING→STOPPING. This service fills the
    gap for PENDING sessions: gate premature scheduling and expire missed ones.

See: docs/implementation/bootstrap-prompts/SPRINT_H_TIMESLOT_MANAGER_PLAN.md
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from lcm_core.infrastructure.hosted_services import LeaderElectionConfig
from lcm_core.integration.clients import ControlPlaneApiClient, EtcdClient
from neuroglia.hosting.abstractions import HostedService

from application.settings import Settings

if TYPE_CHECKING:
    from neuroglia.dependency_injection import ServiceCollection

logger = logging.getLogger(__name__)


class TimeslotManagerHostedService(HostedService):
    """Leader-elected periodic timeslot management service.

    This service:
    1. Uses etcd for leader election (only leader runs timeslot management)
    2. Periodically scans CPA for PENDING sessions with imminent timeslot deadlines
    3. Triggers scheduling for approaching PENDING sessions via etcd writes
    4. Expires PENDING sessions that have missed their timeslot window

    Configuration:
        TIMESLOT_MANAGER_ENABLED: Enable/disable the service (default: true)
        TIMESLOT_MANAGER_INTERVAL_SECONDS: Scan interval (default: 60)
        TIMESLOT_EXPIRY_GRACE_MINUTES: Grace period before expiring (default: 5)
        TIMESLOT_LEAD_TIME_MINUTES: Look-ahead window for approaching (default: 35)
    """

    def __init__(
        self,
        api_client: ControlPlaneApiClient,
        etcd_client: EtcdClient,
        settings: Settings,
    ) -> None:
        """Initialize the timeslot manager hosted service.

        Args:
            api_client: Client for Control Plane API calls.
            etcd_client: Client for etcd leader election and trigger writes.
            settings: Application settings.
        """
        super().__init__()
        self._api = api_client
        self._etcd = etcd_client
        self._settings = settings

        # Leader election configuration
        self._election_config = LeaderElectionConfig(
            etcd_endpoints=settings.etcd_endpoints,
            lease_ttl_seconds=settings.leader_lease_ttl,
            service_name="timeslot-manager",
        )

        # etcd key prefix for trigger writes
        self._key_prefix = getattr(settings, "etcd_key_prefix", "/lcm").rstrip("/")

        # State
        self._is_leader = False
        self._started = False
        self._scan_task: asyncio.Task | None = None
        self._leader_task: asyncio.Task | None = None

        # Deduplication sets — track sessions already triggered/expired to
        # avoid redundant etcd writes or CPA calls. Pruned when sessions
        # disappear from the imminent-deadlines response.
        self._triggered_session_ids: set[str] = set()
        self._expired_session_ids: set[str] = set()

        # Metrics
        self._scan_count = 0
        self._triggers = 0
        self._expirations = 0
        self._last_scan_at: str | None = None
        self._last_error: str | None = None

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start_async(self) -> None:
        """Start the timeslot manager service."""
        if not self._settings.timeslot_manager_enabled:
            logger.info("⏭️ TimeslotManager disabled by configuration (TIMESLOT_MANAGER_ENABLED=false)")
            return

        self._started = True
        logger.info(
            "🚀 Starting TimeslotManager (interval=%ds, lead_time=%dmin, grace=%dmin)",
            self._settings.timeslot_manager_interval_seconds,
            self._settings.timeslot_lead_time_minutes,
            self._settings.timeslot_expiry_grace_minutes,
        )

        # Start leader election
        self._leader_task = asyncio.create_task(self._leader_loop())

    async def stop_async(self) -> None:
        """Stop the timeslot manager service."""
        self._started = False
        self._is_leader = False

        # Cancel tasks
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass

        if self._leader_task:
            self._leader_task.cancel()
            try:
                await self._leader_task
            except asyncio.CancelledError:
                pass

        logger.info(
            "✅ TimeslotManager stopped (scans=%d, triggers=%d, expirations=%d)",
            self._scan_count,
            self._triggers,
            self._expirations,
        )

    # =========================================================================
    # Leader Election (same pattern as CleanupHostedService)
    # =========================================================================

    async def _leader_loop(self) -> None:
        """Leader election loop — runs scans when leader."""
        while self._started:
            try:
                if await self._try_become_leader():
                    if not self._is_leader:
                        logger.info("TimeslotManager acquired leadership")
                        self._is_leader = True
                        # Start scan loop
                        if self._scan_task is None or self._scan_task.done():
                            self._scan_task = asyncio.create_task(self._scan_loop())
                else:
                    if self._is_leader:
                        logger.info("TimeslotManager lost leadership")
                        self._is_leader = False
                        # Cancel scan
                        if self._scan_task:
                            self._scan_task.cancel()

                # Wait before next election attempt
                await asyncio.sleep(self._election_config.renewal_interval_seconds)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in TimeslotManager leader loop: {e}")
                await asyncio.sleep(5.0)

    async def _try_become_leader(self) -> bool:
        """Attempt to acquire or maintain leadership.

        Uses a separate election key from SchedulerHostedService
        (/lcm/timeslot-manager/leader) so both services can be
        leader simultaneously on the same instance.
        """
        try:
            return await self._etcd.try_acquire_leadership(
                key=f"/lcm/{self._election_config.service_name}/leader",
                lease_ttl=self._election_config.lease_ttl_seconds,
            )
        except Exception as e:
            logger.warning(f"TimeslotManager leader election failed: {e}")
            return False

    # =========================================================================
    # Scan Loop
    # =========================================================================

    async def _scan_loop(self) -> None:
        """Periodic scan loop — only runs when leader."""
        # Brief initial delay to let other services settle
        await asyncio.sleep(5)

        while self._started and self._is_leader:
            scan_start = datetime.now(timezone.utc)
            try:
                await self._run_scan()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._last_error = str(e)
                logger.error(f"TimeslotManager scan failed: {e}", exc_info=True)

            # Sleep for configured interval, accounting for scan duration
            elapsed = (datetime.now(timezone.utc) - scan_start).total_seconds()
            sleep_time = max(0, self._settings.timeslot_manager_interval_seconds - elapsed)
            await asyncio.sleep(sleep_time)

    async def _run_scan(self) -> None:
        """Execute a single timeslot scan cycle.

        1. Query CPA for sessions with imminent deadlines
        2. Trigger scheduling for PENDING sessions approaching their timeslot
        3. Expire PENDING sessions that have missed their timeslot
        4. Prune dedup sets for sessions no longer in the response
        """
        self._scan_count += 1
        self._last_scan_at = datetime.now(timezone.utc).isoformat()

        # Query CPA for imminent deadlines (server-side MongoDB filtering)
        result = await self._api.get_sessions_with_imminent_deadlines(
            boot_window_minutes=self._settings.timeslot_lead_time_minutes,
        )

        approaching = result.get("approaching_start", [])
        past_end = result.get("past_end", [])

        # --- Prune dedup sets: remove sessions no longer in the response ---
        current_approaching_ids = {s["id"] for s in approaching}
        current_past_end_ids = {s["id"] for s in past_end}
        self._triggered_session_ids -= self._triggered_session_ids - current_approaching_ids
        self._expired_session_ids -= self._expired_session_ids - current_past_end_ids

        # --- Trigger scheduling for approaching PENDING sessions ---
        for session in approaching:
            session_id = session["id"]
            session_status = session.get("status", "")
            if session_status == "PENDING" and session_id not in self._triggered_session_ids:
                await self._trigger_scheduling(session_id)
                self._triggered_session_ids.add(session_id)
                self._triggers += 1
                logger.info(
                    "⏰ Timeslot approaching: triggering scheduling for PENDING session %s (start=%s)",
                    session_id,
                    session.get("timeslot_start"),
                )

        # --- Expire PENDING sessions past their timeslot ---
        for session in past_end:
            session_id = session["id"]
            session_status = session.get("status", "")
            if session_status == "PENDING" and session_id not in self._expired_session_ids:
                success = await self._expire_session(session_id)
                if success:
                    self._expired_session_ids.add(session_id)
                    self._expirations += 1
                    logger.info(
                        "⏰ Timeslot missed: expired PENDING session %s (start=%s)",
                        session_id,
                        session.get("timeslot_start"),
                    )

        # Log summary if any actions taken
        if self._triggers > 0 or self._expirations > 0:
            logger.debug(
                "TimeslotManager scan #%d: %d approaching, %d past_end (tracking %d triggered, %d expired)",
                self._scan_count,
                len(approaching),
                len(past_end),
                len(self._triggered_session_ids),
                len(self._expired_session_ids),
            )

    # =========================================================================
    # Actions
    # =========================================================================

    async def _trigger_scheduling(self, session_id: str) -> None:
        """Write an etcd trigger key to wake SchedulerHostedService watch.

        Writes to /lcm/sessions/{session_id}/state with value "PENDING"
        which matches the existing on_watch_event() handler in
        SchedulerHostedService (looks for PUT events with PENDING value).

        Uses a 120s TTL lease so the key auto-cleans up.

        Args:
            session_id: The session ID to trigger scheduling for.
        """
        key = f"{self._key_prefix}/sessions/{session_id}/state"
        try:
            lease = await self._etcd.grant_lease(ttl=120)
            await self._etcd.put(key, "PENDING", lease=lease)
            logger.debug("Wrote etcd trigger key: %s = PENDING (lease_ttl=120s)", key)
        except Exception as e:
            logger.warning("Failed to write etcd trigger for session %s: %s", session_id, e)

    async def _expire_session(self, session_id: str) -> bool:
        """Expire a PENDING session that missed its timeslot via CPA.

        Args:
            session_id: The session ID to expire.

        Returns:
            True if expiration succeeded, False on failure (will be retried next scan).
        """
        try:
            await self._api.expire_session(
                session_id=session_id,
                reason="timeslot_missed",
            )
            logger.debug("Expired session %s via CPA (reason=timeslot_missed)", session_id)
            return True
        except Exception as e:
            logger.error("Failed to expire session %s: %s", session_id, e)
            return False

    # =========================================================================
    # Service Info
    # =========================================================================

    @property
    def stats(self) -> dict[str, Any]:
        """Get timeslot manager statistics for admin endpoints."""
        return {
            "enabled": self._settings.timeslot_manager_enabled,
            "is_leader": self._is_leader,
            "scan_count": self._scan_count,
            "triggers": self._triggers,
            "expirations": self._expirations,
            "tracked_triggered": len(self._triggered_session_ids),
            "tracked_expired": len(self._expired_session_ids),
            "last_scan_at": self._last_scan_at,
            "last_error": self._last_error,
            "interval_seconds": self._settings.timeslot_manager_interval_seconds,
            "lead_time_minutes": self._settings.timeslot_lead_time_minutes,
            "expiry_grace_minutes": self._settings.timeslot_expiry_grace_minutes,
        }

    @property
    def triggered_session_ids(self) -> set[str]:
        """Get the set of session IDs currently tracked as approaching (triggered)."""
        return self._triggered_session_ids.copy()

    @property
    def expired_session_ids(self) -> set[str]:
        """Get the set of session IDs currently tracked as expired."""
        return self._expired_session_ids.copy()

    async def get_approaching_sessions(self) -> list[dict[str, Any]]:
        """Query CPA for PENDING sessions with approaching timeslots.

        Returns the live list from CPA, not just the dedup set. This provides
        full session details for admin visibility.

        Returns:
            List of session dicts with approaching timeslots.
        """
        try:
            result = await self._api.get_sessions_with_imminent_deadlines(
                boot_window_minutes=self._settings.timeslot_lead_time_minutes,
            )
            return result.get("approaching_start", [])
        except Exception as e:
            logger.error("Failed to fetch approaching sessions: %s", e)
            return []

    async def get_expired_sessions(self) -> list[dict[str, Any]]:
        """Query CPA for PENDING sessions past their timeslot.

        Returns the live list from CPA, not just the dedup set.

        Returns:
            List of session dicts with expired timeslots.
        """
        try:
            result = await self._api.get_sessions_with_imminent_deadlines(
                boot_window_minutes=self._settings.timeslot_lead_time_minutes,
            )
            return result.get("past_end", [])
        except Exception as e:
            logger.error("Failed to fetch expired sessions: %s", e)
            return []

    # =========================================================================
    # DI Registration (same pattern as CleanupHostedService)
    # =========================================================================

    @classmethod
    def configure(
        cls,
        services: "ServiceCollection",
        settings: Settings,
    ) -> None:
        """Configure DI registration.

        Args:
            services: Neuroglia service collection.
            settings: Application settings.
        """

        def factory(sp) -> "TimeslotManagerHostedService":
            return cls(
                api_client=sp.get_required_service(ControlPlaneApiClient),
                etcd_client=sp.get_required_service(EtcdClient),
                settings=settings,
            )

        # NOTE: implementation_type=cls ensures Neuroglia resolves the actual class,
        # not a string from inspect.signature().return_annotation.
        services.add_singleton(cls, implementation_type=cls, implementation_factory=factory)
