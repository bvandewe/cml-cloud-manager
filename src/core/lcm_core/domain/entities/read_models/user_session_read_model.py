"""Read model for UserSession entities.

Immutable DTO representing the LDS session tracking data for a LabletSession.
Created in Phase 7A per ADR-021 (child entity architecture).

UserSession tracks the Lab Delivery System (LDS) session associated with
a LabletSession. It holds the LDS session reference, login URL, device
access information, and the LCM-internal UserSessionStatus.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class UserSessionReadModel:
    """Read model for a UserSession from the Control Plane API.

    Used by:
    - lablet-controller: For LDS session lifecycle management
    - frontend: For displaying LDS session info (login URL, devices, status)

    All fields except id, lablet_session_id, and status are optional.
    """

    # Core identity
    id: str
    lablet_session_id: str  # FK → LabletSession
    status: str  # UserSessionStatus value

    # LDS session reference
    lds_session_id: str | None = None  # External LDS session identifier
    lds_part_id: str | None = None  # LDS content/session part identifier

    # User access
    login_url: str | None = None  # JWT-signed launch URL for lab access
    devices: list[dict[str, Any]] = field(default_factory=list)  # Device access info (name, type, console_url)

    # Timestamps
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserSessionReadModel":
        """Create from API response dictionary."""
        return cls(
            id=data.get("id", ""),
            lablet_session_id=data.get("lablet_session_id", ""),
            status=data.get("status", ""),
            lds_session_id=data.get("lds_session_id"),
            lds_part_id=data.get("lds_part_id"),
            login_url=data.get("login_url"),
            devices=data.get("devices", []),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )
