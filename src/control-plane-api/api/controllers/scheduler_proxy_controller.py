"""Scheduler Proxy Controller.

Proxies UI requests to the resource-scheduler microservice.
The browser cannot call the resource-scheduler directly (no nginx proxy, CORS),
so all scheduler API calls are routed through this CPA controller.

Endpoints proxied:
- GET  /scheduler/admin/leader-status       → resource-scheduler GET /api/admin/leader-status
- GET  /scheduler/admin/stats               → resource-scheduler GET /api/admin/stats
- POST /scheduler/admin/trigger-reconcile   → resource-scheduler POST /api/admin/trigger-reconcile
- POST /scheduler/admin/resign-leadership   → resource-scheduler POST /api/admin/resign-leadership
- POST /scheduler/scheduling/preview        → resource-scheduler POST /api/scheduling/preview

Auth: Cookie-based session (UI) or Bearer JWT. The proxy forwards the user's
Bearer token to the resource-scheduler for its own auth validation.
"""

import logging
from typing import Any

import httpx
from api.dependencies import get_current_user, require_roles
from application.settings import app_settings
from classy_fastapi.decorators import get, post
from fastapi import Depends, HTTPException, Request
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping.mapper import Mapper
from neuroglia.mediation.mediator import Mediator
from neuroglia.mvc.controller_base import ControllerBase

logger = logging.getLogger(__name__)

# Shared httpx timeout for scheduler proxy calls
_PROXY_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)


