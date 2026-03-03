"""Domain events for Lab Records.

16 domain events per Architecture §4.4:
1.  LabRecordDiscoveredDomainEvent     — New lab found on worker
2.  LabRecordImportedDomainEvent       — Lab imported from YAML
3.  LabRecordStartedDomainEvent        — Lab BOOTED
4.  LabRecordStoppedDomainEvent        — Lab stopped
5.  LabRecordWipedDomainEvent          — Nodes wiped
6.  LabRecordDeletedDomainEvent        — Lab deleted from runtime
7.  LabRecordArchivedDomainEvent       — Lab exported/archived
8.  LabRecordClonedDomainEvent         — Lab cloned
9.  LabRecordRevisionCreatedDomainEvent — Topology updated
10. LabRecordBoundToLabletDomainEvent  — Linked to LabletInstance
11. LabRecordUnboundFromLabletDomainEvent — Unlinked from LabletInstance
12. LabRecordErrorDomainEvent          — Error occurred
13. LabRecordOrphanedDomainEvent       — Worker terminated
14. LabRecordActionRequestedDomainEvent — User requests action (ADR-017)
15. LabRecordActionCompletedDomainEvent — Controller completed action
16. LabRecordActionFailedDomainEvent   — Controller action failed

Core CML data events:
- LabRecordCreatedDomainEvent          — Lab record created from raw CML data
- LabRecordUpdatedDomainEvent          — Lab record updated from raw CML data
- LabStateChangedDomainEvent           — Lab state changed
"""

from dataclasses import dataclass
from datetime import datetime

from neuroglia.data.abstractions import DomainEvent
from neuroglia.eventing.cloud_events.decorators import cloudevent


@cloudevent("lab_record.created.v1")
@dataclass
class LabRecordCreatedDomainEvent(DomainEvent):
    """Event raised when a lab record is first created."""

    worker_id: str
    lab_id: str
    title: str | None
    description: str | None
    notes: str | None
    state: str
    owner_username: str | None
    owner_fullname: str | None
    node_count: int
    link_count: int
    groups: list[str] | None
    cml_created_at: datetime | None
    cml_modified_at: datetime | None
    first_seen_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        worker_id: str,
        lab_id: str,
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
        first_seen_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.worker_id = worker_id
        self.lab_id = lab_id
        self.title = title
        self.description = description
        self.notes = notes
        self.state = state
        self.owner_username = owner_username
        self.owner_fullname = owner_fullname
        self.node_count = node_count
        self.link_count = link_count
        self.groups = groups
        self.cml_created_at = cml_created_at
        self.cml_modified_at = cml_modified_at
        self.first_seen_at = first_seen_at


# @cloudevent("lab_record.updated.v1")
@dataclass
class LabRecordUpdatedDomainEvent(DomainEvent):
    """Event raised when a lab record is updated with fresh CML data."""

    lab_id: str
    title: str | None
    description: str | None
    notes: str | None
    state: str
    owner_username: str | None
    owner_fullname: str | None
    node_count: int
    link_count: int
    groups: list[str] | None
    cml_modified_at: datetime | None
    synced_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        lab_id: str,
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
        synced_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_id = lab_id
        self.title = title
        self.description = description
        self.notes = notes
        self.state = state
        self.owner_username = owner_username
        self.owner_fullname = owner_fullname
        self.node_count = node_count
        self.link_count = link_count
        self.groups = groups
        self.cml_modified_at = cml_modified_at
        self.synced_at = synced_at


@cloudevent("lab_record.state_changed.v1")
@dataclass
class LabStateChangedDomainEvent(DomainEvent):
    """Event raised when a lab's state changes (e.g., STARTED -> STOPPED)."""

    lab_id: str
    previous_state: str
    new_state: str
    changed_fields: dict
    changed_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        lab_id: str,
        previous_state: str,
        new_state: str,
        changed_fields: dict,
        changed_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_id = lab_id
        self.previous_state = previous_state
        self.new_state = new_state
        self.changed_fields = changed_fields
        self.changed_at = changed_at


@cloudevent("lab_record.action_requested.v1")
@dataclass
class LabActionRequestedDomainEvent(DomainEvent):
    """Event raised when a lab action is requested (ADR-017 reconciliation pattern).

    Actions: start, stop, wipe, delete
    Includes worker_id for etcd projection (AD-023).
    """

    lab_id: str
    worker_id: str
    action: str
    requested_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        lab_id: str,
        worker_id: str,
        action: str,
        requested_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_id = lab_id
        self.worker_id = worker_id
        self.action = action
        self.requested_at = requested_at


