"""StandardEndpointsMixin for operational endpoints.

Provides standard /health, /ready, /metrics, /info endpoints that
should be present on all services for consistent operations.
"""

import os
import platform
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest


@dataclass
class ServiceInfo:
    """Service information for the /info endpoint."""

    # Core identification
    name: str
    version: str
    description: str = ""
    image_tag: str = field(default_factory=lambda: os.environ.get("IMAGE_TAG", "latest"))

    # Build/deployment info
    build_commit: str = field(default_factory=lambda: os.environ.get("BUILD_COMMIT", "unknown"))
    build_time: str = field(default_factory=lambda: os.environ.get("BUILD_TIME", "unknown"))
    environment: str = field(default_factory=lambda: os.environ.get("ENVIRONMENT", "development"))

    # Runtime info (populated dynamically)
    hostname: str = field(default_factory=lambda: platform.node())
    python_version: str = field(default_factory=lambda: platform.python_version())
    start_time: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON response."""
        uptime_seconds = time.time() - self.start_time
        return {
            "name": self.name,
            "version": self.version,
            "image_tag": self.image_tag,
            "description": self.description,
            "build": {
                "commit": self.build_commit,
                "time": self.build_time,
            },
            "runtime": {
                "environment": self.environment,
                "hostname": self.hostname,
                "python_version": self.python_version,
                "uptime_seconds": round(uptime_seconds, 2),
                "start_time": datetime.fromtimestamp(self.start_time).isoformat(),
            },
        }


class StandardEndpointsMixin:
    """
    Mixin that adds standard operational endpoints to a FastAPI app.

    Endpoints:
    - GET /health - Liveness probe (200 OK if service is running)
    - GET /ready - Readiness probe (200 OK if service can accept traffic)
    - GET /metrics - Prometheus metrics
    - GET /info - Service information (version, uptime, leader status, etc.)

    Usage:
        from lcm_core.infrastructure.mixins import StandardEndpointsMixin, ServiceInfo

        class MyService(StandardEndpointsMixin):
            def __init__(self):
                self._info = ServiceInfo(
                    name="my-service",
                    version="1.0.0",
                    description="My awesome service"
                )

            # Optional: override readiness check
            async def check_readiness(self) -> tuple[bool, str]:
                if not self._db_connected:
                    return False, "Database not connected"
                return True, "OK"

            # Optional: add extra info
            def get_extra_info(self) -> dict:
                return {"leader": self._is_leader}

        service = MyService()
        app = FastAPI()
        service.configure_standard_endpoints(app)
    """

    # Subclasses should set this
    _service_info: ServiceInfo | None = None

    # Readiness checks (list of async callables returning (ready, message))
    _readiness_checks: list[Callable[[], Any]]

    def __init__(self) -> None:
        """Initialize the mixin."""
        self._readiness_checks = []

    def configure_standard_endpoints(
        self,
        app: FastAPI,
        service_info: ServiceInfo | None = None,
        prefix: str = "",
        tags: Sequence[str | Enum] | None = None,
    ) -> None:
        """Configure standard operational endpoints on the FastAPI app.

        Args:
            app: FastAPI application to add endpoints to.
            service_info: Service information (uses self._service_info if not provided).
            prefix: Optional prefix for all endpoints (e.g., "/internal").
            tags: OpenAPI tags for these endpoints.
        """
        if service_info:
            self._service_info = service_info

        if self._service_info is None:
            raise ValueError("ServiceInfo must be provided either in constructor or configure_standard_endpoints()")

        endpoint_tags: list[str | Enum] = list(tags) if tags else ["Operations"]

        # Store service_info locally for closures
        service_info_local = self._service_info

        # Health check (liveness)
        @app.get(f"{prefix}/health", tags=endpoint_tags, summary="Liveness probe")
        async def health() -> dict[str, Any]:
            """Basic health check. Returns 200 if service is running."""
            return {
                "status": "healthy",
                "timestamp": datetime.now(UTC).isoformat(),
            }

        # Readiness check
        @app.get(f"{prefix}/ready", tags=endpoint_tags, summary="Readiness probe")
        async def ready() -> dict[str, Any]:
            """
            Readiness check. Returns 200 if service can accept traffic.

            Runs all registered readiness checks and returns 503 if any fail.
            """
            # Check custom readiness
            is_ready, message = await self._check_all_readiness()

            if not is_ready:
                raise HTTPException(status_code=503, detail=message)

            return {
                "status": "ready",
                "message": message,
                "timestamp": datetime.now(UTC).isoformat(),
            }

        # Prometheus metrics
        @app.get(f"{prefix}/metrics", tags=endpoint_tags, summary="Prometheus metrics")
        async def metrics() -> Response:
            """Prometheus metrics in text format."""
            return Response(
                content=generate_latest(REGISTRY),
                media_type=CONTENT_TYPE_LATEST,
            )

        # Service info
        @app.get(f"{prefix}/info", tags=endpoint_tags, summary="Service information")
        async def info() -> dict[str, Any]:
            """
            Service information including version, uptime, and custom data.

            Returns build info, runtime stats, and any service-specific info.
            """
            result = service_info_local.to_dict()

            # Add extra info from subclass
            extra = await self._get_extra_info()
            if extra:
                result["extra"] = extra

            return result

    async def _check_all_readiness(self) -> tuple[bool, str]:
        """Run all readiness checks.

        Returns:
            Tuple of (is_ready, message).
        """
        import asyncio

        # First check subclass override
        check_readiness_method = getattr(self, "check_readiness", None)
        if check_readiness_method is not None and callable(check_readiness_method):
            check_func = cast(Callable[[], tuple[bool, str]], check_readiness_method)
            if asyncio.iscoroutinefunction(check_func):
                is_ready, message = await check_func()
            else:
                is_ready, message = check_func()
            if not is_ready:
                return False, message

        # Then check registered checks
        for check in self._readiness_checks:
            try:
                if asyncio.iscoroutinefunction(check):
                    is_ready, message = await check()
                else:
                    is_ready, message = check()

                if not is_ready:
                    return False, message
            except Exception as e:
                return False, f"Readiness check failed: {str(e)}"

        return True, "All checks passed"

    async def _get_extra_info(self) -> dict[str, Any] | None:
        """Get extra info from subclass for /info endpoint.

        Override get_extra_info() in subclass to add custom data.
        """
        import asyncio
        from collections.abc import Awaitable

        get_extra_info_method = getattr(self, "get_extra_info", None)
        if get_extra_info_method is not None and callable(get_extra_info_method):
            if asyncio.iscoroutinefunction(get_extra_info_method):
                async_func = cast(Callable[[], Awaitable[dict[str, Any]]], get_extra_info_method)
                result: dict[str, Any] = await async_func()
                return result
            sync_func = cast(Callable[[], dict[str, Any]], get_extra_info_method)
            return sync_func()
        return None

    def add_readiness_check(self, check: Callable[[], tuple[bool, str]]) -> None:
        """Add a readiness check function.

        Args:
            check: Callable that returns (is_ready: bool, message: str).
                   Can be sync or async.
        """
        self._readiness_checks.append(check)


def add_standard_endpoints(
    app: FastAPI,
    service_info: ServiceInfo,
    readiness_check: Callable[[], tuple[bool, str]] | None = None,
    extra_info: Callable[[], dict[str, Any]] | None = None,
    prefix: str = "",
    tags: Sequence[str | Enum] | None = None,
) -> None:
    """
    Functional alternative to StandardEndpointsMixin for simpler use cases.

    Args:
        app: FastAPI application.
        service_info: Service information.
        readiness_check: Optional async callable returning (ready, message).
        extra_info: Optional async callable returning extra info dict.
        prefix: Optional endpoint prefix.
        tags: OpenAPI tags.

    Example:
        from lcm_core.infrastructure.mixins import add_standard_endpoints, ServiceInfo

        app = FastAPI()
        add_standard_endpoints(
            app,
            ServiceInfo(name="my-service", version="1.0.0"),
            readiness_check=lambda: (db.is_connected, "Database check"),
        )
    """
    import asyncio

    endpoint_tags: list[str | Enum] = list(tags) if tags else ["Operations"]

    @app.get(f"{prefix}/health", tags=endpoint_tags, summary="Liveness probe")
    async def health() -> dict[str, Any]:
        return {"status": "healthy", "timestamp": datetime.now(UTC).isoformat()}

    @app.get(f"{prefix}/ready", tags=endpoint_tags, summary="Readiness probe")
    async def ready() -> dict[str, Any]:
        if readiness_check:
            if asyncio.iscoroutinefunction(readiness_check):
                is_ready, message = await readiness_check()
            else:
                is_ready, message = readiness_check()

            if not is_ready:
                raise HTTPException(status_code=503, detail=message)

        return {"status": "ready", "timestamp": datetime.now(UTC).isoformat()}

    @app.get(f"{prefix}/metrics", tags=endpoint_tags, summary="Prometheus metrics")
    async def metrics() -> Response:
        return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    @app.get(f"{prefix}/info", tags=endpoint_tags, summary="Service information")
    async def info() -> dict[str, Any]:
        result = service_info.to_dict()
        if extra_info:
            if asyncio.iscoroutinefunction(extra_info):
                result["extra"] = await extra_info()
            else:
                result["extra"] = extra_info()
        return result
