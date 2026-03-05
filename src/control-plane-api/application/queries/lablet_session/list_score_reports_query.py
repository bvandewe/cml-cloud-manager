"""List ScoreReports query with handler.

Phase 7D: Aggregate query for ScoreReports by definition_id.
Useful for dashboard reporting across all sessions of a definition.
"""

import logging
from dataclasses import dataclass
from typing import Any

from domain.repositories.score_report_repository import ScoreReportRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

logger = logging.getLogger(__name__)


@dataclass
class ListScoreReportsQuery(Query[OperationResult[list[dict[str, Any]]]]):
    """Query to list ScoreReports with filtering.

    Supports filtering by:
    - definition_id: All score reports for sessions using this definition
    - grading_session_id: Score report for a specific grading session
    """

    definition_id: str | None = None
    grading_session_id: str | None = None
    skip: int = 0
    limit: int = 100


class ListScoreReportsQueryHandler(QueryHandler[ListScoreReportsQuery, OperationResult[list[dict[str, Any]]]]):
    """Handle listing ScoreReports with filtering."""

    def __init__(self, score_report_repository: ScoreReportRepository):
        super().__init__()
        self._repository = score_report_repository

    async def handle_async(self, request: ListScoreReportsQuery) -> OperationResult[list[dict[str, Any]]]:
        try:
            reports = []

            if request.definition_id:
                reports = await self._repository.get_by_definition_id_async(request.definition_id)
            elif request.grading_session_id:
                report = await self._repository.get_by_grading_session_id_async(request.grading_session_id)
                if report:
                    reports = [report]
            else:
                return self.bad_request("Must provide either 'definition_id' or 'grading_session_id'")

            # Apply pagination
            total_count = len(reports)
            paginated = reports[request.skip : request.skip + request.limit]

            result = [_map_score_report_summary(r) for r in paginated]

            logger.info(
                "Listed %d of %d ScoreReports (definition_id=%s, grading_session_id=%s)",
                len(result),
                total_count,
                request.definition_id,
                request.grading_session_id,
            )
            return self.ok(result)

        except Exception as e:
            logger.error("Error listing ScoreReports: %s", e, exc_info=True)
            return self.internal_server_error(str(e))


def _map_score_report_summary(entity) -> dict[str, Any]:
    """Map ScoreReport entity to lightweight summary dict."""
    return {
        "id": entity.id,
        "lablet_session_id": entity.lablet_session_id,
        "grading_session_id": entity.grading_session_id,
        "score": entity.score,
        "max_score": entity.max_score,
        "passed": entity.passed,
        "grade_result": entity.grade_result,
        "percentage": entity.percentage,
        "created_at": entity.created_at.isoformat() if entity.created_at else None,
    }
