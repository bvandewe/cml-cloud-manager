"""LabletSession aggregate definition using the AggregateState pattern.

A LabletSession represents a complete user experience combining a CML lab,
an LDS session, and optional grading — managed through a single lifecycle.

Phase 7C: Replaces LabletInstance aggregate (ADR-020).

Key changes from LabletInstance:
- Renamed from LabletInstance → LabletSession (ADR-020 §1)
- lab_record_id absorbed from LabletLabBinding (ADR-020 §2, §3)
- allocated_ports, started_at, ended_at, duration_seconds absorbed
  from LabletRecordRun (ADR-020 §2)
- Child entity FKs: user_session_id, grading_session_id, score_report_id
  (ADR-021 §4)
- lds_session_id/lds_login_url moved to UserSession child entity
- grading_score/grading_rules_uri moved to GradingSession/ScoreReport

Key Features:
- 11-state lifecycle with validated transitions (ADR-020 §4)
- State history tracking for audit trail
- Port allocation tracking (absorbed from LabletRecordRun)
- Direct lab_record_id binding (absorbed from LabletLabBinding)
- Child entity FK linkage for UserSession, GradingSession, ScoreReport
- Timeslot management
"""

from datetime import datetime, timedelta, timezone
from typing import Any, cast
from uuid import uuid4

from domain.enums import LABLET_SESSION_VALID_TRANSITIONS, LabletSessionStatus
from domain.events.lablet_session_events import (
    LabletSessionArchivedDomainEvent,
    LabletSessionCollectingDomainEvent,
    LabletSessionCreatedDomainEvent,
    LabletSessionExpiredDomainEvent,
    LabletSessionGradingDomainEvent,
    LabletSessionInstantiatingDomainEvent,
    LabletSessionInstantiationProgressUpdatedDomainEvent,
    LabletSessionLabBoundDomainEvent,
    LabletSessionObserveResourcesRequestedDomainEvent,
    LabletSessionPortDriftDetectedDomainEvent,
    LabletSessionPortsReleasedDomainEvent,
    LabletSessionReadyDomainEvent,
    LabletSessionRequeuedDomainEvent,
    LabletSessionResourcesObservedDomainEvent,
    LabletSessionRunningDomainEvent,
    LabletSessionScheduledDomainEvent,
    LabletSessionScoreRecordedDomainEvent,
    LabletSessionStoppedDomainEvent,
    LabletSessionStoppingDomainEvent,
    LabletSessionTerminatedDomainEvent,
    LabletSessionTimeslotExtendedDomainEvent,
)
from domain.value_objects.state_transition import StateTransition
from multipledispatch import dispatch
from neuroglia.data.abstractions import AggregateRoot, AggregateState


class InvalidStateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, from_state: LabletSessionStatus, to_state: LabletSessionStatus, message: str | None = None):
        self.from_state = from_state
        self.to_state = to_state
        self.message = message or f"Invalid transition from {from_state.value} to {to_state.value}"
        super().__init__(self.message)


