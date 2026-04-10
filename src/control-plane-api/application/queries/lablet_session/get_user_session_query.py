"""Get UserSession query with handler.

Phase 7D: Retrieves a UserSession by ID or by parent lablet_session_id.
"""

import logging
from dataclasses import dataclass
from typing import Any

from domain.entities.user_session import UserSession
from domain.repositories.user_session_repository import UserSessionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

logger = logging.getLogger(__name__)


@dataclass
class GetUserSessionQuery(Query[OperationResult[dict[str, Any]]]):
    """Query to retrieve a UserSession by ID or lablet_session_id."""

    id: str | None = None
    lablet_session_id: str | None = None


class GetUserSessionQueryHandler(QueryHandler[GetUserSessionQuery, OperationResult[dict[str, Any]]]):
    """Handle UserSession retrieval."""

    def __init__(self, user_session_repository: UserSessionRepository):
        super().__init__()
        self._repository = user_session_repository

    async def handle_async(self, request: GetUserSessionQuery) -> OperationResult[dict[str, Any]]:
        if not request.id and not request.lablet_session_id:
            return self.bad_request("Must provide either 'id' or 'lablet_session_id'")

        try:
            user_session: UserSession | None = None

            if request.id:
                user_session = await self._repository.get_by_id_async(request.id)
                if not user_session:
                    return self.not_found(UserSession, request.id)
            else:
                user_session = await self._repository.get_by_lablet_session_async(request.lablet_session_id)
                if not user_session:
                    return self.not_found(UserSession, request.lablet_session_id, "lablet_session_id")

            return self.ok(_map_user_session(user_session))

        except Exception as e:
            logger.error("Error retrieving UserSession: %s", e, exc_info=True)
            return self.internal_server_error(str(e))


def _map_user_session(entity: UserSession) -> dict[str, Any]:
    """Map UserSession entity to response dict."""
    return {
        "id": entity.id,
        "lablet_session_id": entity.lablet_session_id,
        "lds_session_id": entity.lds_session_id,
        "lds_part_id": entity.lds_part_id,
        "form_qualified_name": entity.form_qualified_name,
        "login_url": entity.login_url,
        "devices": entity.devices,
        "status": entity.status.value,
        "started_at": entity.started_at.isoformat() if entity.started_at else None,
        "ended_at": entity.ended_at.isoformat() if entity.ended_at else None,
        "error_message": entity.error_message,
        "created_at": entity.created_at.isoformat() if entity.created_at else None,
        "updated_at": entity.updated_at.isoformat() if entity.updated_at else None,
    }
