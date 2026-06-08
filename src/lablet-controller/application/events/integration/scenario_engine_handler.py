"""IntegrationEventHandlers for Scenario Engine job lifecycle CloudEvents.

Phase 3 / AD-CSI-009 (refactored): Replaces the hand-rolled
``EventsController`` with Neuroglia's
:class:`CloudEventIngestor` + :class:`IntegrationEventHandler` pattern (see
the same pattern used by ``knowledge-manager`` and ``control-plane-api``).

Flow per inbound CloudEvent:

1. :class:`CloudEventMiddleware` (registered on the outer FastAPI app) parses
   the structured envelope and pushes the :class:`CloudEvent` onto the
   :class:`CloudEventBus`. The response to the SE is always ``202``.
2. :class:`CloudEventIngestor` (a :class:`HostedService`) subscribes to the
   bus, maps ``cloud_event.type`` to the corresponding ``@cloudevent``-
   decorated class in :mod:`...scenario_engine_events`, instantiates it
   (``e.__dict__ = cloud_event.data``) and publishes via the Mediator.
3. The Mediator resolves the matching ``IntegrationEventHandler`` from this
   module and invokes ``handle_async``.

Validation / failure semantics (behavioural deltas vs the old controller):

- Missing ``metadata.lablet_session_id`` or ``metadata.step_correlation_id``
  on completed / failed / cancelled events → **logged warning, no CPA call**.
  Recovery is via the reconciler picking up SUSPENDED steps (AD-CSI-016).
- CPA 404 on resume / fail → **logged warning, swallowed** (idempotent ack —
  assumed duplicate delivery against an already-resumed step).
- CPA non-404 errors → **logged error, swallowed**. SE will not retry. The
  reconciler is the recovery path (matches knowledge-manager / CPA event
  handler behaviour).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from lcm_core.integration.clients import ControlPlaneApiClient
from lcm_core.integration.clients.control_plane_client import ControlPlaneApiClientError
from multipledispatch import dispatch
from neuroglia.mediation.mediator import IntegrationEventHandler

from application.events.integration.scenario_engine_events import (
    ScenarioEngineJobCancelledIntegrationEventV1,
    ScenarioEngineJobCompletedIntegrationEventV1,
    ScenarioEngineJobFailedIntegrationEventV1,
    ScenarioEngineJobProgressIntegrationEventV1,
    ScenarioEngineJobStartedIntegrationEventV1,
)
from application.services.lifecycle_phase_handler import LifecyclePhaseHandler
from application.settings import Settings

log = logging.getLogger(__name__)

# Default pipeline name when ``metadata.pipeline_name`` is omitted. All
# Phase 3 Tier-B steps (``lab_resolve``, ``lab_start``) live in the
# instantiate pipeline. When Tier-B steps are added to teardown / evidence /
# grading pipelines, SE must round-trip ``metadata.pipeline_name`` and this
# default becomes obsolete.
DEFAULT_PIPELINE_NAME = "instantiate"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _parse_event_time(raw: Any) -> datetime | None:
    """Parse an ISO-8601 / RFC-3339 timestamp from CloudEvent ``data``.

    Returns ``None`` for missing or unparseable values. Always coerces to
    timezone-aware UTC. Copied verbatim from the legacy
    ``events_controller._parse_event_time`` so timestamps forwarded to CPA
    keep the same normalised shape (``Z`` rewritten to ``+00:00``).
    """
    if not raw or not isinstance(raw, str):
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _get_metadata(event: Any) -> dict[str, Any]:
    """Return the ``metadata`` dict from an event, tolerating absence."""
    md = getattr(event, "metadata", None)
    return md if isinstance(md, dict) else {}


def _source_allowed(
    event: Any,
    allowed_sources: list[str] | None,
    event_type: str,
) -> bool:
    """Phase 3 / Q-11 — enforce CloudEvent ``source`` allow-list.

    The Neuroglia :class:`CloudEventIngestor` attaches the incoming envelope's
    ``source`` URI to the deserialised event as ``__cloudevent__source__``
    (see ``cloud_event_ingestor.py``). This helper compares it case-insensitively
    against the configured allow-list.

    A ``None`` or empty allow-list disables the check (caller decided to opt
    out). A non-empty list with no match logs a warning and returns ``False``
    so the calling handler can drop the event silently — SE has already
    received its ``202`` ack at the middleware layer (we never call back).
    """
    if not allowed_sources:
        return True
    source = getattr(event, "__cloudevent__source__", None)
    if not isinstance(source, str):
        log.warning(
            "Dropping %s event %s: missing CloudEvent source (allow-list enforcement)",
            event_type,
            getattr(event, "job_id", "?"),
        )
        return False
    allowed = {s.lower() for s in allowed_sources if isinstance(s, str)}
    if source.lower() not in allowed:
        log.warning(
            "Dropping %s event %s: source %r not in allow-list %s",
            event_type,
            getattr(event, "job_id", "?"),
            source,
            sorted(allowed),
        )
        return False
    return True


def _require_session_correlation(
    event_type: str,
    job_id: str,
    metadata: dict[str, Any],
) -> tuple[str, str] | None:
    """Validate that the metadata carries the AD-CSI-017 routing keys.

    Returns ``(session_id, correlation_id)`` on success, or ``None`` (and
    logs a warning) when either key is missing.
    """
    session_id = metadata.get("lablet_session_id")
    correlation_id = metadata.get("step_correlation_id")
    if not session_id or not correlation_id:
        log.warning(
            "Dropping %s event %s: missing metadata.lablet_session_id " "or metadata.step_correlation_id (recovery will rely on the " "reconciler picking up the SUSPENDED step)",
            event_type,
            job_id,
        )
        return None
    return session_id, correlation_id


async def _signal_handler_resume(session_id: str, cpa_result: dict[str, Any]) -> None:
    """Look up the in-process :class:`LifecyclePhaseHandler` and signal it
    that the suspended step has been resumed in CPA (AD-CSI-016)."""
    handler = LifecyclePhaseHandler.lookup(session_id)
    if handler is None:
        log.info(
            "No in-process handler registered for session %s — " "resume will be picked up by reconciler on next cycle",
            session_id,
        )
        return
    progress = cpa_result.get("pipeline_progress") or {}
    await handler.resume_after_external_completion(progress)


async def _signal_handler_fail(session_id: str, cpa_result: dict[str, Any]) -> None:
    """Look up the in-process :class:`LifecyclePhaseHandler` and signal it
    that the suspended step has been marked failed in CPA."""
    handler = LifecyclePhaseHandler.lookup(session_id)
    if handler is None:
        log.info(
            "No in-process handler registered for session %s — " "fail will be picked up by reconciler on next cycle",
            session_id,
        )
        return
    progress = cpa_result.get("pipeline_progress") or {}
    await handler.fail_after_external_completion(progress)


# ---------------------------------------------------------------------------
# Informational handlers (started / progress)
# ---------------------------------------------------------------------------


class ScenarioEngineJobStartedHandler(
    IntegrationEventHandler[ScenarioEngineJobStartedIntegrationEventV1],
):
    """``scenario_engine.job.started.v1`` — log only."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._allowed_sources = settings.scenario_engine_allowed_sources if settings else None

    @dispatch(ScenarioEngineJobStartedIntegrationEventV1)
    async def handle_async(self, event: ScenarioEngineJobStartedIntegrationEventV1) -> None:
        if not _source_allowed(event, self._allowed_sources, "scenario_engine.job.started.v1"):
            return
        metadata = _get_metadata(event)
        log.info(
            "SE job started: job_id=%s scenario=%s session=%s",
            event.job_id,
            event.scenario_name,
            metadata.get("lablet_session_id"),
        )


