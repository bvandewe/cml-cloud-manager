"""Query for fetching a LabRecord's revision history.

Phase 8 (P8-18): Returns the list of LabRevision value objects
documenting topology changes over time with checksums.
"""

import logging
from dataclasses import dataclass
from typing import Any

from application.queries.query_handler_base import QueryHandlerBase
from domain.entities.lab_record import LabRecord
from domain.repositories.lab_record_repository import LabRecordRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class GetLabRecordRevisionsQuery(Query[OperationResult[dict[str, Any]]]):
    """Query to retrieve the revision history of a LabRecord.

    Attributes:
        lab_record_id: The LabRecord aggregate ID.
    """

    lab_record_id: str


class GetLabRecordRevisionsQueryHandler(
    QueryHandlerBase,
    QueryHandler[GetLabRecordRevisionsQuery, OperationResult[dict[str, Any]]],
):
    """Handler for GetLabRecordRevisionsQuery.

    Returns the full revision history ordered by revision number.
    """

    def __init__(self, lab_record_repository: LabRecordRepository):
        super().__init__()
        self._lab_repository = lab_record_repository

    @tracer.start_as_current_span("get_lab_record_revisions_query_handler")
    async def handle_async(self, request: GetLabRecordRevisionsQuery) -> OperationResult[dict[str, Any]]:
        """Handle the get lab record revisions query."""
        span = trace.get_current_span()
        span.set_attribute("lab_record.id", request.lab_record_id)

        try:
            lab = await self._lab_repository.get_by_id_async(request.lab_record_id)
            if not lab:
                return self.not_found(LabRecord, request.lab_record_id)

            result: dict[str, Any] = {
                "lab_record_id": lab.id(),
                "lab_id": lab.state.lab_id,
                "current_revision": lab.state.revision,
                "revision_count": len(lab.state.revision_history),
                "revisions": lab.state.revision_history,
            }

            span.set_attribute("revisions.count", len(lab.state.revision_history))
            span.set_status(Status(StatusCode.OK))
            return self.ok(result)

        except Exception as e:
            error = f"Error fetching revisions for lab record {request.lab_record_id}: {e}"
            log.exception(error)
            span.set_status(Status(StatusCode.ERROR, error))
            span.record_exception(e)
            return self.internal_server_error(str(e))
