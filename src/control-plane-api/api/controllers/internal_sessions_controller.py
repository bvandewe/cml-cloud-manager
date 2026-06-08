"""Internal Sessions API controller for service-to-service communication.

Phase 7E: Extracted from InternalController (AD-27).
Handles LabletSession lifecycle mutations called by lablet-controller,
worker-controller, and resource-scheduler.

Per ADR-001: Control Plane API is the ONLY component that writes to MongoDB.
All other services request mutations via these internal endpoints.
"""

import logging
from typing import Annotated, Any

from application.commands.lab import (
    AllocateLabRecordPortsCommand,
)
from application.commands.lablet_session import (
    BindLabToSessionCommand,
    ExpireLabletSessionCommand,
    FailPipelineStepCommand,
    MarkSessionReadyCommand,
    RecordResourceObservationCommand,
    ResumePipelineStepCommand,
    ScheduleLabletSessionCommand,
    SetDesiredStatusCommand,
    StartInstantiationCommand,
    TerminateLabletSessionCommand,
    TransitionLabletSessionCommand,
    UpdatePipelineProgressCommand,
)
from application.commands.user_session.create_user_session_command import CreateUserSessionCommand
from application.queries.lablet_session import (
    GetLabletSessionQuery,
    GetPipelineProgressQuery,
    GetSessionsWithImminentDeadlinesQuery,
    ListLabletSessionsQuery,
    ListPipelineExecutionsQuery,
)
from application.settings import Settings
from classy_fastapi.decorators import get, post
from classy_fastapi.routable import Routable
from fastapi import Depends, HTTPException, Path, Query, status
from fastapi.security import APIKeyHeader
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping.mapper import Mapper
from neuroglia.mediation.mediator import Mediator
from neuroglia.mvc.controller_base import ControllerBase, generate_unique_id_function
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ==============================================================================
# API Key Authentication (shared with InternalController)
# ==============================================================================

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_internal_api_key(api_key: str | None = Depends(api_key_header)) -> str:
    """Verify internal API key for service-to-service communication."""
    expected = Settings().internal_api_key
    if not api_key or api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing internal API key",
        )
    return api_key


# ==============================================================================
# Path Parameter Annotations
# ==============================================================================

session_id_annotation = Annotated[str, Path(description="Lablet session ID")]


# ==============================================================================
# Request Models
# ==============================================================================


class ScheduleSessionRequest(BaseModel):
    """Request to schedule a session on a worker.

    Phase 7E: Replaces ScheduleInstanceRequest.
    Now includes allocated_ports and lab_record_id (absorbed from LabletLabBinding).
    """

    worker_id: str = Field(..., description="ID of the worker to assign")
    allocated_ports: dict[str, int] = Field(..., description="Port allocation map (port_name -> port_number)")
    lab_record_id: str = Field(..., description="Lab record to bind to this session")
    scheduled_by: str = Field(default="resource-scheduler", description="Identity of the scheduling agent")


class TransitionSessionRequest(BaseModel):
    """Request to transition a session to a new status."""

    status: str = Field(..., description="Target status (e.g., COLLECTING, STOPPING, STOPPED)")
    reason: str | None = Field(default=None, description="Reason for the transition")


class MarkSessionReadyRequest(BaseModel):
    """Request to mark a session as READY after lab provisioning.

    Phase 7E: Replaces MarkInstanceReadyRequest.
    ADR-021: Uses user_session_id + cml_lab_id (not lds_session_id/lds_login_url).
    """

    user_session_id: str = Field(..., description="ID of the provisioned UserSession child entity")
    cml_lab_id: str = Field(..., description="CML lab identifier on the worker")


class CreateUserSessionRequest(BaseModel):
    """Request to create a UserSession child entity on a LabletSession.

    Called by lablet-controller after provisioning an LDS session.
    The UserSession tracks the individual user's connection to the CML lab.
    If ``lds_login_url`` is provided the entity is immediately transitioned
    to PROVISIONED state.
    """

    lds_session_id: str = Field(..., description="LDS session identifier from provisioning")
    lds_login_url: str | None = Field(default=None, description="JWT-signed launch URL for lablet access")
    cml_lab_id: str | None = Field(default=None, description="CML lab identifier on the worker (informational)")


class StartInstantiationRequest(BaseModel):
    """Request to begin lab instantiation (SCHEDULED → INSTANTIATING)."""

    # No fields needed — session_id comes from path parameter


