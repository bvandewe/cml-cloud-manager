"""Domain enumerations for Control Plane API.

Shared enums (CMLWorkerStatus, LabletSessionStatus, etc.) are defined in
lcm_core and re-exported here for local convenience. All CPA code should
import enums from this module:
    from domain.enums import LabletSessionStatus

Phase 7C: LabletInstanceStatus/LABLET_INSTANCE_VALID_TRANSITIONS kept as
local aliases for application layer backward compatibility until Phase 7D.
"""

# Re-export shared enums from lcm_core (canonical definitions)
from lcm_core.domain.enums import (  # noqa: F401
    CML_WORKER_VALID_TRANSITIONS,
    LABLET_SESSION_VALID_TRANSITIONS,
    AwsRegion,
    CMLServiceStatus,
    CMLWorkerStatus,
    GradingSessionStatus,
    LabletDefinitionStatus,
    LabletSessionStatus,
    LicenseStatus,
    LicenseType,
    UserSessionStatus,
    WorkerOrigin,
)

# Phase 7D: Backward-compatible aliases removed. All code now uses
# LabletSessionStatus and LABLET_SESSION_VALID_TRANSITIONS directly.
