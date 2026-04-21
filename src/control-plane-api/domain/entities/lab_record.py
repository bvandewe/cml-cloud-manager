"""Lab Record Aggregate for tracking CML lab state and history.

Refactored for Phase 7 (LabRecord Architecture):
- Typed LabRecordStatus enum replacing raw CML state strings
- RuntimeBinding value object replacing bare worker_id + lab_id
- LabTopologySpec for structured topology with checksum-based change detection
- ExternalInterface list derived from CML node tags
- Revision tracking with LabRevision history
- Run history with LabRunRecord entries
- State machine with validated transitions
- 16 domain events per Architecture §4.4
"""

from datetime import datetime, timezone
from typing import Any

from domain.events.lab_record_events import (
    LabActionClearedDomainEvent,
    LabActionCompletedDomainEvent,
    LabActionFailedDomainEvent,
    LabActionRequestedDomainEvent,
    LabRecordArchivedDomainEvent,
    LabRecordBoundToLabletDomainEvent,
    LabRecordClonedDomainEvent,
    LabRecordCreatedDomainEvent,
    LabRecordDeletedDomainEvent,
    LabRecordDiscoveredDomainEvent,
    LabRecordErrorDomainEvent,
    LabRecordImportedDomainEvent,
    LabRecordOrphanedDomainEvent,
    LabRecordPortsAllocatedDomainEvent,
    LabRecordRevisionCreatedDomainEvent,
    LabRecordStartedDomainEvent,
    LabRecordStoppedDomainEvent,
    LabRecordUnboundFromLabletDomainEvent,
    LabRecordUpdatedDomainEvent,
    LabRecordWipedDomainEvent,
    LabStateChangedDomainEvent,
    PipelineRunRecordedDomainEvent,
)
from domain.value_objects.external_interface import ExternalInterface
from domain.value_objects.lab_revision import LabRevision
from domain.value_objects.lab_run_record import LabRunRecord
from domain.value_objects.lab_topology_spec import LabTopologySpec
from domain.value_objects.pipeline_run_record import PipelineRunRecord
from domain.value_objects.runtime_binding import RuntimeBinding
from lcm_core.domain.entities.resource import ResourceState
from lcm_core.domain.enums import (
    CML_STATE_TO_LAB_RECORD_STATUS,
    LAB_RECORD_VALID_TRANSITIONS,
    LabRecordStatus,
)
from lcm_core.domain.value_objects.state_transition import StateTransition
from multipledispatch import dispatch
from neuroglia.data.abstractions import AggregateRoot


class InvalidLabRecordTransitionError(Exception):
    """Raised when an invalid LabRecord state transition is attempted."""

    def __init__(self, from_status: LabRecordStatus, to_status: LabRecordStatus, message: str | None = None):
        self.from_status = from_status
        self.to_status = to_status
        self.message = message or f"Invalid LabRecord transition from {from_status.value} to {to_status.value}"
        super().__init__(self.message)


