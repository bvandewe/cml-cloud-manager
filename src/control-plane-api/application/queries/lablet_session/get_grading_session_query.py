"""Get GradingSession query with handler.

Phase 7D: Retrieves a GradingSession by ID or by parent lablet_session_id.
"""

import logging
from dataclasses import dataclass
from typing import Any

from domain.entities.grading_session import GradingSession
from domain.repositories.grading_session_repository import GradingSessionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

logger = logging.getLogger(__name__)


@dataclass
class GetGradingSessionQuery(Query[OperationResult[dict[str, Any]]]):
    """Query to retrieve a GradingSession by ID or lablet_session_id."""

    id: str | None = None
    lablet_session_id: str | None = None


class GetGradingSessionQueryHandler(QueryHandler[GetGradingSessionQuery, OperationResult[dict[str, Any]]]):
    """Handle GradingSession retrieval."""

    def __init__(self, grading_session_repository: GradingSessionRepository):
        super().__init__()
        self._repository = grading_session_repository

    async def handle_async(self, request: GetGradingSessionQuery) -> OperationResult[dict[str, Any]]:
        if not request.id and not request.lablet_session_id:
            return self.bad_request("Must provide either 'id' or 'lablet_session_id'")

        try:
            grading_session: GradingSession | None = None

            if request.id:
                grading_session = await self._repository.get_by_id_async(request.id)
                if not grading_session:
                    return self.not_found(GradingSession, request.id)
            else:
                grading_session = await self._repository.get_by_lablet_session_id_async(request.lablet_session_id)
                if not grading_session:
                    return self.not_found(GradingSession, request.lablet_session_id, "lablet_session_id")

            return self.ok(_map_grading_session(grading_session))

        except Exception as e:
            logger.error("Error retrieving GradingSession: %s", e, exc_info=True)
            return self.internal_server_error(str(e))


def _map_grading_session(entity: GradingSession) -> dict[str, Any]:
    """Map GradingSession entity to response dict."""
    return {
        "id": entity.id,
        "lablet_session_id": entity.lablet_session_id,
        "external_grading_session_id": entity.external_grading_session_id,
        "grading_part_id": entity.grading_part_id,
        "pod_id": entity.pod_id,
        "form_qualified_name": entity.form_qualified_name,
        "grading_rules_uri": entity.grading_rules_uri,
        "devices": entity.devices,
        "status": entity.status.value,
        "started_at": entity.started_at.isoformat() if entity.started_at else None,
        "ended_at": entity.ended_at.isoformat() if entity.ended_at else None,
        "error_message": entity.error_message,
        "created_at": entity.created_at.isoformat() if entity.created_at else None,
        "updated_at": entity.updated_at.isoformat() if entity.updated_at else None,
    }
