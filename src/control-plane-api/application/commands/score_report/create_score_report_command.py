"""Create ScoreReport command.

Phase 7D: Creates an immutable ScoreReport child entity.
ScoreReport is append-only — no lifecycle methods, no status transitions.

ADR-021: ScoreReport is Entity[str], immutable after creation.
"""

import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.score_report import ScoreReport, ScoreSection
from domain.repositories.score_report_repository import ScoreReportRepository
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

log = logging.getLogger(__name__)


@dataclass
class CreateScoreReportCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to create an immutable ScoreReport.

    Attributes:
        lablet_session_id: Parent LabletSession ID.
        grading_session_id: FK to the GradingSession that produced this report.
        score: Total points earned.
        max_score: Total points possible.
        cut_score: Minimum passing score (default 0.0).
        passed: Whether the assessment was passed.
        grade_result: "pass" or "fail".
        sections: Optional list of section-level score details.
    """

    lablet_session_id: str
    grading_session_id: str
    score: float
    max_score: float
    cut_score: float = 0.0
    passed: bool = False
    grade_result: str = ""
    sections: list[dict[str, Any]] | None = None


class CreateScoreReportCommandHandler(
    CommandHandlerBase,
    CommandHandler[CreateScoreReportCommand, OperationResult[dict[str, Any]]],
):
    """Handle ScoreReport creation."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        score_report_repository: ScoreReportRepository,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._repository = score_report_repository

    async def handle_async(self, request: CreateScoreReportCommand) -> OperationResult[dict[str, Any]]:
        """Handle create score report command."""
        if not request.lablet_session_id or not request.lablet_session_id.strip():
            return self.bad_request("lablet_session_id is required")

        if not request.grading_session_id or not request.grading_session_id.strip():
            return self.bad_request("grading_session_id is required")

        # Parse sections if provided
        sections: list[ScoreSection] | None = None
        if request.sections:
            try:
                sections = [
                    ScoreSection(
                        name=s.get("name", ""),
                        score=float(s.get("score", 0.0)),
                        max_score=float(s.get("max_score", 0.0)),
                        cut_score=float(s.get("cut_score", 0.0)),
                        passed=bool(s.get("passed", True)),
                        details=s.get("details", {}),
                    )
                    for s in request.sections
                ]
            except (TypeError, KeyError) as e:
                return self.bad_request(f"Invalid sections format: {e}")

        score_report = ScoreReport.create(
            score_report_id=str(uuid4()),
            lablet_session_id=request.lablet_session_id.strip(),
            grading_session_id=request.grading_session_id.strip(),
            score=request.score,
            max_score=request.max_score,
            cut_score=request.cut_score,
            passed=request.passed,
            grade_result=request.grade_result,
            sections=sections,
        )

        await self._repository.add_async(score_report)

        log.info(
            "Created ScoreReport %s for lablet_session %s (score=%.1f/%.1f, %s)",
            score_report.id,
            request.lablet_session_id,
            request.score,
            request.max_score,
            request.grade_result,
        )

        return self.created(
            {
                "score_report_id": score_report.id,
                "lablet_session_id": score_report.lablet_session_id,
                "grading_session_id": score_report.grading_session_id,
                "score": score_report.score,
                "max_score": score_report.max_score,
                "passed": score_report.passed,
                "grade_result": score_report.grade_result,
                "percentage": score_report.percentage,
            }
        )
