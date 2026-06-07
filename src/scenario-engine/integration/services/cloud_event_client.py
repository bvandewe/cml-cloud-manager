"""CloudEventCallbackService — delivers CloudEvents to sink URLs.

Uses httpx.AsyncClient to POST CloudEvents in JSON format.
Supports global sink + per-job callback_url override.
Fire-and-forget — delivery failures are logged but never raised.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx
from application.settings import Settings

logger = logging.getLogger(__name__)


class CloudEventCallbackService:
    """Delivers CloudEvents to configured sink URLs.

    Resolution logic:
    - If job specifies callback_url, deliver there
    - Otherwise use settings.cloud_event_sink
    - If neither is set, log and skip

    Retry: 3 attempts with exponential backoff (1s, 2s, 4s).
    Progress throttling: max one progress event per job_progress_interval per job.
    """

    # CloudEvent types
    EVENT_STARTED = "scenario_engine.job.started.v1"
    EVENT_PROGRESS = "scenario_engine.job.progress.v1"
    EVENT_COMPLETED = "scenario_engine.job.completed.v1"
    EVENT_FAILED = "scenario_engine.job.failed.v1"
    EVENT_CANCELLED = "scenario_engine.job.cancelled.v1"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(timeout=10.0)
        # Track last progress emission per job for throttling
        self._last_progress_time: dict[str, float] = {}

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    def _resolve_target_url(self, callback_url: str | None) -> str | None:
        """Resolve the target URL for CloudEvent delivery."""
        if callback_url:
            return callback_url
        if self._settings.cloud_event_sink:
            return self._settings.cloud_event_sink
        return None

    async def emit_started(self, job_id: str, scenario_name: str, started_at: str, callback_url: str | None = None) -> None:
        """Emit a job.started CloudEvent."""
        await self._emit(
            event_type=self.EVENT_STARTED,
            job_id=job_id,
            data={"job_id": job_id, "scenario_name": scenario_name, "started_at": started_at},
            callback_url=callback_url,
        )

    async def emit_progress(
        self,
        job_id: str,
        percentage: int,
        message: str,
        details: dict[str, Any] | None = None,
        callback_url: str | None = None,
    ) -> None:
        """Emit a job.progress CloudEvent (throttled).

        At most one progress event per job_progress_interval seconds per job.
        """
        now = time.monotonic()
        last = self._last_progress_time.get(job_id, 0.0)
        if now - last < self._settings.job_progress_interval:
            return  # Throttled

        self._last_progress_time[job_id] = now
        await self._emit(
            event_type=self.EVENT_PROGRESS,
            job_id=job_id,
            data={"job_id": job_id, "percentage": percentage, "message": message, "details": details},
            callback_url=callback_url,
        )

    async def emit_completed(
        self,
        job_id: str,
        output_data: dict[str, Any],
        artifacts: list[str],
        duration: float,
        callback_url: str | None = None,
    ) -> None:
        """Emit a job.completed CloudEvent."""
        self._cleanup_progress_tracking(job_id)
        await self._emit(
            event_type=self.EVENT_COMPLETED,
            job_id=job_id,
            data={"job_id": job_id, "output_data": output_data, "artifacts": artifacts, "duration": duration},
            callback_url=callback_url,
        )

    async def emit_failed(self, job_id: str, error: str, duration: float, callback_url: str | None = None) -> None:
        """Emit a job.failed CloudEvent."""
        self._cleanup_progress_tracking(job_id)
        await self._emit(
            event_type=self.EVENT_FAILED,
            job_id=job_id,
            data={"job_id": job_id, "error": error, "duration": duration},
            callback_url=callback_url,
        )

    async def emit_cancelled(self, job_id: str, cancelled_at: str, callback_url: str | None = None) -> None:
        """Emit a job.cancelled CloudEvent."""
        self._cleanup_progress_tracking(job_id)
        await self._emit(
            event_type=self.EVENT_CANCELLED,
            job_id=job_id,
            data={"job_id": job_id, "cancelled_at": cancelled_at},
            callback_url=callback_url,
        )

    def _cleanup_progress_tracking(self, job_id: str) -> None:
        """Remove progress throttle tracking for a completed/failed/cancelled job."""
        self._last_progress_time.pop(job_id, None)

    async def _emit(self, event_type: str, job_id: str, data: dict[str, Any], callback_url: str | None = None) -> None:
        """Emit a CloudEvent with retry logic. Fire-and-forget."""
        target_url = self._resolve_target_url(callback_url)
        if not target_url:
            logger.debug("No CloudEvent sink configured — skipping event %s for job %s", event_type, job_id)
            return

        headers = {
            "Content-Type": "application/cloudevents+json; charset=utf-8",
            "ce-specversion": "1.0",
            "ce-type": event_type,
            "ce-source": "scenario-engine",
            "ce-id": f"{job_id}-{event_type}-{int(time.time() * 1000)}",
            "ce-subject": job_id,
        }

        payload = {
            "specversion": "1.0",
            "type": event_type,
            "source": "scenario-engine",
            "id": headers["ce-id"],
            "subject": job_id,
            "data": data,
        }

        backoff_delays = [1.0, 2.0, 4.0]
        for attempt, delay in enumerate(backoff_delays, start=1):
            try:
                response = await self._client.post(target_url, json=payload, headers=headers)
                if response.status_code < 400:
                    logger.debug("CloudEvent %s delivered for job %s (attempt %d)", event_type, job_id, attempt)
                    return
                logger.warning(
                    "CloudEvent delivery returned %d for job %s (attempt %d/%d)",
                    response.status_code,
                    job_id,
                    attempt,
                    len(backoff_delays),
                )
            except httpx.HTTPError as exc:
                logger.warning(
                    "CloudEvent delivery failed for job %s (attempt %d/%d): %s",
                    job_id,
                    attempt,
                    len(backoff_delays),
                    str(exc),
                )

            # Wait before retry (except on last attempt)
            if attempt < len(backoff_delays):
                await asyncio.sleep(delay)

        logger.error("CloudEvent %s delivery exhausted retries for job %s", event_type, job_id)