class ScenarioEngineJobProgressHandler(
    IntegrationEventHandler[ScenarioEngineJobProgressIntegrationEventV1],
):
    """``scenario_engine.job.progress.v1`` — log only (no CPA write)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._allowed_sources = settings.scenario_engine_allowed_sources if settings else None

    @dispatch(ScenarioEngineJobProgressIntegrationEventV1)
    async def handle_async(self, event: ScenarioEngineJobProgressIntegrationEventV1) -> None:
        if not _source_allowed(event, self._allowed_sources, "scenario_engine.job.progress.v1"):
            return
        metadata = _get_metadata(event)
        log.debug(
            "SE job progress: job_id=%s pct=%s msg=%s session=%s",
            event.job_id,
            event.percentage,
            event.message,
            metadata.get("lablet_session_id"),
        )


# ---------------------------------------------------------------------------
# Terminal handlers (completed / failed / cancelled)
# ---------------------------------------------------------------------------


class ScenarioEngineJobCompletedHandler(
    IntegrationEventHandler[ScenarioEngineJobCompletedIntegrationEventV1],
):
    """``scenario_engine.job.completed.v1`` — resume the suspended pipeline
    step in CPA and signal the in-process lifecycle handler."""

    def __init__(self, control_plane_client: ControlPlaneApiClient, settings: Settings | None = None) -> None:
        self._cpa = control_plane_client
        self._allowed_sources = settings.scenario_engine_allowed_sources if settings else None

    @dispatch(ScenarioEngineJobCompletedIntegrationEventV1)
    async def handle_async(self, event: ScenarioEngineJobCompletedIntegrationEventV1) -> None:
        if not _source_allowed(event, self._allowed_sources, "scenario_engine.job.completed.v1"):
            return
        metadata = _get_metadata(event)
        routing = _require_session_correlation("scenario_engine.job.completed.v1", event.job_id, metadata)
        if routing is None:
            return
        session_id, correlation_id = routing

        pipeline_name = metadata.get("pipeline_name", DEFAULT_PIPELINE_NAME)
        output_data = event.output_data or {}
        completed_at = _parse_event_time(event.completed_at)

        try:
            result = await self._cpa.resume_pipeline_step(
                session_id=session_id,
                pipeline_name=pipeline_name,
                step_correlation_id=correlation_id,
                output_data=output_data,
                completed_at=completed_at.isoformat() if completed_at else None,
            )
        except ControlPlaneApiClientError as e:
            if e.status_code == 404:
                log.warning(
                    "CPA returned 404 resuming session=%s pipeline=%s correlation=%s — " "assuming duplicate delivery against already-resumed step",
                    session_id,
                    pipeline_name,
                    correlation_id,
                )
                return
            log.error(
                "CPA error resuming session=%s pipeline=%s correlation=%s: %s — " "reconciler will retry",
                session_id,
                pipeline_name,
                correlation_id,
                e,
            )
            return

        log.info(
            "Resumed suspended step in CPA: session=%s pipeline=%s step=%s idempotent=%s",
            session_id,
            pipeline_name,
            result.get("step_name"),
            result.get("idempotent", False),
        )
        await _signal_handler_resume(session_id, result)


class ScenarioEngineJobFailedHandler(
    IntegrationEventHandler[ScenarioEngineJobFailedIntegrationEventV1],
):
    """``scenario_engine.job.failed.v1`` — mark the suspended pipeline step
    failed in CPA and signal the in-process lifecycle handler."""

    def __init__(self, control_plane_client: ControlPlaneApiClient, settings: Settings | None = None) -> None:
        self._cpa = control_plane_client
        self._allowed_sources = settings.scenario_engine_allowed_sources if settings else None

    @dispatch(ScenarioEngineJobFailedIntegrationEventV1)
    async def handle_async(self, event: ScenarioEngineJobFailedIntegrationEventV1) -> None:
        if not _source_allowed(event, self._allowed_sources, "scenario_engine.job.failed.v1"):
            return
        metadata = _get_metadata(event)
        routing = _require_session_correlation("scenario_engine.job.failed.v1", event.job_id, metadata)
        if routing is None:
            return
        session_id, correlation_id = routing

        pipeline_name = metadata.get("pipeline_name", DEFAULT_PIPELINE_NAME)
        # Tolerate both SE's actual field name (``error``) and the legacy
        # ``error_message`` shape exercised by historical tests.
        error_msg = event.error_message or event.error or "external job failed"
        details = event.error_details if event.error_details is not None else event.details
        failed_at = _parse_event_time(event.failed_at)

        try:
            result = await self._cpa.fail_pipeline_step(
                session_id=session_id,
                pipeline_name=pipeline_name,
                step_correlation_id=correlation_id,
                error=error_msg,
                details=details,
                failed_at=failed_at.isoformat() if failed_at else None,
            )
        except ControlPlaneApiClientError as e:
            if e.status_code == 404:
                log.warning(
                    "CPA returned 404 failing session=%s pipeline=%s correlation=%s — " "assuming duplicate delivery against already-terminal step",
                    session_id,
                    pipeline_name,
                    correlation_id,
                )
                return
            log.error(
                "CPA error failing session=%s pipeline=%s correlation=%s: %s — " "reconciler will retry",
                session_id,
                pipeline_name,
                correlation_id,
                e,
            )
            return

        log.warning(
            "Failed suspended step in CPA: session=%s pipeline=%s step=%s error=%s",
            session_id,
            pipeline_name,
            result.get("step_name"),
            error_msg,
        )
        await _signal_handler_fail(session_id, result)


class ScenarioEngineJobCancelledHandler(
    IntegrationEventHandler[ScenarioEngineJobCancelledIntegrationEventV1],
):
    """``scenario_engine.job.cancelled.v1`` — treated identically to failed
    with a ``cancelled:`` prefix and ``details.cancelled = True`` marker."""

    def __init__(self, control_plane_client: ControlPlaneApiClient, settings: Settings | None = None) -> None:
        self._cpa = control_plane_client
        self._allowed_sources = settings.scenario_engine_allowed_sources if settings else None

    @dispatch(ScenarioEngineJobCancelledIntegrationEventV1)
    async def handle_async(self, event: ScenarioEngineJobCancelledIntegrationEventV1) -> None:
        if not _source_allowed(event, self._allowed_sources, "scenario_engine.job.cancelled.v1"):
            return
        metadata = _get_metadata(event)
        routing = _require_session_correlation("scenario_engine.job.cancelled.v1", event.job_id, metadata)
        if routing is None:
            return
        session_id, correlation_id = routing

        pipeline_name = metadata.get("pipeline_name", DEFAULT_PIPELINE_NAME)
        reason = event.reason or "job cancelled"
        cancelled_at = _parse_event_time(event.cancelled_at)

        try:
            result = await self._cpa.fail_pipeline_step(
                session_id=session_id,
                pipeline_name=pipeline_name,
                step_correlation_id=correlation_id,
                error=f"cancelled: {reason}",
                details={"cancelled": True, "reason": reason},
                failed_at=cancelled_at.isoformat() if cancelled_at else None,
            )
        except ControlPlaneApiClientError as e:
            if e.status_code == 404:
                log.warning(
                    "CPA returned 404 cancelling session=%s pipeline=%s correlation=%s — " "assuming duplicate delivery against already-terminal step",
                    session_id,
                    pipeline_name,
                    correlation_id,
                )
                return
            log.error(
                "CPA error cancelling session=%s pipeline=%s correlation=%s: %s — " "reconciler will retry",
                session_id,
                pipeline_name,
                correlation_id,
                e,
            )
            return

        log.info(
            "Cancelled suspended step in CPA: session=%s pipeline=%s step=%s reason=%s",
            session_id,
            pipeline_name,
            result.get("step_name"),
            reason,
        )
        await _signal_handler_fail(session_id, result)