class RecordResourceObservationRequest(BaseModel):
    """Request to record runtime resource observations from CML.

    ADR-030: Resource & Port Observation — "Learn from Live"
    """

    observed_resources: dict = Field(..., description="Serialized ResourceObservation from CML introspection")
    observed_ports: dict[str, int] = Field(default_factory=dict, description="Actual CML port allocations")


class UpdatePipelineProgressRequest(BaseModel):
    """Request to update a pipeline step on a session's pipeline progress.

    ADR-034 Sprint E: Supports all pipeline types
    (instantiate, teardown, collect_evidence, compute_grading).
    """

    pipeline_name: str = Field(..., description="Pipeline type: 'instantiate', 'teardown', 'collect_evidence', 'compute_grading'")
    step_name: str = Field(..., description="Pipeline step name (e.g., 'stop_lab', 'wipe_lab')")
    step_status: str = Field(..., description="Step outcome: 'completed', 'failed', 'skipped', or 'suspended'")
    result_data: dict | None = Field(default=None, description="Optional result payload for completed/suspended steps")
    error: str | None = Field(default=None, description="Optional error message for failed steps")


class ResumePipelineStepRequest(BaseModel):
    """Request to resume a suspended pipeline step (Phase 3 / AD-CSI-009)."""

    pipeline_name: str = Field(..., description="Pipeline holding the suspended step")
    step_correlation_id: str = Field(..., description="Correlation token issued when the step was suspended")
    output_data: dict = Field(default_factory=dict, description="Output payload from the external job")
    completed_at: str | None = Field(default=None, description="ISO 8601 external completion timestamp")


class FailPipelineStepRequest(BaseModel):
    """Request to mark a suspended pipeline step as failed (Phase 3 / AD-CSI-009)."""

    pipeline_name: str = Field(..., description="Pipeline holding the suspended step")
    step_correlation_id: str = Field(..., description="Correlation token issued when the step was suspended")
    error: str = Field(..., description="Human-readable failure message")
    details: dict | None = Field(default=None, description="Optional structured error payload")
    failed_at: str | None = Field(default=None, description="ISO 8601 external failure timestamp")


class BindLabToSessionRequest(BaseModel):
    """Request to bind a LabRecord to a session during the instantiation pipeline.

    ADR-031 / ADR-032: Lab binding is a pipeline step.
    """

    worker_id: str = Field(..., description="ID of the CMLWorker hosting the lab")
    lab_record_id: str = Field(..., description="ID of the LabRecord to bind")
    cml_lab_id: str | None = Field(default=None, description="CML lab identifier on the worker")
    cml_lab_title: str | None = Field(default=None, description="CML lab title for display")


class SetDesiredStatusRequest(BaseModel):
    """Request to set the desired lifecycle state (spec) for a session.

    ADR-034 Sprint E / ADR-015 pattern: Follows the Kubernetes-like
    reconciliation model — desired_status is the target state that
    controllers reconcile towards.
    """

    desired_status: str = Field(..., description="Target lifecycle state (running, stopped, terminated)")
    requested_by: str | None = Field(default=None, description="User or system requesting the change")
    reason: str | None = Field(default=None, description="Optional reason for the change")


class ExpireSessionRequest(BaseModel):
    """Request to expire a session due to timeslot exhaustion.

    ADR-031 / AD-TIMESLOT-001: Timeslot-centric lifecycle.
    """

    reason: str = Field(default="timeslot_expired", description="Expiry reason")


class TerminateSessionInternalRequest(BaseModel):
    """Request to terminate a session (internal, system-initiated).

    AD-PIPELINE-008: Used by lablet-controller for unrecoverable situations
    (max pipeline retries exhausted, timeslot expiry, admin force-kill).
    Reuses TerminateLabletSessionCommand for port release and capacity release.
    """

    terminated_by: str = Field(default="lablet-controller", description="Identity of the terminating agent")
    reason: str | None = Field(default=None, description="Reason for termination")


class AllocateLabRecordPortsRequest(BaseModel):
    """Request to allocate ports from worker pool for a LabRecord.

    ADR-032: Port allocation is a LabRecord topology concern.
    """

    lab_record_id: str = Field(..., description="ID of the LabRecord to allocate ports for")
    worker_id: str = Field(..., description="ID of the CMLWorker hosting the lab")


