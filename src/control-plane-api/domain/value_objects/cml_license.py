from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from domain.enums import LicenseStatus

# Type alias for pending license operations
PendingLicenseOperation = Literal["register", "deregister"] | None


@dataclass(frozen=True)
class CMLLicense:
    """A Value Object representing the CML license details.

    ADR-016: License operations follow reconciliation pattern.
    - pending_token: Token to register (set by control-plane-api)
    - pending_operation: "register" | "deregister" | None
    - worker-controller reconciles by calling CML API
    """

    status: LicenseStatus = LicenseStatus.UNREGISTERED
    token: str | None = None  # Currently registered token
    pending_token: str | None = None  # Token to register (ADR-016)
    pending_operation: PendingLicenseOperation = None  # Desired operation (ADR-016)
    operation_in_progress: bool = False
    expiry_date: date | None = None
    features: tuple[str, ...] = ()  # Immutable tuple of licensed features
    raw_info: dict[str, Any] | None = None
