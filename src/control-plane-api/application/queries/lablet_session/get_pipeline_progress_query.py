"""Get Pipeline Progress query with handler.

Sprint G (G2): Retrieves the pipeline_progress dict from a LabletSession.
Returns a dictionary of pipeline names → step progress snapshots.
"""

import logging
from dataclasses import dataclass
from typing import Any

from application.queries.query_handler_base import QueryHandlerBase
from domain.entities.lablet_session import LabletSession
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

logger = logging.getLogger(__name__)


@dataclass
class GetPipelineProgressQuery(Query[OperationResult[dict[str, Any]]]):
    """Query to retrieve pipeline progress for a LabletSession.

    Args:
        session_id: LabletSession ID.
        pipeline_name: Optional — if provided, return only that pipeline's
            progress. If None, return all pipelines.
    """

    session_id: str = ""
    pipeline_name: str | None = None


class GetPipelineProgressQueryHandler(QueryHandlerBase, QueryHandler[GetPipelineProgressQuery, OperationResult[dict[str, Any]]]):
    """Handle pipeline progress retrieval from LabletSession aggregate.

    Sprint G (G2): Reads the ``pipeline_progress`` dict stored on the
    LabletSession state. This is the live progress view (complement to
    PipelineExecutionRecord which is the audit history).
    """

    def __init__(self, lablet_session_repository: LabletSessionRepository):
        super().__init__()
        self._repository = lablet_session_repository

    async def handle_async(self, request: GetPipelineProgressQuery) -> OperationResult[dict[str, Any]]:
        if not request.session_id:
            return self.bad_request("session_id is required")

        try:
            session = await self._repository.get_by_id_async(request.session_id)
            if not session:
                return self.not_found(LabletSession, request.session_id)

            pipeline_progress = session.state.pipeline_progress or {}

            if request.pipeline_name:
                if request.pipeline_name not in pipeline_progress:
                    return self.ok({"pipeline_name": request.pipeline_name, "steps": {}, "found": False})
                return self.ok(
                    {
                        "pipeline_name": request.pipeline_name,
                        "steps": pipeline_progress[request.pipeline_name],
                        "found": True,
                    }
                )

            # Return all pipelines
            result = {
                "session_id": request.session_id,
                "pipelines": {},
            }
            for name, steps in pipeline_progress.items():
                total = len(steps)
                completed = sum(1 for s in steps.values() if s.get("status") == "completed")
                failed = sum(1 for s in steps.values() if s.get("status") == "failed")
                skipped = sum(1 for s in steps.values() if s.get("status") == "skipped")
                in_progress = sum(1 for s in steps.values() if s.get("status") == "in_progress")

                result["pipelines"][name] = {
                    "steps": steps,
                    "summary": {
                        "total": total,
                        "completed": completed,
                        "failed": failed,
                        "skipped": skipped,
                        "in_progress": in_progress,
                        "pending": total - completed - failed - skipped - in_progress,
                    },
                }

            logger.info("Retrieved pipeline progress for session %s (%d pipelines)", request.session_id, len(pipeline_progress))
            return self.ok(result)

        except Exception as e:
            logger.error("Error retrieving pipeline progress: %s", e, exc_info=True)
            return self.internal_server_error(str(e))
