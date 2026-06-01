"""List Pipeline Executions query with handler.

Sprint G (G2): Queries PipelineExecutionRecord entities for execution
history and auditing. Supports filtering by session_id, pipeline_name,
and status.
"""

import logging
from dataclasses import dataclass
from typing import Any

from application.queries.query_handler_base import QueryHandlerBase
from domain.entities.pipeline_execution_record import PipelineExecutionRecord
from domain.repositories.pipeline_execution_repository import PipelineExecutionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

logger = logging.getLogger(__name__)


@dataclass
class ListPipelineExecutionsQuery(Query[OperationResult[list[dict[str, Any]]]]):
    """Query to list PipelineExecutionRecords with filtering.

    Supports filtering by:
    - session_id (required): All execution records for a session.
    - pipeline_name (optional): Filter to a specific pipeline type.
    - status (optional): Filter by execution status.

    Pagination via skip/limit.
    """

    session_id: str = ""
    pipeline_name: str | None = None
    status: str | None = None
    skip: int = 0
    limit: int = 50


class ListPipelineExecutionsQueryHandler(QueryHandlerBase, QueryHandler[ListPipelineExecutionsQuery, OperationResult[list[dict[str, Any]]]]):
    """Handle listing PipelineExecutionRecords with filtering.

    Sprint G (G2): Queries the ``pipeline_executions`` MongoDB collection
    for execution history. Returns lightweight summary dicts.
    """

    def __init__(self, pipeline_execution_repository: PipelineExecutionRepository):
        super().__init__()
        self._repository = pipeline_execution_repository

    async def handle_async(self, request: ListPipelineExecutionsQuery) -> OperationResult[list[dict[str, Any]]]:
        if not request.session_id:
            return self.bad_request("session_id is required")

        try:
            if request.pipeline_name:
                records = await self._repository.get_by_session_and_pipeline_async(request.session_id, request.pipeline_name)
            else:
                records = await self._repository.get_by_session_async(request.session_id)

            # Filter by status if provided
            if request.status:
                records = [r for r in records if r.status == request.status]

            # Apply pagination
            total_count = len(records)
            paginated = records[request.skip : request.skip + request.limit]

            result = [_map_execution_summary(r) for r in paginated]

            logger.info(
                "Listed %d of %d PipelineExecutionRecords for session %s (pipeline=%s, status=%s)",
                len(result),
                total_count,
                request.session_id,
                request.pipeline_name,
                request.status,
            )
            return self.ok(result)

        except Exception as e:
            logger.error("Error listing PipelineExecutionRecords: %s", e, exc_info=True)
            return self.internal_server_error(str(e))


def _map_execution_summary(entity: PipelineExecutionRecord) -> dict[str, Any]:
    """Map PipelineExecutionRecord to lightweight summary dict."""
    return {
        "id": entity.id,
        "session_id": entity.session_id,
        "pipeline_name": entity.pipeline_name,
        "status": entity.status,
        "attempt": entity.attempt,
        "started_at": entity.started_at.isoformat() if entity.started_at else None,
        "completed_at": entity.completed_at.isoformat() if entity.completed_at else None,
        "duration_seconds": entity.duration_seconds,
        "steps_total": len(entity.steps),
        "steps_completed": sum(1 for s in entity.steps if s.get("status") == "completed"),
        "steps_failed": sum(1 for s in entity.steps if s.get("status") == "failed"),
        "error": entity.error,
    }
