"""Query for fetching a LabRecord's run history.

Phase 8 (P8-19): Returns the list of LabRunRecord value objects
documenting lab execution sessions with timing and outcome data.
"""

import logging
from dataclasses import dataclass
from typing import Any

from domain.entities.lab_record import LabRecord
from domain.repositories.lab_record_repository import LabRecordRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class GetLabRecordRunsQuery(Query[OperationResult[dict[str, Any]]]):
    """Query to retrieve the run history of a LabRecord.

    Attributes:
        lab_record_id: The LabRecord aggregate ID.
    """

    lab_record_id: str


class GetLabRecordRunsQueryHandler(
    QueryHandler[GetLabRecordRunsQuery, OperationResult[dict[str, Any]]],
):
    """Handler for GetLabRecordRunsQuery.

    Returns the run history (most recent first) capped at max_run_history_size.
    """

    def __init__(self, lab_record_repository: LabRecordRepository):
        super().__init__()
        self._lab_repository = lab_record_repository

    @tracer.start_as_current_span("get_lab_record_runs_query_handler")
    async def handle_async(self, request: GetLabRecordRunsQuery) -> OperationResult[dict[str, Any]]:
        """Handle the get lab record runs query."""
        span = trace.get_current_span()
        span.set_attribute("lab_record.id", request.lab_record_id)

        try:
            lab = await self._lab_repository.get_by_id_async(request.lab_record_id)
            if not lab:
                return self.not_found(LabRecord, request.lab_record_id)

            # Return runs in reverse chronological order (most recent first)
            runs = list(reversed(lab.state.run_history_v2))

            result: dict[str, Any] = {
                "lab_record_id": lab.id(),
                "lab_id": lab.state.lab_id,
                "run_count": len(runs),
                "runs": runs,
            }

            span.set_attribute("runs.count", len(runs))
            span.set_status(Status(StatusCode.OK))
            return self.ok(result)

        except Exception as e:
            error = f"Error fetching runs for lab record {request.lab_record_id}: {e}"
            log.exception(error)
            span.set_status(Status(StatusCode.ERROR, error))
            span.record_exception(e)
            return self.internal_server_error(str(e))
