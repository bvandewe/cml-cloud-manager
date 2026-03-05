"""Admin Controller for Resource Scheduler.

Provides admin endpoints for scheduler operations and monitoring.

POST endpoints require authenticated admin user (JWT via Keycloak).
GET endpoints are public for monitoring tools.
"""

import logging
from typing import Any

from application.hosted_services import SchedulerHostedService
from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_admin

logger = logging.getLogger(__name__)


class AdminController:
    """Admin controller for resource-scheduler service.

    Provides endpoints for:
    - /admin/trigger-reconcile - Trigger immediate reconciliation
    - /admin/leader-status - Get current leader status
    - /admin/stats - Get scheduler statistics
    """

    def __init__(self, scheduler: SchedulerHostedService):
        """Initialize admin controller.

        Args:
            scheduler: The SchedulerHostedService hosted service.
        """
        self._scheduler = scheduler
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
