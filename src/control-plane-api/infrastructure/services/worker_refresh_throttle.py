"""Worker refresh throttling service.

Provides in-memory tracking of last refresh timestamps per worker to prevent
excessive refresh requests from overwhelming the backend.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neuroglia.hosting.web import WebApplicationBuilder

log = logging.getLogger(__name__)


class WorkerRefreshThrottle:
    """Throttles worker refresh requests using in-memory timestamp tracking.

    This service prevents excessive refresh requests by tracking the last
    refresh time for each worker and rejecting requests that occur too soon.
    """

    def __init__(self, min_interval_seconds: int = 10):
        """Initialize the throttle service.

        Args:
            min_interval_seconds: Minimum seconds between refresh requests
        """
        self._min_interval = timedelta(seconds=min_interval_seconds)
        self._last_refresh: dict[str, datetime] = {}
        log.info(f"WorkerRefreshThrottle initialized with {min_interval_seconds}s min interval")

    @staticmethod
    def configure(builder: "WebApplicationBuilder") -> None:
        """Configure the throttle service in the application builder.

        Args:
            builder: Application builder instance
        """
        from application.settings import app_settings

        # Create instance with settings
        instance = WorkerRefreshThrottle(min_interval_seconds=app_settings.worker_refresh_min_interval)

        # Register as singleton
        builder.services.add_singleton(WorkerRefreshThrottle, singleton=instance)
        log.info("✅ WorkerRefreshThrottle configured as singleton")

    def can_refresh(self, worker_id: str) -> bool:
        """Check if a worker can be refreshed based on throttle rules.

        Args:
            worker_id: Worker UUID

        Returns:
            True if refresh is allowed, False if throttled
        """
        now = datetime.now(timezone.utc)
        last_refresh = self._last_refresh.get(worker_id)

        if last_refresh is None:
            # Never refreshed before - allow
            return True

        time_since_last = now - last_refresh
        can_refresh = time_since_last >= self._min_interval

        if not can_refresh:
            remaining = self._min_interval - time_since_last
            log.debug(f"Worker {worker_id} refresh throttled - " f"{remaining.total_seconds():.1f}s remaining")

        return can_refresh

    def record_refresh(self, worker_id: str) -> None:
        """Record that a worker was just refreshed.

        Args:
            worker_id: Worker UUID
        """
        now = datetime.now(timezone.utc)
        self._last_refresh[worker_id] = now
        log.debug(f"Recorded refresh for worker {worker_id} at {now.isoformat()}")

    def get_last_refresh(self, worker_id: str) -> datetime | None:
        """Get the timestamp of the last refresh for a worker.

        Args:
            worker_id: Worker UUID

        Returns:
            datetime of last refresh, or None if never refreshed
        """
        return self._last_refresh.get(worker_id)

    def get_time_until_next_refresh(self, worker_id: str) -> float | None:
        """Get seconds until next refresh is allowed.

        Args:
            worker_id: Worker UUID

        Returns:
            Seconds until next refresh allowed, or None if can refresh now
        """
        last_refresh = self._last_refresh.get(worker_id)
        if last_refresh is None:
            return None

        now = datetime.now(timezone.utc)
        time_since_last = now - last_refresh

        if time_since_last >= self._min_interval:
            return None

        remaining = self._min_interval - time_since_last
        return remaining.total_seconds()

    def cleanup_old_entries(self, max_age_hours: int = 24) -> int:
        """Remove entries older than max_age to prevent unbounded memory growth.

        Args:
            max_age_hours: Maximum age in hours before entry is removed

        Returns:
            Number of entries removed
        """
        now = datetime.now(timezone.utc)
        max_age = timedelta(hours=max_age_hours)

        old_entries = [worker_id for worker_id, last_refresh in self._last_refresh.items() if now - last_refresh > max_age]

        for worker_id in old_entries:
            del self._last_refresh[worker_id]

        if old_entries:
            log.info(f"Cleaned up {len(old_entries)} throttle entries older than {max_age_hours}h")

        return len(old_entries)
