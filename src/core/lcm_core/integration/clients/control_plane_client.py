"""Control Plane API Client.

HTTP client for communicating with the Control Plane API service.
Used by schedulers and controllers to query and update state.

This is a shared client in lcm-core that can be used by all services.
"""

import logging
from enum import Enum
from typing import Any, TypeVar

import httpx
from neuroglia.dependency_injection.service_provider import ServiceProviderBase

from lcm_core.domain.enums import CMLWorkerStatus

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ControlPlaneApiClientError(Exception):
    """Base exception for Control Plane API errors."""

    def __init__(self, message: str, status_code: int | None = None, response: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class ControlPlaneApiClient:
    """
    HTTP client for the Control Plane API.

    Provides typed methods for querying and mutating:
    - LabletSessions (scheduling, state transitions, child entities)
    - CMLWorkers (capacity, status)
    - LabRecords (lifecycle, topology, binding)
    - LabletDefinitions
    - WorkerTemplates

    Features:
    - Automatic retry with exponential backoff
    - Connection pooling via httpx.AsyncClient
    - Request/response logging
    - Circuit breaker pattern (via tenacity)

    Usage:
        # Direct instantiation
        client = ControlPlaneApiClient(base_url="http://control-plane:8000")

        # Or via DI
        ControlPlaneApiClient.configure(builder.services, "http://control-plane:8000")
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = 30.0,
        max_retries: int = 3,
        api_key: str | None = None,
    ):
        """Initialize the Control Plane API client.

        Args:
            base_url: Base URL of the Control Plane API.
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retries for failed requests.
            api_key: Optional API key for internal authentication.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            headers = {}
            if self.api_key:
                headers["X-API-Key"] = self.api_key

            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers=headers,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Make an HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, PATCH).
            path: API path (will be appended to base_url).
            params: Query parameters.
            json: JSON body data.

        Returns:
            Parsed JSON response.

        Raises:
            ControlPlaneApiClientError: If the request fails.
        """
        client = await self._get_client()
        last_exception: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await client.request(method, path, params=params, json=json)

                if response.status_code >= 400:
                    try:
                        error_body = response.json()
                    except Exception:
                        error_body = {"detail": response.text}

                    raise ControlPlaneApiClientError(
                        f"{method} {path} failed with status {response.status_code}",
                        status_code=response.status_code,
                        response=error_body,
                    )

                if response.status_code == 204:
                    return None

                # Guard against empty response bodies (e.g., un-followed redirects)
                body = response.text
                if not body or not body.strip():
                    logger.warning(f"Empty response body from {method} {path} (status={response.status_code})")
                    return None

                return response.json()

            except httpx.TimeoutException as e:
                logger.warning(f"Request timeout (attempt {attempt + 1}/{self.max_retries + 1}): {method} {path}")
                last_exception = e
            except httpx.ConnectError as e:
                logger.warning(f"Connection error (attempt {attempt + 1}/{self.max_retries + 1}): {method} {path}")
                last_exception = e
            except ControlPlaneApiClientError:
                raise

            # Wait before retry (exponential backoff)
            if attempt < self.max_retries:
                import asyncio

                wait_time = 2**attempt  # 1, 2, 4 seconds
                await asyncio.sleep(wait_time)

        raise ControlPlaneApiClientError(f"Request failed after {self.max_retries + 1} attempts: {last_exception}")

    # =========================================================================
    # Session Operations
    # =========================================================================

    async def get_lablet_sessions(
        self,
        status: str | None = None,
        worker_id: str | None = None,
        definition_id: str | None = None,
        include_terminated: bool = False,
    ) -> list[dict[str, Any]]:
        """Get lablet sessions with optional filters.

        Uses internal API endpoint (X-API-Key auth).

        Args:
            status: Filter by status (e.g., "PENDING_SCHEDULING", "RUNNING").
            worker_id: Filter by assigned worker ID.
            definition_id: Filter by definition ID.
            include_terminated: Include terminated sessions in results.

        Returns:
            List of session dictionaries.
        """
        params: dict[str, Any] = {}
        if status:
            params["status"] = status.value if isinstance(status, Enum) else status
        if worker_id:
            params["worker_id"] = worker_id
        if definition_id:
            params["definition_id"] = definition_id
        if include_terminated:
            params["include_terminated"] = "true"

        result = await self._request("GET", "/api/internal/lablet-sessions", params=params)
        return list(result) if result else []

    async def get_lablet_session(self, session_id: str) -> dict[str, Any]:
        """Get a single lablet session by ID.

        Uses internal API endpoint (X-API-Key auth).
        """
        result = await self._request("GET", f"/api/internal/lablet-sessions/{session_id}")
        return dict(result) if result else {}

    async def get_sessions_with_imminent_deadlines(
        self,
        boot_window_minutes: int = 35,
    ) -> dict[str, Any]:
        """Get sessions with imminent timeslot deadlines.

        Returns a dict with two lists:
        - approaching_start: SCHEDULED sessions within the boot window.
        - past_end: Non-terminal sessions past their timeslot_end.

        Used by TimeslotWatcherService (AD-TIMESLOT-001).

        Args:
            boot_window_minutes: Look-ahead window for approaching sessions.

        Returns:
            Dict with 'approaching_start' and 'past_end' lists.
        """
        params: dict[str, Any] = {"boot_window_minutes": boot_window_minutes}
        result = await self._request("GET", "/api/internal/lablet-sessions/imminent-deadlines", params=params)
        return dict(result) if result else {"approaching_start": [], "past_end": []}

    async def schedule_session(
        self,
        session_id: str,
        worker_id: str,
        allocated_ports: dict[str, int],
        lab_record_id: str,
        scheduled_by: str = "resource-scheduler",
    ) -> dict[str, Any]:
        """Assign a worker to a session (scheduling decision).

        Phase 7G: Replaces schedule_instance(). Now includes port allocation
        and lab record binding (absorbed from allocate_ports and bind_lab_to_lablet).

        Args:
            session_id: ID of the session to schedule.
            worker_id: ID of the worker to assign.
            allocated_ports: Port allocation map (port_name -> port_number).
            lab_record_id: Lab record to bind to this session.
            scheduled_by: Identity of the scheduling agent.

        Returns:
            Updated session data.
        """
        result = await self._request(
            "POST",
            f"/api/internal/lablet-sessions/{session_id}/schedule",
            json={
                "worker_id": worker_id,
                "allocated_ports": allocated_ports,
                "lab_record_id": lab_record_id,
                "scheduled_by": scheduled_by,
            },
        )
        return dict(result) if result else {}

    async def transition_session(
        self,
        session_id: str,
        new_status: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Transition a session to a new status.

        Args:
            session_id: ID of the session.
            new_status: Target status.
            reason: Optional reason for the transition.

        Returns:
            Updated session data.
        """
        result = await self._request(
            "POST",
            f"/api/internal/lablet-sessions/{session_id}/transition",
            json={"status": new_status, "reason": reason},
        )
        return dict(result) if result else {}

    async def report_resource_observations(
        self,
        session_id: str,
        observed_resources: dict[str, Any],
        observed_ports: dict[str, int],
    ) -> dict[str, Any]:
        """Report resource observations for a session.

        Posts runtime CML resource and port observations to CPA
        for storage on the LabletSession aggregate.

        ADR-030: Resource & Port Observation — "Learn from Live"

        Args:
            session_id: ID of the session.
            observed_resources: Serialized ResourceObservation dict.
            observed_ports: Actual CML port allocations {port_name: port_number}.

        Returns:
            Response dict with observation_count and port_drift_detected.
        """
        result = await self._request(
            "POST",
            f"/api/internal/lablet-sessions/{session_id}/resource-observations",
            json={
                "observed_resources": observed_resources,
                "observed_ports": observed_ports,
            },
        )
        return dict(result) if result else {}

    async def mark_session_ready(
        self,
        session_id: str,
        user_session_id: str,
        cml_lab_id: str,
    ) -> dict[str, Any]:
        """Mark a session as READY with UserSession and CML lab info.

        Phase 7G (ADR-021): Atomically sets user_session_id + cml_lab_id
        and transitions INSTANTIATING → READY. Called by lablet-controller
        after UserSession is provisioned and lab is deployed.

        Args:
            session_id: ID of the session.
            user_session_id: ID of the provisioned UserSession child entity.
            cml_lab_id: CML lab identifier on the worker.

        Returns:
            Updated session data.
        """
        result = await self._request(
            "POST",
            f"/api/internal/lablet-sessions/{session_id}/mark-ready",
            json={"user_session_id": user_session_id, "cml_lab_id": cml_lab_id},
        )
        return dict(result) if result else {}

    async def terminate_session(
        self,
        session_id: str,
        terminated_by: str = "lablet-controller",
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Terminate a session (system-initiated, internal).

        AD-PIPELINE-008: Used by lablet-controller for unrecoverable
        situations such as max pipeline retries exhausted, timeslot
        expiry, or admin force-kill.

        Reuses the existing TerminateLabletSessionCommand which handles
        port release, capacity release, and domain events.

        Args:
            session_id: ID of the session to terminate.
            terminated_by: Identity of the terminating agent.
            reason: Optional reason for termination.

        Returns:
            Response dict with termination details.
        """
        result = await self._request(
            "POST",
            f"/api/internal/lablet-sessions/{session_id}/terminate",
            json={"terminated_by": terminated_by, "reason": reason},
        )
        return dict(result) if result else {}

    async def start_instantiation(
        self,
        session_id: str,
    ) -> dict[str, Any]:
        """Begin lab instantiation for a session (SCHEDULED → INSTANTIATING).

        Phase 7G: Called by lablet-controller when it begins lab import/startup
        on the worker.

        Args:
            session_id: ID of the session.

        Returns:
            Updated session data.
        """
        result = await self._request(
            "POST",
            f"/api/internal/lablet-sessions/{session_id}/start-instantiation",
        )
        return dict(result) if result else {}

    # -------------------------------------------------------------------------
    # Pipeline Progress Operations (ADR-034)
    # -------------------------------------------------------------------------

    async def update_pipeline_progress(
        self,
        session_id: str,
        pipeline_name: str,
        step_name: str,
        step_status: str,
        result_data: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Update a pipeline step on a session's pipeline progress.

        ADR-034 Sprint E: Supports all pipeline types
        (instantiate, teardown, collect_evidence, compute_grading).

        Args:
            session_id: ID of the session.
            pipeline_name: Pipeline type (e.g., "instantiate", "teardown").
            step_name: Pipeline step name (e.g., "stop_lab", "wipe_lab").
            step_status: Step status ("completed", "failed", "skipped").
            result_data: Step-specific evidence dict.
            error: Error message if step_status is "failed".

        Returns:
            Updated progress summary.
        """
        body: dict[str, Any] = {
            "pipeline_name": pipeline_name,
            "step_name": step_name,
            "step_status": step_status,
        }
        if result_data is not None:
            body["result_data"] = result_data
        if error is not None:
            body["error"] = error

        result = await self._request(
            "POST",
            f"/api/internal/lablet-sessions/{session_id}/pipeline-progress",
            json=body,
        )
        return dict(result) if result else {}

    async def set_session_desired_status(
        self,
        session_id: str,
        desired_status: str,
        requested_by: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Set the desired lifecycle state (spec) for a LabletSession.

        ADR-034 Sprint E / ADR-015 pattern: Follows the Kubernetes-like
        reconciliation model. The desired_status triggers etcd watch-based
        reconciliation in the lablet-controller.

        Args:
            session_id: ID of the session.
            desired_status: Target lifecycle state ("running", "stopped", "terminated").
            requested_by: User or system requesting the change.
            reason: Optional reason for the change.

        Returns:
            Dict with session_id, desired_status, and changed flag.
        """
        body: dict[str, Any] = {"desired_status": desired_status}
        if requested_by is not None:
            body["requested_by"] = requested_by
        if reason is not None:
            body["reason"] = reason

        result = await self._request(
            "POST",
            f"/api/internal/lablet-sessions/{session_id}/desired-status",
            json=body,
        )
        return dict(result) if result else {}

    async def allocate_lab_record_ports(
        self,
        lab_record_id: str,
        worker_id: str,
    ) -> dict[str, Any]:
        """Allocate ports from worker pool for a LabRecord.

        ADR-031 / AD-PORT-001: Port allocation is a LabRecord topology
        concern. Ports are allocated via PortAllocationService (etcd),
        keyed by lab_record_id, then persisted on the LabRecord aggregate.

        Called by lablet-controller during the ``ports_alloc`` pipeline step.
        Idempotent — returns existing allocation if ports already allocated.

        Args:
            lab_record_id: LabRecord aggregate ID (owner of the ports).
            worker_id: Worker hosting the lab (determines port pool).

        Returns:
            Dict with ``allocated_ports`` map and ``already_allocated`` flag.
        """
        result = await self._request(
            "POST",
            "/api/internal/lablet-sessions/allocate-lab-record-ports",
            json={
                "lab_record_id": lab_record_id,
                "worker_id": worker_id,
            },
        )
        return dict(result) if result else {}

    async def bind_lab_to_session(
        self,
        session_id: str,
        worker_id: str,
        lab_record_id: str,
        cml_lab_id: str | None = None,
        cml_lab_title: str | None = None,
    ) -> dict[str, Any]:
        """Bind a LabRecord to a session during the instantiation pipeline.

        ADR-031 / AD-BIND-001: Creates a LabRunRecord on the LabRecord
        (runtime tracking — NO port fields), sets active_lablet_session_id,
        and denormalizes ``allocated_ports`` from the LabRecord onto the
        LabletSession.

        Called by lablet-controller during the ``lab_binding`` pipeline step.

        Args:
            session_id: ID of the session to bind.
            worker_id: Worker hosting the lab.
            lab_record_id: LabRecord aggregate ID to bind.
            cml_lab_id: CML lab identifier on the worker.
            cml_lab_title: CML lab title for display.

        Returns:
            Dict with ``lab_record_id``, ``run_id``, and ``allocated_ports``.
        """
        body: dict[str, Any] = {
            "worker_id": worker_id,
            "lab_record_id": lab_record_id,
        }
        if cml_lab_id is not None:
            body["cml_lab_id"] = cml_lab_id
        if cml_lab_title is not None:
            body["cml_lab_title"] = cml_lab_title
        result = await self._request(
            "POST",
            f"/api/internal/lablet-sessions/{session_id}/bind-lab",
            json=body,
        )
        return dict(result) if result else {}

    async def expire_session(
        self,
        session_id: str,
        reason: str = "timeslot_expired",
    ) -> dict[str, Any]:
        """Expire a session due to timeslot exhaustion.

        ADR-031 / AD-TIMESLOT-001: Expires the session and triggers
        downstream cleanup — unbind LabRecord, close LabRunRecord,
        release capacity. Ports are NOT released (they belong to the
        LabRecord and persist for lab reuse).

        Called by lablet-controller when the reconciler detects that
        a session's timeslot has expired.

        Args:
            session_id: ID of the session to expire.
            reason: Expiry reason (default: "timeslot_expired").

        Returns:
            Dict with ``session_id`` and ``status``.
        """
        result = await self._request(
            "POST",
            f"/api/internal/lablet-sessions/{session_id}/expire",
            json={"reason": reason},
        )
        return dict(result) if result else {}

    # -------------------------------------------------------------------------
    # Session Child Entity Operations
    # -------------------------------------------------------------------------

    async def create_user_session(
        self,
        session_id: str,
        lds_session_id: str,
        lds_login_url: str,
        cml_lab_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a UserSession child entity on a lablet session.

        Phase 7G: Called by lablet-controller after provisioning an LDS
        session for a user. The UserSession tracks the individual user's
        connection to the CML lab.

        Args:
            session_id: Parent LabletSession ID.
            lds_session_id: LDS session identifier.
            lds_login_url: JWT-signed URL for lablet access.
            cml_lab_id: Optional CML lab identifier.

        Returns:
            Created UserSession data including user_session_id.
        """
        body: dict[str, Any] = {
            "lds_session_id": lds_session_id,
            "lds_login_url": lds_login_url,
        }
        if cml_lab_id is not None:
            body["cml_lab_id"] = cml_lab_id
        result = await self._request(
            "POST",
            f"/api/internal/lablet-sessions/{session_id}/user-session",
            json=body,
        )
        return dict(result) if result else {}

    async def create_grading_session(
        self,
        session_id: str,
        grading_session_id: str,
        grading_engine_url: str | None = None,
    ) -> dict[str, Any]:
        """Create a GradingSession child entity on a lablet session.

        Phase 7G: Called by lablet-controller when grading is initiated
        for a session. The GradingSession tracks the grading lifecycle.

        Args:
            session_id: Parent LabletSession ID.
            grading_session_id: External grading session identifier.
            grading_engine_url: URL of the grading engine instance.

        Returns:
            Created GradingSession data.
        """
        body: dict[str, Any] = {
            "grading_session_id": grading_session_id,
        }
        if grading_engine_url is not None:
            body["grading_engine_url"] = grading_engine_url
        result = await self._request(
            "POST",
            f"/api/internal/lablet-sessions/{session_id}/grading-session",
            json=body,
        )
        return dict(result) if result else {}

    async def create_score_report(
        self,
        session_id: str,
        score: float,
        max_score: float,
        grade_result: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a ScoreReport child entity on a lablet session.

        Phase 7G: Called by lablet-controller after receiving grading
        results from the grading engine. Records the final score.

        Args:
            session_id: Parent LabletSession ID.
            score: Achieved score.
            max_score: Maximum possible score.
            grade_result: Grade result string (e.g., "PASS", "FAIL").
            details: Optional detailed scoring breakdown.

        Returns:
            Created ScoreReport data.
        """
        body: dict[str, Any] = {
            "score": score,
            "max_score": max_score,
        }
        if grade_result is not None:
            body["grade_result"] = grade_result
        if details is not None:
            body["details"] = details
        result = await self._request(
            "POST",
            f"/api/internal/lablet-sessions/{session_id}/score-report",
            json=body,
        )
        return dict(result) if result else {}

    # =========================================================================
    # Worker Operations
    # =========================================================================

    async def get_workers(
        self,
        status: CMLWorkerStatus | str | None = None,
        aws_region: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get CML workers with optional filters.

        Uses the internal API endpoint for service-to-service calls.

        Args:
            status: Filter by status (e.g., CMLWorkerStatus.RUNNING or "RUNNING").
            aws_region: Filter by AWS region (e.g., "us-east-1").

        Returns:
            List of worker dictionaries.
        """
        params = {}
        if status:
            params["status"] = status.value if isinstance(status, Enum) else status
        if aws_region:
            params["aws_region"] = aws_region

        result = await self._request("GET", "/api/internal/workers", params=params)
        return list(result) if result else []

    async def get_worker(self, worker_id: str) -> dict[str, Any]:
        """Get a single worker by ID.

        Uses the internal API endpoint for service-to-service calls.
        """
        result = await self._request("GET", f"/api/internal/workers/{worker_id}")
        return dict(result) if result else {}

    async def get_worker_capacity(self, worker_id: str) -> dict[str, Any]:
        """Get capacity details for a worker.

        Returns:
            Capacity info including available resources and port ranges.
        """
        result = await self._request("GET", f"/api/internal/workers/{worker_id}/capacity")
        return dict(result) if result else {}

    async def request_scale_up(self, template_name: str, reason: str) -> dict[str, Any]:
        """Request a new worker to be provisioned.

        Args:
            template_name: Name of the worker template to use.
            reason: Reason for the scale-up request.

        Returns:
            Scale-up request details including new worker ID.
        """
        result = await self._request(
            "POST",
            "/api/internal/workers/scale-up",
            json={"template": template_name, "reason": reason},
        )
        return dict(result) if result else {}

    async def drain_worker(
        self,
        worker_id: str,
        reason: str = "scale_down",
        requested_by: str = "worker-controller",
    ) -> dict[str, Any]:
        """Request graceful drain of a worker.

        Sets worker to DRAINING status. The worker-controller will
        stop accepting new lab assignments and wait for active labs
        to complete before stopping the instance.

        Args:
            worker_id: ID of the worker to drain.
            reason: Reason for draining (e.g., "scale_down", "maintenance").
            requested_by: System requesting the drain.

        Returns:
            Drain status info.
        """
        result = await self._request(
            "POST",
            f"/api/internal/workers/{worker_id}/drain",
            params={"reason": reason, "requested_by": requested_by},
        )
        return dict(result) if result else {}

    async def mark_worker_terminated(
        self,
        worker_id: str,
        reason: str = "orphan_detection",
        terminated_by: str = "worker-controller",
    ) -> dict[str, Any]:
        """Mark a worker as terminated (database-only, no AWS calls).

        Used when worker-controller detects an orphaned worker
        (EC2 instance no longer exists). Per ADR-015, this does NOT
        call AWS - it only updates the database.

        Args:
            worker_id: ID of the worker to mark as terminated.
            reason: Reason for termination (e.g., "orphan_detection", "manual_cleanup").
            terminated_by: System/user that detected termination.

        Returns:
            Termination result with worker info.
        """
        result = await self._request(
            "POST",
            f"/api/internal/workers/{worker_id}/terminate",
            json={
                "reason": reason,
                "terminated_by": terminated_by,
            },
        )
        return dict(result) if result else {}

    async def update_worker_status(
        self,
        worker_id: str,
        status: CMLWorkerStatus | str,
        ec2_instance_id: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update worker status and optionally EC2 instance ID and metrics.

        Args:
            worker_id: ID of the worker.
            status: New status (CMLWorkerStatus enum or string).
            ec2_instance_id: EC2 instance ID (set during provisioning).
            metrics: Optional metrics data.

        Returns:
            Updated worker data.
        """
        # Normalize to enum for reliable comparison
        try:
            status_enum = CMLWorkerStatus(status)
        except ValueError:
            status_enum = None

        # For TERMINATED status, use the new dedicated endpoint
        if status_enum == CMLWorkerStatus.TERMINATED:
            return await self.mark_worker_terminated(
                worker_id=worker_id,
                reason="status_update",
                terminated_by="worker-controller",
            )

        body: dict[str, Any] = {"status": status.value if isinstance(status, Enum) else status}
        if ec2_instance_id:
            body["ec2_instance_id"] = ec2_instance_id
        if metrics:
            body["metrics"] = metrics

        result = await self._request(
            "POST",
            f"/api/internal/workers/{worker_id}/status",
            json=body,
        )
        return dict(result) if result else {}

    async def bulk_import_workers(
        self,
        discovered_instances: list[dict[str, Any]],
        aws_region: str,
        source: str = "worker-controller",
    ) -> dict[str, Any]:
        """Submit discovered EC2 instances for bulk import.

        Called by worker-controller after discovering EC2 instances.
        Control Plane API will filter and persist new workers.

        Args:
            discovered_instances: List of discovered EC2 instance data, each containing:
                - instance_id: EC2 instance ID
                - state: Current EC2 state
                - public_ip: Public IP address (optional)
                - private_ip: Private IP address (optional)
                - instance_type: EC2 instance type (optional)
                - launch_time: Instance launch time (optional)
            aws_region: AWS region where instances were discovered.
            source: Source of the import (e.g., "worker-controller").

        Returns:
            Import results including:
            - total_found: Number of instances submitted
            - total_imported: Number of new workers created
            - total_skipped: Number of instances already registered
            - imported: List of newly imported worker IDs
            - skipped: List of skipped instances with reasons
        """
        body: dict[str, Any] = {
            "discovered_instances": discovered_instances,
            "aws_region": aws_region,
            "source": source,
        }

        result = await self._request(
            "POST",
            "/api/internal/workers/bulk-import",
            json=body,
        )
        return dict(result) if result else {}

    async def report_worker_metrics(
        self,
        worker_id: str,
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        """Report worker metrics from reconciler.

        This is called by the WorkerReconciler during metrics collection.
        It reports EC2 (CloudWatch) and CML system stats to Control Plane API.

        Args:
            worker_id: ID of the worker.
            metrics: Metrics data containing:
                - collected_at: ISO 8601 timestamp
                - ec2: EC2/CloudWatch metrics (cpu_utilization, network_in/out)
                - cml: CML system stats (cpu_percent, memory_percent, disk_percent)

        Returns:
            Updated worker data.
        """
        result = await self._request(
            "POST",
            f"/api/internal/workers/{worker_id}/metrics",
            json=metrics,
        )
        return dict(result) if result else {}

    async def report_worker_cml_data(
        self,
        worker_id: str,
        cml_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Report CML system data (version, system_info, health, license) for a worker.

        Called by worker-controller during reconciliation to report CML application-level
        data that is separate from utilization metrics. This data includes CML version,
        readiness state, system_info (compute nodes), system_health, and license info.

        Args:
            worker_id: ID of the worker.
            cml_data: CML data containing:
                - cml_version: CML version string (e.g., "2.9.0")
                - ready: Whether CML is ready
                - system_info: Full system information dict from CML API
                - system_health: Health check data from CML API
                - license_info: License information from CML API
                - uptime_seconds: CML uptime
                - labs_count: Number of labs

        Returns:
            Acknowledgment data.
        """
        result = await self._request(
            "POST",
            f"/api/internal/workers/{worker_id}/cml-data",
            json=cml_data,
        )
        return dict(result) if result else {}

    async def update_worker_ec2_details(
        self,
        worker_id: str,
        ec2_details: dict[str, Any],
    ) -> dict[str, Any]:
        """Update EC2 instance details (AMI info, IPs, instance type) for a worker.

        Called by worker-controller after provisioning or on-demand refresh to report
        EC2 instance metadata including AMI details.

        Args:
            worker_id: ID of the worker.
            ec2_details: EC2 details containing:
                - public_ip: Public IP address
                - private_ip: Private IP address
                - instance_type: EC2 instance type
                - ami_id: AMI image ID
                - ami_name: AMI name
                - ami_description: AMI description
                - ami_creation_date: AMI creation date string

        Returns:
            Acknowledgment data.
        """
        result = await self._request(
            "POST",
            f"/api/internal/workers/{worker_id}/ec2-details",
            json=ec2_details,
        )
        return dict(result) if result else {}

    async def record_worker_activity(
        self,
        worker_id: str,
        activity_type: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record worker activity for idle detection.

        Args:
            worker_id: ID of the worker.
            activity_type: Type of activity (e.g., "lab_started", "api_call").
            details: Optional activity details.

        Returns:
            Updated activity tracking data.
        """
        body: dict[str, Any] = {"activity_type": activity_type}
        if details:
            body["details"] = details

        result = await self._request(
            "POST",
            f"/api/internal/workers/{worker_id}/activity",
            json=body,
        )
        return dict(result) if result else {}

    async def detect_worker_idle(
        self,
        worker_id: str,
        force_check: bool = False,
        raw_telemetry_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Execute idle detection for a worker.

        Orchestrates the idle detection workflow:
        1. Process telemetry events (provided by caller per ADR-015)
        2. Update worker activity state
        3. Check idle status and eligibility
        4. Auto-pause if conditions met

        Args:
            worker_id: ID of the worker.
            force_check: Skip next_idle_check_at validation.
            raw_telemetry_events: Raw CML telemetry events fetched by caller.
                Per ADR-015, CPA does not call CML API directly.

        Returns:
            Detection results including:
            - is_idle: Whether the worker is considered idle
            - idle_minutes: Duration of idle time
            - auto_pause_triggered: Whether auto-pause was executed
            - error: Error message if detection failed
        """
        body: dict[str, Any] = {"force_check": force_check}
        if raw_telemetry_events is not None:
            body["raw_telemetry_events"] = raw_telemetry_events

        result = await self._request(
            "POST",
            f"/api/internal/workers/{worker_id}/detect-idle",
            json=body,
        )
        return dict(result) if result else {}

    async def get_worker_idle_status(
        self,
        worker_id: str,
    ) -> dict[str, Any]:
        """Get the idle status of a worker.

        Uses the internal API endpoint for service-to-service calls.

        Args:
            worker_id: ID of the worker.

        Returns:
            Idle status including:
            - is_idle: Whether the worker is considered idle
            - idle_minutes: Duration of idle time
            - eligible_for_pause: Whether the worker can be auto-paused
            - last_activity_at: Timestamp of last detected activity
        """
        result = await self._request(
            "GET",
            f"/api/internal/workers/{worker_id}/idle-status",
        )
        return dict(result) if result else {}

    async def cleanup_terminated_workers(
        self,
        retention_days: int = 30,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Cleanup terminated worker records older than retention period.

        Called by resource-scheduler's CleanupHostedService to remove
        stale TERMINATED records from the database.

        Args:
            retention_days: Number of days to retain terminated records.
            dry_run: If True, only report what would be deleted.

        Returns:
            Cleanup results including:
            - deleted_count: Number of records deleted
            - deleted_ids: List of deleted worker IDs (if dry_run=False)
            - would_delete: List of worker IDs that would be deleted (if dry_run=True)
        """
        body: dict[str, Any] = {
            "retention_days": retention_days,
            "dry_run": dry_run,
        }

        result = await self._request(
            "POST",
            "/api/internal/workers/cleanup",
            json=body,
        )
        return dict(result) if result else {}

    # =========================================================================
    # License Operations (ADR-016)
    # =========================================================================

    async def start_license_registration(
        self,
        worker_id: str,
        initiated_by: str = "worker-controller",
    ) -> dict[str, Any]:
        """Mark license registration as started.

        ADR-016: Called by worker-controller when starting CML API call.

        Args:
            worker_id: ID of the worker.
            initiated_by: Service/user that initiated the operation.

        Returns:
            Result of the operation.
        """
        body: dict[str, Any] = {"initiated_by": initiated_by}

        result = await self._request(
            "POST",
            f"/api/internal/workers/{worker_id}/license/start-registration",
            json=body,
        )
        return dict(result) if result else {}

    async def complete_license_registration(
        self,
        worker_id: str,
        registration_status: str = "COMPLETED",
        smart_account: str | None = None,
        virtual_account: str | None = None,
    ) -> dict[str, Any]:
        """Mark license registration as completed.

        ADR-016: Called by worker-controller after successful CML API call.

        Args:
            worker_id: ID of the worker.
            registration_status: CML registration status.
            smart_account: Smart Licensing account name.
            virtual_account: Virtual account name.

        Returns:
            Result of the operation.
        """
        body: dict[str, Any] = {
            "registration_status": registration_status,
            "smart_account": smart_account,
            "virtual_account": virtual_account,
        }

        result = await self._request(
            "POST",
            f"/api/internal/workers/{worker_id}/license/complete-registration",
            json=body,
        )
        return dict(result) if result else {}

    async def fail_license_registration(
        self,
        worker_id: str,
        error_message: str,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        """Mark license registration as failed.

        ADR-016: Called by worker-controller after failed CML API call.

        Args:
            worker_id: ID of the worker.
            error_message: Error message.
            error_code: Optional error code.

        Returns:
            Result of the operation.
        """
        body: dict[str, Any] = {
            "error_message": error_message,
            "error_code": error_code,
        }

        result = await self._request(
            "POST",
            f"/api/internal/workers/{worker_id}/license/fail-registration",
            json=body,
        )
        return dict(result) if result else {}

    async def start_license_deregistration(
        self,
        worker_id: str,
        initiated_by: str = "worker-controller",
    ) -> dict[str, Any]:
        """Mark license deregistration as started.

        ADR-016: Called by worker-controller when starting CML API call.

        Args:
            worker_id: ID of the worker.
            initiated_by: Service/user that initiated the operation.

        Returns:
            Result of the operation.
        """
        body: dict[str, Any] = {"initiated_by": initiated_by}

        result = await self._request(
            "POST",
            f"/api/internal/workers/{worker_id}/license/start-deregistration",
            json=body,
        )
        return dict(result) if result else {}

    async def complete_license_deregistration(
        self,
        worker_id: str,
        message: str = "Deregistration completed",
    ) -> dict[str, Any]:
        """Mark license deregistration as completed.

        ADR-016: Called by worker-controller after successful CML API call.

        Args:
            worker_id: ID of the worker.
            message: Completion message.

        Returns:
            Result of the operation.
        """
        body: dict[str, Any] = {"message": message}

        result = await self._request(
            "POST",
            f"/api/internal/workers/{worker_id}/license/complete-deregistration",
            json=body,
        )
        return dict(result) if result else {}

    async def fail_license_deregistration(
        self,
        worker_id: str,
        error_message: str,
    ) -> dict[str, Any]:
        """Mark license deregistration as failed.

        ADR-016: Called by worker-controller after failed CML API call.

        Args:
            worker_id: ID of the worker.
            error_message: Error message.

        Returns:
            Result of the operation.
        """
        body: dict[str, Any] = {"error_message": error_message}

        result = await self._request(
            "POST",
            f"/api/internal/workers/{worker_id}/license/fail-deregistration",
            json=body,
        )
        return dict(result) if result else {}

    async def get_lab_records_for_worker(
        self,
        worker_id: str,
        status: str | None = None,
        include_terminal: bool = False,
    ) -> list[dict[str, Any]]:
        """Get lab records for a specific worker.

        Phase 9 (P9-4): Called by lablet-controller's reconciler to query
        existing LabRecords for lab resolution and reuse logic.

        Args:
            worker_id: Worker aggregate ID.
            status: Optional LabRecordStatus filter (e.g., 'wiped', 'stopped').
            include_terminal: Include deleted/archived labs.

        Returns:
            List of lab record dictionaries.
        """
        params: dict[str, Any] = {"worker_id": worker_id}
        if status is not None:
            params["status"] = status.value if isinstance(status, Enum) else status
        if include_terminal:
            params["include_terminal"] = "true"
        result = await self._request("GET", "/api/internal/lab-records", params=params)
        return list(result) if result else []

    async def discover_lab_records(
        self,
        worker_id: str,
        labs: list[dict[str, Any]],
        source: str = "lab-discovery-service",
        partial_scan: bool = False,
    ) -> dict[str, Any]:
        """Discover lab records for a worker.

        Phase 8 (P8-25): Called by worker-controller or lablet-controller after
        scanning CML for labs. Creates new LabRecords, updates existing ones,
        and marks orphaned labs.

        Args:
            worker_id: ID of the worker hosting these labs.
            labs: List of lab data from CML scan.
            source: Source of the discovery.
            partial_scan: If True, skip orphan sweep (single-lab registration).

        Returns:
            Discovery results (synced, discovered, updated, orphaned, revisions_created, errors).
        """
        body: dict[str, Any] = {
            "worker_id": worker_id,
            "labs": labs,
            "source": source,
            "partial_scan": partial_scan,
        }
        result = await self._request("POST", "/api/internal/lab-records/discover", json=body)
        return dict(result) if result else {}

    async def update_lab_record_status(
        self,
        lab_record_id: str,
        new_status: str | None = None,
        cml_state: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        """Update the status of a lab record.

        Phase 8 (P8-25): Called by lablet-controller when observing CML lab
        state changes during reconciliation or polling.

        Args:
            lab_record_id: LabRecord aggregate ID.
            new_status: New LabRecordStatus (e.g., 'booted', 'stopped').
            cml_state: CML native state string.
            error_message: Error details if status indicates failure.

        Returns:
            Updated lab record summary.
        """
        body: dict[str, Any] = {}
        if new_status is not None:
            body["new_status"] = new_status
        if cml_state is not None:
            body["cml_state"] = cml_state
        if error_message is not None:
            body["error_message"] = error_message
        result = await self._request(
            "POST",
            f"/api/internal/lab-records/{lab_record_id}/status",
            json=body,
        )
        return dict(result) if result else {}

    async def update_lab_topology(
        self,
        lab_record_id: str,
        topology_data: dict[str, Any],
        change_summary: str | None = None,
    ) -> dict[str, Any]:
        """Update the topology specification of a lab record.

        Phase 8 (P8-25): Called by lablet-controller when detecting topology
        changes. Creates a new LabRevision if the topology checksum differs.

        Args:
            lab_record_id: LabRecord aggregate ID.
            topology_data: Full topology spec (nodes, links, etc.).
            change_summary: Human-readable summary of what changed.

        Returns:
            Topology update result with revision info.
        """
        body: dict[str, Any] = {"topology_data": topology_data}
        if change_summary is not None:
            body["change_summary"] = change_summary
        result = await self._request(
            "POST",
            f"/api/internal/lab-records/{lab_record_id}/topology",
            json=body,
        )
        return dict(result) if result else {}

    async def record_lab_run_completed(
        self,
        lab_record_id: str,
        started_at: str | None = None,
        stopped_at: str | None = None,
        started_by: str = "system",
        stop_reason: str | None = None,
        lablet_session_id: str | None = None,
        final_state: str | None = None,
    ) -> dict[str, Any]:
        """Record a completed lab run.

        Phase 8 (P8-25): Called by lablet-controller when a lab session ends.
        Creates a LabRunRecord documenting the execution cycle.

        Args:
            lab_record_id: LabRecord aggregate ID.
            started_at: ISO 8601 run start time.
            stopped_at: ISO 8601 run stop time.
            started_by: Who started the run.
            stop_reason: Why the run stopped.
            lablet_session_id: LabletSession ID if bound during run.
            final_state: Final CML state at run end.

        Returns:
            Created run record summary.
        """
        body: dict[str, Any] = {"started_by": started_by}
        if started_at is not None:
            body["started_at"] = started_at
        if stopped_at is not None:
            body["stopped_at"] = stopped_at
        if stop_reason is not None:
            body["stop_reason"] = stop_reason
        if lablet_session_id is not None:
            body["lablet_session_id"] = lablet_session_id
        if final_state is not None:
            body["final_state"] = final_state
        result = await self._request(
            "POST",
            f"/api/internal/lab-records/{lab_record_id}/run-completed",
            json=body,
        )
        return dict(result) if result else {}

    async def append_pipeline_run(
        self,
        lab_record_id: str,
        pipeline_name: str,
        status: str = "completed",
        started_at: str | None = None,
        completed_at: str | None = None,
        duration_seconds: float | None = None,
        steps_completed: int = 0,
        steps_failed: int = 0,
        steps_skipped: int = 0,
        step_results: dict[str, Any] | None = None,
        error_message: str | None = None,
        triggered_by: str = "lablet-controller",
        lablet_session_id: str | None = None,
    ) -> dict[str, Any]:
        """Record a completed pipeline execution on a LabRecord.

        Sprint F (ADR-034): Called by lablet-controller after a lifecycle
        pipeline completes (instantiate, teardown, collect_evidence,
        compute_grading). Appends a PipelineRunRecord to the aggregate.

        Args:
            lab_record_id: LabRecord aggregate ID.
            pipeline_name: Name of the pipeline (e.g., "instantiate", "teardown").
            status: Terminal status ("completed", "failed", "partial").
            started_at: ISO 8601 pipeline start time.
            completed_at: ISO 8601 pipeline completion time.
            duration_seconds: Total pipeline duration in seconds.
            steps_completed: Number of successfully completed steps.
            steps_failed: Number of failed steps.
            steps_skipped: Number of skipped steps.
            step_results: Per-step outcome dict.
            error_message: Pipeline-level error message if failed.
            triggered_by: Who triggered the pipeline.
            lablet_session_id: LabletSession ID that owns this run.

        Returns:
            Created pipeline run record summary.
        """
        body: dict[str, Any] = {
            "pipeline_name": pipeline_name,
            "status": status,
            "steps_completed": steps_completed,
            "steps_failed": steps_failed,
            "steps_skipped": steps_skipped,
            "triggered_by": triggered_by,
        }
        if started_at is not None:
            body["started_at"] = started_at
        if completed_at is not None:
            body["completed_at"] = completed_at
        if duration_seconds is not None:
            body["duration_seconds"] = duration_seconds
        if step_results is not None:
            body["step_results"] = step_results
        if error_message is not None:
            body["error_message"] = error_message
        if lablet_session_id is not None:
            body["lablet_session_id"] = lablet_session_id
        result = await self._request(
            "POST",
            f"/api/internal/lab-records/{lab_record_id}/pipeline-run",
            json=body,
        )
        return dict(result) if result else {}

    async def complete_lab_action(
        self,
        lab_record_id: str,
        action: str | None = None,
        cml_state: str | None = None,
    ) -> dict[str, Any]:
        """Mark a pending lab action as completed.

        ADR-017 reconciliation: Called by lablet-controller after successfully
        executing a CML API action (start, stop, wipe, delete, clone).

        Args:
            lab_record_id: LabRecord aggregate ID.
            action: Action that was completed (e.g., 'start', 'stop').
            cml_state: CML state after action completion.

        Returns:
            Updated lab record summary.
        """
        body: dict[str, Any] = {}
        if action is not None:
            body["action"] = action
        if cml_state is not None:
            body["cml_state"] = cml_state
        result = await self._request(
            "POST",
            f"/api/internal/lab-records/{lab_record_id}/complete-action",
            json=body,
        )
        return dict(result) if result else {}

    async def fail_lab_action(
        self,
        lab_record_id: str,
        error_message: str,
        transition_to_error: bool = False,
    ) -> dict[str, Any]:
        """Mark a pending lab action as failed.

        ADR-017 reconciliation: Called by lablet-controller when a CML API
        action fails.

        Args:
            lab_record_id: LabRecord aggregate ID.
            error_message: Error message describing the failure.
            transition_to_error: Whether to transition the lab to ERROR state.

        Returns:
            Updated lab record summary.
        """
        body: dict[str, Any] = {
            "error_message": error_message,
            "transition_to_error": transition_to_error,
        }
        result = await self._request(
            "POST",
            f"/api/internal/lab-records/{lab_record_id}/fail-action",
            json=body,
        )
        return dict(result) if result else {}

    async def mark_lab_orphaned(
        self,
        lab_record_id: str,
        error_message: str = "Lab not found on worker during scan",
        transition_to_error: bool = True,
    ) -> dict[str, Any]:
        """Mark a lab record as orphaned.

        Phase 8 (P8-25): Called by worker-controller when a lab record
        exists in the database but is not found on the CML worker.

        Args:
            lab_record_id: LabRecord aggregate ID.
            error_message: Reason for orphan status.
            transition_to_error: Whether to transition to ERROR state.

        Returns:
            Updated lab record summary.
        """
        body: dict[str, Any] = {
            "error_message": error_message,
            "transition_to_error": transition_to_error,
        }
        result = await self._request(
            "POST",
            f"/api/internal/lab-records/{lab_record_id}/mark-orphaned",
            json=body,
        )
        return dict(result) if result else {}

    # =========================================================================
    # Definition Operations
    # =========================================================================

    async def get_lablet_definitions(self) -> list[dict[str, Any]]:
        """Get all lablet definitions.

        Uses internal API endpoint (X-API-Key auth).
        """
        result = await self._request("GET", "/api/internal/lablet-definitions")
        return list(result) if result else []

    async def get_lablet_definition(self, definition_id: str) -> dict[str, Any]:
        """Get a single lablet definition by ID.

        Uses internal API endpoint (X-API-Key auth).
        """
        result = await self._request("GET", f"/api/internal/lablet-definitions/{definition_id}")
        return dict(result) if result else {}

    async def get_definitions_needing_sync(self) -> list[dict[str, Any]]:
        """Get lablet definitions with sync_status='sync_requested'.

        Used by ContentSyncService polling fallback (AD-CS-001) to discover
        definitions awaiting content synchronization.

        Uses internal API endpoint (X-API-Key auth).

        Returns:
            List of definition dicts with sync_status='sync_requested'.
        """
        result = await self._request(
            "GET",
            "/api/internal/lablet-definitions",
            params={"sync_status": "sync_requested"},
        )
        return list(result) if result else []

    async def record_content_sync_result(
        self,
        definition_id: str,
        sync_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Report content sync result to CPA.

        Called by ContentSyncService after completing the sync pipeline
        (download from Mosaic, upload to RustFS, upstream notification).

        Uses internal API endpoint (X-API-Key auth).

        Args:
            definition_id: The LabletDefinition aggregate ID.
            sync_result: Dict with sync_status, content_package_hash,
                         upstream_version, cml_yaml_content, devices_json, etc.

        Returns:
            Response from CPA (LabletDefinitionSyncResultDto).
        """
        result = await self._request(
            "POST",
            f"/api/internal/lablet-definitions/{definition_id}/content-synced",
            json=sync_result,
        )
        return dict(result) if result else {}

    # =========================================================================
    # Template Operations
    # =========================================================================

    async def get_worker_templates(self) -> list[dict[str, Any]]:
        """Get all worker templates via internal API."""
        result = await self._request("GET", "/api/internal/worker-templates")
        return list(result) if result else []

    async def get_worker_template(self, template_name: str) -> dict[str, Any]:
        """Get a single worker template by name via internal API."""
        result = await self._request("GET", f"/api/internal/worker-templates/by-name/{template_name}")
        return dict(result) if result else {}

    # =========================================================================
    # Settings Operations
    # =========================================================================

    async def get_discovery_settings(self) -> dict[str, Any]:
        """Get worker discovery settings from the Control Plane API.

        Uses the internal API endpoint for service-to-service calls.
        Returns settings for worker discovery including:
        - enabled: Whether discovery is enabled
        - regions: List of AWS regions to scan
        - ami_name_pattern: AMI name pattern to match (e.g., "CML-*")
        - scan_interval_seconds: Interval between discovery runs

        Returns:
            Dictionary with discovery settings, or empty dict if unavailable.
        """
        try:
            result = await self._request("GET", "/api/internal/settings/discovery")
            return dict(result) if result else {}
        except ControlPlaneApiClientError as e:
            logger.warning(f"Failed to fetch discovery settings: {e}")
            return {}

    # =========================================================================
    # Health Check
    # =========================================================================

    async def health_check(self) -> bool:
        """Check if the Control Plane API is healthy.

        Returns:
            True if healthy, False otherwise.
        """
        try:
            await self._request("GET", "/health")
            return True
        except Exception:
            return False

    # =========================================================================
    # DI Configuration
    # =========================================================================

    @staticmethod
    def configure(
        services: Any,
        base_url: str,
        timeout: float = 30.0,
        api_key: str | None = None,
    ) -> None:
        """Configure the client for dependency injection.

        Args:
            services: ServiceCollection from the application builder.
            base_url: Base URL of the Control Plane API.
            timeout: Request timeout.
            api_key: Optional API key.

        Usage:
            ControlPlaneApiClient.configure(
                builder.services,
                base_url="http://control-plane:8000",
            )
        """

        def factory(sp: ServiceProviderBase) -> ControlPlaneApiClient:
            return ControlPlaneApiClient(
                base_url=base_url,
                timeout=timeout,
                api_key=api_key,
            )

        services.add_singleton(ControlPlaneApiClient, implementation_factory=factory)
        logger.info(f"✅ ControlPlaneApiClient configured (base_url={base_url})")