class SchedulerController(ControllerBase):
    """Proxy controller that forwards requests to the resource-scheduler service.

    The resource-scheduler runs as a separate microservice (resource-scheduler:8081).
    Since the browser has no direct route to it (no nginx location block, CORS),
    the CPA acts as a Backend-for-Frontend (BFF) proxy for scheduler operations.

    Routes are mounted under /api/scheduler/* by Neuroglia's prefix convention
    (class name 'SchedulerController' → prefix 'scheduler').
    """

    def __init__(self, service_provider: ServiceProviderBase, mapper: Mapper, mediator: Mediator):
        ControllerBase.__init__(self, service_provider, mapper, mediator)

    def _get_scheduler_url(self) -> str:
        """Get the resource-scheduler base URL from settings."""
        return app_settings.resource_scheduler_url.rstrip("/")

    async def _proxy_get(self, path: str, request: Request) -> Any:
        """Proxy a GET request to the resource-scheduler.

        Args:
            path: URL path on the resource-scheduler (e.g. /admin/stats).
            request: Original FastAPI request (for forwarding auth headers).

        Returns:
            JSON response from the resource-scheduler.

        Raises:
            HTTPException: On connection errors or non-2xx responses.
        """
        url = f"{self._get_scheduler_url()}{path}"
        headers = self._build_proxy_headers(request)

        try:
            async with httpx.AsyncClient(timeout=_PROXY_TIMEOUT) as client:
                resp = await client.get(url, headers=headers)
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="Resource scheduler is unavailable")
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Resource scheduler request timed out")

        return self._process_response(resp)

    async def _proxy_post(self, path: str, request: Request, body: dict | None = None) -> Any:
        """Proxy a POST request to the resource-scheduler.

        Args:
            path: URL path on the resource-scheduler (e.g. /scheduling/preview).
            request: Original FastAPI request (for forwarding auth headers).
            body: Optional JSON body to forward.

        Returns:
            JSON response from the resource-scheduler.

        Raises:
            HTTPException: On connection errors or non-2xx responses.
        """
        url = f"{self._get_scheduler_url()}{path}"
        headers = self._build_proxy_headers(request)

        try:
            async with httpx.AsyncClient(timeout=_PROXY_TIMEOUT) as client:
                resp = await client.post(url, headers=headers, json=body)
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="Resource scheduler is unavailable")
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Resource scheduler request timed out")

        return self._process_response(resp)

    def _build_proxy_headers(self, request: Request) -> dict[str, str]:
        """Build headers for the proxy request.

        The resource-scheduler only accepts Bearer tokens (no session store).
        When the browser user authenticates via session cookie, the proxy
        resolves the session's access_token and forwards it as a Bearer header.
        """
        headers: dict[str, str] = {}

        # If the request already has a Bearer token, forward it directly
        auth_header = request.headers.get("authorization")
        if auth_header:
            headers["Authorization"] = auth_header
            return headers

        # Cookie-based auth: resolve session → access_token → Bearer header
        session_id = request.cookies.get("session_id")
        if session_id:
            auth_service = getattr(request.state, "auth_service", None)
            if auth_service and hasattr(auth_service, "session_store"):
                session = auth_service.session_store.get_session(session_id)
                if session:
                    tokens = session.get("tokens", {})
                    access_token = tokens.get("access_token")
                    if access_token:
                        headers["Authorization"] = f"Bearer {access_token}"

        return headers

    def _process_response(self, resp: httpx.Response) -> Any:
        """Process the upstream response, raising HTTPException on errors.

        Args:
            resp: httpx Response from resource-scheduler.

        Returns:
            Parsed JSON body on success.

        Raises:
            HTTPException: With upstream status code and detail on non-2xx.
        """
        if resp.is_success:
            return resp.json()

        # Forward the upstream error as-is
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text or f"Upstream error (HTTP {resp.status_code})"

        raise HTTPException(status_code=resp.status_code, detail=detail)

    # =========================================================================
    # Admin endpoints (admin-only)
    # =========================================================================

    @get(
        "/admin/leader-status",
        response_model=dict,
        response_description="Scheduler leader election status",
        status_code=200,
        responses=ControllerBase.error_responses,
        tags=["Scheduler"],
    )
    async def get_leader_status(
        self,
        request: Request,
        user: dict = Depends(get_current_user),
    ) -> Any:
        """Get scheduler leader election status."""
        return await self._proxy_get("/api/admin/leader-status", request)

    @get(
        "/admin/stats",
        response_model=dict,
        response_description="Scheduler statistics",
        status_code=200,
        responses=ControllerBase.error_responses,
        tags=["Scheduler"],
    )
    async def get_stats(
        self,
        request: Request,
        user: dict = Depends(get_current_user),
    ) -> Any:
        """Get scheduler statistics."""
        return await self._proxy_get("/api/admin/stats", request)

    @post(
        "/admin/trigger-reconcile",
        response_model=dict,
        response_description="Reconciliation trigger result",
        status_code=200,
        responses=ControllerBase.error_responses,
        tags=["Scheduler"],
    )
    async def trigger_reconcile(
        self,
        request: Request,
        user: dict = Depends(get_current_user),
        roles: str = Depends(require_roles("admin")),
    ) -> Any:
        """Trigger immediate reconciliation cycle (admin only)."""
        return await self._proxy_post("/api/admin/trigger-reconcile", request)

    @post(
        "/admin/resign-leadership",
        response_model=dict,
        response_description="Leadership resignation result",
        status_code=200,
        responses=ControllerBase.error_responses,
        tags=["Scheduler"],
    )
    async def resign_leadership(
        self,
        request: Request,
        user: dict = Depends(get_current_user),
        roles: str = Depends(require_roles("admin")),
    ) -> Any:
        """Resign scheduler leadership (admin only)."""
        return await self._proxy_post("/api/admin/resign-leadership", request)

    # =========================================================================
    # Scheduling endpoints (all authenticated users)
    # =========================================================================

    @post(
        "/scheduling/preview",
        response_model=dict,
        response_description="Placement preview result (dry-run)",
        status_code=200,
        responses=ControllerBase.error_responses,
        tags=["Scheduler"],
    )
    async def preview_placement(
        self,
        request: Request,
        user: dict = Depends(get_current_user),
    ) -> Any:
        """Run placement preview (dry-run) via the resource-scheduler.

        AD-SCHED-001/002: Proxies the request to the resource-scheduler's
        PlacementEngine.schedule_preview() endpoint. Available to all
        authenticated users (read-only operation).
        """
        body = await request.json()
        return await self._proxy_post("/api/scheduling/preview", request, body=body)
