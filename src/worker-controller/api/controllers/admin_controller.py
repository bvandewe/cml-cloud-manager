"""Admin Controller for Worker Controller Service.

Provides administrative endpoints for operational control:
- Trigger immediate reconciliation
- View leader status
- View reconciler statistics
- Worker fleet overview from CPA with reconciliation state
- Operational overview: discovery, metrics, scale-down, licenses

POST endpoints require authenticated admin user (JWT via Keycloak).
GET endpoints are public for monitoring tools.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_admin
from application.hosted_services import WorkerReconciler

logger = logging.getLogger(__name__)


class AdminController:
    """Admin controller for worker-controller service.

    Provides endpoints for:
    - /admin/trigger-reconcile - Trigger immediate reconciliation
    - /admin/leader-status - Get current leader status
    - /admin/stats - Get reconciler statistics
    - /admin/fleet - Worker fleet overview with status distribution
    - /admin/operations - Operations overview (discovery, metrics, scale-down)
    """

    def __init__(self, reconciler: WorkerReconciler):
        """Initialize admin controller.

        Args:
            reconciler: The WorkerReconciler hosted service.
        """
        self._reconciler = reconciler
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
            if not self._reconciler.is_leader:
                raise HTTPException(
                    status_code=409,
                    detail="This instance is not the leader. Only the leader can trigger reconciliation.",
                )

            await self._reconciler.reconcile_now()
            logger.info(f"Manual reconciliation triggered by {user.get('username')} via admin endpoint")

            return {
                "status": "triggered",
                "message": "Reconciliation cycle started",
                "triggered_by": user.get("username"),
                "stats": self._reconciler.stats,
            }

        @self.router.get("/leader-status", summary="Leader Status")
        async def leader_status() -> dict[str, Any]:
            """Get current leader election status.

            Returns:
                Leader status including whether this instance is the leader.
            """
            return {
                "is_leader": self._reconciler.is_leader,
                "current_leader_id": self._reconciler.current_leader_id,
                "instance_id": self._reconciler.instance_id,
            }

        @self.router.get("/stats", summary="Stats")
        async def stats() -> dict[str, Any]:
            """Get reconciler statistics.

            Returns:
                Statistics about reconciliation cycles and worker lifecycle actions.
            """
            return self._reconciler.stats

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
            if not self._reconciler.is_leader:
                raise HTTPException(
                    status_code=409,
                    detail="This instance is not the leader.",
                )

            await self._reconciler.resign_leadership()
            logger.info(f"Leadership resigned by {user.get('username')} via admin endpoint")

            return {
                "status": "resigned",
                "message": "Leadership has been resigned. Another instance will take over.",
                "resigned_by": user.get("username"),
            }

        # =================================================================
        # Fleet & Operations Endpoints
        # =================================================================

        @self.router.get("/fleet", summary="Worker Fleet Overview")
        async def fleet() -> dict[str, Any]:
            """Get worker fleet overview from Control Plane API.

            Returns current worker list enriched with reconciliation state.
            Public endpoint for monitoring and admin dashboards.

            Returns:
                Worker fleet with status distribution and resource states.
            """
            try:
                workers = await self._reconciler._api.get_workers()
            except Exception as e:
                logger.exception("Failed to fetch workers from CPA")
                raise HTTPException(status_code=502, detail=f"Failed to fetch workers: {e}")

            # Enrich with resource reconciliation state
            resource_states = {}
            for rid, rs in self._reconciler._resource_states.items():
                resource_states[rid] = {
                    "in_progress": rs.in_progress,
                    "failure_count": rs.failure_count,
                    "last_attempt": rs.last_attempt,
                    "next_retry": rs.next_retry,
                }

            # Summarize by status
            status_counts: dict[str, int] = {}
            for w in workers:
                status = w.get("status", "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1

            return {
                "total": len(workers),
                "status_counts": status_counts,
                "workers": workers,
                "resource_states": resource_states,
            }

        @self.router.get("/operations", summary="Operations Overview")
        async def operations() -> dict[str, Any]:
            """Get operational overview including discovery, metrics, and resource states.

            Returns extended info from the reconciler including discovery statistics,
            scale-down tracking, and per-resource reconciliation state summary.

            Public endpoint for monitoring and admin dashboards.

            Returns:
                Operational overview with discovery stats and resource state summary.
            """
            extra = self._reconciler.get_extra_info()

            # Resource states summary
            states = self._reconciler._resource_states
            resource_summary = {
                "total": len(states),
                "in_progress": sum(1 for rs in states.values() if rs.in_progress),
                "failed": sum(1 for rs in states.values() if rs.failure_count > 0),
                "healthy": sum(1 for rs in states.values() if rs.failure_count == 0 and not rs.in_progress),
            }

            return {
                **extra,
                "resource_states_summary": resource_summary,
            }
