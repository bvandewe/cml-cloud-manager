"""Admin Controller for Lablet Controller Service.

Provides administrative endpoints for operational control:
- Trigger immediate reconciliation
- View leader status
- View reconciler statistics
- Pipeline control: retry, cancel, status, active handlers (Sprint G)
- Sessions overview: lablet sessions with pipeline handler states
- Sub-services health: lab discovery, lab records, content sync, timeslot watcher

POST endpoints require authenticated admin user (JWT via Keycloak).
GET endpoints are public for monitoring tools.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_admin
from application.hosted_services import LabletReconciler

logger = logging.getLogger(__name__)


class AdminController:
    """Admin controller for lablet-controller service.

    Provides endpoints for:
    - /admin/trigger-reconcile - Trigger immediate reconciliation
    - /admin/leader-status - Get current leader status
    - /admin/stats - Get reconciler statistics
    - /admin/sessions/{session_id}/retry-pipeline - Retry failed pipeline (Sprint G)
    - /admin/sessions/{session_id}/cancel-pipeline - Cancel running pipeline (Sprint G)
    - /admin/sessions/{session_id}/pipeline-status - Pipeline handler state (Sprint G)
    - /admin/active-handlers - List all in-flight handlers (Sprint G)
    - /admin/sessions-overview - Sessions with pipeline states
    - /admin/sub-services - Sub-service health and stats
    """

    def __init__(self, reconciler: LabletReconciler):
        """Initialize admin controller.

        Args:
            reconciler: The LabletReconciler hosted service.
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
                Statistics about reconciliation cycles and lab lifecycle actions.
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
        # Sprint G: Pipeline Control Endpoints
        # =================================================================

        @self.router.post(
            "/sessions/{session_id}/retry-pipeline",
            summary="Retry Pipeline",
        )
        async def retry_pipeline(
            session_id: str,
            user: dict = Depends(require_admin),
        ) -> dict[str, Any]:
            """Retry a failed or stopped pipeline for a session.

            Clears the handler from _active_handlers and resets the retry
            count so the reconciliation loop will restart the pipeline on
            its next cycle.

            Requires admin authentication.

            Args:
                session_id: The LabletSession ID.

            Returns:
                Status of the retry operation.

            Raises:
                HTTPException: 404 if no handler exists for this session.
            """
            if not self._reconciler.is_leader:
                raise HTTPException(
                    status_code=409,
                    detail="This instance is not the leader. Only the leader can control pipelines.",
                )

            # Find handler(s) for this session
            handler_keys = [key for key in self._reconciler._active_handlers if key.startswith(f"{session_id}:")]

            if not handler_keys:
                raise HTTPException(
                    status_code=404,
                    detail=f"No active pipeline handler found for session '{session_id}'.",
                )

            cleared = []
            for key in handler_keys:
                handler = self._reconciler._active_handlers.get(key)
                if handler:
                    # Stop if still running
                    if handler.is_running:
                        await handler.stop()
                    # Remove from active handlers
                    del self._reconciler._active_handlers[key]
                    # Reset retry count so reconciler treats it as fresh
                    self._reconciler._pipeline_retry_counts.pop(key, None)
                    cleared.append(key)

            logger.info(
                "Pipeline retry triggered by %s for session %s — cleared handlers: %s",
                user.get("username"),
                session_id,
                cleared,
            )

            return {
                "status": "retry_scheduled",
                "message": "Handler cleared. Reconcile loop will restart the pipeline.",
                "session_id": session_id,
                "cleared_handlers": cleared,
                "triggered_by": user.get("username"),
            }

        @self.router.post(
            "/sessions/{session_id}/cancel-pipeline",
            summary="Cancel Pipeline",
        )
        async def cancel_pipeline(
            session_id: str,
            user: dict = Depends(require_admin),
        ) -> dict[str, Any]:
            """Cancel a running pipeline for a session.

            Calls handler.stop() on the LifecyclePhaseHandler and removes
            it from _active_handlers. The pipeline will NOT be restarted
            by the reconciler unless retry-pipeline is called.

            Requires admin authentication.

            Args:
                session_id: The LabletSession ID.

            Returns:
                Status of the cancel operation.

            Raises:
                HTTPException: 404 if no handler exists for this session.
            """
            if not self._reconciler.is_leader:
                raise HTTPException(
                    status_code=409,
                    detail="This instance is not the leader. Only the leader can control pipelines.",
                )

            handler_keys = [key for key in self._reconciler._active_handlers if key.startswith(f"{session_id}:")]

            if not handler_keys:
                raise HTTPException(
                    status_code=404,
                    detail=f"No active pipeline handler found for session '{session_id}'.",
                )

            cancelled = []
            for key in handler_keys:
                handler = self._reconciler._active_handlers.get(key)
                if handler:
                    if handler.is_running:
                        await handler.stop()
                    del self._reconciler._active_handlers[key]
                    # Keep retry count — prevents reconciler from restarting
                    cancelled.append(
                        {
                            "handler_key": key,
                            "pipeline_name": handler.pipeline_name,
                            "was_running": handler.is_running,  # After stop, always False
                        }
                    )

            logger.info(
                "Pipeline cancelled by %s for session %s — cancelled: %s",
                user.get("username"),
                session_id,
                [c["handler_key"] for c in cancelled],
            )

            return {
                "status": "cancelled",
                "message": "Pipeline handler(s) stopped and removed.",
                "session_id": session_id,
                "cancelled_handlers": cancelled,
                "triggered_by": user.get("username"),
            }

        @self.router.get(
            "/sessions/{session_id}/pipeline-status",
            summary="Pipeline Status",
        )
        async def pipeline_status(
            session_id: str,
        ) -> dict[str, Any]:
            """Get pipeline handler state for a session.

            Returns the current state of all active pipeline handlers
            for the given session, including running status, attempt count,
            and result information.

            Public endpoint for monitoring tools.

            Args:
                session_id: The LabletSession ID.

            Returns:
                Pipeline handler state for the session.

            Raises:
                HTTPException: 404 if no handler exists for this session.
            """
            handler_keys = [key for key in self._reconciler._active_handlers if key.startswith(f"{session_id}:")]

            if not handler_keys:
                raise HTTPException(
                    status_code=404,
                    detail=f"No active pipeline handler found for session '{session_id}'.",
                )

            handlers_state = []
            for key in handler_keys:
                handler = self._reconciler._active_handlers[key]
                result = handler.result
                error = handler.error
                handler_info: dict[str, Any] = {
                    "handler_key": key,
                    "pipeline_name": handler.pipeline_name,
                    "session_id": handler.session_id,
                    "is_running": handler.is_running,
                    "attempt": handler.pipeline_attempt,
                    "retry_count": self._reconciler._pipeline_retry_counts.get(key, 0),
                }
                if result:
                    handler_info["result_status"] = result.status
                    handler_info["steps_completed"] = result.steps_completed
                    handler_info["steps_failed"] = result.steps_failed
                    handler_info["steps_skipped"] = result.steps_skipped
                    handler_info["duration_seconds"] = result.duration_seconds
                    if result.error:
                        handler_info["result_error"] = result.error
                elif error:
                    handler_info["result_status"] = "crashed"
                    handler_info["crash_error"] = str(error)
                else:
                    handler_info["result_status"] = "running" if handler.is_running else "pending"

                handlers_state.append(handler_info)

            return {
                "session_id": session_id,
                "handlers": handlers_state,
            }

        @self.router.get(
            "/active-handlers",
            summary="Active Handlers",
        )
        async def active_handlers() -> dict[str, Any]:
            """List all in-flight pipeline handlers.

            Returns all entries in the reconciler's _active_handlers dict
            with their current status.

            Public endpoint for monitoring tools.

            Returns:
                List of all active handlers with status information.
            """
            handlers = []
            for key, handler in self._reconciler._active_handlers.items():
                result = handler.result
                error = handler.error
                info: dict[str, Any] = {
                    "handler_key": key,
                    "pipeline_name": handler.pipeline_name,
                    "session_id": handler.session_id,
                    "is_running": handler.is_running,
                    "attempt": handler.pipeline_attempt,
                    "retry_count": self._reconciler._pipeline_retry_counts.get(key, 0),
                }
                if result:
                    info["result_status"] = result.status
                    info["duration_seconds"] = result.duration_seconds
                    if result.error:
                        info["result_error"] = result.error
                elif error:
                    info["result_status"] = "crashed"
                    info["crash_error"] = str(error)
                else:
                    info["result_status"] = "running" if handler.is_running else "pending"

                handlers.append(info)

            return {
                "total": len(handlers),
                "handlers": handlers,
            }

        # =================================================================
        # Sessions & Sub-Services Endpoints
        # =================================================================

        @self.router.get("/sessions-overview", summary="Sessions Overview")
        async def sessions_overview() -> dict[str, Any]:
            """Get lablet sessions overview with pipeline handler states.

            Returns active sessions enriched with pipeline handler information
            and reconciliation state.

            Public endpoint for monitoring and admin dashboards.

            Returns:
                Sessions list with status distribution and pipeline handler data.
            """
            try:
                sessions = await self._reconciler._api.get_lablet_sessions()
            except Exception as e:
                logger.exception("Failed to fetch sessions from CPA")
                raise HTTPException(status_code=502, detail=f"Failed to fetch sessions: {e}")

            # Build pipeline handler map keyed by session_id
            handler_map: dict[str, list[dict[str, Any]]] = {}
            for key, handler in self._reconciler._active_handlers.items():
                sid = handler.session_id
                result = handler.result
                error = handler.error
                info: dict[str, Any] = {
                    "handler_key": key,
                    "pipeline_name": handler.pipeline_name,
                    "is_running": handler.is_running,
                    "attempt": handler.pipeline_attempt,
                    "retry_count": self._reconciler._pipeline_retry_counts.get(key, 0),
                }
                if result:
                    info["result_status"] = result.status
                    info["steps_completed"] = result.steps_completed
                    info["duration_seconds"] = result.duration_seconds
                    if result.error:
                        info["result_error"] = result.error
                elif error:
                    info["result_status"] = "crashed"
                    info["crash_error"] = str(error)
                else:
                    info["result_status"] = "running" if handler.is_running else "pending"
                handler_map.setdefault(sid, []).append(info)

            # Resource states
            resource_states = {}
            for rid, rs in self._reconciler._resource_states.items():
                resource_states[rid] = {
                    "in_progress": rs.in_progress,
                    "failure_count": rs.failure_count,
                }

            # Status counts
            status_counts: dict[str, int] = {}
            for s in sessions:
                status = s.get("status", "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1

            return {
                "total": len(sessions),
                "status_counts": status_counts,
                "active_handlers": len(self._reconciler._active_handlers),
                "sessions": sessions,
                "pipeline_handlers": handler_map,
                "resource_states": resource_states,
            }

        @self.router.get("/sub-services", summary="Sub-Services Health")
        async def sub_services() -> dict[str, Any]:
            """Get health and stats for all sub-services.

            Returns statistics from Lab Discovery, Lab Record Reconciler,
            Content Sync, and Timeslot Watcher sub-services.

            Public endpoint for monitoring and admin dashboards.

            Returns:
                Per-service health status and statistics.
            """
            result: dict[str, Any] = {}

            if self._reconciler._lab_discovery_service:
                result["lab_discovery"] = self._reconciler._lab_discovery_service.get_stats()
            else:
                result["lab_discovery"] = {"enabled": False, "message": "Not configured"}

            if self._reconciler._lab_record_reconciler:
                result["lab_record_reconciler"] = self._reconciler._lab_record_reconciler.get_stats()
            else:
                result["lab_record_reconciler"] = {"enabled": False, "message": "Not configured"}

            if self._reconciler._content_sync_service:
                result["content_sync"] = self._reconciler._content_sync_service.get_stats()
            else:
                result["content_sync"] = {"enabled": False, "message": "Not configured"}

            if self._reconciler._timeslot_watcher_service:
                result["timeslot_watcher"] = self._reconciler._timeslot_watcher_service.get_stats()
            else:
                result["timeslot_watcher"] = {"enabled": False, "message": "Not configured"}

            return result
