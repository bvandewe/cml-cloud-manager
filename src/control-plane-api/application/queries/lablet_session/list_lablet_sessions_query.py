"""List LabletSessions query with handler.

Phase 7D: Replaces list_lablet_instances_query.py.
Supports filtering by status, worker_id, owner_id, definition_id with pagination.
"""

import logging
from dataclasses import dataclass

from application.dtos.lablet_session_dto import LabletSessionSummaryDto, map_lablet_session_to_summary_dto
from application.queries.query_handler_base import QueryHandlerBase
from domain.enums import LabletSessionStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

logger = logging.getLogger(__name__)


@dataclass
class ListLabletSessionsQuery(Query[OperationResult[list[LabletSessionSummaryDto]]]):
    """Query to list LabletSessions with filtering and pagination.

    Supports filtering by:
    - status: Filter by session status (pending, running, etc.)
    - worker_id: Filter by assigned worker
    - owner_id: Filter by owner
    - definition_id: Filter by LabletDefinition

    Supports pagination:
    - skip: Number of records to skip
    - limit: Maximum number of records to return
    """

    status: str | None = None
    worker_id: str | None = None
    owner_id: str | None = None
    definition_id: str | None = None
    include_terminated: bool = False
    skip: int = 0
    limit: int = 100


class ListLabletSessionsQueryHandler(QueryHandlerBase, QueryHandler[ListLabletSessionsQuery, OperationResult[list[LabletSessionSummaryDto]]]):
    """Handle listing LabletSessions with filtering and pagination."""

    def __init__(
        self,
        lablet_session_repository: LabletSessionRepository,
        lablet_definition_repository: LabletDefinitionRepository,
        cml_worker_repository: CMLWorkerRepository,
    ):
        super().__init__()
        self._repository = lablet_session_repository
        self._definition_repository = lablet_definition_repository
        self._worker_repository = cml_worker_repository

    async def handle_async(self, request: ListLabletSessionsQuery) -> OperationResult[list[LabletSessionSummaryDto]]:
        try:
            sessions = []

            if request.status:
                try:
                    status_enum = LabletSessionStatus(request.status)
                    sessions = await self._repository.list_by_status_async(status_enum)
                except ValueError:
                    valid_statuses = ", ".join(s.value for s in LabletSessionStatus)
                    return self.bad_request(f"Invalid status '{request.status}'. Must be one of: {valid_statuses}")
            elif request.worker_id:
                sessions = await self._repository.list_by_worker_async(request.worker_id)
            elif request.owner_id:
                sessions = await self._repository.list_by_owner_async(request.owner_id)
            elif request.definition_id:
                sessions = await self._repository.list_by_definition_async(request.definition_id)
            else:
                if request.include_terminated:
                    # All sessions including terminal statuses
                    non_terminal = await self._repository.list_by_statuses_async(
                        [
                            LabletSessionStatus.PENDING,
                            LabletSessionStatus.SCHEDULED,
                            LabletSessionStatus.INSTANTIATING,
                            LabletSessionStatus.READY,
                            LabletSessionStatus.RUNNING,
                            LabletSessionStatus.COLLECTING,
                            LabletSessionStatus.GRADING,
                            LabletSessionStatus.STOPPING,
                            LabletSessionStatus.STOPPED,
                            LabletSessionStatus.ARCHIVED,
                        ]
                    )
                    terminal = await self._repository.list_by_statuses_async(
                        [
                            LabletSessionStatus.TERMINATED,
                            LabletSessionStatus.EXPIRED,
                        ]
                    )
                    sessions = non_terminal + terminal
                else:
                    # All non-terminal statuses (default "All Statuses" view)
                    sessions = await self._repository.list_by_statuses_async(
                        [
                            LabletSessionStatus.PENDING,
                            LabletSessionStatus.SCHEDULED,
                            LabletSessionStatus.INSTANTIATING,
                            LabletSessionStatus.READY,
                            LabletSessionStatus.RUNNING,
                            LabletSessionStatus.COLLECTING,
                            LabletSessionStatus.GRADING,
                            LabletSessionStatus.STOPPING,
                            LabletSessionStatus.STOPPED,
                        ]
                    )

            # Filter out terminated if not requested and using a specific filter
            if not request.include_terminated and (request.worker_id or request.owner_id or request.definition_id):
                sessions = [s for s in sessions if s.state.status != LabletSessionStatus.TERMINATED]

            # Apply pagination
            total_count = len(sessions)
            paginated = sessions[request.skip : request.skip + request.limit]

            # Batch-collect unique FK IDs for cross-aggregate enrichment
            definition_ids = {s.state.definition_id for s in paginated if s.state.definition_id}
            worker_ids = {s.state.worker_id for s in paginated if s.state.worker_id}

            # Batch-fetch definitions and workers
            definitions_by_id: dict[str, object] = {}
            for def_id in definition_ids:
                try:
                    defn = await self._definition_repository.get_by_id_async(def_id)
                    if defn:
                        definitions_by_id[def_id] = defn
                except Exception:
                    logger.warning("Failed to fetch LabletDefinition %s for enrichment", def_id)

            workers_by_id: dict[str, object] = {}
            for wid in worker_ids:
                try:
                    worker = await self._worker_repository.get_by_id_async(wid)
                    if worker:
                        workers_by_id[wid] = worker
                except Exception:
                    logger.warning("Failed to fetch CMLWorker %s for enrichment", wid)

            # Map with enrichment
            result = []
            for s in paginated:
                defn = definitions_by_id.get(s.state.definition_id)
                defn_enrichment = (
                    {
                        "form_qualified_name": defn.state.form_qualified_name,
                        "node_count": defn.state.node_count,
                        "upstream_sync_status": defn.state.upstream_sync_status,
                    }
                    if defn
                    else None
                )

                worker = workers_by_id.get(s.state.worker_id) if s.state.worker_id else None
                worker_enrichment = {"name": worker.state.name} if worker else None

                result.append(map_lablet_session_to_summary_dto(s, defn_enrichment, worker_enrichment))

            logger.info(
                "Listed %d of %d LabletSessions (skip=%d, limit=%d, filters: status=%s, worker_id=%s, owner_id=%s, definition_id=%s)",
                len(result),
                total_count,
                request.skip,
                request.limit,
                request.status,
                request.worker_id,
                request.owner_id,
                request.definition_id,
            )
            return self.ok(result)

        except Exception as e:
            logger.error("Error listing LabletSessions: %s", e, exc_info=True)
            return self.internal_server_error(str(e))
