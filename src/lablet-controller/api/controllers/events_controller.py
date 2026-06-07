"""Events Controller — CloudEvent ingestion endpoint for Scenario Engine callbacks.

Receives CloudEvents delivered by the Scenario Engine when job state changes:
- scenario_engine.job.started.v1
- scenario_engine.job.progress.v1
- scenario_engine.job.completed.v1
- scenario_engine.job.failed.v1
- scenario_engine.job.cancelled.v1

The lablet-controller processes these events to update LabletSession pipeline state
and trigger subsequent lifecycle operations.

ADR-044: SE↔LCM Integration.
"""

import logging
from typing import Any

from fastapi import APIRouter, Request, Response

logger = logging.getLogger(__name__)

# CloudEvent types from Scenario Engine
CE_JOB_STARTED = "scenario_engine.job.started.v1"
CE_JOB_PROGRESS = "scenario_engine.job.progress.v1"
CE_JOB_COMPLETED = "scenario_engine.job.completed.v1"
CE_JOB_FAILED = "scenario_engine.job.failed.v1"
CE_JOB_CANCELLED = "scenario_engine.job.cancelled.v1"


class EventsController:
    """Controller for CloudEvent ingestion from Scenario Engine.

    Mounts at /events under the API sub-app.
    Accepts structured CloudEvents (application/cloudevents+json)
    and binary-content-mode CloudEvents.
    """

    def __init__(self) -> None:
        """Initialize events controller."""
        self.router = APIRouter(prefix="/events", tags=["Events"])
        self._register_routes()

    def _register_routes(self) -> None:
        """Register event ingestion routes."""

        @self.router.post("/", summary="Ingest CloudEvent", status_code=202)
        async def ingest_cloud_event(request: Request) -> Response:
            """Receive a CloudEvent from the Scenario Engine.

            Supports both structured (application/cloudevents+json) and
            binary content mode (ce-* headers).

            Returns 202 Accepted immediately — processing is async.
            """
            event = await _parse_cloud_event(request)
            if event is None:
                return Response(status_code=400, content="Invalid CloudEvent")

            event_type = event.get("type", "")
            job_id = event.get("subject", "")
            data = event.get("data", {})

            logger.info(f"Received CloudEvent: type={event_type}, job_id={job_id}")

            # Dispatch by event type
            if event_type == CE_JOB_STARTED:
                await _handle_job_started(job_id, data)
            elif event_type == CE_JOB_PROGRESS:
                await _handle_job_progress(job_id, data)
            elif event_type == CE_JOB_COMPLETED:
                await _handle_job_completed(job_id, data)
            elif event_type == CE_JOB_FAILED:
                await _handle_job_failed(job_id, data)
            elif event_type == CE_JOB_CANCELLED:
                await _handle_job_cancelled(job_id, data)
            else:
                logger.warning(f"Unknown CloudEvent type: {event_type}")

            return Response(status_code=202)


async def _parse_cloud_event(request: Request) -> dict[str, Any] | None:
    """Parse a CloudEvent from the request (structured or binary mode).

    Structured mode: Content-Type is application/cloudevents+json,
    entire body is the CloudEvent envelope.

    Binary mode: ce-* headers carry metadata, body is the event data.

    Returns:
        Parsed CloudEvent dict with type, source, subject, data fields.
        None if parsing fails.
    """
    content_type = request.headers.get("content-type", "")

    try:
        if "cloudevents+json" in content_type:
            # Structured mode — body is the full CloudEvent
            body = await request.json()
            return {
                "type": body.get("type", ""),
                "source": body.get("source", ""),
                "subject": body.get("subject", ""),
                "id": body.get("id", ""),
                "data": body.get("data", {}),
            }
        else:
            # Binary content mode — metadata in ce-* headers
            body = await request.json()
            return {
                "type": request.headers.get("ce-type", ""),
                "source": request.headers.get("ce-source", ""),
                "subject": request.headers.get("ce-subject", ""),
                "id": request.headers.get("ce-id", ""),
                "data": body if body else {},
            }
    except Exception as e:
        logger.error(f"Failed to parse CloudEvent: {e}")
        return None


async def _handle_job_started(job_id: str, data: dict[str, Any]) -> None:
    """Handle job.started event — log and update pipeline state."""
    logger.info(f"Job started: job_id={job_id}, scenario={data.get('scenario_name')}")
    # TODO: Update LabletSession pipeline state via CPA command


async def _handle_job_progress(job_id: str, data: dict[str, Any]) -> None:
    """Handle job.progress event — update progress on the session."""
    pct = data.get("progress_pct", 0)
    msg = data.get("progress_message", "")
    logger.debug(f"Job progress: job_id={job_id}, pct={pct}, msg={msg}")
    # TODO: Update LabletSession pipeline progress via CPA command


async def _handle_job_completed(job_id: str, data: dict[str, Any]) -> None:
    """Handle job.completed event — mark pipeline phase done, trigger next."""
    output = data.get("output_data", {})
    logger.info(f"Job completed: job_id={job_id}, output_keys={list(output.keys()) if output else []}")
    # TODO: Update LabletSession status, trigger next pipeline phase


async def _handle_job_failed(job_id: str, data: dict[str, Any]) -> None:
    """Handle job.failed event — mark pipeline phase as failed."""
    error = data.get("error_message", "unknown error")
    logger.error(f"Job failed: job_id={job_id}, error={error}")
    # TODO: Update LabletSession status to ERROR, trigger recovery/notification


async def _handle_job_cancelled(job_id: str, data: dict[str, Any]) -> None:
    """Handle job.cancelled event — mark pipeline as cancelled."""
    logger.info(f"Job cancelled: job_id={job_id}")
    # TODO: Update LabletSession pipeline status
