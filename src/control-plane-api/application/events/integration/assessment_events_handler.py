"""Assessment integration event handlers.

Phase 7D: Migrated from LabletInstance to LabletSession model.

Handles CloudEvents from Assessment Platform to update LabletSession lifecycle:
- collection.completed → Create GradingSession, transition to GRADING
- grading.completed → Create ScoreReport, record score, transition to STOPPING
- collection.failed → Handle failure
- grading.failed → Handle failure

ADR-020: Session Entity Model — uses LabletSession aggregate.
ADR-021: Child Entity Architecture — creates GradingSession/ScoreReport child entities.
"""

import logging
from uuid import uuid4

from application.events.integration.assessment_events import (
    AssessmentCollectionCompletedIntegrationEventV1,
    AssessmentCollectionFailedIntegrationEventV1,
    AssessmentGradingCompletedIntegrationEventV1,
    AssessmentGradingFailedIntegrationEventV1,
)
from application.services.event_deduplication_service import EventDeduplicationService
from domain.entities.grading_session import GradingSession
from domain.entities.lablet_session import InvalidStateTransitionError, LabletSession
from domain.entities.score_report import ScoreReport, ScoreSection
from domain.enums import LabletSessionStatus
from domain.repositories.grading_session_repository import GradingSessionRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from domain.repositories.score_report_repository import ScoreReportRepository
from multipledispatch import dispatch
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping.mapper import Mapper
from neuroglia.mediation.mediator import IntegrationEventHandler, Mediator

log = logging.getLogger(__name__)


