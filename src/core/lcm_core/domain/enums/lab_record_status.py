"""LabRecord status enum — shared across all services.

Represents the 16-state lifecycle of a LabRecord (CML lab managed by LCM).
Owned by Control Plane API (source of truth), consumed by lablet-controller
and worker-controller.

State Machine (§4.2d-4.3 of LabRecord Architecture):
    Discovery:  DISCOVERED → IMPORTING → DEFINED
    Running:    STARTING → QUEUED → BOOTED → PAUSED
    Shutdown:   STOPPING → STOPPED → WIPING → WIPED
    Cleanup:    DELETING → DELETED (terminal), ARCHIVED (terminal)
    Error:      ERROR (recoverable), ORPHANED (cleanup only)

CML State Mapping (migration from raw strings):
    DEFINED_ON_CORE → DEFINED
    STARTED / BOOTED → BOOTED
    STOPPED → STOPPED
    QUEUED → QUEUED
"""

from lcm_core.domain.enums.case_insensitive_enum import CaseInsensitiveStrEnum


class LabRecordStatus(CaseInsensitiveStrEnum):
    """Lifecycle states for a LabRecord.

    Values are lowercase (canonical form). Case-insensitive lookup
    is supported via _missing_(): LabRecordStatus("BOOTED") works.
    """

    # Discovery & Import
    DISCOVERED = "discovered"  # New lab found on worker, not yet managed
    IMPORTING = "importing"  # Lab being imported from YAML/topology
    DEFINED = "defined"  # Lab exists on CML runtime, nodes not started

    # Running
    STARTING = "starting"  # Lab nodes being started
    QUEUED = "queued"  # Lab start queued (CML resource contention)
    BOOTED = "booted"  # All lab nodes running
    PAUSED = "paused"  # Lab paused (nodes suspended)

    # Shutdown
    STOPPING = "stopping"  # Lab nodes being stopped
    STOPPED = "stopped"  # All lab nodes stopped
    WIPING = "wiping"  # Lab nodes being wiped (configs reset)
    WIPED = "wiped"  # Lab nodes wiped, ready for reuse

    # Cleanup
    DELETING = "deleting"  # Lab being deleted from runtime
    DELETED = "deleted"  # Lab deleted from runtime (terminal)
    ARCHIVED = "archived"  # Lab exported/archived (terminal)

    # Error & Orphan
    ERROR = "error"  # Recoverable error state
    ORPHANED = "orphaned"  # Worker terminated, lab unreachable


# CML raw state string → LabRecordStatus mapping for migration
CML_STATE_TO_LAB_RECORD_STATUS: dict[str, LabRecordStatus] = {
    "DEFINED_ON_CORE": LabRecordStatus.DEFINED,
    "STARTED": LabRecordStatus.BOOTED,
    "BOOTED": LabRecordStatus.BOOTED,
    "STOPPED": LabRecordStatus.STOPPED,
    "QUEUED": LabRecordStatus.QUEUED,
}


