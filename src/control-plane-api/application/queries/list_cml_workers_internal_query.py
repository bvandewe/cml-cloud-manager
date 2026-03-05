"""List CML Workers internal query for service-to-service calls.

This query is used by internal controllers to list workers without requiring
a specific AWS region. It's designed for worker-controller, lablet-controller,
and resource-scheduler reconciliation loops.
"""

import logging
from dataclasses import dataclass
from typing import Any

from application.mappers import map_worker_to_dto, worker_dto_to_dict
from domain.enums import CMLWorkerStatus
from domain.repositories import CMLWorkerRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

logger = logging.getLogger(__name__)


@dataclass
class ListCMLWorkersInternalQuery(Query[OperationResult[list[dict[str, Any]]]]):
    """Internal query to list CML Workers for service-to-service calls.

    Unlike GetCMLWorkersQuery, this query does NOT require an aws_region,
    making it suitable for controllers that need to list all workers across regions.
    """

    status: str | None = None
    aws_region: str | None = None
    include_terminated: bool = False


class ListCMLWorkersInternalQueryHandler(QueryHandler[ListCMLWorkersInternalQuery, OperationResult[list[dict[str, Any]]]]):
    """Handle listing CML Workers for internal service-to-service calls."""

    def __init__(self, worker_repository: CMLWorkerRepository):
        super().__init__()
        self.worker_repository = worker_repository

    async def handle_async(self, request: ListCMLWorkersInternalQuery) -> OperationResult[list[dict[str, Any]]]:
        """Handle the internal list workers query."""
        try:
            # Get workers based on status filter
            if request.status:
                try:
                    status_enum = CMLWorkerStatus(request.status)
                    workers = await self.worker_repository.get_by_status_async(status_enum)
                except ValueError:
                    return self.bad_request(f"Invalid status: {request.status}")
            elif request.include_terminated:
                workers = await self.worker_repository.get_all_async()
            else:
                workers = await self.worker_repository.get_active_workers_async()

            # Filter by AWS region if specified
            if request.aws_region:
                workers = [worker for worker in workers if worker.state.aws_region == request.aws_region]

            # Use DTO mapper for consistent transformation
            result = [worker_dto_to_dict(map_worker_to_dto(worker)) for worker in workers]

            logger.debug(f"[Internal] Listed {len(result)} CML workers (status={request.status}, region={request.aws_region})")
            return self.ok(result)

        except Exception as e:
            logger.error(f"Error listing CML workers: {e}", exc_info=True)
            return self.internal_server_error(str(e))
