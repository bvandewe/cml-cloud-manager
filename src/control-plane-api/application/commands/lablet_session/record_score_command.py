"""Record Score command.

Phase 7D: New command (replaces inline grading result handling).
Records a score on the LabletSession aggregate via record_score().

Note: This does NOT change session status. The session stays in GRADING.
Call transition to STOPPING after recording the score.

Per ADR-001: All state mutations go through Control Plane API.
"""

import logging
from dataclasses import dataclass
from typing import Any

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.lablet_session import LabletSession
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

log = logging.getLogger(__name__)


@dataclass
class RecordScoreCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to record a grading score on a LabletSession.

    Links the ScoreReport child entity and denormalized grade_result
    to the parent session.

    Attributes:
        session_id: The LabletSession aggregate ID.
        score_report_id: FK to the ScoreReport child entity.
        grade_result: "pass" or "fail" (denormalized for quick access).
    """

    session_id: str
    score_report_id: str
    grade_result: str  # "pass" or "fail"


class RecordScoreCommandHandler(
    CommandHandlerBase,
    CommandHandler[RecordScoreCommand, OperationResult[dict[str, Any]]],
):
    """Handle recording a grading score on a LabletSession."""

    def __init__(self, lablet_session_repository: LabletSessionRepository):
        self._session_repository = lablet_session_repository

    async def handle_async(self, request: RecordScoreCommand) -> OperationResult[dict[str, Any]]:
        """Handle record score command."""
        log.info(
            "Recording score on session %s (score_report_id=%s, grade_result=%s)",
            request.session_id,
            request.score_report_id,
            request.grade_result,
        )

        if request.grade_result not in ("pass", "fail"):
            return self.bad_request(f"grade_result must be 'pass' or 'fail', got '{request.grade_result}'")

        session = await self._session_repository.get_by_id_async(request.session_id)
        if not session:
            return self.not_found(LabletSession, request.session_id)

        try:
            session.record_score(
                score_report_id=request.score_report_id,
                grade_result=request.grade_result,
            )
        except Exception as e:
            log.warning("Cannot record score on session %s: %s", request.session_id, e)
            return self.conflict(f"Cannot record score: {e}")

        await self._session_repository.update_async(session)

        log.info("Score recorded on session %s: %s", request.session_id, request.grade_result)

        return self.ok(
            {
                "session_id": request.session_id,
                "score_report_id": request.score_report_id,
                "grade_result": request.grade_result,
            }
        )
