"""LabletSessions API controller with dual authentication (Session + JWT).

Phase 7E: Replaces LabletInstancesController.
Public BFF endpoints for managing LabletSession lifecycle.
"""

import logging

from api.dependencies import get_current_user
from application.commands.lablet_session import (
    BulkRequeueLabletSessionsCommand,
    CreateLabletSessionCommand,
    RequestResourceObservationCommand,
    RequeueLabletSessionCommand,
    TerminateLabletSessionCommand,
    TransitionLabletSessionCommand,
)
from application.queries.lablet_session import (
    GetGradingSessionQuery,
    GetLabletSessionQuery,
    GetScoreReportQuery,
    GetUserSessionQuery,
    ListLabletSessionsQuery,
)
from classy_fastapi.decorators import delete, get, post
from classy_fastapi.routable import Routable
from fastapi import Depends
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator
from neuroglia.mvc import ControllerBase
from neuroglia.mvc.controller_base import generate_unique_id_function
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ==============================================================================
# Request Models
# ==============================================================================


class CreateLabletSessionRequest(BaseModel):
    """Request model for creating a LabletSession (reservation)."""

    definition_id: str = Field(..., description="ID of the LabletDefinition to instantiate")
    timeslot_start: str = Field(..., description="Start time for the lab session (ISO 8601)")
    timeslot_end: str = Field(..., description="End time for the lab session (ISO 8601)")
    reservation_id: str | None = Field(default=None, description="External reservation system reference")


class TerminateLabletSessionRequest(BaseModel):
    """Request model for terminating a LabletSession."""

    reason: str | None = Field(default=None, description="Reason for termination")


class TransitionLabletSessionRequest(BaseModel):
    """Request model for transitioning a LabletSession to a new status (AD-P7-06 manual actions)."""

    status: str = Field(..., description="Target status (e.g., running, collecting, stopping, stopped, archived)")
    reason: str | None = Field(default=None, description="Reason for the transition")


class RequeueLabletSessionRequest(BaseModel):
    """Request model for re-queuing a LabletSession for reconciliation."""

    reason: str | None = Field(default=None, description="Reason for re-queuing")


class BulkRequeueLabletSessionsRequest(BaseModel):
    """Request model for bulk re-queuing LabletSessions."""

    session_ids: list[str] = Field(..., description="List of LabletSession IDs to re-queue")
    reason: str | None = Field(default=None, description="Reason for re-queuing")


# ==============================================================================
# Controller
# ==============================================================================


