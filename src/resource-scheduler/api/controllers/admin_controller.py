"""Admin Controller for Resource Scheduler.

Provides admin endpoints for scheduler operations and monitoring.
- Trigger immediate reconciliation
- View leader status
- View scheduler statistics
- Timeslot manager status (Sprint H)
- Timeslot admin queries: approaching, expired, landscape (Sprint H)
- Scheduling overview: pending sessions, retries, capacity
- Sub-services health: scheduler, timeslot manager, cleanup

POST endpoints require authenticated admin user (JWT via Keycloak).
GET endpoints are public for monitoring tools.
"""

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_admin
from application.hosted_services import SchedulerHostedService

if TYPE_CHECKING:
    from application.hosted_services import CleanupHostedService, TimeslotManagerHostedService

logger = logging.getLogger(__name__)


class AdminController:
    """Admin controller for resource-scheduler service.

    Provides endpoints for:
    - /admin/trigger-reconcile - Trigger immediate reconciliation
    - /admin/leader-status - Get current leader status
    - /admin/stats - Get scheduler statistics
    - /admin/timeslots/status - Get timeslot manager status (Sprint H)
    - /admin/timeslots/approaching - PENDING sessions entering scheduling window (Sprint H)
    - /admin/timeslots/expired - Sessions with expired timeslots (Sprint H)
    - /admin/timeslots/landscape - Timeslot distribution for next 24h (Sprint H)
    - /admin/scheduling-overview - Pending sessions, retries, capacity
    - /admin/sub-services - All sub-service health and stats
    """

    def __init__(
        self,
        scheduler: SchedulerHostedService,
        timeslot_manager: "TimeslotManagerHostedService | None" = None,
        cleanup_service: "CleanupHostedService | None" = None,
    ):
        """Initialize admin controller.

        Args:
            scheduler: The SchedulerHostedService hosted service.
            timeslot_manager: The TimeslotManagerHostedService hosted service (Sprint H).
            cleanup_service: The CleanupHostedService hosted service.
        """
        self._scheduler = scheduler
        self._timeslot_manager = timeslot_manager
        self._cleanup_service = cleanup_service
        self.router = APIRouter(prefix="/admin", tags=["Admin"])
        self._register_routes()

    def _register_routes(self) -> None:
        """Register admin routes."""

        @self.router.post("/trigger-reconcile", summary="Trigger Reconcile")
        async def trigger_reconcile(
            user: dict = Depends(require_admin),
        ) -> dict[str, Any]:
            """Trigger immediate reconciliation cycle.

            Requires admin authentication.
            Only works if this instance is the leader.

            Returns:
                Status and current stats.

            Raises:
                HTTPException: 401 if not authenticated, 403 if not admin, 409 if not leader.
            """
            if not self._scheduler.is_leader:
                raise HTTPException(
                    status_code=409,
                    detail="This instance is not the leader. Only the leader can trigger reconciliation.",
                )

            await self._scheduler.reconcile_now()
            logger.info(f"Manual reconciliation triggered by {user.get('username')} via admin endpoint")

            return {
                "status": "triggered",
                "message": "Reconciliation cycle started",
                "triggered_by": user.get("username"),
                "stats": self._scheduler.stats,
            }

        @self.router.get("/leader-status", summary="Leader Status")
        async def leader_status() -> dict[str, Any]:
            """Get current leader election status.

            Returns:
                Leader status including whether this instance is the leader.
            """
            return {
                "is_leader": self._scheduler.is_leader,
                "current_leader_id": self._scheduler.current_leader_id,
                "instance_id": self._scheduler.instance_id,
                "service_name": "resource-scheduler",
            }

        @self.router.get("/stats", summary="Stats")
        async def stats() -> dict[str, Any]:
            """Get scheduler statistics.

            Returns:
                Statistics about scheduling cycles.
            """
            return self._scheduler.stats

        @self.router.post("/resign-leadership", summary="Resign Leadership")
        async def resign_leadership(
            user: dict = Depends(require_admin),
        ) -> dict[str, Any]:
            """Resign leadership (for testing/maintenance).

            Requires admin authentication.
            This instance will stop being the leader and another
            instance will take over.

            Returns:
                Status of the operation.

            Raises:
                HTTPException: 401 if not authenticated, 403 if not admin, 409 if not leader.
            """
            if not self._scheduler.is_leader:
                raise HTTPException(
                    status_code=409,
                    detail="This instance is not the leader.",
                )

            await self._scheduler.resign_leadership()
            logger.info(f"Leadership resigned by {user.get('username')} via admin endpoint")

            return {
                "status": "resigned",
                "message": "Leadership has been resigned. Another instance will take over.",
                "resigned_by": user.get("username"),
            }

        @self.router.get("/timeslots/status", summary="Timeslot Manager Status")
        async def timeslot_status() -> dict[str, Any]:
            """Get timeslot management status and statistics.

            Returns TimeslotManagerHostedService stats including:
            - Running state, scan count, triggers, expirations
            - Last scan timestamp, last error
            - Currently tracked approaching/expired sessions
            """
            if self._timeslot_manager is None:
                return {
                    "enabled": False,
                    "message": "TimeslotManager not configured",
                }
            return self._timeslot_manager.stats

        @self.router.get("/timeslots/approaching", summary="Approaching Timeslot Sessions")
        async def timeslot_approaching() -> dict[str, Any]:
            """Get PENDING sessions with approaching timeslots.

            Live-queries CPA for sessions whose timeslot_start is within
            the configured lead_time_minutes window. Returns full session
            details for admin visibility.

            Returns:
                Dict with sessions list and metadata.
            """
            if self._timeslot_manager is None:
                return {"enabled": False, "message": "TimeslotManager not configured"}

            sessions = await self._timeslot_manager.get_approaching_sessions()
            return {
                "total": len(sessions),
                "lead_time_minutes": self._timeslot_manager.stats.get("lead_time_minutes"),
                "sessions": sessions,
                "tracked_triggered_ids": sorted(self._timeslot_manager.triggered_session_ids),
            }

        @self.router.get("/timeslots/expired", summary="Expired Timeslot Sessions")
        async def timeslot_expired() -> dict[str, Any]:
            """Get PENDING sessions past their timeslot window.

            Live-queries CPA for sessions whose timeslot has expired.
            These sessions are candidates for expiration by the TimeslotManager.

            Returns:
                Dict with sessions list and metadata.
            """
            if self._timeslot_manager is None:
                return {"enabled": False, "message": "TimeslotManager not configured"}

            sessions = await self._timeslot_manager.get_expired_sessions()
            return {
                "total": len(sessions),
                "expiry_grace_minutes": self._timeslot_manager.stats.get("expiry_grace_minutes"),
                "sessions": sessions,
                "tracked_expired_ids": sorted(self._timeslot_manager.expired_session_ids),
            }

        @self.router.get("/timeslots/landscape", summary="Timeslot Landscape")
        async def timeslot_landscape() -> dict[str, Any]:
            """Get overview of timeslot distribution for the next 24 hours.

            Returns a histogram of PENDING/SCHEDULED sessions bucketed by
            hour of their timeslot_start. Provides visibility into upcoming
            scheduling demand.

            Returns:
                Dict with hourly distribution and summary.
            """
            if self._timeslot_manager is None:
                return {"enabled": False, "message": "TimeslotManager not configured"}

            try:
                # Fetch all pending and scheduled sessions
                pending = await self._scheduler._api.get_lablet_sessions(status="pending")
                scheduled = await self._scheduler._api.get_lablet_sessions(status="scheduled")
            except Exception as e:
                logger.exception("Failed to fetch sessions for timeslot landscape")
                raise HTTPException(status_code=502, detail=f"Failed to fetch sessions: {e}")

            from datetime import datetime, timedelta, timezone

            now = datetime.now(timezone.utc)
            window_end = now + timedelta(hours=24)

            # Build hourly buckets for next 24 hours
            buckets: dict[str, list[dict[str, Any]]] = {}
            for hour_offset in range(24):
                bucket_start = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=hour_offset)
                bucket_key = bucket_start.strftime("%Y-%m-%dT%H:00Z")
                buckets[bucket_key] = []

            no_timeslot: list[dict[str, Any]] = []
            outside_window: list[dict[str, Any]] = []

            for session in pending + scheduled:
                ts_start_raw = session.get("timeslot_start") if isinstance(session, dict) else getattr(session, "timeslot_start", None)
                if ts_start_raw is None:
                    sid = session.get("id") if isinstance(session, dict) else getattr(session, "id", "?")
                    status = session.get("status") if isinstance(session, dict) else getattr(session, "status", "?")
                    no_timeslot.append({"id": sid, "status": status})
                    continue

                # Parse timeslot_start
                if isinstance(ts_start_raw, str):
                    try:
                        ts_start = datetime.fromisoformat(ts_start_raw.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                elif isinstance(ts_start_raw, datetime):
                    ts_start = ts_start_raw if ts_start_raw.tzinfo else ts_start_raw.replace(tzinfo=timezone.utc)
                else:
                    continue

                if ts_start > window_end or ts_start < now - timedelta(hours=1):
                    sid = session.get("id") if isinstance(session, dict) else getattr(session, "id", "?")
                    status = session.get("status") if isinstance(session, dict) else getattr(session, "status", "?")
                    outside_window.append({"id": sid, "status": status, "timeslot_start": ts_start_raw})
                    continue

                # Find the right bucket
                bucket_hour = ts_start.replace(minute=0, second=0, microsecond=0)
                bucket_key = bucket_hour.strftime("%Y-%m-%dT%H:00Z")
                if bucket_key in buckets:
                    sid = session.get("id") if isinstance(session, dict) else getattr(session, "id", "?")
                    status = session.get("status") if isinstance(session, dict) else getattr(session, "status", "?")
                    buckets[bucket_key].append({"id": sid, "status": status, "timeslot_start": ts_start_raw})

            # Summarize
            hourly_counts = {k: len(v) for k, v in buckets.items()}
            total_in_window = sum(hourly_counts.values())

            return {
                "window_start": now.isoformat(),
                "window_end": window_end.isoformat(),
                "total_in_window": total_in_window,
                "no_timeslot": len(no_timeslot),
                "outside_window": len(outside_window),
                "hourly_distribution": hourly_counts,
                "hourly_sessions": {k: v for k, v in buckets.items() if v},
            }

        # =================================================================
        # Scheduling & Sub-Services Endpoints
        # =================================================================

        @self.router.get("/scheduling-overview", summary="Scheduling Overview")
        async def scheduling_overview() -> dict[str, Any]:
            """Get scheduling overview with pending sessions, retries, and capacity.

            Returns pending and scheduled sessions from CPA, per-session retry counts,
            etcd capacity cache stats, and resource reconciliation states.

            Public endpoint for monitoring and admin dashboards.

            Returns:
                Scheduling overview with pending sessions, retries, and capacity data.
            """
            try:
                pending = await self._scheduler._api.get_lablet_sessions(status="pending")
            except Exception as e:
                logger.exception("Failed to fetch pending sessions from CPA")
                raise HTTPException(status_code=502, detail=f"Failed to fetch sessions: {e}")

            try:
                scheduled = await self._scheduler._api.get_lablet_sessions(status="scheduled")
            except Exception:
                scheduled = []

            # Retry counts
            retry_summary = {
                "total_tracked": len(self._scheduler._instance_retry_counts),
                "sessions_at_max": sum(1 for v in self._scheduler._instance_retry_counts.values() if v >= self._scheduler._max_scheduling_retries),
                "retries": dict(self._scheduler._instance_retry_counts),
            }

            # Capacity cache summary
            capacity_summary = {
                "total_cached": len(self._scheduler._etcd_capacities),
            }

            # Resource states
            resource_states = {}
            for rid, rs in self._scheduler._resource_states.items():
                resource_states[rid] = {
                    "in_progress": rs.in_progress,
                    "failure_count": rs.failure_count,
                }

            return {
                "pending_sessions": {
                    "total": len(pending),
                    "sessions": pending,
                },
                "scheduled_sessions": {
                    "total": len(scheduled),
                    "sessions": scheduled,
                },
                "retry_counts": retry_summary,
                "capacity_cache": capacity_summary,
                "resource_states": resource_states,
            }

        @self.router.get("/sub-services", summary="Sub-Services Health")
        async def sub_services() -> dict[str, Any]:
            """Get health and stats for all sub-services.

            Returns statistics from Scheduler, TimeslotManager, and Cleanup services.

            Public endpoint for monitoring and admin dashboards.

            Returns:
                Per-service health status and statistics.
            """
            result: dict[str, Any] = {}

            result["scheduler"] = self._scheduler.stats

            if self._timeslot_manager:
                result["timeslot_manager"] = self._timeslot_manager.stats
            else:
                result["timeslot_manager"] = {"enabled": False, "message": "Not configured"}

            if self._cleanup_service:
                result["cleanup"] = self._cleanup_service.stats
            else:
                result["cleanup"] = {"enabled": False, "message": "Not configured"}

            return result
