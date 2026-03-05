"""User session status enum — shared across all services.

Represents the LCM-internal lifecycle states for a UserSession (ADR-021).
These are simplified abstractions of the LDS (Lab Delivery System) native
session states. The lablet-controller maps LDS native statuses to these
internal values.

LDS native state mapping (for reference):
    LDS pending/initial_login/prelaunch/provisioned  →  PROVISIONED
    LDS running/active                               →  ACTIVE
    LDS paused                                       →  PAUSED
    LDS user_finished/finalized                      →  ENDED
    LDS timeout                                      →  EXPIRED

Renamed from LdsSessionStatus → UserSessionStatus in Phase 7A (AD-P7-06).
"""

from lcm_core.domain.enums.case_insensitive_enum import CaseInsensitiveStrEnum


class UserSessionStatus(CaseInsensitiveStrEnum):
    """Lifecycle states for a UserSession (LDS session tracking).

    State Machine:
        PROVISIONING → PROVISIONED → ACTIVE → PAUSED → ENDED
                                                     ↘ EXPIRED (timeout)
        Any non-terminal → FAULTED (error escape)
    """

    PROVISIONING = "provisioning"  # LDS session being created
    PROVISIONED = "provisioned"  # LDS session created, login URL ready
    ACTIVE = "active"  # Student logged in, session active
    PAUSED = "paused"  # Session paused by proctor/system
    ENDED = "ended"  # Session ended normally (terminal)
    EXPIRED = "expired"  # Session expired due to timeout (terminal)
    FAULTED = "faulted"  # LDS error (terminal)
