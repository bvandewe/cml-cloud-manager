"""Get ScoreReport query with handler.

Phase 7D: Retrieves a ScoreReport by ID or by parent lablet_session_id.
"""

import logging
from dataclasses import dataclass
from typing import Any

from domain.entities.score_report import ScoreReport
from domain.repositories.score_report_repository import ScoreReportRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

logger = logging.getLogger(__name__)


@dataclass
class GetScoreReportQuery(Query[OperationResult[dict[str, Any]]]):
    """Query to retrieve a ScoreReport by ID or lablet_session_id."""

    id: str | None = None
    lablet_session_id: str | None = None


class GetScoreReportQueryHandler(QueryHandler[GetScoreReportQuery, OperationResult[dict[str, Any]]]):
    """Handle ScoreReport retrieval."""

    def __init__(self, score_report_repository: ScoreReportRepository):
        super().__init__()
        self._repository = score_report_repository

    async def handle_async(self, request: GetScoreReportQuery) -> OperationResult[dict[str, Any]]:
        if not request.id and not request.lablet_session_id:
            return self.bad_request("Must provide either 'id' or 'lablet_session_id'")

        try:
            score_report: ScoreReport | None = None

            if request.id:
                score_report = await self._repository.get_by_id_async(request.id)
                if not score_report:
                    return self.not_found(ScoreReport, request.id)
            else:
                score_report = await self._repository.get_by_lablet_session_id_async(request.lablet_session_id)
                if not score_report:
                    return self.not_found(ScoreReport, request.lablet_session_id, "lablet_session_id")

            return self.ok(_map_score_report(score_report))

        except Exception as e:
            logger.error("Error retrieving ScoreReport: %s", e, exc_info=True)
            return self.internal_server_error(str(e))


def _map_score_report(entity: ScoreReport) -> dict[str, Any]:
    """Map ScoreReport entity to response dict."""
    return {
        "id": entity.id,
        "lablet_session_id": entity.lablet_session_id,
        "grading_session_id": entity.grading_session_id,
        "score": entity.score,
        "max_score": entity.max_score,
        "cut_score": entity.cut_score,
        "passed": entity.passed,
        "grade_result": entity.grade_result,
        "percentage": entity.percentage,
        "sections": [s.to_dict() for s in entity.sections] if entity.sections else [],
        "created_at": entity.created_at.isoformat() if entity.created_at else None,
    }
