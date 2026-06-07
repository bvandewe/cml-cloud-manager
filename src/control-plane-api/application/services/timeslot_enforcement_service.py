"""Timeslot Enforcement Service — CPA-side defense-in-depth for expiry.

ADR-036 §2.3 Defense-in-Depth: This service runs inside the Control Plane API
itself, independently of the lablet-controller's TimeslotWatcherService and
reconciler. If the reactive path (etcd watch → reconcile → expire) fails or is
delayed, this service detects and expires stale sessions autonomously.

Architecture:
- Runs as a HostedService (asyncio.Task) within the CPA process
- Polls the LabletSession repository every ENFORCEMENT_INTERVAL_SECONDS
- For each session past its timeslot.end that is still in an actionable status,
  executes ExpireLabletSessionCommand via the Mediator
- Independent of etcd, lablet-controller, or any external coordination
- Idempotent: ExpireLabletSessionCommand is a no-op on already-expired sessions

This is intentionally a simple polling loop, not event-driven, because its
purpose is to catch anything the reactive path misses.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from application.commands.lablet_session.expire_lablet_session_command import ExpireLabletSessionCommand
from application.settings import app_settings
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.hosting.abstractions import HostedService
from neuroglia.mediation import Mediator

if TYPE_CHECKING:
    from neuroglia.dependency_injection.service_provider import ServiceProvider
    from neuroglia.hosting.web import WebApplicationBuilder

logger = logging.getLogger(__name__)

# Default enforcement interval: 60 seconds
ENFORCEMENT_INTERVAL_SECONDS = 60


class TimeslotEnforcementService(HostedService):
    """Periodically expires sessions that have outlived their timeslot.

    This is the CPA's autonomous safety net: if the lablet-controller fails
    to trigger expiry (network partition, etcd outage, controller crash),
    this service ensures sessions don't remain active indefinitely.
    """

    def __init__(self, service_provider: "ServiceProvider"):
        self._service_provider = service_provider
        self._running = False
        self._task: asyncio.Task | None = None
        self._enforcement_count = 0
        self._last_run_at: datetime | None = None
        self._last_error: str | None = None

    async def start_async(self) -> None:
        """Start the enforcement loop."""
        if self._running:
            return

        if not getattr(app_settings, "timeslot_enforcement_enabled", True):
            logger.info("TimeslotEnforcementService disabled by configuration")
            return

        self._running = True
        self._task = asyncio.create_task(self._enforcement_loop(), name="timeslot-enforcement")
        logger.info(
            "TimeslotEnforcementService started (interval=%ds)",
            ENFORCEMENT_INTERVAL_SECONDS,
        )

    async def stop_async(self) -> None:
        """Stop the enforcement loop."""
        if not self._running:
            return
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("TimeslotEnforcementService stopped")

    async def _enforcement_loop(self) -> None:
        """Main loop: periodically check and expire stale sessions."""
        # Brief startup delay to let the app fully initialize
        await asyncio.sleep(10)

        while self._running:
            loop_start = datetime.now(timezone.utc)
            try:
                await self._enforce_timeslots()
                self._last_error = None
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._last_error = str(e)
                logger.error("TimeslotEnforcementService error: %s", e, exc_info=True)

            self._last_run_at = loop_start
            elapsed = (datetime.now(timezone.utc) - loop_start).total_seconds()
            sleep_time = max(0, ENFORCEMENT_INTERVAL_SECONDS - elapsed)
            try:
                await asyncio.sleep(sleep_time)
            except asyncio.CancelledError:
                break

    async def _enforce_timeslots(self) -> None:
        """Find and expire sessions past their timeslot end."""
        now = datetime.now(timezone.utc)

        # Get services from the scoped provider
        scope = self._service_provider.create_scope()
        session_repo = scope.get_required_service(LabletSessionRepository)
        mediator = scope.get_required_service(Mediator)

        # Query for sessions past their timeslot end
        expired_sessions = await session_repo.list_past_end_async(as_of=now)

        if not expired_sessions:
            return

        logger.info(
            "TimeslotEnforcementService: found %d sessions past timeslot end",
            len(expired_sessions),
        )

        for session in expired_sessions:
            session_id = session.id()
            try:
                command = ExpireLabletSessionCommand(
                    session_id=session_id,
                    reason="timeslot_enforcement_cpa",
                )
                result = await mediator.execute_async(command)
                if result.is_success:
                    self._enforcement_count += 1
                    logger.info(
                        "✅ TimeslotEnforcementService: expired session %s",
                        session_id,
                    )
                else:
                    logger.warning(
                        "TimeslotEnforcementService: expire command failed for %s: %s",
                        session_id,
                        result.error_message,
                    )
            except Exception as e:
                logger.error(
                    "TimeslotEnforcementService: exception expiring session %s: %s",
                    session_id,
                    e,
                )

    def get_stats(self) -> dict:
        """Get operational statistics for the admin /info endpoint."""
        return {
            "enabled": getattr(app_settings, "timeslot_enforcement_enabled", True),
            "running": self._running,
            "interval_seconds": ENFORCEMENT_INTERVAL_SECONDS,
            "enforcement_count": self._enforcement_count,
            "last_run_at": self._last_run_at.isoformat() if self._last_run_at else None,
            "last_error": self._last_error,
        }

    @staticmethod
    def configure(builder: "WebApplicationBuilder") -> None:
        """Register TimeslotEnforcementService with the DI builder.

        Registers as a singleton HostedService — the Neuroglia framework
        automatically calls start_async/stop_async with app lifecycle.
        """
        builder.services.add_singleton(
            TimeslotEnforcementService,
            implementation_factory=lambda sp: TimeslotEnforcementService(service_provider=sp),
        )
        logger.info("✅ TimeslotEnforcementService configured as singleton HostedService")
