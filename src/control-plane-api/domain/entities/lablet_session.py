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
    LabletSessionDesiredStatusUpdatedDomainEvent,
    LabletSessionExpiredDomainEvent,
    LabletSessionGradingDomainEvent,
    LabletSessionInstantiatingDomainEvent,
    LabletSessionLabBoundDomainEvent,
    LabletSessionObserveResourcesRequestedDomainEvent,
    LabletSessionPipelineProgressUpdatedDomainEvent,
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
from domain.lifecycles import LABLET_SESSION_LIFECYCLE
from lcm_core.domain.entities.timed_resource import TimedResourceState
from lcm_core.domain.value_objects.managed_lifecycle import ManagedLifecycle
from lcm_core.domain.value_objects.state_transition import StateTransition
from lcm_core.domain.value_objects.timeslot import Timeslot
from multipledispatch import dispatch
from neuroglia.data.abstractions import AggregateRoot


class InvalidStateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, from_state: LabletSessionStatus, to_state: LabletSessionStatus, message: str | None = None):
        self.from_state = from_state
        self.to_state = to_state
        self.message = message or f"Invalid transition from {from_state.value} to {to_state.value}"
        super().__init__(self.message)


class LabletSessionState(TimedResourceState):
    """Encapsulates the persisted state for the LabletSession aggregate.

    Inheritance hierarchy (ADR-036 §2.1.4):
        AggregateState[str]  (Neuroglia)
            └── ResourceState  (Layer 1 — status, desired_status, state_history)
                    └── TimedResourceState  (Layer 2 — timeslot, lifecycle, timestamps)
                            └── LabletSessionState  ← YOU ARE HERE

    Inherits from TimedResourceState:
        - resource_type, owner_id, pipeline_progress (from ResourceState)
        - timeslot, lifecycle (from TimedResourceState)
        - started_at, ended_at, duration_seconds, terminated_at (from TimedResourceState)

    Shadows parent fields with typed versions:
        - status: LabletSessionStatus (parent: str)
        - desired_status: LabletSessionStatus (parent: str | None)
        - state_history: list[dict] (parent: list)

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
    desired_status: LabletSessionStatus  # Spec: What user/system wants (reconciliation target)
    state_history: list[dict]

    # Scheduling (set when SCHEDULED)
    worker_id: str | None

    # Lab binding — absorbed from LabletLabBinding (ADR-020 §2, §3)
    lab_record_id: str | None  # Direct 1:1 FK (was via LabletLabBinding)
    cml_lab_id: str | None  # CML lab identifier on the worker
    cml_lab_title: str | None  # CML lab title for display

    # Port allocation — absorbed from LabletRecordRun (ADR-020 §2)
    allocated_ports: dict[str, int] | None  # {"serial_1": 5041, "vnc_1": 5044}

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

    # Generic pipeline progress — keyed by pipeline name (ADR-034 Sprint E)
    # All pipelines (instantiate, teardown, collect_evidence, compute_grading)
    # are stored here.
    pipeline_progress: dict | None  # {"instantiate": {...}, "teardown": {...}, ...}

    def __init__(self) -> None:
        super().__init__()
        self.resource_type = "lablet_session"
        self.id = ""
        self.definition_id = ""
        self.definition_name = ""
        self.definition_version = ""

        self.owner_id = ""
        self.reservation_id = None

        self.status = LabletSessionStatus.PENDING
        self.desired_status = LabletSessionStatus.RUNNING  # Default: user wants session running
        self.state_history = []

        now = datetime.now(timezone.utc)

        self.worker_id = None
        self.lab_record_id = None
        self.cml_lab_id = None
        self.allocated_ports = None

        self.user_session_id = None
        self.grading_session_id = None
        self.score_report_id = None
        self.grade_result = None

        self.created_at = now
        self.updated_at = now
        self.scheduled_at = None
        self.terminated_at = None

        # ADR-030: Resource observation fields
        self.observed_resources = None
        self.observed_ports = None
        self.port_drift_detected = False
        self.observation_count = 0
        self.observed_at = None

        # ADR-034 Sprint E: Generic pipeline progress
        self.pipeline_progress = None

    # --- Timeslot VO backward-compatible accessors (ADR-036 Batch F) ---

    @property
    def timeslot_start(self) -> datetime:
        """Backward-compatible accessor — reads from Timeslot VO."""
        ts = self.get_timeslot()
        return ts.start if ts else self.created_at

    @timeslot_start.setter
    def timeslot_start(self, value: datetime) -> None:
        """Legacy setter for Neuroglia deserialization of old documents."""
        object.__setattr__(self, "_legacy_ts_start", value)

    @property
    def timeslot_end(self) -> datetime:
        """Backward-compatible accessor — reads from Timeslot VO."""
        ts = self.get_timeslot()
        return ts.end if ts else self.created_at

    @timeslot_end.setter
    def timeslot_end(self, value: datetime) -> None:
        """Legacy setter for Neuroglia deserialization of old documents."""
        object.__setattr__(self, "_legacy_ts_end", value)

    def get_timeslot(self) -> Timeslot | None:
        """Deserialize timeslot with legacy field fallback.

        Overrides TimedResourceState.get_timeslot() to support migration
        from legacy timeslot_start/timeslot_end fields (ADR-036 Batch F).
        """
        result = super().get_timeslot()
        if result is not None:
            return result
        # Fallback: legacy documents with direct timeslot_start/timeslot_end
        ts_start = getattr(self, "_legacy_ts_start", None)
        ts_end = getattr(self, "_legacy_ts_end", None)
        if ts_start is not None and ts_end is not None and isinstance(ts_start, datetime) and isinstance(ts_end, datetime) and ts_end > ts_start:
            return Timeslot(start=ts_start, end=ts_end)
        return None

    def _record_transition(
        self,
        from_state: str | None,
        to_state: str,
        triggered_by: str = "system",
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a state transition in the history.

        Overrides ResourceState._record_transition() for two reasons:
        1. Stores transitions as dicts (via StateTransition.to_dict()) instead
           of StateTransition objects, for Neuroglia serialization compatibility.
        2. Maintains updated_at behavior consistent with ResourceState base class.

        ADR-036 Batch F: Follows CMLWorkerState pattern from Batch E.
        """
        transition = StateTransition(
            from_state=from_state,
            to_state=to_state,
            transitioned_at=datetime.now(timezone.utc),
            triggered_by=triggered_by,
            reason=reason,
            metadata=metadata,
        )
        self.state_history.append(transition.to_dict())
        self.updated_at = datetime.now(timezone.utc)

    # --- Event Handlers (14 @dispatch handlers) ---

    @dispatch(LabletSessionCreatedDomainEvent)
    def on(self, event: LabletSessionCreatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the creation event to the state."""
        self.id = event.aggregate_id
        self.definition_id = event.definition_id
        self.definition_name = event.definition_name
        self.definition_version = event.definition_version
        self.owner_id = event.owner_id
        self.reservation_id = event.reservation_id
        self.created_at = event.created_at
        self.updated_at = event.created_at
        self.status = LabletSessionStatus.PENDING
        self.desired_status = LabletSessionStatus.RUNNING  # Default: user wants session running
        # TimedResource: Timeslot VO and lifecycle (ADR-036 Batch F)
        self.set_timeslot(Timeslot(start=event.timeslot_start, end=event.timeslot_end))
        self.lifecycle = ManagedLifecycle(
            phases=LABLET_SESSION_LIFECYCLE.phases,
            current_phase="schedule",
        ).to_dict()
        self._record_transition(
            from_state=None,
            to_state=LabletSessionStatus.PENDING.value,
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
            from_state=old_status.value,
            to_state=LabletSessionStatus.SCHEDULED.value,
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
            from_state=old_status.value,
            to_state=LabletSessionStatus.INSTANTIATING.value,
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
            from_state=old_status.value,
            to_state=LabletSessionStatus.READY.value,
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
            from_state=old_status.value,
            to_state=LabletSessionStatus.RUNNING.value,
            triggered_by="lds-event",
            reason="User logged in, session active",
        )

    @dispatch(LabletSessionCollectingDomainEvent)
    def on(self, event: LabletSessionCollectingDomainEvent) -> None:  # type: ignore[override]
        """Apply the collecting event to the state."""
        old_status = self.status
        self.status = LabletSessionStatus.COLLECTING
        self._record_transition(
            from_state=old_status.value,
            to_state=LabletSessionStatus.COLLECTING.value,
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
            from_state=old_status.value,
            to_state=LabletSessionStatus.GRADING.value,
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
            from_state=old_status.value,
            to_state=LabletSessionStatus.STOPPING.value,
            triggered_by="lablet-controller",
            reason=event.reason or "Session shutdown initiated",
        )

    @dispatch(LabletSessionStoppedDomainEvent)
    def on(self, event: LabletSessionStoppedDomainEvent) -> None:  # type: ignore[override]
        """Apply the stopped event to the state."""
        old_status = self.status
        self.ended_at = event.stopped_at
        self._compute_duration()
        self.status = LabletSessionStatus.STOPPED
        self._record_transition(
            from_state=old_status.value,
            to_state=LabletSessionStatus.STOPPED.value,
            triggered_by="lablet-controller",
            reason="Session stopped",
        )

    @dispatch(LabletSessionArchivedDomainEvent)
    def on(self, event: LabletSessionArchivedDomainEvent) -> None:  # type: ignore[override]
        """Apply the archived event to the state."""
        old_status = self.status
        self.status = LabletSessionStatus.ARCHIVED
        self._record_transition(
            from_state=old_status.value,
            to_state=LabletSessionStatus.ARCHIVED.value,
            triggered_by=event.archived_by,
            reason="Session archived",
        )

    @dispatch(LabletSessionTerminatedDomainEvent)
    def on(self, event: LabletSessionTerminatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the terminated event to the state."""
        old_status = self.status
        self.terminated_at = event.terminated_at
        self.desired_status = LabletSessionStatus.TERMINATED
        # Only set ended_at if not already set (e.g., from STOPPED → TERMINATED)
        if self.ended_at is None:
            self.ended_at = event.terminated_at
        # Compute duration from started_at/ended_at if not already set
        if self.duration_seconds is None:
            self._compute_duration()
        self.status = LabletSessionStatus.TERMINATED
        self._record_transition(
            from_state=old_status.value,
            to_state=LabletSessionStatus.TERMINATED.value,
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
        current_ts = self.get_timeslot()
        if current_ts:
            new_ts = current_ts.extend(event.new_timeslot_end)
            self.set_timeslot(new_ts)

    @dispatch(LabletSessionRequeuedDomainEvent)
    def on(self, event: LabletSessionRequeuedDomainEvent) -> None:  # type: ignore[override]
        """Apply the requeued event to the state.

        Does NOT change status — only records the requeue in state_history
        so that change-detection mechanisms re-process this session.
        """
        self._record_transition(
            from_state=self.status.value,
            to_state=self.status.value,  # Same status — no change
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

    @dispatch(LabletSessionPipelineProgressUpdatedDomainEvent)
    def on(self, event: LabletSessionPipelineProgressUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Apply pipeline progress update to the state.

        ADR-034 Sprint E: Stores progress per pipeline name in the
        pipeline_progress dict.
        """
        if self.pipeline_progress is None:
            self.pipeline_progress = {}
        self.pipeline_progress[event.pipeline_name] = event.progress_data

    @dispatch(LabletSessionDesiredStatusUpdatedDomainEvent)
    def on(self, event: LabletSessionDesiredStatusUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the desired status updated event to the state (spec change).

        ADR-034 Sprint E: Follows CMLWorker desired_status pattern (ADR-015).
        """
        self.desired_status = LabletSessionStatus(event.new_desired_status)

    @dispatch(LabletSessionExpiredDomainEvent)
    def on(self, event: LabletSessionExpiredDomainEvent) -> None:  # type: ignore[override]
        """Apply the expired event to the state.

        ADR-031 / AD-TIMESLOT-001: Timeslot expiry is a terminal-like state.
        """
        old_status = self.status
        self.ended_at = event.expired_at
        self._compute_duration()
        self.status = LabletSessionStatus.EXPIRED
        self._record_transition(
            from_state=old_status.value,
            to_state=LabletSessionStatus.EXPIRED.value,
            triggered_by="system",
            reason=event.reason or "Timeslot expired",
        )

    @dispatch(LabletSessionLabBoundDomainEvent)
    def on(self, event: LabletSessionLabBoundDomainEvent) -> None:  # type: ignore[override]
        """Apply lab binding to the session state.

        ADR-031 / ADR-032: Lab binding during the instantiation pipeline.
        Sets lab_record_id, denormalizes allocated_ports from the LabRecord,
        and sets cml_lab_id/cml_lab_title early (available before mark_ready).
        """
        self.lab_record_id = event.lab_record_id
        self.allocated_ports = dict(event.allocated_ports) if event.allocated_ports else None
        if event.cml_lab_id:
            self.cml_lab_id = event.cml_lab_id
        if event.cml_lab_title:
            self.cml_lab_title = event.cml_lab_title


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

    # --- Pipeline Progress (ADR-034 Sprint E) ---

    def update_pipeline_progress(
        self,
        pipeline_name: str,
        step_name: str,
        step_status: str,
        progress_data: dict,
    ) -> None:
        """Update pipeline progress after a step completes.

        ADR-034 Sprint E: Tracks progress for all pipeline types
        (instantiate, teardown, collect_evidence, compute_grading).

        Does NOT change session status — the pipeline progress is tracked
        independently. Status transitions happen via dedicated methods.

        Args:
            pipeline_name: Pipeline type (e.g., "instantiate", "teardown").
            step_name: Name of the completed step.
            step_status: Step outcome — "completed", "failed", or "skipped".
            progress_data: Full serialized progress dict for this pipeline.
        """
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionPipelineProgressUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    pipeline_name=pipeline_name,
                    step_name=step_name,
                    step_status=step_status,
                    progress_data=progress_data,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        )

    def update_desired_status(
        self,
        new_desired_status: LabletSessionStatus,
        requested_by: str | None = None,
        reason: str | None = None,
    ) -> bool:
        """Update the desired status (spec) — what the user/system wants.

        ADR-034 Sprint E / ADR-015 pattern: Follows the Kubernetes-like
        reconciliation model. The lablet-controller watches etcd for
        desired_status changes and reconciles actual state accordingly.

        Args:
            new_desired_status: Target lifecycle state.
            requested_by: User or system that requested the change.
            reason: Optional reason for the change.

        Returns:
            True if the desired_status changed, False if already at target.
        """
        if self.state.desired_status == new_desired_status:
            return False

        old_desired_status = self.state.desired_status
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionDesiredStatusUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    old_desired_status=old_desired_status.value,
                    new_desired_status=new_desired_status.value,
                    updated_at=datetime.now(timezone.utc),
                    requested_by=requested_by,
                    reason=reason,
                )
            )
        )
        return True

    def bind_lab(
        self,
        lab_record_id: str,
        allocated_ports: dict[str, int] | None = None,
        cml_lab_id: str | None = None,
        cml_lab_title: str | None = None,
    ) -> None:
        """Bind a LabRecord to this session during the instantiation pipeline.

        ADR-031 / ADR-032: Lab binding is a pipeline step, not part of
        scheduling. Sets lab_record_id and denormalizes allocated_ports
        from the LabRecord for downstream consumption. Also sets cml_lab_id
        and cml_lab_title early so they are available before mark_ready.

        Args:
            lab_record_id: The LabRecord aggregate ID to bind.
            allocated_ports: Port mapping to denormalize from LabRecord.
            cml_lab_id: CML lab identifier on the worker.
            cml_lab_title: CML lab title for display.
        """
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionLabBoundDomainEvent(
                    aggregate_id=self.id(),
                    lab_record_id=lab_record_id,
                    allocated_ports=allocated_ports or {},
                    bound_at=datetime.now(timezone.utc),
                    cml_lab_id=cml_lab_id,
                    cml_lab_title=cml_lab_title,
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
        ts = self.state.get_timeslot()
        if ts:
            return int(ts.duration.total_seconds() / 60)
        return 0

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
        """Return the most recent state transition (reconstructed from dict)."""
        if self.state.state_history:
            return StateTransition.from_dict(self.state.state_history[-1])
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
