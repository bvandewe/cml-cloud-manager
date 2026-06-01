"""Query for fetching a LabRecord's active lablet bindings.

Phase 7F: Refactored to use LabletSession.lab_record_id (direct 1:1 FK)
instead of the deprecated LabletLabBinding entity (ADR-020 §2).
"""

import logging
from dataclasses import dataclass
from typing import Any

from application.queries.query_handler_base import QueryHandlerBase
from domain.entities.lab_record import LabRecord
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def _get_related_session_id(lab: LabRecord) -> str | None:
    """Resolve the best-known LabletSession reference for a LabRecord."""

    if lab.state.active_lablet_session_id:
        return lab.state.active_lablet_session_id

    for run in reversed(lab.run_history_vo):
        if run.lablet_session_id:
            return run.lablet_session_id

    return None


@dataclass
class GetLabRecordBindingsQuery(Query[OperationResult[dict[str, Any]]]):
    """Query to retrieve the LabletSession bound to a LabRecord.

    In the new 1:1 model (ADR-020), each LabRecord is bound to at most
    one LabletSession via LabletSession.lab_record_id.

    Attributes:
        lab_record_id: The LabRecord aggregate ID.
        include_released: Kept for API compatibility. In the 1:1 model,
            only active bindings are queryable (released bindings clear lab_record_id).
    """

    lab_record_id: str
    include_released: bool = False


class GetLabRecordBindingsQueryHandler(
    QueryHandlerBase,
    QueryHandler[GetLabRecordBindingsQuery, OperationResult[dict[str, Any]]],
):
    """Handler for GetLabRecordBindingsQuery.

    Returns the LabletSession bound to this LabRecord (0 or 1 binding
    in the 1:1 model per ADR-020).
    """

    def __init__(
        self,
        lab_record_repository: LabRecordRepository,
        lablet_session_repository: LabletSessionRepository,
    ):
        super().__init__()
        self._lab_repository = lab_record_repository
        self._session_repository = lablet_session_repository

    @tracer.start_as_current_span("get_lab_record_bindings_query_handler")
    async def handle_async(self, request: GetLabRecordBindingsQuery) -> OperationResult[dict[str, Any]]:
        """Handle the get lab record bindings query."""
        span = trace.get_current_span()
        span.set_attribute("lab_record.id", request.lab_record_id)

        try:
            # Verify lab exists
            lab = await self._lab_repository.get_by_id_async(request.lab_record_id)
            if not lab:
                return self.not_found(LabRecord, request.lab_record_id)

            # Find session bound to this lab record (1:1 model)
            session = await self._session_repository.get_by_lab_record_async(request.lab_record_id)

            # Fallback: completed sessions may no longer resolve via the direct
            # FK, but the LabRecord still retains the related session identity.
            if session is None:
                related_session_id = _get_related_session_id(lab)
                if related_session_id:
                    session = await self._session_repository.get_by_id_async(related_session_id)
            binding_dicts: list[dict[str, Any]] = []
            if session:
                binding_dict: dict[str, Any] = {
                    "binding_id": session.id(),
                    "instance_id": session.id(),
                    "lablet_instance_id": session.id(),
                    "lablet_session_id": session.id(),
                    "definition_name": session.state.definition_name,
                    "lab_record_id": request.lab_record_id,
                    "role": "primary",
                    "status": session.state.status.value,
                    "is_active": not session.is_terminal,
                    "bound_at": session.state.scheduled_at.isoformat() if session.state.scheduled_at else None,
                    "released_at": session.state.terminated_at.isoformat() if session.is_terminal else None,
                }
                binding_dicts.append(binding_dict)

            result: dict[str, Any] = {
                "lab_record_id": lab.id(),
                "lab_id": lab.state.lab_id,
                "binding_count": len(binding_dicts),
                "bindings": binding_dicts,
            }

            span.set_attribute("bindings.count", len(binding_dicts))
            span.set_status(Status(StatusCode.OK))
            return self.ok(result)

        except Exception as e:
            error = f"Error fetching bindings for lab record {request.lab_record_id}: {e}"
            log.exception(error)
            span.set_status(Status(StatusCode.ERROR, error))
            span.record_exception(e)
            return self.internal_server_error(str(e))
