"""SubmitJobCommand — Submit a new automation job for execution.

Self-contained CQRS command: request class + handler in same file.
"""

import logging
from dataclasses import dataclass
from typing import Any

from domain.entities.job import Job
from domain.repositories.job_repository import JobRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

from application.dtos.job_dto import JobSubmittedDto
from application.services.job_execution_service import JobExecutionService
from application.services.scenario_registry import get_all_scenarios

logger = logging.getLogger(__name__)


@dataclass
class SubmitJobCommand(Command[OperationResult[JobSubmittedDto]]):
    """Command to submit a new automation job.

    Attributes:
        scenario_name: Name of the scenario to execute.
        scenario_version: Version of the scenario (e.g. "v1").
        input_data: Input parameters for the scenario.
        callback_url: CloudEvents sink URL for progress/completion notifications.
        pod_definition_id: Reference to the PodDefinition containing content.
    """

    scenario_name: str = ""
    scenario_version: str = "v1"
    input_data: dict[str, Any] | None = None
    callback_url: str | None = None
    pod_definition_id: str | None = None


class SubmitJobCommandHandler(CommandHandler[SubmitJobCommand, OperationResult[JobSubmittedDto]]):
    """Handler for SubmitJobCommand.

    Validates input, creates a Job entity, persists, enqueues for execution,
    and returns submitted status.
    """

    def __init__(self, job_repository: JobRepository, job_execution_service: JobExecutionService):
        self._repository = job_repository
        self._executor = job_execution_service

    async def handle_async(self, request: SubmitJobCommand) -> OperationResult[JobSubmittedDto]:
        """Handle job submission."""
        if not request.scenario_name:
            return self.bad_request("scenario_name is required")

        # Validate scenario exists in registry
        registry = get_all_scenarios()
        key = f"{request.scenario_name}@{request.scenario_version}"
        if key not in registry:
            return self.bad_request(f"Scenario '{key}' not found in registry")

        # Create Job entity
        job = Job.create(
            scenario_name=request.scenario_name,
            scenario_version=request.scenario_version,
            input_data=request.input_data,
            callback_url=request.callback_url,
            pod_definition_id=request.pod_definition_id,
        )

        # Persist
        await self._repository.add_async(job)

        # Enqueue for execution
        self._executor.enqueue_job(job.id())

        return self.accepted(
            JobSubmittedDto(
                id=job.id(),
                status="submitted",
                stream_url=None,
            )
        )
