"""Domain events for LabletSession aggregate state transitions.

Each event represents a state transition in the LabletSession lifecycle,
following the CloudEvent specification for event-driven integration.

Phase 7C: Replaces lablet_instance_events.py. CloudEvent type prefix
changed from ``lablet_instance.*`` to ``lablet_session.*``.

ADR-020: Session Entity Model Redesign
ADR-021: Child Entity Architecture
"""

from dataclasses import dataclass
from datetime import datetime

from neuroglia.data.abstractions import DomainEvent
from neuroglia.eventing.cloud_events.decorators import cloudevent

# ---------------------------------------------------------------------------
# 1. Created — Initial creation in PENDING state
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.created.v1")
@dataclass
class LabletSessionCreatedDomainEvent(DomainEvent):
    """Event raised when a new LabletSession is created.

    Initial state: PENDING
    """

    aggregate_id: str
    definition_id: str
    definition_name: str
    definition_version: str
    owner_id: str
    timeslot_start: datetime
    timeslot_end: datetime
    reservation_id: str | None
    created_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        definition_id: str,
        definition_name: str,
        definition_version: str,
        owner_id: str,
        timeslot_start: datetime,
        timeslot_end: datetime,
        reservation_id: str | None,
        created_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.definition_id = definition_id
        self.definition_name = definition_name
        self.definition_version = definition_version
        self.owner_id = owner_id
        self.timeslot_start = timeslot_start
        self.timeslot_end = timeslot_end
        self.reservation_id = reservation_id
        self.created_at = created_at


