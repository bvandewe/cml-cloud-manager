"""LDS integration event handlers.

Handles CloudEvents from LDS (pylds) to update LabletSession lifecycle:
- session.running → Transition READY → RUNNING (user logged in)
- session.paused → Informational logging (future: idle detection)
- session.ended → Informational logging (future: auto-collection trigger)

Follows the established pattern from assessment_events_handler.py:
- DI via constructor (repository, deduplication service)
- @dispatch decorator for Neuroglia integration event routing
- Idempotent processing via EventDeduplicationService
- Defensive state validation before transitions

AD-SSE-RACE-001: State transitions emit domain events → SSE handlers → frontend.
"""

import logging

from multipledispatch import dispatch
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping.mapper import Mapper
from neuroglia.mediation.mediator import IntegrationEventHandler, Mediator

from application.events.integration.lds_events import (
    LdsSessionEndedIntegrationEventV1,
    LdsSessionPausedIntegrationEventV1,
    LdsSessionRunningIntegrationEventV1,
)
from application.services.event_deduplication_service import EventDeduplicationService
from application.settings import Settings
from domain.entities.lablet_session import InvalidStateTransitionError, LabletSession
from domain.enums import LabletSessionStatus
from domain.repositories.lablet_session_repository import LabletSessionRepository

log = logging.getLogger(__name__)


class BaseLdsEventHandler:
    """Base class for LDS event handlers with common dependencies."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        lablet_session_repository: LabletSessionRepository,
        deduplication_service: EventDeduplicationService,
        settings: Settings,
    ) -> None:
        self.mediator = mediator
        self.mapper = mapper
        self.cloud_event_bus = cloud_event_bus
        self.cloud_event_publishing_options = cloud_event_publishing_options
        self._session_repository = lablet_session_repository
        self._deduplication = deduplication_service
        self._settings = settings

    async def _get_session(self, session_id: str) -> LabletSession | None:
        """Fetch LabletSession by ID."""
        return await self._session_repository.get_by_id_async(session_id)

    async def _save_session(self, session: LabletSession) -> None:
        """Save updated LabletSession."""
        await self._session_repository.update_async(session)

    def _is_enabled(self) -> bool:
        """Check if LDS CloudEvent processing is enabled."""
        return self._settings.lds_cloudevent_enabled

    def _resolve_session_id(self, event: LdsSessionRunningIntegrationEventV1 | LdsSessionPausedIntegrationEventV1 | LdsSessionEndedIntegrationEventV1) -> str:
        """Resolve the LabletSession ID from the LDS event.

        LDS events may carry the ID in either aggregate_id or session_id.
        """
        return event.aggregate_id or event.session_id


# ---------------------------------------------------------------------------
# 1. Session Running — READY → RUNNING
# ---------------------------------------------------------------------------


class LdsSessionRunningHandler(
    BaseLdsEventHandler,
    IntegrationEventHandler[LdsSessionRunningIntegrationEventV1],
):
    """Handles io.lablet.lds.session.running.v1 events.

    When the candidate logs in to the LDS session:
    1. Validates the session exists and is in READY state
    2. Calls session.mark_running() to transition READY → RUNNING
    3. Saves the session (triggers domain event → SSE → frontend)
    """

    @dispatch(LdsSessionRunningIntegrationEventV1)
    async def handle_async(self, event: LdsSessionRunningIntegrationEventV1) -> None:
        """Handle LDS session running event."""
        session_id = self._resolve_session_id(event)
        event_id = f"lds.session.running.{session_id}"
        log.info("📥 Received io.lablet.lds.session.running.v1 for session %s", session_id)

        if not self._is_enabled():
            log.info("⏭️ LDS CloudEvent processing is disabled, skipping")
            return

        if await self._deduplication.is_processed(event_id):
            log.info("⏭️ Event %s already processed, skipping", event_id)
            return

        if not session_id:
            log.error("❌ LDS session.running event missing session ID")
            return

        try:
            session = await self._get_session(session_id)
            if session is None:
                log.error("❌ LabletSession %s not found for LDS running event", session_id)
                return

            if session.state.status != LabletSessionStatus.READY:
                log.warning(
                    "⚠️ Session %s not in READY state (current: %s), skipping RUNNING transition",
                    session_id,
                    session.state.status.value,
                )
                # Still mark as processed to avoid repeated warnings
                await self._deduplication.mark_processed(event_id)
                return

            # Transition READY → RUNNING
            session.mark_running()
            await self._save_session(session)

            await self._deduplication.mark_processed(event_id)
            log.info("✅ Session %s transitioned to RUNNING (user logged in via LDS)", session_id)

        except InvalidStateTransitionError as e:
            log.error("❌ Invalid state transition for session %s: %s", session_id, e)
        except Exception as e:
            log.error("❌ Failed to handle LDS session.running for %s: %s", session_id, e)
            raise


# ---------------------------------------------------------------------------
# 2. Session Paused — Informational
# ---------------------------------------------------------------------------


class LdsSessionPausedHandler(
    BaseLdsEventHandler,
    IntegrationEventHandler[LdsSessionPausedIntegrationEventV1],
):
    """Handles io.lablet.lds.session.paused.v1 events.

    Currently informational only — logs the pause event.
    Future: Could trigger idle detection or timeslot extension prompts.
    """

    @dispatch(LdsSessionPausedIntegrationEventV1)
    async def handle_async(self, event: LdsSessionPausedIntegrationEventV1) -> None:
        """Handle LDS session paused event."""
        session_id = self._resolve_session_id(event)
        log.info(
            "📥 Received io.lablet.lds.session.paused.v1 for session %s (reason: %s)",
            session_id,
            event.reason or "unknown",
        )

        if not self._is_enabled():
            return

        # Informational only — no state transition.
        # Future: update session metadata, trigger idle warnings, etc.


# ---------------------------------------------------------------------------
# 3. Session Ended — Informational
# ---------------------------------------------------------------------------


class LdsSessionEndedHandler(
    BaseLdsEventHandler,
    IntegrationEventHandler[LdsSessionEndedIntegrationEventV1],
):
    """Handles io.lablet.lds.session.ended.v1 events.

    Currently informational only — logs the end event.
    Future: Could trigger automatic evidence collection (RUNNING → COLLECTING).
    """

    @dispatch(LdsSessionEndedIntegrationEventV1)
    async def handle_async(self, event: LdsSessionEndedIntegrationEventV1) -> None:
        """Handle LDS session ended event."""
        session_id = self._resolve_session_id(event)
        log.info(
            "📥 Received io.lablet.lds.session.ended.v1 for session %s (ended_by: %s, reason: %s)",
            session_id,
            event.ended_by or "unknown",
            event.reason or "unknown",
        )

        if not self._is_enabled():
            return

        # Informational only — no state transition.
        # Future: trigger RUNNING → COLLECTING if session is in RUNNING state.
