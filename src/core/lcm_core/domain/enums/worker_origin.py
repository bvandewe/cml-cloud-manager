"""Worker origin enum — shared across all services.

Tracks the provenance of a CML Worker instance:
- How it was created (UI, scale-up, discovery)
- Enables admin visibility into fleet composition
"""

from lcm_core.domain.enums.case_insensitive_enum import CaseInsensitiveStrEnum


class WorkerOrigin(CaseInsensitiveStrEnum):
    """Origin/provenance of a CML Worker instance.

    Tracks how a worker was created so admins can distinguish between
    manually provisioned workers, auto-scaled workers, and discovered instances.
    """

    USER_CREATED = "user_created"  # Created via UI or API by an admin
    SCALE_UP = "scale_up"  # Auto-provisioned by resource-scheduler scale-up
    EC2_DISCOVERY = "ec2_discovery"  # Discovered by worker-controller EC2 scan
    UNKNOWN = "unknown"  # Origin not tracked (legacy workers)
