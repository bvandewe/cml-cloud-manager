"""Jobs Controller — submit, query, and cancel automation jobs.

Endpoints:
- POST /api/v1/jobs — Submit a new automation job
- GET /api/v1/jobs/{job_id} — Get job status and progress
- DELETE /api/v1/jobs/{job_id} — Cancel a running job
"""

import logging
from typing import Any

from application.commands.cancel_job_command import CancelJobCommand
from application.commands.submit_job_command import SubmitJobCommand
from application.queries.get_job_query import GetJobQuery
from classy_fastapi.decorators import delete, get, post
from classy_fastapi.routable import Routable
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator
from neuroglia.mvc import ControllerBase
from neuroglia.mvc.controller_base import generate_unique_id_function
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SubmitJobRequest(BaseModel):
    """Request model for job submission."""

    scenario_name: str = Field(..., min_length=1, description="Name of the scenario to execute")
    scenario_version: str = Field(default="v1", description="Version of the scenario")
    input_data: dict[str, Any] | None = Field(default=None, description="Input parameters for the scenario")
    callback_url: str | None = Field(default=None, description="CloudEvents sink URL for notifications")
    pod_definition_id: str | None = Field(default=None, description="Reference to PodDefinition content")


class JobsController(ControllerBase):
    """Controller for job submission and lifecycle management.

    Routes mounted at /v1/jobs under the API sub-app (/api/v1/jobs/*).
    Uses CQRS pattern: commands via mediator for mutations, queries for reads.
    """

    def __init__(self, service_provider: ServiceProviderBase, mapper: Mapper, mediator: Mediator):
        self.service_provider = service_provider
        self.mapper = mapper
        self.mediator = mediator
        self.name = "Jobs"

        # Initialize ControllerBase (sets up json_serializer)
        ControllerBase.__init__(self, service_provider, mapper, mediator)

        # Override prefix with versioned path
        Routable.__init__(
            self,
            prefix="/v1/jobs",
            tags=["Jobs"],
            generate_unique_id_function=generate_unique_id_function,
        )

    @post("/", summary="Submit Job", status_code=202)
    async def submit_job(self, request: SubmitJobRequest) -> Any:
        """Submit a new automation job.

        Accepts a scenario name, input data, and optional callback URL.
        Returns immediately with a job_id for tracking.

        Returns:
            202 Accepted with job_id, status, and stream_url.
        """
        command = SubmitJobCommand(
            scenario_name=request.scenario_name,
            scenario_version=request.scenario_version,
            input_data=request.input_data,
            callback_url=request.callback_url,
            pod_definition_id=request.pod_definition_id,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @get("/{job_id}", summary="Get Job")
    async def get_job(self, job_id: str) -> Any:
        """Get job status and progress.

        Returns the current state of a job including progress percentage,
        current step, and results (if completed).
        """
        query = GetJobQuery(job_id=job_id)
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @delete("/{job_id}", summary="Cancel Job", status_code=204)
    async def cancel_job(self, job_id: str) -> Any:
        """Cancel a running job.

        Requests cancellation of a running job. The job will transition
        to CANCELLED status after the current task completes.
        """
        command = CancelJobCommand(job_id=job_id)
        result = await self.mediator.execute_async(command)
        return self.process(result)