# Valid state transitions for LabRecord state machine (Architecture §4.3)
# ORPHANED is reachable from ALL non-terminal states because worker termination
# is a force-majeure event — labs on a terminated worker are unreachable
# regardless of their previous state.
LAB_RECORD_VALID_TRANSITIONS: dict[LabRecordStatus, list[LabRecordStatus]] = {
    LabRecordStatus.DISCOVERED: [
        LabRecordStatus.IMPORTING,
        LabRecordStatus.DEFINED,
        LabRecordStatus.STARTING,
        LabRecordStatus.BOOTED,
        LabRecordStatus.STOPPED,
        LabRecordStatus.WIPED,
        LabRecordStatus.DELETED,
        LabRecordStatus.ORPHANED,
    ],
    LabRecordStatus.IMPORTING: [
        LabRecordStatus.DEFINED,
        LabRecordStatus.ERROR,
        LabRecordStatus.ORPHANED,
    ],
    LabRecordStatus.DEFINED: [
        LabRecordStatus.STARTING,
        LabRecordStatus.BOOTED,  # Direct start (CompleteLabActionCommand)
        LabRecordStatus.WIPING,
        LabRecordStatus.DELETING,
        LabRecordStatus.DELETED,  # Direct delete (CompleteLabActionCommand)
        LabRecordStatus.ORPHANED,
        LabRecordStatus.ERROR,
    ],
    LabRecordStatus.STARTING: [
        LabRecordStatus.QUEUED,
        LabRecordStatus.BOOTED,
        LabRecordStatus.STOPPED,  # Abort/stop while starting
        LabRecordStatus.ERROR,
        LabRecordStatus.ORPHANED,
    ],
    LabRecordStatus.QUEUED: [
        LabRecordStatus.BOOTED,
        LabRecordStatus.STOPPED,  # Abort/stop while queued
        LabRecordStatus.ERROR,
        LabRecordStatus.ORPHANED,
    ],
    LabRecordStatus.BOOTED: [
        LabRecordStatus.STOPPING,
        LabRecordStatus.STOPPED,  # Direct stop (CompleteLabActionCommand)
        LabRecordStatus.PAUSED,
        LabRecordStatus.WIPED,  # Direct wipe (CompleteLabActionCommand)
        LabRecordStatus.ERROR,
        LabRecordStatus.ORPHANED,
    ],
    LabRecordStatus.PAUSED: [
        LabRecordStatus.STARTING,
        LabRecordStatus.BOOTED,  # Direct resume
        LabRecordStatus.STOPPING,
        LabRecordStatus.STOPPED,  # Direct stop (CompleteLabActionCommand)
        LabRecordStatus.ERROR,
        LabRecordStatus.ORPHANED,
    ],
    LabRecordStatus.STOPPING: [
        LabRecordStatus.STOPPED,
        LabRecordStatus.ERROR,
        LabRecordStatus.ORPHANED,
    ],
    LabRecordStatus.STOPPED: [
        LabRecordStatus.STARTING,
        LabRecordStatus.BOOTED,  # Direct start (CompleteLabActionCommand)
        LabRecordStatus.WIPING,
        LabRecordStatus.WIPED,  # Direct wipe (CompleteLabActionCommand)
        LabRecordStatus.DELETING,
        LabRecordStatus.DELETED,  # Direct delete (CompleteLabActionCommand)
        LabRecordStatus.ARCHIVED,
        LabRecordStatus.ORPHANED,
        LabRecordStatus.ERROR,
    ],
    LabRecordStatus.WIPING: [
        LabRecordStatus.WIPED,
        LabRecordStatus.ERROR,
        LabRecordStatus.ORPHANED,
    ],
    LabRecordStatus.WIPED: [
        LabRecordStatus.STARTING,
        LabRecordStatus.BOOTED,  # Direct start (CompleteLabActionCommand)
        LabRecordStatus.DELETING,
        LabRecordStatus.DELETED,  # Direct delete (CompleteLabActionCommand)
        LabRecordStatus.ARCHIVED,
        LabRecordStatus.ORPHANED,
    ],
    LabRecordStatus.DELETING: [
        LabRecordStatus.DELETED,
        LabRecordStatus.ERROR,
        LabRecordStatus.ORPHANED,
    ],
    LabRecordStatus.DELETED: [],  # Terminal state
    LabRecordStatus.ARCHIVED: [],  # Terminal state
    LabRecordStatus.ERROR: [
        LabRecordStatus.STARTING,
        LabRecordStatus.STOPPING,
        LabRecordStatus.WIPING,
        LabRecordStatus.WIPED,  # Direct wipe (CompleteLabActionCommand)
        LabRecordStatus.DELETING,
        LabRecordStatus.DELETED,  # Direct delete (CompleteLabActionCommand)
        LabRecordStatus.DEFINED,
        LabRecordStatus.ORPHANED,
    ],
    LabRecordStatus.ORPHANED: [
        LabRecordStatus.DELETED,
        LabRecordStatus.ARCHIVED,
    ],
}