class LabletSessionState(AggregateState[str]):
    """Encapsulates the persisted state for the LabletSession aggregate.

    Tracks the full lifecycle of a lab session including scheduling,
    execution, assessment, and termination.

    Consolidated state — replaces LabletInstanceState + LabletLabBinding
    + LabletRecordRun fields (ADR-020 §2).
    """

    id: str

    # Definition reference (pinned at creation)
    definition_id: str
    definition_name: str
    definition_version: str

    # Ownership
    owner_id: str
    reservation_id: str | None

    # Lifecycle state
    status: LabletSessionStatus
    state_history: list[StateTransition]

    # Scheduling (set when SCHEDULED)
    worker_id: str | None
    timeslot_start: datetime
    timeslot_end: datetime

    # Lab binding — absorbed from LabletLabBinding (ADR-020 §2, §3)
    lab_record_id: str | None  # Direct 1:1 FK (was via LabletLabBinding)
    cml_lab_id: str | None  # CML lab identifier on the worker

    # Port allocation — absorbed from LabletRecordRun (ADR-020 §2)
    allocated_ports: dict[str, int] | None  # {"serial_1": 5041, "vnc_1": 5044}

    # Runtime tracking — absorbed from LabletRecordRun (ADR-020 §2)
    started_at: datetime | None  # When RUNNING state entered
    ended_at: datetime | None  # When session completed (STOPPED/TERMINATED)
    duration_seconds: float | None  # Computed on completion

    # Child entity FKs (ADR-021 §4)
    user_session_id: str | None  # → UserSession (LDS session tracking)
    grading_session_id: str | None  # → GradingSession
    score_report_id: str | None  # → ScoreReport

    # Assessment result — denormalized from ScoreReport for quick access
    grade_result: str | None  # "pass" / "fail" / None

    # Timestamps
    created_at: datetime
    scheduled_at: datetime | None
    terminated_at: datetime | None

    # Resource observation — ADR-030 "Learn from Live"
    observed_resources: dict | None  # Serialized ResourceObservation
    observed_ports: dict[str, int] | None  # Actual CML port allocations at runtime
    port_drift_detected: bool  # True if observed ports ≠ allocated ports
    observation_count: int  # Number of observations recorded
    observed_at: datetime | None  # Timestamp of last observation

    # Instantiation pipeline (ADR-031)
    instantiation_progress: dict | None  # Serialized InstantiationProgress

    def __init__(self) -> None:
        super().__init__()
        self.id = ""
        self.definition_id = ""
        self.definition_name = ""
        self.definition_version = ""

        self.owner_id = ""
        self.reservation_id = None

        self.status = LabletSessionStatus.PENDING
        self.state_history = []

        now = datetime.now(timezone.utc)
        self.timeslot_start = now
        self.timeslot_end = now

        self.worker_id = None
        self.lab_record_id = None
        self.cml_lab_id = None
        self.allocated_ports = None

        self.started_at = None
        self.ended_at = None
        self.duration_seconds = None

        self.user_session_id = None
        self.grading_session_id = None
        self.score_report_id = None
        self.grade_result = None

        self.created_at = now
        self.scheduled_at = None
        self.terminated_at = None

        # ADR-030: Resource observation fields
        self.observed_resources = None
        self.observed_ports = None
        self.port_drift_detected = False
        self.observation_count = 0
        self.observed_at = None

        # ADR-031: Instantiation pipeline
        self.instantiation_progress = None

    def _record_transition(
        self,
        from_state: LabletSessionStatus | None,
        to_state: LabletSessionStatus,
        triggered_by: str,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a state transition in the history."""
        transition = StateTransition(
            from_state=from_state,
            to_state=to_state,
            transitioned_at=datetime.now(timezone.utc),
            triggered_by=triggered_by,
            reason=reason,
            metadata=metadata,
        )
        self.state_history.append(transition)

    # --- Event Handlers (14 @dispatch handlers) ---

    @dispatch(LabletSessionCreatedDomainEvent)
    def on(self, event: LabletSessionCreatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the creation event to the state."""
        self.id = event.aggregate_id
        self.definition_id = event.definition_id
        self.definition_name = event.definition_name
        self.definition_version = event.definition_version
        self.owner_id = event.owner_id
        self.timeslot_start = event.timeslot_start
        self.timeslot_end = event.timeslot_end
        self.reservation_id = event.reservation_id
        self.created_at = event.created_at
        self.status = LabletSessionStatus.PENDING
        self._record_transition(
            from_state=None,
            to_state=LabletSessionStatus.PENDING,
            triggered_by="system",
            reason="Session created",
        )

    @dispatch(LabletSessionScheduledDomainEvent)
    def on(self, event: LabletSessionScheduledDomainEvent) -> None:  # type: ignore[override]
        """Apply the scheduled event to the state."""
        old_status = self.status
        self.worker_id = event.worker_id
        self.allocated_ports = event.allocated_ports
        self.lab_record_id = event.lab_record_id
        self.scheduled_at = event.scheduled_at
        self.status = LabletSessionStatus.SCHEDULED
        self._record_transition(
            from_state=old_status,
            to_state=LabletSessionStatus.SCHEDULED,
            triggered_by=event.scheduled_by,
            reason=f"Scheduled on worker {event.worker_id}",
            metadata={
                "allocated_ports": event.allocated_ports,
                "lab_record_id": event.lab_record_id,
            },
        )

    @dispatch(LabletSessionInstantiatingDomainEvent)
    def on(self, event: LabletSessionInstantiatingDomainEvent) -> None:  # type: ignore[override]
        """Apply the instantiating event to the state."""
        old_status = self.status
        self.status = LabletSessionStatus.INSTANTIATING
        self._record_transition(
            from_state=old_status,
            to_state=LabletSessionStatus.INSTANTIATING,
            triggered_by="lablet-controller",
            reason="Lab import/startup initiated",
        )

    @dispatch(LabletSessionReadyDomainEvent)
    def on(self, event: LabletSessionReadyDomainEvent) -> None:  # type: ignore[override]
        """Apply the ready event to the state."""
        old_status = self.status
        self.user_session_id = event.user_session_id
        self.cml_lab_id = event.cml_lab_id
        self.status = LabletSessionStatus.READY
        self._record_transition(
            from_state=old_status,
            to_state=LabletSessionStatus.READY,
            triggered_by="lablet-controller",
            reason="Infrastructure ready, UserSession provisioned",
            metadata={
                "user_session_id": event.user_session_id,
                "cml_lab_id": event.cml_lab_id,
            },
        )

    @dispatch(LabletSessionRunningDomainEvent)
    def on(self, event: LabletSessionRunningDomainEvent) -> None:  # type: ignore[override]
        """Apply the running event to the state."""
        old_status = self.status
        self.started_at = event.started_at
        self.status = LabletSessionStatus.RUNNING
        self._record_transition(
            from_state=old_status,
            to_state=LabletSessionStatus.RUNNING,
            triggered_by="lds-event",
            reason="User logged in, session active",
        )

    @dispatch(LabletSessionCollectingDomainEvent)
    def on(self, event: LabletSessionCollectingDomainEvent) -> None:  # type: ignore[override]
        """Apply the collecting event to the state."""
        old_status = self.status
        self.status = LabletSessionStatus.COLLECTING
        self._record_transition(
            from_state=old_status,
            to_state=LabletSessionStatus.COLLECTING,
            triggered_by="lablet-controller",
            reason="Assessment data collection started",
        )

    @dispatch(LabletSessionGradingDomainEvent)
    def on(self, event: LabletSessionGradingDomainEvent) -> None:  # type: ignore[override]
        """Apply the grading event to the state."""
        old_status = self.status
        self.grading_session_id = event.grading_session_id
        self.status = LabletSessionStatus.GRADING
        self._record_transition(
            from_state=old_status,
            to_state=LabletSessionStatus.GRADING,
            triggered_by="lablet-controller",
            reason="Grading started",
            metadata={"grading_session_id": event.grading_session_id},
        )

    @dispatch(LabletSessionScoreRecordedDomainEvent)
    def on(self, event: LabletSessionScoreRecordedDomainEvent) -> None:  # type: ignore[override]
        """Apply the score recorded event to the state.

        Note: This doesn't change the status — score is recorded while
        still in GRADING state. Transition to STOPPING happens next.
        """
        self.score_report_id = event.score_report_id
        self.grade_result = event.grade_result

    @dispatch(LabletSessionStoppingDomainEvent)
    def on(self, event: LabletSessionStoppingDomainEvent) -> None:  # type: ignore[override]
        """Apply the stopping event to the state."""
        old_status = self.status
        self.status = LabletSessionStatus.STOPPING
        self._record_transition(
            from_state=old_status,
            to_state=LabletSessionStatus.STOPPING,
            triggered_by="lablet-controller",
            reason=event.reason or "Session shutdown initiated",
        )

    @dispatch(LabletSessionStoppedDomainEvent)
    def on(self, event: LabletSessionStoppedDomainEvent) -> None:  # type: ignore[override]
        """Apply the stopped event to the state."""
        old_status = self.status
        self.ended_at = event.stopped_at
        self.duration_seconds = event.duration_seconds
        self.status = LabletSessionStatus.STOPPED
        self._record_transition(
            from_state=old_status,
            to_state=LabletSessionStatus.STOPPED,
            triggered_by="lablet-controller",
            reason="Session stopped",
        )

    @dispatch(LabletSessionArchivedDomainEvent)
    def on(self, event: LabletSessionArchivedDomainEvent) -> None:  # type: ignore[override]
        """Apply the archived event to the state."""
        old_status = self.status
        self.status = LabletSessionStatus.ARCHIVED
        self._record_transition(
            from_state=old_status,
            to_state=LabletSessionStatus.ARCHIVED,
            triggered_by=event.archived_by,
            reason="Session archived",
        )

    @dispatch(LabletSessionTerminatedDomainEvent)
    def on(self, event: LabletSessionTerminatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the terminated event to the state."""
        old_status = self.status
        self.terminated_at = event.terminated_at
        # Only set ended_at if not already set (e.g., from STOPPED → TERMINATED)
        if self.ended_at is None:
            self.ended_at = event.terminated_at
        # Only set duration if not already computed
        if self.duration_seconds is None and event.duration_seconds is not None:
            self.duration_seconds = event.duration_seconds
        self.status = LabletSessionStatus.TERMINATED
        self._record_transition(
            from_state=old_status,
            to_state=LabletSessionStatus.TERMINATED,
            triggered_by=event.terminated_by,
            reason=event.reason or "Session terminated",
        )

    @dispatch(LabletSessionPortsReleasedDomainEvent)
    def on(self, event: LabletSessionPortsReleasedDomainEvent) -> None:  # type: ignore[override]
        """Apply the ports released event to the state."""
        self.allocated_ports = None

    @dispatch(LabletSessionTimeslotExtendedDomainEvent)
    def on(self, event: LabletSessionTimeslotExtendedDomainEvent) -> None:  # type: ignore[override]
        """Apply the timeslot extended event to the state."""
        self.timeslot_end = event.new_timeslot_end

    @dispatch(LabletSessionRequeuedDomainEvent)
    def on(self, event: LabletSessionRequeuedDomainEvent) -> None:  # type: ignore[override]
        """Apply the requeued event to the state.

        Does NOT change status — only records the requeue in state_history
        so that change-detection mechanisms re-process this session.
        """
        self._record_transition(
            from_state=self.status,
            to_state=self.status,  # Same status — no change
            triggered_by=event.requeued_by,
            reason=event.reason or "Manual requeue for reconciliation",
            metadata={"requeue": True},
        )

    @dispatch(LabletSessionResourcesObservedDomainEvent)
    def on(self, event: LabletSessionResourcesObservedDomainEvent) -> None:  # type: ignore[override]
        """Apply the resource observation event to the state.

        Does NOT change status — this is a data-enrichment event (ADR-030).
        """
        self.observed_resources = event.observed_resources
        self.observed_ports = event.observed_ports
        self.port_drift_detected = event.port_drift_detected
        self.observation_count += 1
        self.observed_at = event.observed_at

    @dispatch(LabletSessionPortDriftDetectedDomainEvent)
    def on(self, event: LabletSessionPortDriftDetectedDomainEvent) -> None:  # type: ignore[override]
        """Apply the port drift detected event to the state.

        State already updated by ResourcesObserved handler — this handler
        exists for completeness (separate event enables independent handling).
        """
        pass  # port_drift_detected already set by ResourcesObserved handler

    @dispatch(LabletSessionObserveResourcesRequestedDomainEvent)
    def on(self, event: LabletSessionObserveResourcesRequestedDomainEvent) -> None:  # type: ignore[override]
        """Apply the observe resources requested event to the state.

        No-op for state changes — this event triggers an etcd projector
        that notifies lablet-controller to perform the observation.
        ADR-030 / AD-OLR-007.
        """
        self.updated_at = event.requested_at

    @dispatch(LabletSessionInstantiationProgressUpdatedDomainEvent)
    def on(self, event: LabletSessionInstantiationProgressUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Apply instantiation pipeline step update to the state.

        ADR-031: Updates the serialized instantiation_progress dict.
        Does NOT change session status — status transitions happen via
        their own events (e.g., INSTANTIATING → READY).
        """
        self.instantiation_progress = event.progress_data

    @dispatch(LabletSessionExpiredDomainEvent)
    def on(self, event: LabletSessionExpiredDomainEvent) -> None:  # type: ignore[override]
        """Apply the expired event to the state.

        ADR-031 / AD-TIMESLOT-001: Timeslot expiry is a terminal-like state.
        """
        old_status = self.status
        self.ended_at = event.expired_at
        if self.duration_seconds is None and event.duration_seconds is not None:
            self.duration_seconds = event.duration_seconds
        self.status = LabletSessionStatus.EXPIRED
        self._record_transition(
            from_state=old_status,
            to_state=LabletSessionStatus.EXPIRED,
            triggered_by="system",
            reason=event.reason or "Timeslot expired",
        )

    @dispatch(LabletSessionLabBoundDomainEvent)
    def on(self, event: LabletSessionLabBoundDomainEvent) -> None:  # type: ignore[override]
        """Apply lab binding to the session state.

        ADR-031 / ADR-032: Lab binding during the instantiation pipeline.
        Sets lab_record_id and denormalizes allocated_ports from the LabRecord.
        """
        self.lab_record_id = event.lab_record_id
        self.allocated_ports = dict(event.allocated_ports) if event.allocated_ports else None


class LabletSession(AggregateRoot[LabletSessionState, str]):
    """LabletSession aggregate — runtime lifecycle of a lab session.

    Represents a complete user experience from reservation through
    execution and grading to termination. Enforces valid state transitions
    and maintains a complete audit trail of state changes.

    Replaces LabletInstance aggregate (ADR-020).
    """

    def __init__(self) -> None:
        super().__init__()

    def id(self) -> str:
        """Return the aggregate identifier with a precise type."""
        aggregate_id = super().id()
        if aggregate_id is None:
            raise ValueError("LabletSession aggregate identifier has not been initialized")
        return cast(str, aggregate_id)

    def _validate_transition(self, to_state: LabletSessionStatus) -> None:
        """Validate that a state transition is allowed.

        Args:
            to_state: The target state

        Raises:
            InvalidStateTransitionError: If the transition is not allowed
        """
        valid_targets = LABLET_SESSION_VALID_TRANSITIONS.get(self.state.status, [])
        if to_state not in valid_targets:
            raise InvalidStateTransitionError(self.state.status, to_state)

    # --- Factory Method ---

    @staticmethod
    def create(
        definition_id: str,
        definition_name: str,
        definition_version: str,
        owner_id: str,
        timeslot_start: datetime,
        timeslot_end: datetime,
        reservation_id: str | None = None,
    ) -> "LabletSession":
        """Create a new LabletSession in PENDING state.

        Args:
            definition_id: ID of the LabletDefinition
            definition_name: Name of the definition (for display)
            definition_version: Version of the definition (pinned)
            owner_id: User ID who owns this session
            timeslot_start: When the lab session should start
            timeslot_end: When the lab session should end
            reservation_id: Optional external reservation reference

        Returns:
            A new LabletSession in PENDING state
        """
        if timeslot_end <= timeslot_start:
            raise ValueError("timeslot_end must be after timeslot_start")

        if timeslot_start < datetime.now(timezone.utc) - timedelta(minutes=5):
            raise ValueError("timeslot_start cannot be in the past")

        session = LabletSession()
        session.state.on(
            session.register_event(  # type: ignore
                LabletSessionCreatedDomainEvent(
                    aggregate_id=str(uuid4()),
                    definition_id=definition_id,
                    definition_name=definition_name,
                    definition_version=definition_version,
                    owner_id=owner_id,
                    timeslot_start=timeslot_start,
                    timeslot_end=timeslot_end,
                    reservation_id=reservation_id,
                    created_at=datetime.now(timezone.utc),
                )
            )
        )
        return session

    # --- State Transition Methods ---

    def schedule(
        self,
        worker_id: str,
        allocated_ports: dict[str, int],
        lab_record_id: str,
        scheduled_by: str,
    ) -> None:
        """Assign this session to a worker with port allocation and lab binding.

        Args:
            worker_id: ID of the CMLWorker to assign to
            allocated_ports: Port mapping from template names to actual ports
            lab_record_id: ID of the LabRecord (direct 1:1 binding, ADR-020 §3)
            scheduled_by: User or system that performed scheduling

        Raises:
            InvalidStateTransitionError: If not in PENDING state
        """
        self._validate_transition(LabletSessionStatus.SCHEDULED)
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionScheduledDomainEvent(
                    aggregate_id=self.id(),
                    worker_id=worker_id,
                    allocated_ports=allocated_ports,
                    lab_record_id=lab_record_id,
                    scheduled_at=datetime.now(timezone.utc),
                    scheduled_by=scheduled_by,
                )
            )
        )

    def start_instantiation(self) -> None:
        """Begin lab import and startup.

        Raises:
            InvalidStateTransitionError: If not in SCHEDULED state
        """
        self._validate_transition(LabletSessionStatus.INSTANTIATING)
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionInstantiatingDomainEvent(
                    aggregate_id=self.id(),
                    instantiation_started_at=datetime.now(timezone.utc),
                )
            )
        )

    def mark_ready(self, user_session_id: str, cml_lab_id: str) -> None:
        """Mark the session as ready after lab deployed and UserSession provisioned.

        Args:
            user_session_id: The UserSession entity ID (ADR-021)
            cml_lab_id: The CML lab identifier on the worker

        Raises:
            InvalidStateTransitionError: If not in INSTANTIATING state
        """
        self._validate_transition(LabletSessionStatus.READY)
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionReadyDomainEvent(
                    aggregate_id=self.id(),
                    user_session_id=user_session_id,
                    cml_lab_id=cml_lab_id,
                    ready_at=datetime.now(timezone.utc),
                )
            )
        )

    def mark_running(self) -> None:
        """Mark the session as running after user logs in via LDS.

        Triggered by LDS CloudEvent (lds.session.started).

        Raises:
            InvalidStateTransitionError: If not in READY state
        """
        self._validate_transition(LabletSessionStatus.RUNNING)
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionRunningDomainEvent(
                    aggregate_id=self.id(),
                    started_at=datetime.now(timezone.utc),
                )
            )
        )

    def start_collection(self) -> None:
        """Begin assessment data collection.

        Raises:
            InvalidStateTransitionError: If not in RUNNING state
        """
        self._validate_transition(LabletSessionStatus.COLLECTING)
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionCollectingDomainEvent(
                    aggregate_id=self.id(),
                    collection_started_at=datetime.now(timezone.utc),
                )
            )
        )

    def start_grading(self, grading_session_id: str) -> None:
        """Begin grading with the GradingEngine.

        Args:
            grading_session_id: The GradingSession entity ID (ADR-021)

        Raises:
            InvalidStateTransitionError: If not in COLLECTING state
        """
        self._validate_transition(LabletSessionStatus.GRADING)
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionGradingDomainEvent(
                    aggregate_id=self.id(),
                    grading_session_id=grading_session_id,
                    grading_started_at=datetime.now(timezone.utc),
                )
            )
        )

    def record_score(self, score_report_id: str, grade_result: str) -> None:
        """Record the grading result.

        Note: This doesn't change state — the session stays in GRADING.
        Call start_stopping() after recording the score.

        Args:
            score_report_id: The ScoreReport entity ID (ADR-021)
            grade_result: "pass" or "fail" (denormalized for quick access)
        """
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionScoreRecordedDomainEvent(
                    aggregate_id=self.id(),
                    score_report_id=score_report_id,
                    grade_result=grade_result,
                    scored_at=datetime.now(timezone.utc),
                )
            )
        )

    def start_stopping(self, reason: str | None = None) -> None:
        """Begin session shutdown.

        Can be called from RUNNING, COLLECTING, or GRADING states.

        Args:
            reason: Optional reason for stopping

        Raises:
            InvalidStateTransitionError: If not in a valid state
        """
        self._validate_transition(LabletSessionStatus.STOPPING)
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionStoppingDomainEvent(
                    aggregate_id=self.id(),
                    stopping_started_at=datetime.now(timezone.utc),
                    reason=reason,
                )
            )
        )

    def mark_stopped(self) -> None:
        """Mark the session as stopped.

        Computes duration_seconds from started_at if the session was running.

        Raises:
            InvalidStateTransitionError: If not in STOPPING state
        """
        self._validate_transition(LabletSessionStatus.STOPPED)
        now = datetime.now(timezone.utc)
        duration = None
        if self.state.started_at:
            duration = (now - self.state.started_at).total_seconds()
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionStoppedDomainEvent(
                    aggregate_id=self.id(),
                    stopped_at=now,
                    duration_seconds=duration,
                )
            )
        )

    def archive(self, archived_by: str) -> None:
        """Archive this session for historical records.

        Args:
            archived_by: User who triggered archival

        Raises:
            InvalidStateTransitionError: If not in STOPPED state
        """
        self._validate_transition(LabletSessionStatus.ARCHIVED)
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionArchivedDomainEvent(
                    aggregate_id=self.id(),
                    archived_at=datetime.now(timezone.utc),
                    archived_by=archived_by,
                )
            )
        )

    def terminate(self, terminated_by: str, reason: str | None = None) -> None:
        """Terminate this session (emergency/force termination).

        Can be called from most states. Computes duration if applicable.

        Args:
            terminated_by: User or system that triggered termination
            reason: Optional reason for termination

        Raises:
            InvalidStateTransitionError: If already TERMINATED
        """
        self._validate_transition(LabletSessionStatus.TERMINATED)
        now = datetime.now(timezone.utc)
        duration = None
        if self.state.started_at and self.state.ended_at is None:
            duration = (now - self.state.started_at).total_seconds()
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionTerminatedDomainEvent(
                    aggregate_id=self.id(),
                    terminated_at=now,
                    terminated_by=terminated_by,
                    reason=reason,
                    from_state=self.state.status.value,
                    duration_seconds=duration,
                )
            )
        )

    def release_ports(self) -> None:
        """Release allocated ports back to the worker pool.

        Should be called during termination or after stopping.
        """
        if self.state.worker_id and self.state.allocated_ports:
            self.state.on(
                self.register_event(  # type: ignore
                    LabletSessionPortsReleasedDomainEvent(
                        aggregate_id=self.id(),
                        worker_id=self.state.worker_id,
                        released_ports=self.state.allocated_ports,
                        released_at=datetime.now(timezone.utc),
                    )
                )
            )

    def extend_timeslot(self, new_end: datetime, extended_by: str) -> None:
        """Extend the timeslot for this session.

        Args:
            new_end: New end time (must be after current end)
            extended_by: User who requested the extension

        Raises:
            ValueError: If new_end is not after current end
        """
        if new_end <= self.state.timeslot_end:
            raise ValueError("new_end must be after current timeslot_end")

        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionTimeslotExtendedDomainEvent(
                    aggregate_id=self.id(),
                    old_timeslot_end=self.state.timeslot_end,
                    new_timeslot_end=new_end,
                    extended_by=extended_by,
                    extended_at=datetime.now(timezone.utc),
                )
            )
        )

    def requeue(self, requeued_by: str, reason: str | None = None) -> None:
        """Re-queue this session for reconciliation.

        Does NOT change the session status. Records a requeue event
        that bumps updated_at (via repository save) and records the
        action in state_history for audit purposes.

        Only valid for non-terminal states.

        Args:
            requeued_by: User or system that triggered the requeue
            reason: Optional reason for re-queuing

        Raises:
            InvalidStateTransitionError: If session is in a terminal state
        """
        terminal_states = {LabletSessionStatus.TERMINATED, LabletSessionStatus.ARCHIVED}
        if self.state.status in terminal_states:
            raise InvalidStateTransitionError(
                self.state.status,
                self.state.status,
                f"Cannot requeue a session in {self.state.status.value} state",
            )

        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionRequeuedDomainEvent(
                    aggregate_id=self.id(),
                    requeued_at=datetime.now(timezone.utc),
                    requeued_by=requeued_by,
                    reason=reason,
                    current_status=self.state.status.value,
                )
            )
        )

    # --- Resource Observation (ADR-030) ---

    def record_resource_observation(
        self,
        observed_resources: dict,
        observed_ports: dict[str, int],
    ) -> None:
        """Record runtime resource observations from CML.

        Compares observed_ports against allocated_ports to detect drift.
        Emits LabletSessionResourcesObservedDomainEvent always.
        Additionally emits LabletSessionPortDriftDetectedDomainEvent if drift found.

        Args:
            observed_resources: Serialized ResourceObservation dict
            observed_ports: Actual CML port allocations {port_name: port_number}
        """
        now = datetime.now(timezone.utc)

        # Detect port drift
        allocated = self.state.allocated_ports or {}
        drift_detected = False
        drift_details: dict[str, Any] = {"added": {}, "removed": {}, "changed": {}}

        if allocated and observed_ports:
            allocated_set = set(allocated.keys())
            observed_set = set(observed_ports.keys())

            # Ports in CML but not in LCM allocation
            for name in observed_set - allocated_set:
                drift_details["added"][name] = observed_ports[name]
                drift_detected = True

            # Ports in LCM allocation but not in CML
            for name in allocated_set - observed_set:
                drift_details["removed"][name] = allocated[name]
                drift_detected = True

            # Ports present in both but with different port numbers
            for name in allocated_set & observed_set:
                if allocated[name] != observed_ports[name]:
                    drift_details["changed"][name] = {
                        "allocated": allocated[name],
                        "observed": observed_ports[name],
                    }
                    drift_detected = True

        # Always emit the observation event
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionResourcesObservedDomainEvent(
                    aggregate_id=self.id(),
                    observed_resources=observed_resources,
                    observed_ports=observed_ports,
                    port_drift_detected=drift_detected,
                    observed_at=now,
                )
            )
        )

        # Emit drift event if detected
        if drift_detected:
            self.state.on(
                self.register_event(  # type: ignore
                    LabletSessionPortDriftDetectedDomainEvent(
                        aggregate_id=self.id(),
                        allocated_ports=allocated,
                        observed_ports=observed_ports,
                        drift_details=drift_details,
                        detected_at=now,
                    )
                )
            )

    def request_resource_observation(self, requested_by: str = "") -> None:
        """Request resource observation (manual trigger).

        Emits event for etcd projector to notify lablet-controller.
        Does NOT change session status.

        ADR-030 / AD-OLR-007: Manual trigger via reactive etcd watch.

        Args:
            requested_by: User/system requesting the observation.
        """
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionObserveResourcesRequestedDomainEvent(
                    aggregate_id=self.id(),
                    requested_by=requested_by,
                    requested_at=datetime.now(timezone.utc),
                )
            )
        )

    # --- Instantiation Pipeline (ADR-031) ---

    def update_instantiation_progress(
        self,
        step_name: str,
        step_status: str,
        progress_data: dict,
    ) -> None:
        """Update instantiation pipeline progress after a step completes.

        Does NOT change session status — the pipeline progress is tracked
        independently. Status transitions (e.g., INSTANTIATING → READY)
        happen via their own dedicated methods.

        ADR-031: Checkpoint-based instantiation pipeline.

        Args:
            step_name: Name of the completed step (e.g., "ports_alloc").
            step_status: Step outcome — "completed", "failed", or "skipped".
            progress_data: Full serialized InstantiationProgress dict.
        """
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionInstantiationProgressUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    step_name=step_name,
                    step_status=step_status,
                    progress_data=progress_data,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        )

    def bind_lab(self, lab_record_id: str, allocated_ports: dict[str, int] | None = None) -> None:
        """Bind a LabRecord to this session during the instantiation pipeline.

        ADR-031 / ADR-032: Lab binding is a pipeline step, not part of
        scheduling. Sets lab_record_id and denormalizes allocated_ports
        from the LabRecord for downstream consumption.

        Args:
            lab_record_id: The LabRecord aggregate ID to bind.
            allocated_ports: Port mapping to denormalize from LabRecord.
        """
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionLabBoundDomainEvent(
                    aggregate_id=self.id(),
                    lab_record_id=lab_record_id,
                    allocated_ports=allocated_ports or {},
                    bound_at=datetime.now(timezone.utc),
                )
            )
        )

    def expire(self, reason: str = "timeslot_expired") -> None:
        """Expire this session due to timeslot expiry.

        ADR-031 / AD-TIMESLOT-001: Timeslot-centric lifecycle.
        Transitions to EXPIRED from any active state. Downstream
        cleanup (LabRunRecord closure, LabRecord unbind, capacity release)
        is handled by the command handler — NOT port release (ports
        belong to LabRecord, not session).

        Args:
            reason: Expiry reason.

        Raises:
            InvalidStateTransitionError: If already in a terminal state.
        """
        self._validate_transition(LabletSessionStatus.EXPIRED)
        now = datetime.now(timezone.utc)
        duration = None
        if self.state.started_at and self.state.ended_at is None:
            duration = (now - self.state.started_at).total_seconds()
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionExpiredDomainEvent(
                    aggregate_id=self.id(),
                    expired_at=now,
                    reason=reason,
                    from_state=self.state.status.value,
                    duration_seconds=duration,
                )
            )
        )

    # --- Computed Properties ---

    @property
    def is_terminal(self) -> bool:
        """Check if this session is in a terminal state."""
        return self.state.status == LabletSessionStatus.TERMINATED

    @property
    def is_active(self) -> bool:
        """Check if this session is in an active (running/processing) state."""
        return self.state.status in (
            LabletSessionStatus.RUNNING,
            LabletSessionStatus.COLLECTING,
            LabletSessionStatus.GRADING,
        )

    @property
    def is_pending_execution(self) -> bool:
        """Check if this session is waiting to be executed."""
        return self.state.status in (
            LabletSessionStatus.PENDING,
            LabletSessionStatus.SCHEDULED,
        )

    @property
    def can_be_terminated(self) -> bool:
        """Check if this session can be terminated."""
        return LabletSessionStatus.TERMINATED in LABLET_SESSION_VALID_TRANSITIONS.get(self.state.status, [])

    @property
    def duration_minutes(self) -> int:
        """Calculate the scheduled duration in minutes."""
        delta = self.state.timeslot_end - self.state.timeslot_start
        return int(delta.total_seconds() / 60)

    @property
    def actual_duration_minutes(self) -> int | None:
        """Calculate actual execution duration if started and stopped."""
        if not self.state.started_at:
            return None
        end_time = self.state.ended_at or self.state.terminated_at or datetime.now(timezone.utc)
        delta = end_time - self.state.started_at
        return int(delta.total_seconds() / 60)

    @property
    def transition_count(self) -> int:
        """Return the number of state transitions."""
        return len(self.state.state_history)

    @property
    def last_transition(self) -> StateTransition | None:
        """Return the most recent state transition."""
        if self.state.state_history:
            return self.state.state_history[-1]
        return None

    @property
    def has_user_session(self) -> bool:
        """Check if a UserSession has been linked."""
        return self.state.user_session_id is not None

    @property
    def has_grading_session(self) -> bool:
        """Check if a GradingSession has been linked."""
        return self.state.grading_session_id is not None

    @property
    def has_score_report(self) -> bool:
        """Check if a ScoreReport has been recorded."""
        return self.state.score_report_id is not None