class LabRecordState(ResourceState):
    """Encapsulates the persisted state for a Lab Record.

    Inheritance hierarchy (ADR-036 §2.1.4, Batch G):
        AggregateState[str]  (Neuroglia)
            └── ResourceState  (Layer 1 — status, desired_status, state_history)
                    └── LabRecordState  ← YOU ARE HERE

    Inherits from ResourceState (Layer 1):
        - id, resource_type, owner_id
        - status (str), desired_status (str | None)
        - state_history (list), pipeline_progress (dict | None)
        - created_at, updated_at

    Shadows parent fields with typed versions:
        - status: LabRecordStatus (parent: str)

    LabRecords use ResourceState (Layer 1) rather than TimedResourceState
    (Layer 2) because CML labs have open-ended lifetimes — they are not
    timeslotted and don't follow a managed lifecycle. Lab run durations
    are tracked via LabRunRecord entries in run_history_v2.

    Phase 7 additions:
    - status: LabRecordStatus (typed enum replacing raw state string)
    - runtime_binding: RuntimeBinding (replaces bare worker_id + lab_id)
    - topology_spec: LabTopologySpec (structured topology)
    - external_interfaces: list[dict] (ExternalInterface VOs, serialized)
    - revision: int + revision_history: list[dict] (LabRevision VOs, serialized)
    - run_history_v2: list[dict] (LabRunRecord VOs, serialized)
    - source: str (how lab was created: "discovery", "import", "clone")
    - based_on_definition_id: str | None (LabletDefinition that seeded this lab)

    Backward-compatible fields preserved:
    - state: str (raw CML state string, kept for legacy sync)
    - worker_id: str (kept, RuntimeBinding is the canonical source)
    - lab_id: str (kept, RuntimeBinding is the canonical source)

    NOTE: All fields MUST be declared as class-level annotations (not just in
    __init__) so that Neuroglia's MotorRepository/JsonSerializer can see them via
    get_type_hints(). This ensures missing optional fields are populated with
    None during deserialization (the deserializer bypasses __init__).
    See CMLWorkerState for the reference pattern.
    """

    # =========================================================================
    # Class-level annotations — required for Neuroglia deserialization
    # =========================================================================

    # Identity (id inherited from ResourceState)
    worker_id: str
    lab_id: str
    worker_ip: str | None

    # Typed status (Phase 7) — shadows ResourceState.status (str)
    status: LabRecordStatus

    # State history — audit trail (ADR-036 §2.1.4 Batch G)
    # Stored as list[dict] (StateTransition.to_dict()) for Neuroglia serialization.
    state_history: list[dict]

    # Lab metadata
    title: str | None
    description: str | None
    notes: str | None
    state: str | None  # Legacy: raw CML state string
    owner_username: str | None
    owner_fullname: str | None
    node_count: int
    link_count: int
    groups: list[str]

    # Runtime binding (Phase 7)
    runtime_binding: dict[str, Any] | None

    # Topology (Phase 7)
    topology_spec: dict[str, Any] | None
    external_interfaces: list[dict[str, Any]]

    # Versioning (Phase 7)
    revision: int
    revision_history: list[dict[str, Any]]

    # Run history (Phase 7)
    run_history_v2: list[dict[str, Any]]
    max_run_history_size: int

    # Pipeline run history (Sprint F, ADR-034)
    pipeline_run_history: list[dict[str, Any]]

    # Provenance
    source: str
    based_on_definition_id: str | None

    # Timestamps
    cml_created_at: datetime | None
    modified_at: datetime | None
    last_synced_at: datetime | None
    first_seen_at: datetime | None

    # Port allocation (ADR-031 / AD-PORT-001)
    allocated_ports: dict[str, int] | None  # {port_name: port_number}

    # Active binding (ADR-031 / AD-BIND-001)
    active_lablet_session_id: str | None
    active_binding_id: str | None

    # Pending action (ADR-017 reconciliation)
    pending_action: str | None
    pending_action_at: datetime | None
    pending_action_error: str | None

    # Error tracking
    last_error: str | None
    last_error_at: datetime | None
    previous_status_before_error: str | None

    def __init__(self) -> None:
        super().__init__()
        self.resource_type = "lab_record"

        # Identity (id initialized by ResourceState)
        self.worker_id = ""
        self.lab_id = ""
        self.worker_ip = None

        # Typed status (Phase 7 — shadows ResourceState.status)
        self.status = LabRecordStatus.DISCOVERED

        # State history (ADR-036 Batch G)
        self.state_history = []

        # Current lab metadata
        self.title = None
        self.description = None
        self.notes = None
        self.state = None
        self.owner_username = None
        self.owner_fullname = None
        self.node_count = 0
        self.link_count = 0
        self.groups = []

        # Runtime binding (Phase 7 — replaces bare worker_id + lab_id)
        self.runtime_binding = None

        # Topology (Phase 7)
        self.topology_spec = None
        self.external_interfaces = []

        # Versioning (Phase 7)
        self.revision = 1
        self.revision_history = []

        # Run history (Phase 7)
        self.run_history_v2 = []
        self.max_run_history_size = 50

        # Pipeline run history (Sprint F, ADR-034)
        self.pipeline_run_history = []

        # Provenance
        self.source = "discovery"
        self.based_on_definition_id = None

        # Timestamps
        self.cml_created_at = None
        self.modified_at = None
        self.last_synced_at = None
        self.first_seen_at = None

        # Port allocation (ADR-031 / AD-PORT-001)
        self.allocated_ports = None

        # Active binding (ADR-031 / AD-BIND-001)
        self.active_lablet_session_id = None
        self.active_binding_id = None

        # Pending action (ADR-017 reconciliation)
        self.pending_action = None
        self.pending_action_at = None
        self.pending_action_error = None

        # Error tracking
        self.last_error = None
        self.last_error_at = None
        self.previous_status_before_error = None

    def _record_transition(
        self,
        from_state: str | None,
        to_state: str,
        triggered_by: str = "system",
        reason: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Record a state transition in the history.

        Overrides ResourceState._record_transition() for two reasons:
        1. Stores transitions as dicts (via StateTransition.to_dict()) instead
           of StateTransition objects, for Neuroglia serialization compatibility.
        2. Maintains updated_at behavior consistent with ResourceState base class.

        ADR-036 Batch G: Follows CMLWorkerState/LabletSessionState pattern.
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

    # =========================================================================
    # Event Handlers — creation and update from raw CML data
    # =========================================================================

    @dispatch(LabRecordCreatedDomainEvent)
    def on(self, event: LabRecordCreatedDomainEvent) -> None:  # type: ignore[override]
        """Apply lab record creation event."""
        self.id = event.aggregate_id
        self.worker_id = event.worker_id
        self.lab_id = event.lab_id
        self.title = event.title
        self.description = event.description
        self.notes = event.notes
        self.state = event.state
        self.owner_username = event.owner_username
        self.owner_fullname = event.owner_fullname
        self.node_count = event.node_count
        self.link_count = event.link_count
        self.groups = event.groups or []
        self.cml_created_at = event.cml_created_at
        self.modified_at = event.cml_modified_at
        self.first_seen_at = event.first_seen_at
        self.last_synced_at = event.first_seen_at
        # Map raw CML state to typed status
        self.status = CML_STATE_TO_LAB_RECORD_STATUS.get(event.state, LabRecordStatus.DISCOVERED)
        # Create runtime binding from legacy fields
        self.runtime_binding = RuntimeBinding.for_cml(
            worker_id=event.worker_id,
            lab_id=event.lab_id,
        ).to_dict()
        self.source = "discovery"
        self._record_transition(
            from_state=None,
            to_state=self.status.value,
            triggered_by="system",
            reason="Lab record created from CML data",
        )

    @dispatch(LabRecordUpdatedDomainEvent)
    def on(self, event: LabRecordUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Apply lab record update event (legacy sync path)."""
        old_status = self.status
        self.title = event.title
        self.description = event.description
        self.notes = event.notes
        self.state = event.state
        self.owner_username = event.owner_username
        self.owner_fullname = event.owner_fullname
        self.node_count = event.node_count
        self.link_count = event.link_count
        self.groups = event.groups or []
        self.modified_at = event.cml_modified_at
        self.last_synced_at = event.synced_at
        # Map raw CML state to typed status
        self.status = CML_STATE_TO_LAB_RECORD_STATUS.get(event.state, self.status)
        if self.status != old_status:
            self._record_transition(
                from_state=old_status.value,
                to_state=self.status.value,
                triggered_by="cml-sync",
                reason=f"Updated from CML state '{event.state}'",
            )

    @dispatch(LabStateChangedDomainEvent)
    def on(self, event: LabStateChangedDomainEvent) -> None:  # type: ignore[override]
        """Apply lab state change event (legacy sync path)."""
        old_status = self.status
        self.state = event.new_state
        # Map raw CML state to typed status
        self.status = CML_STATE_TO_LAB_RECORD_STATUS.get(event.new_state, self.status)
        if self.status != old_status:
            self._record_transition(
                from_state=old_status.value,
                to_state=self.status.value,
                triggered_by="cml-sync",
                reason=f"CML state changed from '{event.previous_state}' to '{event.new_state}'",
            )

    # =========================================================================
    # ADR-017 RECONCILIATION EVENT HANDLERS
    # =========================================================================

    @dispatch(LabActionRequestedDomainEvent)
    def on(self, event: LabActionRequestedDomainEvent) -> None:  # type: ignore[override]
        """Apply lab action requested event (ADR-017 reconciliation)."""
        self.pending_action = event.action
        self.pending_action_at = event.requested_at
        self.pending_action_error = None

    @dispatch(LabActionCompletedDomainEvent)
    def on(self, event: LabActionCompletedDomainEvent) -> None:  # type: ignore[override]
        """Apply lab action completed event — clear pending action."""
        self.pending_action = None
        self.pending_action_at = None
        self.pending_action_error = None

    @dispatch(LabActionFailedDomainEvent)
    def on(self, event: LabActionFailedDomainEvent) -> None:  # type: ignore[override]
        """Apply lab action failed event — clear pending action and preserve the error."""
        self.pending_action = None
        self.pending_action_at = None
        self.pending_action_error = event.error_message

    @dispatch(LabActionClearedDomainEvent)
    def on(self, event: LabActionClearedDomainEvent) -> None:  # type: ignore[override]
        """Apply lab action cleared event — clear all pending action state."""
        self.pending_action = None
        self.pending_action_at = None
        self.pending_action_error = None

    # =========================================================================
    # NEW LIFECYCLE EVENT HANDLERS (Phase 7 — Architecture §4.4)
    # =========================================================================

    @dispatch(LabRecordDiscoveredDomainEvent)
    def on(self, event: LabRecordDiscoveredDomainEvent) -> None:  # type: ignore[override]
        """Apply lab discovery event."""
        self.id = event.aggregate_id
        self.worker_id = event.worker_id
        self.lab_id = event.lab_id
        self.title = event.title
        self.description = event.description
        self.notes = event.notes
        self.state = event.state
        self.owner_username = event.owner_username
        self.node_count = event.node_count
        self.link_count = event.link_count
        self.worker_ip = event.worker_ip
        self.first_seen_at = event.discovered_at
        self.last_synced_at = event.discovered_at
        self.status = LabRecordStatus.DISCOVERED
        self.source = "discovery"
        self.based_on_definition_id = event.based_on_definition_id
        self.runtime_binding = RuntimeBinding.for_cml(
            worker_id=event.worker_id,
            lab_id=event.lab_id,
        ).to_dict()
        self._record_transition(
            from_state=None,
            to_state=LabRecordStatus.DISCOVERED.value,
            triggered_by="system",
            reason="Lab discovered on worker",
        )

    @dispatch(LabRecordImportedDomainEvent)
    def on(self, event: LabRecordImportedDomainEvent) -> None:  # type: ignore[override]
        """Apply lab import event."""
        old_status = self.status
        self.lab_id = event.lab_id
        self.title = event.title
        self.status = LabRecordStatus.DEFINED
        self.source = "import"
        self.last_synced_at = event.imported_at
        self.runtime_binding = RuntimeBinding.for_cml(
            worker_id=event.worker_id,
            lab_id=event.lab_id,
        ).to_dict()
        # Create initial revision
        initial_rev = LabRevision(
            revision=1,
            topology_checksum=event.topology_checksum,
            created_at=event.imported_at,
            created_by=event.imported_by,
            change_summary="Imported from YAML",
            node_count=self.node_count,
            link_count=self.link_count,
        )
        self.revision = 1
        self.revision_history = [initial_rev.to_dict()]
        self._record_transition(
            from_state=old_status.value,
            to_state=LabRecordStatus.DEFINED.value,
            triggered_by=event.imported_by,
            reason="Lab imported from YAML topology",
        )

    @dispatch(LabRecordStartedDomainEvent)
    def on(self, event: LabRecordStartedDomainEvent) -> None:  # type: ignore[override]
        """Apply lab started event."""
        old_status = self.status
        self.status = LabRecordStatus.BOOTED
        self.state = "BOOTED"
        self._record_transition(
            from_state=old_status.value,
            to_state=LabRecordStatus.BOOTED.value,
            triggered_by="system",
            reason="Lab started (all nodes running)",
        )

    @dispatch(LabRecordStoppedDomainEvent)
    def on(self, event: LabRecordStoppedDomainEvent) -> None:  # type: ignore[override]
        """Apply lab stopped event."""
        old_status = self.status
        self.status = LabRecordStatus.STOPPED
        self.state = "STOPPED"
        self._record_transition(
            from_state=old_status.value,
            to_state=LabRecordStatus.STOPPED.value,
            triggered_by="system",
            reason="Lab stopped",
        )

    @dispatch(LabRecordWipedDomainEvent)
    def on(self, event: LabRecordWipedDomainEvent) -> None:  # type: ignore[override]
        """Apply lab wiped event."""
        old_status = self.status
        self.status = LabRecordStatus.WIPED
        self.state = "WIPED"
        self._record_transition(
            from_state=old_status.value,
            to_state=LabRecordStatus.WIPED.value,
            triggered_by="system",
            reason="Lab wiped (nodes reset)",
        )

    @dispatch(LabRecordDeletedDomainEvent)
    def on(self, event: LabRecordDeletedDomainEvent) -> None:  # type: ignore[override]
        """Apply lab deleted event (terminal)."""
        old_status = self.status
        self.status = LabRecordStatus.DELETED
        self.state = "DELETED"
        self._record_transition(
            from_state=old_status.value,
            to_state=LabRecordStatus.DELETED.value,
            triggered_by="system",
            reason="Lab deleted from runtime",
        )

    @dispatch(LabRecordArchivedDomainEvent)
    def on(self, event: LabRecordArchivedDomainEvent) -> None:  # type: ignore[override]
        """Apply lab archived event (terminal)."""
        old_status = self.status
        self.status = LabRecordStatus.ARCHIVED
        self.state = "ARCHIVED"
        self._record_transition(
            from_state=old_status.value,
            to_state=LabRecordStatus.ARCHIVED.value,
            triggered_by="system",
            reason="Lab archived",
        )

    @dispatch(LabRecordClonedDomainEvent)
    def on(self, event: LabRecordClonedDomainEvent) -> None:  # type: ignore[override]
        """Apply lab cloned event — sets identity on the new clone."""
        self.id = event.aggregate_id
        self.lab_id = event.lab_id
        self.source = "clone"
        old_status = self.status
        self.status = LabRecordStatus.DEFINED
        self.state = "DEFINED_ON_CORE"
        self._record_transition(
            from_state=old_status.value,
            to_state=LabRecordStatus.DEFINED.value,
            triggered_by="system",
            reason="Lab cloned",
        )

    @dispatch(LabRecordRevisionCreatedDomainEvent)
    def on(self, event: LabRecordRevisionCreatedDomainEvent) -> None:  # type: ignore[override]
        """Apply topology revision event."""
        self.revision = event.revision
        self.node_count = event.node_count
        self.link_count = event.link_count
        new_rev = LabRevision(
            revision=event.revision,
            topology_checksum=event.topology_checksum,
            created_at=event.created_at,
            created_by="system",
            change_summary=event.change_summary,
            node_count=event.node_count,
            link_count=event.link_count,
        )
        self.revision_history.append(new_rev.to_dict())

    @dispatch(LabRecordPortsAllocatedDomainEvent)
    def on(self, event: LabRecordPortsAllocatedDomainEvent) -> None:  # type: ignore[override]
        """Apply port allocation event (ADR-031 / AD-PORT-001)."""
        self.allocated_ports = dict(event.allocated_ports)

    @dispatch(LabRecordBoundToLabletDomainEvent)
    def on(self, event: LabRecordBoundToLabletDomainEvent) -> None:  # type: ignore[override]
        """Apply binding event — records that a lablet session is using this lab.

        ADR-031 / AD-BIND-001: Tracks the active binding on the LabRecord.
        """
        self.active_lablet_session_id = event.lablet_session_id
        self.active_binding_id = event.binding_id

    @dispatch(LabRecordUnboundFromLabletDomainEvent)
    def on(self, event: LabRecordUnboundFromLabletDomainEvent) -> None:  # type: ignore[override]
        """Apply unbinding event — clears active binding if matching.

        ADR-031 / AD-BIND-001: Only clears if the binding_id matches.
        """
        if self.active_binding_id == event.binding_id:
            self.active_lablet_session_id = None
            self.active_binding_id = None

    @dispatch(LabRecordErrorDomainEvent)
    def on(self, event: LabRecordErrorDomainEvent) -> None:  # type: ignore[override]
        """Apply error event."""
        old_status = self.status
        self.previous_status_before_error = event.previous_status
        self.last_error = event.error_message
        self.last_error_at = event.occurred_at
        self.status = LabRecordStatus.ERROR
        self.state = "ERROR"
        self._record_transition(
            from_state=old_status.value,
            to_state=LabRecordStatus.ERROR.value,
            triggered_by="system",
            reason=event.error_message,
        )

    @dispatch(LabRecordOrphanedDomainEvent)
    def on(self, event: LabRecordOrphanedDomainEvent) -> None:  # type: ignore[override]
        """Apply orphaned event."""
        old_status = self.status
        self.status = LabRecordStatus.ORPHANED
        self.state = "ORPHANED"
        self._record_transition(
            from_state=old_status.value,
            to_state=LabRecordStatus.ORPHANED.value,
            triggered_by="system",
            reason="Lab orphaned (worker terminated)",
        )

    # =========================================================================
    # PIPELINE RUN HISTORY EVENT HANDLER (Sprint F, ADR-034)
    # =========================================================================

    @dispatch(PipelineRunRecordedDomainEvent)
    def on(self, event: PipelineRunRecordedDomainEvent) -> None:  # type: ignore[override]
        """Apply pipeline run recorded event — appends to pipeline_run_history."""
        record = PipelineRunRecord(
            run_id=event.run_id,
            pipeline_name=event.pipeline_name,
            started_at=event.started_at,
            completed_at=event.completed_at,
            status=event.status,
            step_results=event.step_results,
            error_message=event.error_message,
            triggered_by=event.triggered_by,
            lablet_session_id=event.lablet_session_id,
            duration_seconds=event.duration_seconds,
            steps_completed=event.steps_completed,
            steps_failed=event.steps_failed,
            steps_skipped=event.steps_skipped,
        )
        self.pipeline_run_history.append(record.to_dict())
        # Bounded list — keep last 50 entries (same as run_history_v2)
        if len(self.pipeline_run_history) > self.max_run_history_size:
            self.pipeline_run_history = self.pipeline_run_history[-self.max_run_history_size :]


class LabRecord(AggregateRoot[LabRecordState, str]):
    """Lab Record aggregate for tracking CML lab state and operation history.

    Phase 7 enhancements:
    - Typed LabRecordStatus with guarded transitions
    - RuntimeBinding, LabTopologySpec, ExternalInterface value objects
    - Revision tracking and run history
    - 16 domain events per Architecture §4.4
    """

    def __init__(self) -> None:
        super().__init__()

    def id(self) -> str:
        """Return the aggregate identifier with a precise type."""
        from typing import cast

        aggregate_id = super().id()
        if aggregate_id is None:
            raise ValueError("LabRecord aggregate identifier has not been initialized")
        return cast(str, aggregate_id)

    # =========================================================================
    # STATE MACHINE GUARD
    # =========================================================================

    def _validate_transition(self, to_status: LabRecordStatus) -> None:
        """Validate that a state transition is allowed per Architecture §4.3."""
        valid_targets = LAB_RECORD_VALID_TRANSITIONS.get(self.state.status, [])
        if to_status not in valid_targets:
            raise InvalidLabRecordTransitionError(self.state.status, to_status)

    # =========================================================================
    # PROPERTY ACCESSORS (deserialized value objects)
    # =========================================================================

    @property
    def runtime_binding_vo(self) -> RuntimeBinding | None:
        """Return the deserialized RuntimeBinding value object."""
        if self.state.runtime_binding:
            return RuntimeBinding.from_dict(self.state.runtime_binding)
        return None

    @property
    def topology_spec_vo(self) -> LabTopologySpec | None:
        """Return the deserialized LabTopologySpec value object."""
        if self.state.topology_spec:
            return LabTopologySpec.from_dict(self.state.topology_spec)
        return None

    @property
    def external_interfaces_vo(self) -> list[ExternalInterface]:
        """Return the deserialized list of ExternalInterface value objects."""
        return [ExternalInterface.from_dict(ei) for ei in self.state.external_interfaces]

    @property
    def revision_history_vo(self) -> list[LabRevision]:
        """Return the deserialized list of LabRevision value objects."""
        return [LabRevision.from_dict(rev) for rev in self.state.revision_history]

    @property
    def run_history_vo(self) -> list[LabRunRecord]:
        """Return the deserialized list of LabRunRecord value objects."""
        return [LabRunRecord.from_dict(run) for run in self.state.run_history_v2]

    @property
    def pipeline_run_history_vo(self) -> list[PipelineRunRecord]:
        """Return the deserialized list of PipelineRunRecord value objects."""
        return [PipelineRunRecord.from_dict(run) for run in self.state.pipeline_run_history]

    # =========================================================================
    # FACTORY METHODS
    # =========================================================================

    @staticmethod
    def create(
        lab_id: str,
        worker_id: str,
        title: str | None,
        description: str | None,
        notes: str | None,
        state: str,
        owner_username: str | None,
        owner_fullname: str | None,
        node_count: int,
        link_count: int,
        groups: list[str] | None,
        cml_created_at: datetime | None,
        cml_modified_at: datetime | None,
    ) -> "LabRecord":
        """Create a new lab record from raw CML data."""
        import uuid

        record = LabRecord()
        record_id = str(uuid.uuid4())
        first_seen = datetime.now(timezone.utc)
        event = LabRecordCreatedDomainEvent(
            aggregate_id=record_id,
            worker_id=worker_id,
            lab_id=lab_id,
            title=title,
            description=description,
            notes=notes,
            state=state,
            owner_username=owner_username,
            owner_fullname=owner_fullname,
            node_count=node_count,
            link_count=link_count,
            groups=groups,
            cml_created_at=cml_created_at,
            cml_modified_at=cml_modified_at,
            first_seen_at=first_seen,
        )
        record.state.on(record.register_event(event))  # type: ignore
        return record

    @staticmethod
    def discover(
        lab_id: str,
        worker_id: str,
        title: str | None,
        description: str | None,
        state: str,
        owner_username: str | None,
        node_count: int,
        link_count: int,
        notes: str | None = None,
        worker_ip: str | None = None,
        based_on_definition_id: str | None = None,
    ) -> "LabRecord":
        """Create a new lab record from discovery scan (Phase 7 factory)."""
        import uuid

        record = LabRecord()
        record_id = str(uuid.uuid4())
        discovered_at = datetime.now(timezone.utc)
        event = LabRecordDiscoveredDomainEvent(
            aggregate_id=record_id,
            worker_id=worker_id,
            lab_id=lab_id,
            title=title,
            description=description,
            notes=notes,
            state=state,
            owner_username=owner_username,
            node_count=node_count,
            link_count=link_count,
            worker_ip=worker_ip,
            discovered_at=discovered_at,
            based_on_definition_id=based_on_definition_id,
        )
        record.state.on(record.register_event(event))  # type: ignore
        return record

    # =========================================================================
    # Update from raw CML data
    # =========================================================================

    def update_from_cml(
        self,
        title: str | None,
        description: str | None,
        notes: str | None,
        state: str,
        owner_username: str | None,
        owner_fullname: str | None,
        node_count: int,
        link_count: int,
        groups: list[str] | None,
        cml_modified_at: datetime | None,
        worker_ip: str | None = None,
    ) -> None:
        """Update lab record with fresh data from CML.

        R6 freshness guard: If the incoming cml_modified_at is older than
        the currently stored value, the update is silently skipped to
        prevent stale data from overwriting newer state.
        """
        # R6: Freshness guard — skip stale data
        if cml_modified_at is not None and self.state.modified_at is not None:
            # Normalize both to UTC-aware to avoid naive/aware comparison
            incoming = cml_modified_at if cml_modified_at.tzinfo else cml_modified_at.replace(tzinfo=timezone.utc)
            stored = self.state.modified_at if self.state.modified_at.tzinfo else self.state.modified_at.replace(tzinfo=timezone.utc)
            if incoming <= stored:
                return

        # Update worker_ip if provided (keeps it current as worker IPs may change)
        if worker_ip is not None:
            self.state.worker_ip = worker_ip

        synced_at = datetime.now(timezone.utc)
        if self.state.state and self.state.state != state:
            changed_fields: dict[str, Any] = {}
            if self.state.title != title:
                changed_fields["title"] = {"old": self.state.title, "new": title}
            if self.state.node_count != node_count:
                changed_fields["node_count"] = {"old": self.state.node_count, "new": node_count}
            if self.state.link_count != link_count:
                changed_fields["link_count"] = {"old": self.state.link_count, "new": link_count}
            state_change_event = LabStateChangedDomainEvent(
                aggregate_id=self.id(),
                lab_id=self.state.lab_id,
                previous_state=self.state.state,
                new_state=state,
                changed_fields=changed_fields,
                changed_at=synced_at,
            )
            self.state.on(self.register_event(state_change_event))  # type: ignore

        update_event = LabRecordUpdatedDomainEvent(
            aggregate_id=self.id(),
            lab_id=self.state.lab_id,
            title=title,
            description=description,
            notes=notes,
            state=state,
            owner_username=owner_username,
            owner_fullname=owner_fullname,
            node_count=node_count,
            link_count=link_count,
            groups=groups,
            cml_modified_at=cml_modified_at,
            synced_at=synced_at,
        )
        self.state.on(self.register_event(update_event))  # type: ignore

    # =========================================================================
    # TYPED STATUS TRANSITIONS (Phase 7)
    # =========================================================================

    def mark_imported(
        self,
        lab_id: str,
        worker_id: str,
        title: str | None,
        topology_checksum: str,
        imported_by: str = "system",
    ) -> None:
        """Mark the lab as imported from YAML topology."""
        self._validate_transition(LabRecordStatus.DEFINED)
        event = LabRecordImportedDomainEvent(
            aggregate_id=self.id(),
            worker_id=worker_id,
            lab_id=lab_id,
            title=title,
            topology_checksum=topology_checksum,
            imported_by=imported_by,
            imported_at=datetime.now(timezone.utc),
        )
        self.state.on(self.register_event(event))  # type: ignore

    def mark_started(self, started_by: str = "system") -> None:
        """Mark the lab as booted (all nodes running)."""
        self._validate_transition(LabRecordStatus.BOOTED)
        event = LabRecordStartedDomainEvent(
            aggregate_id=self.id(),
            lab_id=self.state.lab_id,
            started_at=datetime.now(timezone.utc),
            started_by=started_by,
        )
        self.state.on(self.register_event(event))  # type: ignore

    def mark_stopped(self, stop_reason: str | None = None) -> None:
        """Mark the lab as stopped."""
        self._validate_transition(LabRecordStatus.STOPPED)
        event = LabRecordStoppedDomainEvent(
            aggregate_id=self.id(),
            lab_id=self.state.lab_id,
            stopped_at=datetime.now(timezone.utc),
            stop_reason=stop_reason,
        )
        self.state.on(self.register_event(event))  # type: ignore

    def mark_wiped(self) -> None:
        """Mark the lab as wiped (nodes reset, ready for reuse)."""
        self._validate_transition(LabRecordStatus.WIPED)
        event = LabRecordWipedDomainEvent(
            aggregate_id=self.id(),
            lab_id=self.state.lab_id,
            wiped_at=datetime.now(timezone.utc),
        )
        self.state.on(self.register_event(event))  # type: ignore

    def mark_deleted(self, deleted_by: str = "system") -> None:
        """Mark the lab as deleted from runtime (terminal)."""
        self._validate_transition(LabRecordStatus.DELETED)
        event = LabRecordDeletedDomainEvent(
            aggregate_id=self.id(),
            lab_id=self.state.lab_id,
            deleted_at=datetime.now(timezone.utc),
            deleted_by=deleted_by,
        )
        self.state.on(self.register_event(event))  # type: ignore

    def mark_archived(self, archived_by: str = "system") -> None:
        """Mark the lab as archived (terminal)."""
        self._validate_transition(LabRecordStatus.ARCHIVED)
        event = LabRecordArchivedDomainEvent(
            aggregate_id=self.id(),
            lab_id=self.state.lab_id,
            archived_at=datetime.now(timezone.utc),
            archived_by=archived_by,
        )
        self.state.on(self.register_event(event))  # type: ignore

    def mark_error(self, error_message: str) -> None:
        """Mark the lab as errored (recoverable)."""
        self._validate_transition(LabRecordStatus.ERROR)
        event = LabRecordErrorDomainEvent(
            aggregate_id=self.id(),
            lab_id=self.state.lab_id,
            error_message=error_message,
            previous_status=self.state.status.value,
            occurred_at=datetime.now(timezone.utc),
        )
        self.state.on(self.register_event(event))  # type: ignore

    def mark_orphaned(self) -> None:
        """Mark the lab as orphaned (worker terminated)."""
        self._validate_transition(LabRecordStatus.ORPHANED)
        event = LabRecordOrphanedDomainEvent(
            aggregate_id=self.id(),
            lab_id=self.state.lab_id,
            worker_id=self.state.worker_id,
            orphaned_at=datetime.now(timezone.utc),
        )
        self.state.on(self.register_event(event))  # type: ignore

    # =========================================================================
    # TOPOLOGY & REVISION METHODS (Phase 7)
    # =========================================================================

    def update_topology(self, topology_spec: LabTopologySpec, change_summary: str | None = None) -> None:
        """Update topology and create a new revision if checksum changed."""
        new_checksum = topology_spec.checksum()
        current_checksum = None
        if self.state.revision_history:
            last_rev = LabRevision.from_dict(self.state.revision_history[-1])
            current_checksum = last_rev.topology_checksum

        self.state.topology_spec = topology_spec.to_dict()
        self.state.node_count = topology_spec.node_count
        self.state.link_count = topology_spec.link_count

        if current_checksum != new_checksum:
            new_revision = self.state.revision + 1
            event = LabRecordRevisionCreatedDomainEvent(
                aggregate_id=self.id(),
                lab_id=self.state.lab_id,
                revision=new_revision,
                topology_checksum=new_checksum,
                previous_checksum=current_checksum,
                change_summary=change_summary,
                node_count=topology_spec.node_count,
                link_count=topology_spec.link_count,
                created_at=datetime.now(timezone.utc),
            )
            self.state.on(self.register_event(event))  # type: ignore

    def set_external_interfaces(self, interfaces: list[ExternalInterface]) -> None:
        """Set the external interfaces for this lab (derived from node tags)."""
        self.state.external_interfaces = [ei.to_dict() for ei in interfaces]

    # =========================================================================
    # PORT ALLOCATION (ADR-031 / AD-PORT-001)
    # =========================================================================

    def allocate_ports(self, allocated_ports: dict[str, int]) -> None:
        """Record port allocation on this lab record.

        Ports are a topology concern — they persist across start/stop/wipe.
        Called by AllocateLabRecordPortsCommandHandler after
        PortAllocationService allocates from etcd.

        Args:
            allocated_ports: Mapping of port name to port number.
                e.g. {"PC_serial": 3001, "PC_vnc": 3002}
        """
        event = LabRecordPortsAllocatedDomainEvent(
            aggregate_id=self.id(),
            lab_id=self.state.lab_id,
            allocated_ports=allocated_ports,
            allocated_at=datetime.now(timezone.utc),
        )
        self.state.on(self.register_event(event))  # type: ignore

    # =========================================================================
    # BINDING METHODS (Phase 7)
    # =========================================================================

    def bind_to_lablet(self, lablet_session_id: str, binding_id: str, binding_role: str) -> None:
        """Record that this lab is bound to a LabletSession."""
        event = LabRecordBoundToLabletDomainEvent(
            aggregate_id=self.id(),
            lab_id=self.state.lab_id,
            lablet_session_id=lablet_session_id,
            binding_id=binding_id,
            binding_role=binding_role,
            bound_at=datetime.now(timezone.utc),
        )
        self.state.on(self.register_event(event))  # type: ignore

    def unbind_from_lablet(self, lablet_session_id: str, binding_id: str) -> None:
        """Record that this lab is unbound from a LabletSession."""
        event = LabRecordUnboundFromLabletDomainEvent(
            aggregate_id=self.id(),
            lab_id=self.state.lab_id,
            lablet_session_id=lablet_session_id,
            binding_id=binding_id,
            unbound_at=datetime.now(timezone.utc),
        )
        self.state.on(self.register_event(event))  # type: ignore

    # =========================================================================
    # RUN HISTORY METHODS (Phase 7)
    # =========================================================================

    def record_run(self, run: LabRunRecord) -> None:
        """Add a run record to the history."""
        self.state.run_history_v2.append(run.to_dict())
        if len(self.state.run_history_v2) > self.state.max_run_history_size:
            self.state.run_history_v2 = self.state.run_history_v2[-self.state.max_run_history_size :]

    # =========================================================================
    # PIPELINE RUN HISTORY METHODS (Sprint F, ADR-034)
    # =========================================================================

    def append_pipeline_run(self, pipeline_run: PipelineRunRecord) -> None:
        """Append a pipeline execution record via domain event.

        Sprint F (ADR-034): Records a completed pipeline run on this LabRecord.
        Emits PipelineRunRecordedDomainEvent which the state handler appends
        to pipeline_run_history (bounded list, max 50 entries).

        Args:
            pipeline_run: The PipelineRunRecord value object to record.
        """
        event = PipelineRunRecordedDomainEvent(
            aggregate_id=self.id(),
            lab_id=self.state.lab_id,
            run_id=pipeline_run.run_id,
            pipeline_name=pipeline_run.pipeline_name,
            status=pipeline_run.status,
            started_at=pipeline_run.started_at,
            completed_at=pipeline_run.completed_at,
            duration_seconds=pipeline_run.duration_seconds,
            steps_completed=pipeline_run.steps_completed,
            steps_failed=pipeline_run.steps_failed,
            steps_skipped=pipeline_run.steps_skipped,
            step_results=pipeline_run.step_results,
            error_message=pipeline_run.error_message,
            triggered_by=pipeline_run.triggered_by,
            lablet_session_id=pipeline_run.lablet_session_id,
            recorded_at=datetime.now(timezone.utc),
        )
        self.state.on(self.register_event(event))  # type: ignore

    # =========================================================================
    # PENDING ACTION METHODS (ADR-017 Reconciliation Pattern)
    # =========================================================================

    def request_start(self) -> None:
        """Request lab start via reconciliation (ADR-017)."""
        event = LabActionRequestedDomainEvent(
            aggregate_id=self.id(),
            lab_id=self.state.lab_id,
            worker_id=self.state.worker_id,
            action="start",
            requested_at=datetime.now(timezone.utc),
        )
        self.state.on(self.register_event(event))  # type: ignore

    def request_stop(self) -> None:
        """Request lab stop via reconciliation (ADR-017)."""
        event = LabActionRequestedDomainEvent(
            aggregate_id=self.id(),
            lab_id=self.state.lab_id,
            worker_id=self.state.worker_id,
            action="stop",
            requested_at=datetime.now(timezone.utc),
        )
        self.state.on(self.register_event(event))  # type: ignore

    def request_wipe(self) -> None:
        """Request lab wipe via reconciliation (ADR-017)."""
        event = LabActionRequestedDomainEvent(
            aggregate_id=self.id(),
            lab_id=self.state.lab_id,
            worker_id=self.state.worker_id,
            action="wipe",
            requested_at=datetime.now(timezone.utc),
        )
        self.state.on(self.register_event(event))  # type: ignore

    def request_delete(self) -> None:
        """Request lab deletion via reconciliation (ADR-017)."""
        event = LabActionRequestedDomainEvent(
            aggregate_id=self.id(),
            lab_id=self.state.lab_id,
            worker_id=self.state.worker_id,
            action="delete",
            requested_at=datetime.now(timezone.utc),
        )
        self.state.on(self.register_event(event))  # type: ignore

    def complete_pending_action(self) -> None:
        """Mark pending action as completed successfully."""
        if not self.state.pending_action:
            return
        event = LabActionCompletedDomainEvent(
            aggregate_id=self.id(),
            lab_id=self.state.lab_id,
            action=self.state.pending_action,
            completed_at=datetime.now(timezone.utc),
        )
        self.state.on(self.register_event(event))  # type: ignore

    def fail_pending_action(self, error_message: str) -> None:
        """Mark pending action as failed."""
        if not self.state.pending_action:
            return
        event = LabActionFailedDomainEvent(
            aggregate_id=self.id(),
            lab_id=self.state.lab_id,
            action=self.state.pending_action,
            error_message=error_message,
            failed_at=datetime.now(timezone.utc),
        )
        self.state.on(self.register_event(event))  # type: ignore

    def clear_pending_action(self) -> None:
        """Clear pending action via domain event (e.g., user acknowledges failure or cancels).

        R4 hardening: Emits LabActionClearedDomainEvent instead of direct state
        mutation, ensuring event replay consistency and audit visibility.
        """
        if not self.state.pending_action:
            return
        event = LabActionClearedDomainEvent(
            aggregate_id=self.id(),
            lab_id=self.state.lab_id,
            action=self.state.pending_action,
            cleared_at=datetime.now(timezone.utc),
        )
        self.state.on(self.register_event(event))  # type: ignore

    # =========================================================================
    # COMPUTED PROPERTIES
    # =========================================================================

    @property
    def is_terminal(self) -> bool:
        """Check if this lab is in a terminal state (DELETED or ARCHIVED)."""
        return self.state.status in (LabRecordStatus.DELETED, LabRecordStatus.ARCHIVED)

    @property
    def is_running(self) -> bool:
        """Check if this lab is running (BOOTED)."""
        return self.state.status == LabRecordStatus.BOOTED

    @property
    def is_reusable(self) -> bool:
        """Check if this lab can be reused (WIPED or STOPPED)."""
        return self.state.status in (LabRecordStatus.WIPED, LabRecordStatus.STOPPED)

    @property
    def is_error(self) -> bool:
        """Check if this lab is in an error state."""
        return self.state.status == LabRecordStatus.ERROR

    @property
    def is_orphaned(self) -> bool:
        """Check if this lab is orphaned."""
        return self.state.status == LabRecordStatus.ORPHANED