@cloudevent("lab_record.action_completed.v1")
@dataclass
class LabActionCompletedDomainEvent(DomainEvent):
    """Event raised when a lab action completes successfully."""

    lab_id: str
    action: str
    completed_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        lab_id: str,
        action: str,
        completed_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_id = lab_id
        self.action = action
        self.completed_at = completed_at


@cloudevent("lab_record.action_failed.v1")
@dataclass
class LabActionFailedDomainEvent(DomainEvent):
    """Event #16: Controller action failed."""

    lab_id: str
    action: str
    error_message: str
    failed_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        lab_id: str,
        action: str,
        error_message: str,
        failed_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_id = lab_id
        self.action = action
        self.error_message = error_message
        self.failed_at = failed_at


@cloudevent("lab_record.action_cleared.v1")
@dataclass
class LabActionClearedDomainEvent(DomainEvent):
    """Event raised when a pending action is cleared (user cancel or acknowledge).

    R4 hardening: Replaces direct state mutation for event replay consistency.
    """

    lab_id: str
    action: str
    cleared_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        lab_id: str,
        action: str,
        cleared_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_id = lab_id
        self.action = action
        self.cleared_at = cleared_at


# =============================================================================
# NEW LIFECYCLE EVENTS (Architecture §4.4)
# =============================================================================


@cloudevent("lab_record.discovered.v1")
@dataclass
class LabRecordDiscoveredDomainEvent(DomainEvent):
    """Event #1: New lab found on a worker during discovery scan."""

    worker_id: str
    lab_id: str
    title: str | None
    description: str | None
    notes: str | None
    state: str
    owner_username: str | None
    node_count: int
    link_count: int
    worker_ip: str | None
    discovered_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        worker_id: str,
        lab_id: str,
        title: str | None,
        description: str | None,
        notes: str | None,
        state: str,
        owner_username: str | None,
        node_count: int,
        link_count: int,
        worker_ip: str | None,
        discovered_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.worker_id = worker_id
        self.lab_id = lab_id
        self.title = title
        self.description = description
        self.notes = notes
        self.state = state
        self.owner_username = owner_username
        self.node_count = node_count
        self.link_count = link_count
        self.worker_ip = worker_ip
        self.discovered_at = discovered_at


@cloudevent("lab_record.imported.v1")
@dataclass
class LabRecordImportedDomainEvent(DomainEvent):
    """Event #2: Lab imported from topology YAML."""

    worker_id: str
    lab_id: str
    title: str | None
    topology_checksum: str
    imported_by: str
    imported_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        worker_id: str,
        lab_id: str,
        title: str | None,
        topology_checksum: str,
        imported_by: str,
        imported_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.worker_id = worker_id
        self.lab_id = lab_id
        self.title = title
        self.topology_checksum = topology_checksum
        self.imported_by = imported_by
        self.imported_at = imported_at


