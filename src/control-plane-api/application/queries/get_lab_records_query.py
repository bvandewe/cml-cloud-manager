"""Query for fetching LabRecords with optional filters.

Phase 8 (P8-15): List query with filtering by worker, status, owner,
and bound/unbound state. Replaces ad-hoc DB queries scattered in controllers.
"""

import logging
from dataclasses import dataclass
from typing import Any

from lcm_core.domain.enums import LabRecordStatus
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler
from opentelemetry import trace

from application.queries.query_handler_base import QueryHandlerBase
from opentelemetry.trace import Status, StatusCode

from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class GetLabRecordsQuery(Query[OperationResult[list[dict[str, Any]]]]):
    """Query to list LabRecords with optional filters.

    All filters are optional. When multiple filters are provided,
    they are combined with AND semantics.

    Attributes:
        worker_id: Filter by hosting worker ID.
        status: Filter by LabRecordStatus (case-insensitive).
        owner: Filter by owner username.
        bound: If True, return only labs with active bindings.
                If False, return only unbound labs. None = no filter.
        include_terminal: Whether to include DELETED/ARCHIVED/ORPHANED labs. Default False.
    """

    worker_id: str | None = None
    status: str | None = None
    owner: str | None = None
    bound: bool | None = None
    include_terminal: bool = False


class GetLabRecordsQueryHandler(QueryHandlerBase, QueryHandler[GetLabRecordsQuery, OperationResult[list[dict[str, Any]]]]):
    """Handler for GetLabRecordsQuery.

    Fetches lab records from the repository and applies in-memory filtering.
    """

    def __init__(
        self,
        lab_record_repository: LabRecordRepository,
        lablet_session_repository: LabletSessionRepository,
        cml_worker_repository: CMLWorkerRepository,
    ):
        super().__init__()
        self._lab_repository = lab_record_repository
        self._session_repository = lablet_session_repository
        self._worker_repository = cml_worker_repository

    @tracer.start_as_current_span("get_lab_records_query_handler")
    async def handle_async(self, request: GetLabRecordsQuery) -> OperationResult[list[dict[str, Any]]]:
        """Handle the get lab records query with filtering."""
        span = trace.get_current_span()

        try:
            # Fetch base set from repository
            if request.worker_id:
                span.set_attribute("filter.worker_id", request.worker_id)
                records = await self._lab_repository.get_all_by_worker_async(request.worker_id)
            else:
                records = await self._lab_repository.get_all_async()

            # Apply status filter
            if request.status:
                span.set_attribute("filter.status", request.status)
                try:
                    target_status = LabRecordStatus(request.status)
                except ValueError:
                    return self.bad_request(f"Invalid status filter: {request.status}")
                records = [r for r in records if r.state.status == target_status]

            # Apply owner filter
            if request.owner:
                span.set_attribute("filter.owner", request.owner)
                records = [r for r in records if r.state.owner_username == request.owner]

            # Exclude terminal and orphaned states unless requested
            if not request.include_terminal:
                records = [r for r in records if not r.is_terminal and not r.is_orphaned]

            # Apply bound/unbound filter
            if request.bound is not None:
                span.set_attribute("filter.bound", request.bound)
                filtered = []
                for record in records:
                    session = await self._session_repository.get_by_lab_record_async(record.id())
                    has_binding = session is not None
                    if request.bound == has_binding:
                        filtered.append(record)
                records = filtered

            # Map to response dicts
            # Batch-resolve worker names to avoid N+1 queries
            unique_worker_ids = {r.state.worker_id for r in records if r.state.worker_id}
            worker_name_map: dict[str, str] = {}
            for wid in unique_worker_ids:
                worker = await self._worker_repository.get_by_id_async(wid)
                if worker and worker.state.name:
                    worker_name_map[wid] = worker.state.name

            labs = []
            for record in records:
                s = record.state
                lab_dict: dict[str, Any] = {
                    "id": record.id(),
                    "lab_id": s.lab_id,
                    "worker_id": s.worker_id,
                    "worker_name": worker_name_map.get(s.worker_id),
                    "worker_ip": s.worker_ip,
                    "title": s.title,
                    "description": s.description,
                    "status": s.status.value,
                    "state": s.state,
                    "owner_username": s.owner_username,
                    "node_count": s.node_count,
                    "link_count": s.link_count,
                    "revision": s.revision,
                    "source": s.source,
                    "pending_action": s.pending_action,
                    "created": (s.cml_created_at.isoformat() if s.cml_created_at else None),
                    "modified": (s.modified_at.isoformat() if s.modified_at else None),
                    "last_synced": (s.last_synced_at.isoformat() if s.last_synced_at else None),
                }
                labs.append(lab_dict)

            span.set_attribute("labs.count", len(labs))
            span.set_status(Status(StatusCode.OK))
            log.info("GetLabRecordsQuery returned %d lab records", len(labs))

            return self.ok(labs)

        except Exception as e:
            error = f"Error fetching lab records: {e}"
            log.exception(error)
            span.set_status(Status(StatusCode.ERROR, error))
            span.record_exception(e)
            return self.internal_server_error(str(e))
