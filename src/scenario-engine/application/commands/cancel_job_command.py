"""CancelJobCommand — Cancel a running automation job.

Self-contained CQRS command: request class + handler in same file.
"""

import logging
from dataclasses import dataclass

from domain.entities.job import Job, JobStatus
from domain.repositories.job_repository import JobRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

from application.services.job_execution_service import JobExecutionService

logger = logging.getLogger(__name__)


@dataclass
class CancelJobCommand(Command[OperationResult[None]]):
    """Command to cancel a running job.

    Attributes:
        job_id: The job identifier to cancel.
    """

    job_id: str = ""


class CancelJobCommandHandler(CommandHandler[CancelJobCommand, OperationResult[None]]):
    """Handler for CancelJobCommand.

    Validates job exists and is cancellable, then requests cancellation.
    """

    def __init__(self, job_repository: JobRepository, job_execution_service: JobExecutionService):
        self._repository = job_repository
        self._executor = job_execution_service

    async def handle_async(self, request: CancelJobCommand) -> OperationResult[None]:
        """Handle job cancellation."""
        if not request.job_id:
            return self.bad_request("job_id is required")

        # Look up job
        job = await self._repository.get_by_id_async(request.job_id)
        if job is None:
            return self.not_found(Job, request.job_id)

        # Validate cancellable state
        if job.state.status not in (JobStatus.SUBMITTED, JobStatus.RUNNING):
            return self.conflict(f"Job '{request.job_id}' is in '{job.state.status}' state and cannot be cancelled")

        # Cancel
        job.cancel()
        await self._repository.update_async(job)

        # Request cancellation in executor
        self._executor.request_cancel(request.job_id)

        return self.no_content()