@cloudevent("lab_record.started.v1")
@dataclass
class LabRecordStartedDomainEvent(DomainEvent):
    """Event #3: Lab nodes booted successfully."""

    lab_id: str
    started_at: datetime
    started_by: str

    def __init__(
        self,
        aggregate_id: str,
        lab_id: str,
        started_at: datetime,
        started_by: str = "system",
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_id = lab_id
        self.started_at = started_at
        self.started_by = started_by


@cloudevent("lab_record.stopped.v1")
@dataclass
class LabRecordStoppedDomainEvent(DomainEvent):
    """Event #4: Lab nodes stopped."""

    lab_id: str
    stopped_at: datetime
    stop_reason: str | None

    def __init__(
        self,
        aggregate_id: str,
        lab_id: str,
        stopped_at: datetime,
        stop_reason: str | None = None,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_id = lab_id
        self.stopped_at = stopped_at
        self.stop_reason = stop_reason


@cloudevent("lab_record.wiped.v1")
@dataclass
class LabRecordWipedDomainEvent(DomainEvent):
    """Event #5: Lab nodes wiped (configs reset)."""

    lab_id: str
    wiped_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        lab_id: str,
        wiped_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_id = lab_id
        self.wiped_at = wiped_at


@cloudevent("lab_record.deleted.v1")
@dataclass
class LabRecordDeletedDomainEvent(DomainEvent):
    """Event #6: Lab deleted from runtime."""

    lab_id: str
    deleted_at: datetime
    deleted_by: str

    def __init__(
        self,
        aggregate_id: str,
        lab_id: str,
        deleted_at: datetime,
        deleted_by: str = "system",
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_id = lab_id
        self.deleted_at = deleted_at
        self.deleted_by = deleted_by


@cloudevent("lab_record.archived.v1")
@dataclass
class LabRecordArchivedDomainEvent(DomainEvent):
    """Event #7: Lab exported/archived."""

    lab_id: str
    archived_at: datetime
    archived_by: str

    def __init__(
        self,
        aggregate_id: str,
        lab_id: str,
        archived_at: datetime,
        archived_by: str = "system",
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_id = lab_id
        self.archived_at = archived_at
        self.archived_by = archived_by


@cloudevent("lab_record.cloned.v1")
@dataclass
class LabRecordClonedDomainEvent(DomainEvent):
    """Event #8: Lab cloned to a new LabRecord."""

    lab_id: str
    source_lab_record_id: str
    cloned_at: datetime
    cloned_by: str

    def __init__(
        self,
        aggregate_id: str,
        lab_id: str,
        source_lab_record_id: str,
        cloned_at: datetime,
        cloned_by: str = "system",
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_id = lab_id
        self.source_lab_record_id = source_lab_record_id
        self.cloned_at = cloned_at
        self.cloned_by = cloned_by


@cloudevent("lab_record.revision_created.v1")
@dataclass
class LabRecordRevisionCreatedDomainEvent(DomainEvent):
    """Event #9: Topology updated, new revision created."""

    lab_id: str
    revision: int
    topology_checksum: str
    previous_checksum: str | None
    change_summary: str | None
    node_count: int
    link_count: int
    created_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        lab_id: str,
        revision: int,
        topology_checksum: str,
        previous_checksum: str | None,
        change_summary: str | None,
        node_count: int,
        link_count: int,
        created_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_id = lab_id
        self.revision = revision
        self.topology_checksum = topology_checksum
        self.previous_checksum = previous_checksum
        self.change_summary = change_summary
        self.node_count = node_count
        self.link_count = link_count
        self.created_at = created_at


@cloudevent("lab_record.bound_to_lablet.v1")
@dataclass
class LabRecordBoundToLabletDomainEvent(DomainEvent):
    """Event #10: Lab linked to a LabletSession."""

    lab_id: str
    lablet_session_id: str
    binding_id: str
    binding_role: str
    bound_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        lab_id: str,
        lablet_session_id: str,
        binding_id: str,
        binding_role: str,
        bound_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_id = lab_id
        self.lablet_session_id = lablet_session_id
        self.binding_id = binding_id
        self.binding_role = binding_role
        self.bound_at = bound_at


@cloudevent("lab_record.unbound_from_lablet.v1")
@dataclass
class LabRecordUnboundFromLabletDomainEvent(DomainEvent):
    """Event #11: Lab unlinked from a LabletSession."""

    lab_id: str
    lablet_session_id: str
    binding_id: str
    unbound_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        lab_id: str,
        lablet_session_id: str,
        binding_id: str,
        unbound_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_id = lab_id
        self.lablet_session_id = lablet_session_id
        self.binding_id = binding_id
        self.unbound_at = unbound_at


@cloudevent("lab_record.error.v1")
@dataclass
class LabRecordErrorDomainEvent(DomainEvent):
    """Event #12: Error occurred on the lab."""

    lab_id: str
    error_message: str
    previous_status: str
    occurred_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        lab_id: str,
        error_message: str,
        previous_status: str,
        occurred_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_id = lab_id
        self.error_message = error_message
        self.previous_status = previous_status
        self.occurred_at = occurred_at


@cloudevent("lab_record.orphaned.v1")
@dataclass
class LabRecordOrphanedDomainEvent(DomainEvent):
    """Event #13: Worker terminated, lab is orphaned."""

    lab_id: str
    worker_id: str
    orphaned_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        lab_id: str,
        worker_id: str,
        orphaned_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_id = lab_id
        self.worker_id = worker_id
        self.orphaned_at = orphaned_at


# =============================================================================
# ADR-031: INSTANTIATION PIPELINE EVENTS
# =============================================================================


@cloudevent("lab_record.ports_allocated.v1")
@dataclass
class LabRecordPortsAllocatedDomainEvent(DomainEvent):
    """Event raised when ports are allocated to a LabRecord.

    ADR-031 / AD-PORT-001: Ports are a LabRecord topology concern.
    Allocated via PortAllocationService (etcd), keyed by lab_record_id.
    Ports persist across start/stop/wipe cycles.
    """

    lab_id: str
    allocated_ports: dict[str, int]  # {port_name: port_number}
    allocated_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        lab_id: str,
        allocated_ports: dict[str, int],
        allocated_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_id = lab_id
        self.allocated_ports = allocated_ports
        self.allocated_at = allocated_at
