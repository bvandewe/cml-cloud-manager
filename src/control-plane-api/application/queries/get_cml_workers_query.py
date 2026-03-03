"""Get CML Workers query with handler."""

import logging
from dataclasses import dataclass
from typing import Any

from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

from application.mappers import map_worker_to_dto, worker_dto_to_dict
from domain.enums import CMLWorkerStatus
from domain.repositories import CMLWorkerRepository
from integration.enums import AwsRegion

logger = logging.getLogger(__name__)


@dataclass
class GetCMLWorkersQuery(Query[OperationResult[list[dict[str, Any]]]]):
    """Query to retrieve CML Workers filtered by region and/or status."""

    aws_region: AwsRegion | None = None
    status: CMLWorkerStatus | None = None
    include_terminated: bool = False


class GetCMLWorkersQueryHandler(QueryHandler[GetCMLWorkersQuery, OperationResult[list[dict[str, Any]]]]):
    """Handle retrieving CML Workers with optional filtering."""

    def __init__(self, worker_repository: CMLWorkerRepository):
        super().__init__()
        self.worker_repository = worker_repository

    async def handle_async(self, request: GetCMLWorkersQuery) -> OperationResult[list[dict[str, Any]]]:
        """Handle get CML workers query."""
        try:
            # Get workers based on status filter
            if request.status:
                workers = await self.worker_repository.get_by_status_async(request.status)
            elif request.include_terminated:
                workers = await self.worker_repository.get_all_async()
            else:
                workers = await self.worker_repository.get_active_workers_async()

            # Filter by AWS region if specified
            if request.aws_region:
                filtered_workers = [worker for worker in workers if worker.state.aws_region == request.aws_region.value]
            else:
                filtered_workers = workers

            # Use DTO mapper for consistent transformation
            result = [worker_dto_to_dict(map_worker_to_dto(worker)) for worker in filtered_workers]

            region_msg = request.aws_region.value if request.aws_region else "all regions"
            logger.info(f"Retrieved {len(result)} CML workers in {region_msg}")
            return self.ok(result)

        except Exception as e:
            logger.error(f"Error retrieving CML workers: {e}", exc_info=True)
            return self.internal_server_error(str(e))
