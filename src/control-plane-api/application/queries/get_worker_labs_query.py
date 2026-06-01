"""Query for fetching CML Worker labs from cached database records.

This query handler fetches lab information from the lab_records collection
which is refreshed every 30 minutes by the LabsRefreshJob background job.
This is a read-only operation with no side effects.
"""

import logging
from dataclasses import dataclass
from typing import Any

from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler
from opentelemetry import trace

from application.queries.query_handler_base import QueryHandlerBase
from opentelemetry.trace import Status, StatusCode

from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.lab_record_repository import LabRecordRepository

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class GetWorkerLabsQuery(Query[OperationResult[list[dict[str, Any]]]]):
    """Query to get labs from a CML worker.

    Attributes:
        worker_id: The ID of the worker to get labs from
    """

    worker_id: str


class GetWorkerLabsQueryHandler(QueryHandlerBase, QueryHandler[GetWorkerLabsQuery, OperationResult[list[dict[str, Any]]]]):
    """Handler for GetWorkerLabsQuery.

    This handler retrieves lab details from the cached lab_records database collection.
    Lab records are refreshed every 30 minutes by the LabsRefreshJob background job.
    This provides faster response times and reduces load on the CML API.
    """

    def __init__(
        self,
        worker_repository: CMLWorkerRepository,
        lab_record_repository: LabRecordRepository,
    ):
        """Initialize the handler.

        Args:
            worker_repository: Repository for accessing worker data
            lab_record_repository: Repository for accessing cached lab records
        """
        super().__init__()
        self._worker_repository = worker_repository
        self._lab_record_repository = lab_record_repository

    @tracer.start_as_current_span("get_worker_labs_query_handler")
    async def handle_async(self, request: GetWorkerLabsQuery) -> OperationResult[list[dict[str, Any]]]:
        """Handle the get worker labs query.

        Fetches lab records from the database (cached data refreshed every 30 minutes).

        Args:
            request: The query containing worker_id

        Returns:
            OperationResult containing list of lab details or error
        """
        query = request
        span = trace.get_current_span()
        span.set_attribute("worker.id", query.worker_id)

        try:
            # Verify worker exists
            worker = await self._worker_repository.get_by_id_async(query.worker_id)
            if not worker:
                error = f"Worker {query.worker_id} not found"
                log.warning(error)
                span.set_status(Status(StatusCode.ERROR, error))
                return self.bad_request(error)

            # Fetch lab records from database
            log.info(f"Fetching labs from database for worker {query.worker_id}")
            lab_records = await self._lab_record_repository.get_all_by_worker_async(query.worker_id)

            span.set_attribute("labs.count", len(lab_records))

            # Log worker status for debugging if no labs found
            if len(lab_records) == 0:
                log.info(
                    f"No labs found for worker {query.worker_id}. "
                    f"Worker status: {worker.state.status.value}, "
                    f"Has endpoint: {bool(worker.state.https_endpoint)}, "
                    f"Endpoint: {worker.state.https_endpoint}"
                )

            # Convert lab records to dict format for API response
            labs = []
            for record in lab_records:
                lab_dict = {
                    "id": record.state.lab_id,
                    "title": record.state.title,
                    "description": record.state.description,
                    "notes": record.state.notes,
                    "state": record.state.state,
                    "owner": record.state.owner_fullname,
                    "owner_username": record.state.owner_username,
                    "node_count": record.state.node_count,
                    "link_count": record.state.link_count,
                    "created": (record.state.cml_created_at.isoformat() if record.state.cml_created_at else None),
                    "modified": (record.state.modified_at.isoformat() if record.state.modified_at else None),
                    "groups": record.state.groups,
                    "last_synced": (record.state.last_synced_at.isoformat() if record.state.last_synced_at else None),
                }
                labs.append(lab_dict)

            log.info(f"Successfully fetched {len(labs)} labs from database for worker {query.worker_id}")
            span.set_attribute("labs.fetched", len(labs))
            span.set_status(Status(StatusCode.OK))

            return self.ok(labs)

        except Exception as e:
            error = f"Error getting labs for worker {query.worker_id}: {str(e)}"
            log.exception(error)
            span.set_status(Status(StatusCode.ERROR, error))
            span.record_exception(e)
            return self.internal_server_error(str(e))
