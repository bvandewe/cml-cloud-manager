"""Lablet session status enum — shared across all services.

Represents the lifecycle states for a LabletSession (ADR-020).
Owned by Control Plane API (source of truth), consumed by
lablet-controller and resource-scheduler.

All services import and use this canonical enum for status
comparisons. CaseInsensitiveStrEnum ensures case-insensitive
lookup: LabletSessionStatus("RUNNING") == LabletSessionStatus("running").

Renamed from LabletInstanceStatus → LabletSessionStatus in Phase 7A.
"""

from lcm_core.domain.enums.case_insensitive_enum import CaseInsensitiveStrEnum


class LabletSessionStatus(CaseInsensitiveStrEnum):
    """Lifecycle states for a LabletSession.

    State Machine (ADR-020 §4, ADR-031):
    PENDING → SCHEDULED → INSTANTIATING → READY → RUNNING → COLLECTING → GRADING → STOPPING → STOPPED → ARCHIVED
                                                                                  ↘ TERMINATED (from any state)
                           ↘ EXPIRED (from INSTANTIATING/READY/RUNNING/COLLECTING/GRADING — timeslot expiry)
    """

    PENDING = "pending"
    SCHEDULED = "scheduled"
    INSTANTIATING = "instantiating"
    READY = "ready"
    RUNNING = "running"
    COLLECTING = "collecting"
    GRADING = "grading"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ARCHIVED = "archived"
    TERMINATED = "terminated"
    EXPIRED = "expired"  # ADR-031 / AD-TIMESLOT-001: timeslot expiry


# Valid state transitions for LabletSession state machine (ADR-020 §4)
LABLET_SESSION_VALID_TRANSITIONS: dict[LabletSessionStatus, list[LabletSessionStatus]] = {
    LabletSessionStatus.PENDING: [
        LabletSessionStatus.SCHEDULED,
        LabletSessionStatus.TERMINATED,
    ],
    LabletSessionStatus.SCHEDULED: [
        LabletSessionStatus.INSTANTIATING,
        LabletSessionStatus.TERMINATED,
    ],
    LabletSessionStatus.INSTANTIATING: [
        LabletSessionStatus.READY,
        LabletSessionStatus.EXPIRED,
        LabletSessionStatus.TERMINATED,
    ],
    LabletSessionStatus.READY: [
        LabletSessionStatus.RUNNING,
        LabletSessionStatus.EXPIRED,
        LabletSessionStatus.TERMINATED,
    ],
    LabletSessionStatus.RUNNING: [
        LabletSessionStatus.COLLECTING,
        LabletSessionStatus.STOPPING,
        LabletSessionStatus.EXPIRED,
        LabletSessionStatus.TERMINATED,
    ],
    LabletSessionStatus.COLLECTING: [
        LabletSessionStatus.GRADING,
        LabletSessionStatus.STOPPING,
        LabletSessionStatus.EXPIRED,
        LabletSessionStatus.TERMINATED,
    ],
    LabletSessionStatus.GRADING: [
        LabletSessionStatus.STOPPING,
        LabletSessionStatus.EXPIRED,
        LabletSessionStatus.TERMINATED,
    ],
    LabletSessionStatus.STOPPING: [
        LabletSessionStatus.STOPPED,
        LabletSessionStatus.ARCHIVED,  # Teardown pipeline: STOPPING → ARCHIVED (skip STOPPED)
        LabletSessionStatus.TERMINATED,
    ],
    LabletSessionStatus.STOPPED: [
        LabletSessionStatus.ARCHIVED,
        LabletSessionStatus.TERMINATED,
    ],
    LabletSessionStatus.ARCHIVED: [
        LabletSessionStatus.TERMINATED,
    ],
    LabletSessionStatus.TERMINATED: [],  # Terminal state
    LabletSessionStatus.EXPIRED: [
        LabletSessionStatus.STOPPING,  # Teardown pipeline: expired sessions need infrastructure cleanup
        LabletSessionStatus.TERMINATED,  # ADR-031: force-terminate an expired session
    ],
}
