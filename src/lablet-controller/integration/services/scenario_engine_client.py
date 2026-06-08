"""Scenario Engine client — submits automation jobs and receives callbacks.

Calls the Scenario Engine REST API to submit jobs (POST /api/v1/jobs),
query job status (GET /api/v1/jobs/{job_id}), and cancel jobs (DELETE /api/v1/jobs/{job_id}).

The lablet-controller provides its own callback_url so the Scenario Engine
can deliver CloudEvent notifications (started, progress, completed, failed)
back to this service.

ADR-044: SE↔LCM Integration.
"""

import logging
from dataclasses import dataclass, field
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
class ContentSyncResult:
    """Result from a `POST /api/v1/content/sync` call to the Scenario Engine.

    Phase 2 (AD-CSI-003 / G-02): wraps SE's synchronous-from-HTTP-perspective
    response — SE downloads, extracts, validates, persists, and supersedes
    inside the request, then returns the new (or refreshed) PodDefinition id.

    Attributes:
        pod_definition_id: SE's PodDefinition aggregate id (used by CPA as
            ``pod_definition_ref.definition_id``).
        version: PodDefinition version string (echoed from the request — SE's
            HTTP response does not include it today).
        status: Aggregate status from SE's response — typically
            ``"ready"`` for a successful sync.
        content_hash: SHA-256 of the source package as SE computed it.
        pod_type: Detected pod type string (e.g. ``"cml_on_aws"``) as SE
            computed it via :class:`PodTypeDetector` (AD-CSI-002).
        message: Optional human-readable note (e.g. "already READY").
        superseded_ids: List of PodDefinition ids that SE marked SUPERSEDED
            as a result of this sync (same ``(name, pod_type)`` but different
            content_hash). May be empty.
    """

    pod_definition_id: str
    version: str
    status: str
    content_hash: str
    pod_type: str | None = None
    message: str | None = None
    superseded_ids: list[str] = field(default_factory=list)


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
        metadata: dict[str, Any] | None = None,
    ) -> JobSubmissionResult:
        """Submit a new automation job to the Scenario Engine.

        Args:
            scenario_name: Name of the scenario to execute (e.g., "lab_instantiate").
            input_data: Input parameters for the scenario.
            scenario_version: Version of the scenario (default: "v1").
            pod_definition_id: Reference to PodDefinition content in SE.
            callback_url: Override callback URL (default: client-level callback_url).
            metadata: Phase 3 / AD-CSI-017 — opaque dict forwarded to SE's
                ``SubmitJobCommand.metadata`` and round-tripped onto the
                CloudEvent payload as ``data.metadata``. Tier-B step handlers
                use this to ferry ``lablet_session_id`` / ``step_name`` /
                ``step_correlation_id`` so the lablet-controller's
                ``events_controller`` can route resume/fail commands back to
                the suspended pipeline step. SE versions prior to AD-CSI-017
                silently ignore the field.

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
        if metadata:
            payload["metadata"] = metadata

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
    # Content Sync (Phase 2 / G-02 — AD-CSI-003 + AD-CSI-014)
    # =========================================================================

    async def sync_content(
        self,
        *,
        source_uri: str,
        name: str,
        version: str = "v1",
        content_hash: str | None = None,
        pod_type: str | None = None,
        force: bool = False,
        definition_id: str | None = None,
        timeout: float = 60.0,
    ) -> ContentSyncResult:
        """Trigger a PodDefinition content sync in the Scenario Engine.

        POSTs to ``{base_url}/api/v1/content/sync`` and returns the
        ``ContentSyncResult`` from the response body. SE downloads the package
        from ``source_uri``, extracts PAv1, validates, and persists the
        PodDefinition aggregate before responding (202 Accepted).

        Defense-in-depth (AD-CSI-002): ``content_hash`` and ``pod_type`` are
        currently advisory — SE recomputes both from the package itself. They
        are accepted for forward compatibility but ignored by SE today.

        Args:
            source_uri: BlobStorage / S3 URI of the content package
                (e.g. ``s3://lablets/<bucket>/<key>``).
            name: PodDefinition name (required when SE has to create a new
                aggregate; ignored when ``definition_id`` is provided and
                already exists).
            version: PodDefinition version (default ``"v1"``).
            content_hash: Advisory SHA-256 the caller computed (SE recomputes).
            pod_type: Advisory detected pod type (SE recomputes).
            force: If ``True``, SE re-syncs even when the aggregate is already
                READY with a matching hash.
            definition_id: Optional existing PodDefinition id to refresh.
            timeout: HTTP timeout (seconds) — content sync can be slow because
                SE downloads + extracts inline.

        Returns:
            ContentSyncResult with SE's ``definition_id``, status, content_hash,
            pod_type, and any superseded_ids.

        Raises:
            ScenarioEngineError: On non-2xx response or connection failure.
        """
        payload: dict[str, Any] = {
            "source_uri": source_uri,
            "name": name,
            "version": version,
            "force": force,
        }
        # SE's HTTP DTO currently does not declare these but Pydantic v2's
        # default model config ignores unknowns — sending them is safe and
        # forward-compatible (SE may promote them to first-class fields).
        if content_hash:
            payload["content_hash"] = content_hash
        if pod_type:
            payload["pod_type"] = pod_type
        if definition_id:
            payload["definition_id"] = definition_id

        logger.info(
            "Submitting content sync to SE: name=%s version=%s source_uri=%s force=%s",
            name,
            version,
            source_uri,
            force,
        )

        try:
            response = await self._http.post(
                f"{self._base_url}/api/v1/content/sync",
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            error_body: dict[str, Any] | None = None
            try:
                error_body = e.response.json()
            except Exception:  # nosec B110: best-effort error body extraction
                pass
            raise ScenarioEngineError(
                f"Content sync failed: {e.response.status_code}",
                status_code=e.response.status_code,
                response=error_body,
            ) from e
        except httpx.RequestError as e:
            raise ScenarioEngineError(f"Connection to Scenario Engine failed: {e}") from e

        data = response.json()
        result = ContentSyncResult(
            pod_definition_id=data.get("definition_id", ""),
            version=version,
            status=data.get("status", "unknown"),
            content_hash=data.get("content_hash", content_hash or ""),
            pod_type=data.get("pod_type", pod_type),
            message=data.get("message"),
            superseded_ids=list(data.get("superseded_ids", []) or []),
        )

        logger.info(
            "Content sync acknowledged: pod_definition_id=%s status=%s superseded=%d",
            result.pod_definition_id,
            result.status,
            len(result.superseded_ids),
        )
        return result

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
