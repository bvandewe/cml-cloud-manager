"""GetJobQuery — Retrieve job status and progress.

Self-contained CQRS query: request class + handler in same file.
"""

import logging
from dataclasses import dataclass

from domain.entities.job import Job
from domain.repositories.job_repository import JobRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

from application.dtos.job_dto import JobDto, map_job_to_dto

logger = logging.getLogger(__name__)


@dataclass
class GetJobQuery(Query[OperationResult[JobDto]]):
    """Query to retrieve job status.

    Attributes:
        job_id: The job identifier to look up.
    """

    job_id: str = ""


class GetJobQueryHandler(QueryHandler[GetJobQuery, OperationResult[JobDto]]):
    """Handler for GetJobQuery.

    Retrieves job entity from repository and returns status/progress.
    """

    def __init__(self, job_repository: JobRepository):
        self._repository = job_repository

    async def handle_async(self, request: GetJobQuery) -> OperationResult[JobDto]:
        """Handle job query."""
        if not request.job_id:
            return self.bad_request("job_id is required")

        job = await self._repository.get_by_id_async(request.job_id)
        if job is None:
            return self.not_found(Job, request.job_id)

        return self.ok(map_job_to_dto(job))