class BaseAssessmentEventHandler:
    """Base class for assessment event handlers with common dependencies."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        lablet_session_repository: LabletSessionRepository,
        grading_session_repository: GradingSessionRepository,
        score_report_repository: ScoreReportRepository,
        deduplication_service: EventDeduplicationService,
    ) -> None:
        self.mediator = mediator
        self.mapper = mapper
        self.cloud_event_bus = cloud_event_bus
        self.cloud_event_publishing_options = cloud_event_publishing_options
        self._session_repository = lablet_session_repository
        self._grading_repository = grading_session_repository
        self._score_repository = score_report_repository
        self._deduplication = deduplication_service

    async def _get_session(self, session_id: str) -> LabletSession | None:
        """Fetch LabletSession by ID."""
        return await self._session_repository.get_by_id_async(session_id)

    async def _save_session(self, session: LabletSession) -> None:
        """Save updated LabletSession."""
        await self._session_repository.update_async(session)


class AssessmentCollectionCompletedHandler(
    BaseAssessmentEventHandler,
    IntegrationEventHandler[AssessmentCollectionCompletedIntegrationEventV1],
):
    """Handles assessment.collection.completed events.

    When collection is complete:
    1. Creates a GradingSession child entity
    2. Transitions the LabletSession to GRADING state
    """

    @dispatch(AssessmentCollectionCompletedIntegrationEventV1)
    async def handle_async(self, event: AssessmentCollectionCompletedIntegrationEventV1) -> None:
        """Handle collection completed event."""
        event_id = f"collection.completed.{event.collection_id}"
        log.info("📥 Received assessment.collection.completed for session %s", event.aggregate_id)

        if await self._deduplication.is_processed(event_id):
            log.info("⏭️ Event %s already processed, skipping", event_id)
            return

        try:
            session = await self._get_session(event.aggregate_id)
            if session is None:
                log.error("❌ LabletSession %s not found", event.aggregate_id)
                return

            if session.state.status != LabletSessionStatus.COLLECTING:
                log.warning(
                    "⚠️ Session %s not in COLLECTING state (current: %s), skipping transition",
                    event.aggregate_id,
                    session.state.status.value,
                )
                return

            # Create GradingSession child entity (ADR-021)
            grading_session = GradingSession.create(
                grading_session_id=str(uuid4()),
                lablet_session_id=session.id(),
                external_grading_session_id=event.collection_id,
                grading_rules_uri=getattr(event, "artifacts_uri", None),
            )
            await self._grading_repository.add_async(grading_session)

            # Transition to GRADING with grading_session_id FK
            session.start_grading(grading_session_id=grading_session.id)
            await self._save_session(session)

            await self._deduplication.mark_processed(event_id)
            log.info("✅ Session %s transitioned to GRADING (grading_session=%s)", event.aggregate_id, grading_session.id)

        except InvalidStateTransitionError as e:
            log.error("❌ Invalid state transition for session %s: %s", event.aggregate_id, e)
        except Exception as e:
            log.error("❌ Failed to handle collection completed for %s: %s", event.aggregate_id, e)
            raise


class AssessmentGradingCompletedHandler(
    BaseAssessmentEventHandler,
    IntegrationEventHandler[AssessmentGradingCompletedIntegrationEventV1],
):
    """Handles assessment.grading.completed events.

    When grading is complete:
    1. Creates a ScoreReport child entity from the score data
    2. Records the score on the LabletSession
    3. Transitions the LabletSession to STOPPING state
    """

    @dispatch(AssessmentGradingCompletedIntegrationEventV1)
    async def handle_async(self, event: AssessmentGradingCompletedIntegrationEventV1) -> None:
        """Handle grading completed event."""
        event_id = f"grading.completed.{event.grading_id}"
        log.info("📥 Received assessment.grading.completed for session %s", event.aggregate_id)

        if await self._deduplication.is_processed(event_id):
            log.info("⏭️ Event %s already processed, skipping", event_id)
            return

        try:
            session = await self._get_session(event.aggregate_id)
            if session is None:
                log.error("❌ LabletSession %s not found", event.aggregate_id)
                return

            if session.state.status != LabletSessionStatus.GRADING:
                log.warning(
                    "⚠️ Session %s not in GRADING state (current: %s), skipping",
                    event.aggregate_id,
                    session.state.status.value,
                )
                return

            # Extract score data from event
            score_data = event.score or {}
            grade_result = "pass" if event.passed else "fail"

            # Parse sections if available
            sections = None
            raw_sections = score_data.get("check_results", [])
            if raw_sections:
                sections = [
                    ScoreSection(
                        name=s.get("check_name", s.get("check_id", "")),
                        score=float(s.get("points_earned", 0.0)),
                        max_score=float(s.get("points_possible", 0.0)),
                        passed=bool(s.get("passed", True)),
                        details=s.get("details", {}),
                    )
                    for s in raw_sections
                ]

            # Create ScoreReport child entity (ADR-021)
            grading_session_id = session.state.grading_session_id or ""
            score_report = ScoreReport.create(
                score_report_id=str(uuid4()),
                lablet_session_id=session.id(),
                grading_session_id=grading_session_id,
                score=float(score_data.get("total_points_earned", 0.0)),
                max_score=float(score_data.get("total_points_possible", 0.0)),
                passed=event.passed,
                grade_result=grade_result,
                sections=sections,
            )
            await self._score_repository.add_async(score_report)

            # Record score on LabletSession (does not change status)
            session.record_score(
                score_report_id=score_report.id,
                grade_result=grade_result,
            )

            # Transition to STOPPING
            stop_reason = f"Grading completed: {grade_result.upper()}"
            session.start_stopping(reason=stop_reason)
            await self._save_session(session)

            await self._deduplication.mark_processed(event_id)
            log.info(
                "✅ Session %s graded (%.1f/%.1f, %s) and transitioned to STOPPING",
                event.aggregate_id,
                score_report.score,
                score_report.max_score,
                grade_result,
            )

        except InvalidStateTransitionError as e:
            log.error("❌ Invalid state transition for session %s: %s", event.aggregate_id, e)
        except Exception as e:
            log.error("❌ Failed to handle grading completed for %s: %s", event.aggregate_id, e)
            raise


class AssessmentCollectionFailedHandler(
    BaseAssessmentEventHandler,
    IntegrationEventHandler[AssessmentCollectionFailedIntegrationEventV1],
):
    """Handles assessment.collection.failed events.

    When collection fails, logs the error and optionally stops the session.
    """

    @dispatch(AssessmentCollectionFailedIntegrationEventV1)
    async def handle_async(self, event: AssessmentCollectionFailedIntegrationEventV1) -> None:
        """Handle collection failed event."""
        event_id = f"collection.failed.{event.collection_id}"
        log.warning("⚠️ Collection failed for session %s: %s - %s", event.aggregate_id, event.error_code, event.error_message)

        if await self._deduplication.is_processed(event_id):
            log.info("⏭️ Event %s already processed, skipping", event_id)
            return

        try:
            session = await self._get_session(event.aggregate_id)
            if session is None:
                log.error("❌ LabletSession %s not found", event.aggregate_id)
                return

            if not event.retry_possible:
                if session.state.status in [
                    LabletSessionStatus.COLLECTING,
                    LabletSessionStatus.RUNNING,
                ]:
                    session.start_stopping(reason=f"Collection failed: {event.error_code} - {event.error_message}")
                    await self._save_session(session)
                    log.info("🛑 Session %s stopped due to collection failure", event.aggregate_id)

            await self._deduplication.mark_processed(event_id)

        except Exception as e:
            log.error("❌ Failed to handle collection failure for %s: %s", event.aggregate_id, e)


class AssessmentGradingFailedHandler(
    BaseAssessmentEventHandler,
    IntegrationEventHandler[AssessmentGradingFailedIntegrationEventV1],
):
    """Handles assessment.grading.failed events.

    When grading fails, logs the error and stops the session.
    """

    @dispatch(AssessmentGradingFailedIntegrationEventV1)
    async def handle_async(self, event: AssessmentGradingFailedIntegrationEventV1) -> None:
        """Handle grading failed event."""
        event_id = f"grading.failed.{event.grading_id}"
        log.error("❌ Grading failed for session %s: %s - %s", event.aggregate_id, event.error_code, event.error_message)

        if await self._deduplication.is_processed(event_id):
            log.info("⏭️ Event %s already processed, skipping", event_id)
            return

        try:
            session = await self._get_session(event.aggregate_id)
            if session is None:
                log.error("❌ LabletSession %s not found", event.aggregate_id)
                return

            if session.state.status == LabletSessionStatus.GRADING:
                session.start_stopping(reason=f"Grading failed: {event.error_code} - {event.error_message}")
                await self._save_session(session)
                log.info("🛑 Session %s stopped due to grading failure", event.aggregate_id)

            await self._deduplication.mark_processed(event_id)

        except Exception as e:
            log.error("❌ Failed to handle grading failure for %s: %s", event.aggregate_id, e)
