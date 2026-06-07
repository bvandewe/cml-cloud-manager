"""Scenario Engine client — submits automation jobs and receives callbacks.

Calls the Scenario Engine REST API to submit jobs (POST /api/v1/jobs),
query job status (GET /api/v1/jobs/{job_id}), and cancel jobs (DELETE /api/v1/jobs/{job_id}).

The lablet-controller provides its own callback_url so the Scenario Engine
can deliver CloudEvent notifications (started, progress, completed, failed)
back to this service.

ADR-044: SE↔LCM Integration.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from neuroglia.dependency_injection import ServiceCollection
    from neuroglia.dependency_injection.service_provider import ServiceProviderBase

logger = logging.getLogger(__name__)


class ScenarioEngineError(Exception):
    """Error from the Scenario Engine service."""

    def __init__(self, message: str, status_code: int | None = None, response: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response


@dataclass
class JobSubmissionResult:
    """Result from submitting a job to the Scenario Engine."""

    job_id: str
    status: str
    scenario_name: str
    scenario_version: str
    stream_url: str | None = None


@dataclass
class JobStatusResult:
    """Result from querying job status."""

    job_id: str
    status: str
    scenario_name: str
    progress_pct: int
    progress_message: str | None = None
    output_data: dict[str, Any] | None = None
    error_message: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class ScenarioEngineClient:
    """Client for the Scenario Engine service.

    Submits automation jobs (lab instantiation, teardown, evidence collection)
    and queries their status. Provides callback_url for CloudEvent delivery.

    Configuration:
        SCENARIO_ENGINE_URL: Service base URL (e.g., http://scenario-engine:8083)
        SCENARIO_ENGINE_CALLBACK_URL: This service's CloudEvent ingestion URL
    """

    def __init__(
        self,
        base_url: str,
        callback_url: str | None = None,
    ) -> None:
        """Initialize the Scenario Engine client.

        Args:
            base_url: Scenario Engine service base URL.
            callback_url: URL where SE should deliver CloudEvent callbacks.
        """
        self._base_url = base_url.rstrip("/")
        self._callback_url = callback_url
        self._http = httpx.AsyncClient(timeout=30.0)

    async def submit_job(
        self,
        scenario_name: str,
        input_data: dict[str, Any] | None = None,
        scenario_version: str = "v1",
        pod_definition_id: str | None = None,
        callback_url: str | None = None,
    ) -> JobSubmissionResult:
        """Submit a new automation job to the Scenario Engine.

        Args:
            scenario_name: Name of the scenario to execute (e.g., "lab_instantiate").
            input_data: Input parameters for the scenario.
            scenario_version: Version of the scenario (default: "v1").
            pod_definition_id: Reference to PodDefinition content in SE.
            callback_url: Override callback URL (default: client-level callback_url).

        Returns:
            JobSubmissionResult with job_id and initial status.

        Raises:
            ScenarioEngineError: On non-2xx response.
        """
        effective_callback = callback_url or self._callback_url

        payload: dict[str, Any] = {
            "scenario_name": scenario_name,
            "scenario_version": scenario_version,
        }
        if input_data:
            payload["input_data"] = input_data
        if effective_callback:
            payload["callback_url"] = effective_callback
        if pod_definition_id:
            payload["pod_definition_id"] = pod_definition_id

        logger.info(f"Submitting job: scenario={scenario_name}@{scenario_version}, callback={effective_callback}")

        try:
            response = await self._http.post(
                f"{self._base_url}/api/v1/jobs",
                json=payload,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            error_body = None
            try:
                error_body = e.response.json()
            except Exception:  # nosec B110: best-effort error body extraction
                pass
            raise ScenarioEngineError(
                f"Job submission failed: {e.response.status_code}",
                status_code=e.response.status_code,
                response=error_body,
            ) from e
        except httpx.RequestError as e:
            raise ScenarioEngineError(f"Connection to Scenario Engine failed: {e}") from e

        data = response.json()
        result = JobSubmissionResult(
            job_id=data.get("job_id", ""),
            status=data.get("status", "submitted"),
            scenario_name=data.get("scenario_name", scenario_name),
            scenario_version=data.get("scenario_version", scenario_version),
            stream_url=data.get("stream_url"),
        )

        logger.info(f"Job submitted: job_id={result.job_id}, status={result.status}")
        return result

    async def get_job_status(self, job_id: str) -> JobStatusResult:
        """Query the status of a submitted job.

        Args:
            job_id: The job identifier returned by submit_job.

        Returns:
            JobStatusResult with current progress and state.

        Raises:
            ScenarioEngineError: On non-2xx response.
        """
        try:
            response = await self._http.get(f"{self._base_url}/api/v1/jobs/{job_id}")
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise ScenarioEngineError(
                f"Job status query failed for {job_id}: {e.response.status_code}",
                status_code=e.response.status_code,
            ) from e
        except httpx.RequestError as e:
            raise ScenarioEngineError(f"Connection to Scenario Engine failed: {e}") from e

        data = response.json()
        return JobStatusResult(
            job_id=data.get("job_id", job_id),
            status=data.get("status", "unknown"),
            scenario_name=data.get("scenario_name", ""),
            progress_pct=data.get("progress_pct", 0),
            progress_message=data.get("progress_message"),
            output_data=data.get("output_data"),
            error_message=data.get("error_message"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
        )

    async def cancel_job(self, job_id: str) -> None:
        """Cancel a running job.

        Args:
            job_id: The job identifier to cancel.

        Raises:
            ScenarioEngineError: On non-2xx response.
        """
        try:
            response = await self._http.delete(f"{self._base_url}/api/v1/jobs/{job_id}")
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise ScenarioEngineError(
                f"Job cancellation failed for {job_id}: {e.response.status_code}",
                status_code=e.response.status_code,
            ) from e
        except httpx.RequestError as e:
            raise ScenarioEngineError(f"Connection to Scenario Engine failed: {e}") from e

        logger.info(f"Job cancelled: job_id={job_id}")

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    # =========================================================================
    # DI Configuration
    # =========================================================================

    @classmethod
    def configure(
        cls,
        services: "ServiceCollection",
        base_url: str,
        callback_url: str | None = None,
    ) -> None:
        """Register ScenarioEngineClient as singleton in DI container.

        Args:
            services: Neuroglia service collection.
            base_url: Scenario Engine service base URL.
            callback_url: URL for CloudEvent callbacks to this service.
        """

        def factory(sp: "ServiceProviderBase") -> "ScenarioEngineClient":
            return cls(base_url=base_url, callback_url=callback_url)

        services.add_singleton(cls, implementation_factory=factory)
