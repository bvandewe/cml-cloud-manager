"""Metrics middleware for API request monitoring.

This module provides FastAPI middleware for automatically tracking
API request metrics including latency, status codes, and error rates.
"""

import logging
import time
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from infrastructure.observability import (
    api_errors,
    api_request_duration,
)
from infrastructure.observability.logging import (
    clear_context,
    get_correlation_id,
    set_correlation_id,
)

log = logging.getLogger(__name__)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware for collecting API metrics and managing request context.

    This middleware:
    - Tracks request duration and status codes
    - Manages correlation IDs for request tracing
    - Records API errors for monitoring dashboards
    """

    # Endpoints to exclude from metrics (health checks, metrics endpoint, etc.)
    EXCLUDED_PATHS = {
        "/health",
        "/ready",
        "/metrics",
        "/favicon.ico",
    }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and collect metrics.

        Args:
            request: The incoming request
            call_next: The next middleware/handler in the chain

        Returns:
            The response from the handler
        """
        # Skip metrics for excluded paths
        path = request.url.path
        if path in self.EXCLUDED_PATHS:
            return await call_next(request)

        # Normalize path for metrics (replace IDs with placeholders)
        normalized_path = self._normalize_path(path)

        # Set up correlation ID from header or generate new one
        correlation_id = request.headers.get("X-Correlation-ID") or get_correlation_id()
        set_correlation_id(correlation_id)

        # Track request timing
        start_time = time.perf_counter()
        status_code = 500  # Default to error if something goes wrong

        try:
            response = await call_next(request)
            status_code = response.status_code

            # Add correlation ID to response headers
            response.headers["X-Correlation-ID"] = correlation_id

            return response

        except Exception:
            # Re-raise after recording error metric
            raise

        finally:
            # Calculate duration
            duration = time.perf_counter() - start_time

            # Record metrics
            method = request.method
            api_request_duration.record(
                duration,
                {
                    "method": method,
                    "endpoint": normalized_path,
                    "status": str(status_code),
                },
            )

            # Record errors separately
            if status_code >= 400:
                api_errors.add(
                    1,
                    {
                        "endpoint": normalized_path,
                        "status": str(status_code),
                        "method": method,
                    },
                )

            # Clear context at end of request
            clear_context()

    def _normalize_path(self, path: str) -> str:
        """Normalize a path by replacing IDs with placeholders.

        This prevents high-cardinality metric labels from path parameters.

        Args:
            path: The URL path to normalize

        Returns:
            Normalized path with ID placeholders
        """
        parts = path.split("/")
        normalized_parts = []

        for i, part in enumerate(parts):
            if not part:
                normalized_parts.append(part)
                continue

            # Check if this looks like a UUID
            if self._is_uuid(part):
                normalized_parts.append("{id}")
            # Check if this looks like a numeric ID
            elif part.isdigit():
                normalized_parts.append("{id}")
            # Check for common ID patterns
            elif part.startswith("inst-") or part.startswith("worker-"):
                normalized_parts.append("{id}")
            else:
                normalized_parts.append(part)

        return "/".join(normalized_parts)

    def _is_uuid(self, value: str) -> bool:
        """Check if a string looks like a UUID.

        Args:
            value: The string to check

        Returns:
            True if the string looks like a UUID
        """
        # UUID pattern: 8-4-4-4-12 hex characters
        if len(value) == 36 and value.count("-") == 4:
            parts = value.split("-")
            expected_lengths = [8, 4, 4, 4, 12]
            if all(len(p) == expected for p, expected in zip(parts, expected_lengths)):
                try:
                    int(value.replace("-", ""), 16)
                    return True
                except ValueError:
                    pass
        return False


def configure_metrics_middleware(app):
    """Configure the metrics middleware for a FastAPI application.

    Args:
        app: The FastAPI application instance
    """
    app.add_middleware(MetricsMiddleware)
    log.info("📊 Metrics middleware configured")


__all__ = [
    "MetricsMiddleware",
    "configure_metrics_middleware",
]