# ==============================================================================
# Controller
# ==============================================================================


class InternalSessionsController(ControllerBase):
    """Internal controller for LabletSession lifecycle mutations.

    Phase 7E (AD-27): Extracted from InternalController to keep session
    management separate from worker/lab record operations.

    All endpoints are protected by internal API key authentication.
    Called by lablet-controller, worker-controller, and resource-scheduler.
    """

    def __init__(self, service_provider: ServiceProviderBase, mapper: Mapper, mediator: Mediator):
        # Store DI services
        self.service_provider = service_provider
        self.mapper = mapper
        self.mediator = mediator
        self.name = "InternalSessions"

        # Initialize base Controller
        ControllerBase.__init__(self, service_provider, mapper, mediator)

        # Use /internal prefix — endpoints will be /internal/lablet-sessions/*
        Routable.__init__(
            self,
            prefix="/internal/lablet-sessions",
            tags=["Internal - Sessions"],
            generate_unique_id_function=generate_unique_id_function,
        )

    # --------------------------------------------------------------------------
    # Query Endpoints
    # --------------------------------------------------------------------------

    @get(
        "/",
        summary="List Lablet Sessions (Internal)",
        tags=["Internal - Sessions"],
        status_code=200,
    )
    async def list_sessions(
        self,
        api_key: str = Depends(verify_internal_api_key),
        status: str | None = Query(default=None, description="Filter by status"),
        worker_id: str | None = Query(default=None, description="Filter by worker ID"),
        definition_id: str | None = Query(default=None, description="Filter by definition ID"),
        include_terminated: bool = Query(default=False, description="Include terminated sessions"),
        skip: int = Query(default=0, ge=0, description="Number of records to skip"),
        limit: int = Query(default=100, ge=1, le=1000, description="Maximum number of records"),
    ) -> dict[str, Any]:
        """List lablet sessions with optional filtering.

        Called by lablet-controller, worker-controller, and resource-scheduler
        to query session state.
        """
        logger.info(f"[Internal] Listing lablet sessions (status={status}, worker_id={worker_id})")

        query = ListLabletSessionsQuery(
            status=status,
            worker_id=worker_id,
            definition_id=definition_id,
            include_terminated=include_terminated,
            skip=skip,
            limit=limit,
        )
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @get(
        "/imminent-deadlines",
        summary="Get Sessions with Imminent Timeslot Deadlines (Internal)",
        tags=["Internal - Sessions"],
        status_code=200,
    )
    async def get_imminent_deadlines(
        self,
        api_key: str = Depends(verify_internal_api_key),
        boot_window_minutes: int = Query(
            default=35,
            ge=1,
            le=120,
            description="Look-ahead window for SCHEDULED sessions approaching their timeslot_start (minutes)",
        ),
    ) -> dict[str, Any]:
        """Get sessions with imminent timeslot deadlines.

        Returns two lists:
        - approaching_start: SCHEDULED sessions whose timeslot_start is within
          the boot_window_minutes look-ahead (need instantiation).
        - past_end: Non-terminal sessions whose timeslot_end has passed
          (need stopping/expiry).

        Called by lablet-controller's TimeslotWatcherService every ~10s.
        Uses MongoDB indexes for efficient server-side filtering (AD-TIMESLOT-001).
        """
        logger.debug(f"[Internal] Querying imminent deadlines (boot_window={boot_window_minutes}min)")

        query = GetSessionsWithImminentDeadlinesQuery(boot_window_minutes=boot_window_minutes)
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @get(
        "/{session_id}",
        summary="Get Lablet Session by ID (Internal)",
        tags=["Internal - Sessions"],
        status_code=200,
    )
    async def get_session(
        self,
        session_id: session_id_annotation,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Get a single lablet session by ID.

        Called by lablet-controller and worker-controller to get session details.
        """
        logger.info(f"[Internal] Getting lablet session {session_id}")

        query = GetLabletSessionQuery(id=session_id)
        result = await self.mediator.execute_async(query)
        return self.process(result)

    # --------------------------------------------------------------------------
    # Command Endpoints
    # --------------------------------------------------------------------------

    @post(
        "/{session_id}/schedule",
        summary="Schedule Session on Worker (Internal)",
        tags=["Internal - Sessions"],
        status_code=200,
    )
    async def schedule_session(
        self,
        session_id: session_id_annotation,
        request: ScheduleSessionRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Assign a worker to a session (scheduling decision).

        Called by resource-scheduler after placement decision.
        Phase 7E: Now includes port allocation and lab record binding
        (absorbed from the deleted AllocateInstancePortsCommand and LabletLabBinding).
        """
        logger.info(f"[Internal] Scheduling session {session_id} to worker {request.worker_id}")

        command = ScheduleLabletSessionCommand(
            session_id=session_id,
            worker_id=request.worker_id,
            allocated_ports=request.allocated_ports,
            lab_record_id=request.lab_record_id,
            scheduled_by=request.scheduled_by,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/{session_id}/start-instantiation",
        summary="Start Lab Instantiation (Internal)",
        tags=["Internal - Sessions"],
        status_code=200,
    )
    async def start_instantiation(
        self,
        session_id: session_id_annotation,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Begin lab instantiation for a session (SCHEDULED → INSTANTIATING).

        Called by lablet-controller when it begins lab import/startup on the worker.
        """
        logger.info(f"[Internal] Starting instantiation for session {session_id}")

        command = StartInstantiationCommand(session_id=session_id)
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/{session_id}/transition",
        summary="Transition Session Status (Internal)",
        tags=["Internal - Sessions"],
        status_code=200,
    )
    async def transition_session(
        self,
        session_id: session_id_annotation,
        request: TransitionSessionRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Transition a session to a new status.

        Called by lablet-controller during reconciliation.
        Valid transitions depend on current session state.
        """
        logger.info(f"[Internal] Transitioning session {session_id} to {request.status}")

        command = TransitionLabletSessionCommand(
            session_id=session_id,
            target_status=request.status,
            reason=request.reason,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/{session_id}/mark-ready",
        summary="Mark Session as Ready (Internal)",
        tags=["Internal - Sessions"],
        status_code=200,
    )
    async def mark_session_ready(
        self,
        session_id: session_id_annotation,
        request: MarkSessionReadyRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Mark a session as READY with UserSession and CML lab info.

        Phase 7E (ADR-021): Atomically sets user_session_id + cml_lab_id
        and transitions INSTANTIATING → READY. Called by lablet-controller
        after UserSession is provisioned and lab is deployed.
        """
        logger.info(f"[Internal] Marking session {session_id} as READY (user_session={request.user_session_id})")

        command = MarkSessionReadyCommand(
            session_id=session_id,
            user_session_id=request.user_session_id,
            cml_lab_id=request.cml_lab_id,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/{session_id}/user-session",
        summary="Create User Session (Internal)",
        tags=["Internal - Sessions"],
        status_code=201,
    )
    async def create_user_session(
        self,
        session_id: session_id_annotation,
        request: CreateUserSessionRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Create a UserSession child entity on a LabletSession.

        Called by lablet-controller after provisioning an LDS session.
        Creates a UserSession in PROVISIONING state; if ``lds_login_url``
        is provided the entity is immediately transitioned to PROVISIONED.

        Returns the created UserSession data including ``user_session_id``.
        """
        logger.info(f"[Internal] Creating UserSession for session {session_id} (lds_session_id={request.lds_session_id})")

        command = CreateUserSessionCommand(
            lablet_session_id=session_id,
            lds_session_id=request.lds_session_id,
            lds_login_url=request.lds_login_url,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/{session_id}/resource-observations",
        summary="Record Resource Observations (Internal)",
        tags=["Internal - Sessions"],
        status_code=200,
    )
    async def record_resource_observations(
        self,
        session_id: session_id_annotation,
        request: RecordResourceObservationRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Record runtime resource observations from CML introspection.

        ADR-030: Called by lablet-controller during COLLECTING phase or
        via manual trigger. Stores observations on the LabletSession
        aggregate and detects port drift.
        """
        logger.info(f"[Internal] Recording resource observations for session {session_id}")

        command = RecordResourceObservationCommand(
            session_id=session_id,
            observed_resources=request.observed_resources,
            observed_ports=request.observed_ports,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    # --------------------------------------------------------------------------
    # Phase 1: Pipeline Progress Endpoints (ADR-034)
    # --------------------------------------------------------------------------

    @post(
        "/{session_id}/pipeline-progress",
        summary="Update Pipeline Progress (Internal)",
        tags=["Internal - Sessions"],
        status_code=200,
    )
    async def update_pipeline_progress(
        self,
        session_id: session_id_annotation,
        request: UpdatePipelineProgressRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Update a pipeline step on a session's pipeline progress.

        ADR-034 Sprint E: The CPA is the source of truth — the controller
        sends step-level deltas, and the handler applies them per pipeline_name.
        """
        logger.info(f"[Internal] Updating pipeline progress for session {session_id} (pipeline={request.pipeline_name}, step={request.step_name}, status={request.step_status})")

        command = UpdatePipelineProgressCommand(
            session_id=session_id,
            pipeline_name=request.pipeline_name,
            step_name=request.step_name,
            step_status=request.step_status,
            result_data=request.result_data,
            error=request.error,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    # --------------------------------------------------------------------------
    # Phase 3 / AD-CSI-009: SE-suspended step resume/fail (Scenario Engine bridge)
    # --------------------------------------------------------------------------

    @post(
        "/{session_id}/pipeline-steps/resume",
        summary="Resume Suspended Pipeline Step (Internal)",
        tags=["Internal - Sessions"],
        status_code=200,
    )
    async def resume_pipeline_step(
        self,
        session_id: session_id_annotation,
        request: ResumePipelineStepRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Resume a suspended pipeline step after an external job completes.

        Phase 3 / AD-CSI-009: Called by lablet-controller's events_controller
        when a Scenario Engine ``job.completed`` CloudEvent arrives. Flips the
        suspended step to ``"completed"`` and merges ``output_data`` into the
        step's ``result_data``. Returns the refreshed ``pipeline_progress`` so
        the in-process ``LifecyclePhaseHandler`` can resume executor execution.
        """
        logger.info(
            "[Internal] Resuming suspended step for session %s (pipeline=%s, correlation=%s)",
            session_id,
            request.pipeline_name,
            request.step_correlation_id,
        )
        command = ResumePipelineStepCommand(
            session_id=session_id,
            pipeline_name=request.pipeline_name,
            step_correlation_id=request.step_correlation_id,
            output_data=request.output_data,
            completed_at=request.completed_at,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/{session_id}/pipeline-steps/fail",
        summary="Fail Suspended Pipeline Step (Internal)",
        tags=["Internal - Sessions"],
        status_code=200,
    )
    async def fail_pipeline_step(
        self,
        session_id: session_id_annotation,
        request: FailPipelineStepRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Mark a suspended pipeline step as failed after an external job fails.

        Phase 3 / AD-CSI-009: Called by lablet-controller's events_controller
        on Scenario Engine ``job.failed`` or ``job.cancelled`` CloudEvents.
        Flips the suspended step to ``"failed"`` and records the error.
        """
        logger.info(
            "[Internal] Failing suspended step for session %s (pipeline=%s, correlation=%s)",
            session_id,
            request.pipeline_name,
            request.step_correlation_id,
        )
        command = FailPipelineStepCommand(
            session_id=session_id,
            pipeline_name=request.pipeline_name,
            step_correlation_id=request.step_correlation_id,
            error=request.error,
            details=request.details,
            failed_at=request.failed_at,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/{session_id}/desired-status",
        summary="Set Desired Status (Internal)",
        tags=["Internal - Sessions"],
        status_code=200,
    )
    async def set_desired_status(
        self,
        session_id: session_id_annotation,
        request: SetDesiredStatusRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Set the desired lifecycle state (spec) for a session.

        ADR-034 Sprint E / ADR-015 pattern: Controllers watch etcd for
        desired_status changes and reconcile actual state accordingly.
        """
        logger.info(f"[Internal] Setting desired_status for session {session_id} → {request.desired_status} (requested_by={request.requested_by})")

        command = SetDesiredStatusCommand(
            session_id=session_id,
            desired_status=request.desired_status,
            requested_by=request.requested_by,
            reason=request.reason,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/{session_id}/bind-lab",
        summary="Bind Lab to Session (Internal)",
        tags=["Internal - Sessions"],
        status_code=200,
    )
    async def bind_lab_to_session(
        self,
        session_id: session_id_annotation,
        request: BindLabToSessionRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Bind a LabRecord to a session during the instantiation pipeline.

        ADR-031 / ADR-032: Creates a LabRunRecord on the LabRecord,
        sets active_lablet_session_id, and denormalizes allocated_ports
        from the LabRecord onto the LabletSession.
        """
        logger.info(f"[Internal] Binding lab_record {request.lab_record_id} to session {session_id}")

        command = BindLabToSessionCommand(
            session_id=session_id,
            worker_id=request.worker_id,
            lab_record_id=request.lab_record_id,
            cml_lab_id=request.cml_lab_id,
            cml_lab_title=request.cml_lab_title,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/{session_id}/expire",
        summary="Expire Session (Internal)",
        tags=["Internal - Sessions"],
        status_code=200,
    )
    async def expire_session(
        self,
        session_id: session_id_annotation,
        request: ExpireSessionRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Expire a session due to timeslot exhaustion.

        ADR-031 / AD-TIMESLOT-001: Expires the session and triggers
        downstream cleanup (unbind LabRecord, release capacity).
        Ports are NOT released — they belong to the LabRecord.
        """
        logger.info(f"[Internal] Expiring session {session_id} (reason: {request.reason})")

        command = ExpireLabletSessionCommand(
            session_id=session_id,
            reason=request.reason,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/allocate-lab-record-ports",
        summary="Allocate Lab Record Ports (Internal)",
        tags=["Internal - Sessions"],
        status_code=200,
    )
    async def allocate_lab_record_ports(
        self,
        request: AllocateLabRecordPortsRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Allocate ports from worker pool for a LabRecord.

        ADR-032: Port allocation is a LabRecord topology concern. Ports are
        allocated via PortAllocationService (etcd) keyed by lab_record_id,
        then persisted on the LabRecord aggregate.

        Called by lablet-controller during the `ports_alloc` pipeline step.
        """
        logger.info(f"[Internal] Allocating ports for lab_record {request.lab_record_id} on worker {request.worker_id}")

        command = AllocateLabRecordPortsCommand(
            lab_record_id=request.lab_record_id,
            worker_id=request.worker_id,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    # --------------------------------------------------------------------------
    # AD-PIPELINE-008: Internal Terminate Endpoint
    # --------------------------------------------------------------------------

    @post(
        "/{session_id}/terminate",
        summary="Terminate Session (Internal)",
        tags=["Internal - Sessions"],
        status_code=200,
    )
    async def terminate_session_internal(
        self,
        session_id: session_id_annotation,
        request: TerminateSessionInternalRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Terminate a session (system-initiated, internal).

        AD-PIPELINE-008: Used by lablet-controller for unrecoverable situations
        such as max pipeline retries exhausted, timeslot expiry, or admin
        force-kill. Reuses TerminateLabletSessionCommand which handles port
        release, capacity release, and domain events.
        """
        logger.info(f"[Internal] Terminating session {session_id} (by={request.terminated_by}, reason={request.reason})")

        command = TerminateLabletSessionCommand(
            session_id=session_id,
            terminated_by=request.terminated_by,
            reason=request.reason,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    # --------------------------------------------------------------------------
    # Sprint G (G2): Pipeline Observability Endpoints
    # --------------------------------------------------------------------------

    @get(
        "/{session_id}/pipeline-progress",
        summary="Get Pipeline Progress (Internal)",
        tags=["Internal - Sessions"],
    )
    async def get_pipeline_progress_internal(
        self,
        session_id: session_id_annotation,
        pipeline_name: str | None = None,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Get live pipeline progress for a session.

        Sprint G (G2): Returns per-step status for all pipelines or a
        single pipeline if pipeline_name is provided.
        """
        query = GetPipelineProgressQuery(session_id=session_id, pipeline_name=pipeline_name)
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @get(
        "/{session_id}/pipeline-executions",
        summary="List Pipeline Execution History (Internal)",
        tags=["Internal - Sessions"],
    )
    async def list_pipeline_executions_internal(
        self,
        session_id: session_id_annotation,
        pipeline_name: str | None = None,
        execution_status: str | None = None,
        skip: int = 0,
        limit: int = 50,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """List auditable PipelineExecutionRecords for a session.

        Sprint G (G2): Returns execution history with timing, step counts,
        and error information.
        """
        query = ListPipelineExecutionsQuery(
            session_id=session_id,
            pipeline_name=pipeline_name,
            status=execution_status,
            skip=skip,
            limit=limit,
        )
        result = await self.mediator.execute_async(query)
        return self.process(result)