class LabletSessionsController(ControllerBase):
    """Controller for LabletSession management endpoints.

    Provides CRUD operations for lablet sessions, which represent
    runtime lab sessions from reservation through execution to termination.

    Phase 7E: Replaces LabletInstancesController with the Session Entity Model.
    """

    def __init__(self, service_provider: ServiceProviderBase, mapper: Mapper, mediator: Mediator):
        # Store DI services first
        self.service_provider = service_provider
        self.mapper = mapper
        self.mediator = mediator
        self.name = "LabletSessions"

        # Initialize base Controller (incl. JsonSerializer)
        ControllerBase.__init__(self, service_provider, mapper, mediator)

        # Call Routable.__init__ directly with custom kebab-case prefix
        Routable.__init__(
            self,
            prefix="/lablet-sessions",
            tags=["Lablet Sessions"],
            generate_unique_id_function=generate_unique_id_function,
        )

    @get("/", summary="List Lablet Sessions", tags=["Lablet Sessions"])
    async def list_sessions(
        self,
        status: str | None = None,
        worker_id: str | None = None,
        owner_id: str | None = None,
        definition_id: str | None = None,
        include_terminated: bool = False,
        skip: int = 0,
        limit: int = 100,
        user: dict = Depends(get_current_user),
    ):
        """List lablet sessions with optional filtering.

        Filters:
        - **status**: Filter by session status (pending, scheduled, running, etc.)
        - **worker_id**: Filter by assigned CML worker
        - **owner_id**: Filter by session owner
        - **definition_id**: Filter by lablet definition
        - **include_terminated**: Include terminated sessions

        Pagination:
        - **skip**: Number of records to skip
        - **limit**: Maximum number of records to return
        """
        query = ListLabletSessionsQuery(
            status=status,
            worker_id=worker_id,
            owner_id=owner_id,
            definition_id=definition_id,
            include_terminated=include_terminated,
            skip=skip,
            limit=limit,
        )
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @get("/{lablet_session_id}", summary="Get Lablet Session", tags=["Lablet Sessions"])
    async def get_session(
        self,
        lablet_session_id: str,
        user: dict = Depends(get_current_user),
    ):
        """Get a single lablet session by ID.

        Returns the full session details including assignment info,
        timeslot, state history, and grading results.
        """
        query = GetLabletSessionQuery(id=lablet_session_id)
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @get(
        "/by-reservation/{reservation_id}",
        summary="Get Lablet Session by Reservation ID",
        tags=["Lablet Sessions"],
    )
    async def get_session_by_reservation(
        self,
        reservation_id: str,
        user: dict = Depends(get_current_user),
    ):
        """Get a lablet session by external reservation ID.

        Useful for integrating with external reservation systems.
        """
        query = GetLabletSessionQuery(reservation_id=reservation_id)
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @post("/", summary="Create Lablet Session (Reservation)", tags=["Lablet Sessions"], status_code=201)
    async def create_session(
        self,
        request: CreateLabletSessionRequest,
        user: dict = Depends(get_current_user),
    ):
        """Create a new lablet session (submit a reservation).

        Creates a reservation for a lab session. The session starts in
        PENDING status and will be scheduled to a worker by the scheduler.

        The timeslot specifies when the lab should be available. The system
        will ensure the lab is ready by the start time.
        """
        # Extract owner_id from user info
        owner_id = user.get("sub", user.get("preferred_username", "unknown"))

        command = CreateLabletSessionCommand(
            definition_id=request.definition_id,
            owner_id=owner_id,
            timeslot_start=request.timeslot_start,
            timeslot_end=request.timeslot_end,
            reservation_id=request.reservation_id,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/{lablet_session_id}/transition",
        summary="Transition Lablet Session Status",
        tags=["Lablet Sessions"],
    )
    async def transition_session(
        self,
        lablet_session_id: str,
        request: TransitionLabletSessionRequest,
        user: dict = Depends(get_current_user),
    ):
        """Transition a lablet session to a new status (AD-P7-06 manual actions).

        Valid transitions depend on the current session state:
        - **READY** → running
        - **RUNNING** → collecting
        - **COLLECTING** → grading, stopping
        - **GRADING** → stopping
        - **STOPPING** → stopped
        - **STOPPED** → archived

        Some transitions (instantiating, ready, terminated) require
        dedicated endpoints and cannot be triggered through this endpoint.
        """
        command = TransitionLabletSessionCommand(
            session_id=lablet_session_id,
            target_status=request.status,
            reason=request.reason,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @delete("/{lablet_session_id}", summary="Terminate Lablet Session", tags=["Lablet Sessions"])
    async def terminate_session(
        self,
        lablet_session_id: str,
        request: TerminateLabletSessionRequest | None = None,
        user: dict = Depends(get_current_user),
    ):
        """Terminate a lablet session.

        Terminates the session and releases any allocated resources.
        Can be called from most states as an emergency/force termination.

        Users can terminate their own sessions. Admins can terminate any session.
        """
        # Extract terminator info from user
        terminated_by = user.get("sub", user.get("preferred_username", "unknown"))
        reason = request.reason if request else None

        command = TerminateLabletSessionCommand(
            session_id=lablet_session_id,
            terminated_by=terminated_by,
            reason=reason,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/{lablet_session_id}/requeue",
        summary="Requeue Lablet Session",
        tags=["Lablet Sessions"],
    )
    async def requeue_session(
        self,
        lablet_session_id: str,
        request: RequeueLabletSessionRequest | None = None,
        user: dict = Depends(get_current_user),
    ):
        """Re-queue a lablet session for reconciliation.

        Bumps the session's updated_at timestamp and records the requeue
        in state_history so that reconciliation controllers pick it up
        for re-processing. Does NOT change the session status.

        Useful for stuck sessions that were missed by the reconciliation loop.
        Cannot be called on TERMINATED or ARCHIVED sessions.
        """
        requeued_by = user.get("sub", user.get("preferred_username", "unknown"))
        reason = request.reason if request else None

        command = RequeueLabletSessionCommand(
            session_id=lablet_session_id,
            requeued_by=requeued_by,
            reason=reason,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/{lablet_session_id}/observe-resources",
        summary="Request Resource Observation",
        tags=["Lablet Sessions"],
        status_code=202,
    )
    async def observe_resources(
        self,
        lablet_session_id: str,
        user: dict = Depends(get_current_user),
    ):
        """Request on-demand resource observation for a running session.

        Triggers lablet-controller to observe the live CML lab and report
        back observed resources and port allocations. Results are recorded
        asynchronously on the session aggregate.

        ADR-030: Resource & Port Observation — "Learn from Live".
        """
        requested_by = user.get("sub", user.get("preferred_username", "unknown"))

        command = RequestResourceObservationCommand(
            session_id=lablet_session_id,
            requested_by=requested_by,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/bulk/requeue",
        summary="Bulk Requeue Lablet Sessions",
        tags=["Lablet Sessions"],
    )
    async def bulk_requeue_sessions(
        self,
        request: BulkRequeueLabletSessionsRequest,
        user: dict = Depends(get_current_user),
    ):
        """Re-queue multiple lablet sessions for reconciliation.

        Processes each session independently — partial success is possible.
        Returns a summary with success/failure counts and error details.
        """
        requeued_by = user.get("sub", user.get("preferred_username", "unknown"))

        command = BulkRequeueLabletSessionsCommand(
            session_ids=request.session_ids,
            requeued_by=requeued_by,
            reason=request.reason,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @get("/my", summary="List My Lablet Sessions", tags=["Lablet Sessions"])
    async def list_my_sessions(
        self,
        status: str | None = None,
        include_terminated: bool = False,
        skip: int = 0,
        limit: int = 100,
        user: dict = Depends(get_current_user),
    ):
        """List lablet sessions owned by the current user.

        Convenience endpoint that filters sessions by the authenticated user.
        """
        owner_id = user.get("sub", user.get("preferred_username", "unknown"))

        query = ListLabletSessionsQuery(
            status=status,
            owner_id=owner_id,
            include_terminated=include_terminated,
            skip=skip,
            limit=limit,
        )
        result = await self.mediator.execute_async(query)
        return self.process(result)

    # ==========================================================================
    # Sub-entity endpoints (Phase 1 UX — child entity BFF routes)
    # ==========================================================================

    @get(
        "/{lablet_session_id}/user-session",
        summary="Get User Session for Lablet Session",
        tags=["Lablet Sessions"],
    )
    async def get_user_session(
        self,
        lablet_session_id: str,
        user: dict = Depends(get_current_user),
    ):
        """Get the UserSession (LDS tracking) linked to a lablet session.

        Returns the LDS session details including login URL, devices,
        and session status.
        """
        query = GetUserSessionQuery(lablet_session_id=lablet_session_id)
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @get(
        "/{lablet_session_id}/grading-session",
        summary="Get Grading Session for Lablet Session",
        tags=["Lablet Sessions"],
    )
    async def get_grading_session(
        self,
        lablet_session_id: str,
        user: dict = Depends(get_current_user),
    ):
        """Get the GradingSession linked to a lablet session.

        Returns grading lifecycle details including status, devices,
        and grading rules reference.
        """
        query = GetGradingSessionQuery(lablet_session_id=lablet_session_id)
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @get(
        "/{lablet_session_id}/score-report",
        summary="Get Score Report for Lablet Session",
        tags=["Lablet Sessions"],
    )
    async def get_score_report(
        self,
        lablet_session_id: str,
        user: dict = Depends(get_current_user),
    ):
        """Get the ScoreReport (assessment results) linked to a lablet session.

        Returns score, pass/fail status, sections breakdown, and grade result.
        """
        query = GetScoreReportQuery(lablet_session_id=lablet_session_id)
        result = await self.mediator.execute_async(query)
        return self.process(result)
