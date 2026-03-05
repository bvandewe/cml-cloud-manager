"""CML Worker status enum — shared across all services.

Represents the lifecycle states of an AWS EC2 instance running CML.
Owned by Control Plane API (source of truth), consumed by worker-controller.

State Machine:
    pending → provisioning → starting → running → draining → stopping → stopped → terminated
                                                                      ↘ terminating → terminated
                          ↘ failed (from provisioning)
"""

from lcm_core.domain.enums.case_insensitive_enum import CaseInsensitiveStrEnum


class CMLWorkerStatus(CaseInsensitiveStrEnum):
    """AWS EC2 instance states for CML Worker.

    Values are lowercase (canonical form). Case-insensitive lookup
    is supported via _missing_(): CMLWorkerStatus("RUNNING") works.
    """

    PENDING = "pending"  # Instance creation requested, not yet provisioned
    PROVISIONING = "provisioning"  # EC2 instance being launched by worker-controller
    STARTING = "starting"  # Instance is starting (from stopped state)
    RUNNING = "running"  # Instance is running
    DRAINING = "draining"  # Instance is draining workloads before stopping (Phase 3)
    STOPPING = "stopping"  # Instance is being stopped
    STOPPED = "stopped"  # Instance is stopped
    TERMINATING = "terminating"  # Instance is being terminated
    SHUTTING_DOWN = "shutting-down"  # Instance is being terminated (legacy alias)
    TERMINATED = "terminated"  # Instance is terminated
    FAILED = "failed"  # Instance provisioning failed
    UNKNOWN = "unknown"  # Status cannot be determined


# Valid state transitions for CML Worker state machine.
# The reconciler receives status from AWS EC2, which may skip intermediate
# states (e.g. stopping → terminated if EC2 force-terminates).  Callers
# should log invalid transitions as warnings rather than raising, so the
# reconciler is never blocked by an unexpected EC2 state.
CML_WORKER_VALID_TRANSITIONS: dict[CMLWorkerStatus, list[CMLWorkerStatus]] = {
    CMLWorkerStatus.PENDING: [
        CMLWorkerStatus.PROVISIONING,
        CMLWorkerStatus.FAILED,
        CMLWorkerStatus.TERMINATED,
    ],
    CMLWorkerStatus.PROVISIONING: [
        CMLWorkerStatus.STARTING,
        CMLWorkerStatus.RUNNING,
        CMLWorkerStatus.FAILED,
        CMLWorkerStatus.TERMINATED,
    ],
    CMLWorkerStatus.STARTING: [
        CMLWorkerStatus.RUNNING,
        CMLWorkerStatus.FAILED,
        CMLWorkerStatus.STOPPING,
        CMLWorkerStatus.TERMINATED,
    ],
    CMLWorkerStatus.RUNNING: [
        CMLWorkerStatus.DRAINING,
        CMLWorkerStatus.STOPPING,
        CMLWorkerStatus.TERMINATING,
        CMLWorkerStatus.SHUTTING_DOWN,
        CMLWorkerStatus.TERMINATED,
        CMLWorkerStatus.FAILED,
    ],
    CMLWorkerStatus.DRAINING: [
        CMLWorkerStatus.STOPPING,
        CMLWorkerStatus.TERMINATING,
        CMLWorkerStatus.SHUTTING_DOWN,
        CMLWorkerStatus.TERMINATED,
        CMLWorkerStatus.FAILED,
    ],
    CMLWorkerStatus.STOPPING: [
        CMLWorkerStatus.STOPPED,
        CMLWorkerStatus.TERMINATED,
        CMLWorkerStatus.FAILED,
    ],
    CMLWorkerStatus.STOPPED: [
        CMLWorkerStatus.STARTING,
        CMLWorkerStatus.TERMINATING,
        CMLWorkerStatus.SHUTTING_DOWN,
        CMLWorkerStatus.TERMINATED,
    ],
    CMLWorkerStatus.TERMINATING: [
        CMLWorkerStatus.TERMINATED,
    ],
    CMLWorkerStatus.SHUTTING_DOWN: [
        CMLWorkerStatus.TERMINATED,
    ],
    # Terminal states — no valid outbound transitions
    CMLWorkerStatus.TERMINATED: [],
    CMLWorkerStatus.FAILED: [
        CMLWorkerStatus.PENDING,  # retry provisioning
        CMLWorkerStatus.TERMINATED,
    ],
    # Unknown can transition to any state (recovery / first discovery)
    CMLWorkerStatus.UNKNOWN: list(CMLWorkerStatus),
}