# ---------------------------------------------------------------------------
# 2. Scheduled — Worker + ports + lab_record assigned
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.scheduled.v1")
@dataclass
class LabletSessionScheduledDomainEvent(DomainEvent):
    """Event raised when a LabletSession is assigned to a worker.

    Transition: PENDING → SCHEDULED

    Absorbed from LabletLabBinding (ADR-020 §2): lab_record_id is set here
    as a direct 1:1 FK on the session instead of via a separate binding entity.
    """

    aggregate_id: str
    worker_id: str
    allocated_ports: dict[str, int]
    lab_record_id: str  # Direct binding (absorbed from LabletLabBinding)
    scheduled_at: datetime
    scheduled_by: str

    def __init__(
        self,
        aggregate_id: str,
        worker_id: str,
        allocated_ports: dict[str, int],
        lab_record_id: str,
        scheduled_at: datetime,
        scheduled_by: str,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.worker_id = worker_id
        self.allocated_ports = allocated_ports
        self.lab_record_id = lab_record_id
        self.scheduled_at = scheduled_at
        self.scheduled_by = scheduled_by


# ---------------------------------------------------------------------------
# 3. Instantiating — CML lab import + LDS provisioning started
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.instantiating.v1")
@dataclass
class LabletSessionInstantiatingDomainEvent(DomainEvent):
    """Event raised when lab import/startup begins.

    Transition: SCHEDULED → INSTANTIATING
    """

    aggregate_id: str
    instantiation_started_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        instantiation_started_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.instantiation_started_at = instantiation_started_at


# ---------------------------------------------------------------------------
# 4. Ready — Infrastructure provisioned, awaiting user login
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.ready.v1")
@dataclass
class LabletSessionReadyDomainEvent(DomainEvent):
    """Event raised when infrastructure is ready and UserSession provisioned.

    Transition: INSTANTIATING → READY

    The CML lab is imported and running, the UserSession (LDS session) is
    created, and the user can now log in via the login URL on the UserSession.
    """

    aggregate_id: str
    user_session_id: str  # FK → UserSession (ADR-021)
    cml_lab_id: str  # CML lab identifier on the worker
    ready_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        user_session_id: str,
        cml_lab_id: str,
        ready_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.user_session_id = user_session_id
        self.cml_lab_id = cml_lab_id
        self.ready_at = ready_at


# ---------------------------------------------------------------------------
# 5. Running — User actively using the lab session
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.running.v1")
@dataclass
class LabletSessionRunningDomainEvent(DomainEvent):
    """Event raised when the user logs in and the session becomes active.

    Transition: READY → RUNNING
    Triggered by: LDS CloudEvent (lds.session.started)
    """

    aggregate_id: str
    started_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        started_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.started_at = started_at


# ---------------------------------------------------------------------------
# 6. Collecting — Assessment data collection in progress
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.collecting.v1")
@dataclass
class LabletSessionCollectingDomainEvent(DomainEvent):
    """Event raised when assessment data collection begins.

    Transition: RUNNING → COLLECTING
    """

    aggregate_id: str
    collection_started_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        collection_started_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.collection_started_at = collection_started_at


# ---------------------------------------------------------------------------
# 7. Grading — GradingEngine scoring in progress
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.grading.v1")
@dataclass
class LabletSessionGradingDomainEvent(DomainEvent):
    """Event raised when grading begins.

    Transition: COLLECTING → GRADING

    The GradingSession child entity is created first, and its ID
    is linked to the parent LabletSession here.
    """

    aggregate_id: str
    grading_session_id: str  # FK → GradingSession (ADR-021)
    grading_started_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        grading_session_id: str,
        grading_started_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.grading_session_id = grading_session_id
        self.grading_started_at = grading_started_at


# ---------------------------------------------------------------------------
# 8. ScoreRecorded — Grading complete, score report available
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.score_recorded.v1")
@dataclass
class LabletSessionScoreRecordedDomainEvent(DomainEvent):
    """Event raised when a score report is finalized.

    This event records the score but does NOT change the session status.
    The next transition is typically GRADING → STOPPING.
    """

    aggregate_id: str
    score_report_id: str  # FK → ScoreReport (ADR-021)
    grade_result: str  # "pass" / "fail" — denormalized for quick access
    scored_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        score_report_id: str,
        grade_result: str,
        scored_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.score_report_id = score_report_id
        self.grade_result = grade_result
        self.scored_at = scored_at


# ---------------------------------------------------------------------------
# 9. Stopping — Lab shutdown initiated
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.stopping.v1")
@dataclass
class LabletSessionStoppingDomainEvent(DomainEvent):
    """Event raised when lab shutdown begins.

    Transition: RUNNING/COLLECTING/GRADING → STOPPING
    """

    aggregate_id: str
    stopping_started_at: datetime
    reason: str | None

    def __init__(
        self,
        aggregate_id: str,
        stopping_started_at: datetime,
        reason: str | None,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.stopping_started_at = stopping_started_at
        self.reason = reason


# ---------------------------------------------------------------------------
# 10. Stopped — Lab stopped, runtime ended
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.stopped.v1")
@dataclass
class LabletSessionStoppedDomainEvent(DomainEvent):
    """Event raised when the lab is stopped.

    Transition: STOPPING → STOPPED
    Sets ended_at and duration_seconds (computed from started_at).
    """

    aggregate_id: str
    stopped_at: datetime
    duration_seconds: float | None  # None if session never entered RUNNING

    def __init__(
        self,
        aggregate_id: str,
        stopped_at: datetime,
        duration_seconds: float | None,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.stopped_at = stopped_at
        self.duration_seconds = duration_seconds


# ---------------------------------------------------------------------------
# 11. Archived — Session archived for historical records
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.archived.v1")
@dataclass
class LabletSessionArchivedDomainEvent(DomainEvent):
    """Event raised when the session is archived for records.

    Transition: STOPPED → ARCHIVED
    """

    aggregate_id: str
    archived_at: datetime
    archived_by: str

    def __init__(
        self,
        aggregate_id: str,
        archived_at: datetime,
        archived_by: str,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.archived_at = archived_at
        self.archived_by = archived_by


# ---------------------------------------------------------------------------
# 12. Terminated — Emergency/manual termination from any state
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.terminated.v1")
@dataclass
class LabletSessionTerminatedDomainEvent(DomainEvent):
    """Event raised when the session is terminated.

    This is the terminal state. Can be reached from most states.
    Transition: (any) → TERMINATED
    """

    aggregate_id: str
    terminated_at: datetime
    terminated_by: str
    reason: str | None
    from_state: str  # Previous state before termination
    duration_seconds: float | None  # Computed if session was running

    def __init__(
        self,
        aggregate_id: str,
        terminated_at: datetime,
        terminated_by: str,
        reason: str | None,
        from_state: str,
        duration_seconds: float | None,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.terminated_at = terminated_at
        self.terminated_by = terminated_by
        self.reason = reason
        self.from_state = from_state
        self.duration_seconds = duration_seconds


# ---------------------------------------------------------------------------
# 13. PortsReleased — Ports returned to worker pool
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.ports_released.v1")
@dataclass
class LabletSessionPortsReleasedDomainEvent(DomainEvent):
    """Event raised when allocated ports are released back to the worker pool.

    This typically happens during termination or after stopping.
    """

    aggregate_id: str
    worker_id: str
    released_ports: dict[str, int]
    released_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        worker_id: str,
        released_ports: dict[str, int],
        released_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.worker_id = worker_id
        self.released_ports = released_ports
        self.released_at = released_at


# ---------------------------------------------------------------------------
# 14. TimeslotExtended — Timeslot extended for the session
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.timeslot_extended.v1")
@dataclass
class LabletSessionTimeslotExtendedDomainEvent(DomainEvent):
    """Event raised when the timeslot is extended.

    Allows extending a running session's timeslot if resources permit.
    """

    aggregate_id: str
    old_timeslot_end: datetime
    new_timeslot_end: datetime
    extended_by: str
    extended_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        old_timeslot_end: datetime,
        new_timeslot_end: datetime,
        extended_by: str,
        extended_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.old_timeslot_end = old_timeslot_end
        self.new_timeslot_end = new_timeslot_end
        self.extended_by = extended_by
        self.extended_at = extended_at


# ---------------------------------------------------------------------------
# 15. Requeued — Session re-queued for reconciliation
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.requeued.v1")
@dataclass
class LabletSessionRequeuedDomainEvent(DomainEvent):
    """Event raised when a session is manually re-queued for reconciliation.

    This does NOT change the session status — it bumps updated_at and
    records the requeue in state_history so that etcd watchers (or any
    change-detection mechanism) pick up the session for re-processing.

    Applicable from non-terminal states only.
    """

    aggregate_id: str
    requeued_at: datetime
    requeued_by: str
    reason: str | None
    current_status: str

    def __init__(
        self,
        aggregate_id: str,
        requeued_at: datetime,
        requeued_by: str,
        reason: str | None,
        current_status: str,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.requeued_at = requeued_at
        self.requeued_by = requeued_by
        self.reason = reason
        self.current_status = current_status


# ---------------------------------------------------------------------------
# 16. ResourcesObserved — Runtime resource observation recorded (ADR-030)
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.resources_observed.v1")
@dataclass
class LabletSessionResourcesObservedDomainEvent(DomainEvent):
    """Event raised when runtime resource observations are recorded.

    Does NOT change session status — this is a data-enrichment event.
    Can occur during RUNNING or COLLECTING states.

    ADR-030: Resource & Port Observation — "Learn from Live"
    """

    aggregate_id: str
    observed_resources: dict  # Serialized ResourceObservation
    observed_ports: dict[str, int]  # Actual CML port allocations
    port_drift_detected: bool  # True if observed ≠ allocated
    observed_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        observed_resources: dict,
        observed_ports: dict[str, int],
        port_drift_detected: bool,
        observed_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.observed_resources = observed_resources
        self.observed_ports = observed_ports
        self.port_drift_detected = port_drift_detected
        self.observed_at = observed_at


# ---------------------------------------------------------------------------
# 17. PortDriftDetected — Observed ports differ from allocated (ADR-030)
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.port_drift_detected.v1")
@dataclass
class LabletSessionPortDriftDetectedDomainEvent(DomainEvent):
    """Event raised when observed ports differ from allocated ports.

    This is a separate event from ResourcesObserved to allow independent
    handling (e.g., alerting, worker port reconciliation).

    ADR-030: Resource & Port Observation — "Learn from Live"
    """

    aggregate_id: str
    allocated_ports: dict[str, int]  # Planned ports from scheduling
    observed_ports: dict[str, int]  # Actual CML ports at runtime
    drift_details: dict  # {"added": {...}, "removed": {...}, "changed": {...}}
    detected_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        allocated_ports: dict[str, int],
        observed_ports: dict[str, int],
        drift_details: dict,
        detected_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.allocated_ports = allocated_ports
        self.observed_ports = observed_ports
        self.drift_details = drift_details
        self.detected_at = detected_at


# ---------------------------------------------------------------------------
# 18. ObserveResourcesRequested — Manual observation trigger (ADR-030)
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.observe_resources_requested.v1")
@dataclass
class LabletSessionObserveResourcesRequestedDomainEvent(DomainEvent):
    """Event raised when admin requests resource observation.

    Does NOT change session status. Triggers etcd projector for
    lablet-controller to pick up and perform the observation.

    ADR-030 / AD-OLR-007: Manual trigger via reactive etcd watch.
    """

    aggregate_id: str
    requested_by: str
    requested_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        requested_by: str,
        requested_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.requested_by = requested_by
        self.requested_at = requested_at


# ---------------------------------------------------------------------------
# 19. InstantiationProgressUpdated — Pipeline step completed (ADR-031)
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.instantiation_progress_updated.v1")
@dataclass
class LabletSessionInstantiationProgressUpdatedDomainEvent(DomainEvent):
    """Event raised when an instantiation pipeline step completes.

    ADR-031: Checkpoint-based instantiation pipeline.
    Published after each step completes/fails/skips so that SSE
    clients can render real-time progress in the Pipeline tab.
    """

    aggregate_id: str
    step_name: str
    step_status: str  # "completed" | "failed" | "skipped"
    progress_data: dict
    updated_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        step_name: str,
        step_status: str,
        progress_data: dict,
        updated_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.step_name = step_name
        self.step_status = step_status
        self.progress_data = progress_data
        self.updated_at = updated_at


# ---------------------------------------------------------------------------
# 20. Expired — Session timeslot expired (ADR-031 / AD-TIMESLOT-001)
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.expired.v1")
@dataclass
class LabletSessionExpiredDomainEvent(DomainEvent):
    """Event raised when a session's timeslot expires.

    ADR-031 / AD-TIMESLOT-001: Timeslot-centric lifecycle.
    Triggers downstream cleanup (LabRunRecord closure, LabRecord unbind,
    capacity release) — but NOT port release (ports are topology-level).

    Transition: (INSTANTIATING|READY|RUNNING|COLLECTING|GRADING) → EXPIRED
    """

    aggregate_id: str
    expired_at: datetime
    reason: str
    from_state: str
    duration_seconds: float | None

    def __init__(
        self,
        aggregate_id: str,
        expired_at: datetime,
        reason: str,
        from_state: str,
        duration_seconds: float | None,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.expired_at = expired_at
        self.reason = reason
        self.from_state = from_state
        self.duration_seconds = duration_seconds


# ---------------------------------------------------------------------------
# 21. Lab Bound — LabRecord bound to session during instantiation pipeline
# ---------------------------------------------------------------------------


@cloudevent("lablet_session.lab_bound.v1")
@dataclass
class LabletSessionLabBoundDomainEvent(DomainEvent):
    """Event raised when a LabRecord is bound to a session during the pipeline.

    ADR-031 / ADR-032: Lab binding is a pipeline step (not part of scheduling).
    Sets the lab_record_id and denormalizes allocated_ports from the LabRecord
    onto the session for downstream consumption (LDS, grading, monitoring).
    """

    aggregate_id: str
    lab_record_id: str
    allocated_ports: dict[str, int]
    bound_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        lab_record_id: str,
        allocated_ports: dict[str, int],
        bound_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_record_id = lab_record_id
        self.allocated_ports = allocated_ports
        self.bound_at = bound_at
