"""Read model for GradingSession entities.

Immutable DTO representing the Grading Engine session tracking data
for a LabletSession. Created in Phase 7A per ADR-021 (child entity architecture).

GradingSession tracks the Grading Engine session associated with a
LabletSession. It holds the GE session reference, pod assignment,
and the LCM-internal GradingSessionStatus.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class GradingSessionReadModel:
    """Read model for a GradingSession from the Control Plane API.

    Used by:
    - lablet-controller: For grading lifecycle management
    - frontend: For displaying grading status and progress

    All fields except id, lablet_session_id, and status are optional.
    """

    # Core identity
    id: str
    lablet_session_id: str  # FK → LabletSession
    status: str  # GradingSessionStatus value

    # Grading Engine session reference
    grading_session_id: str | None = None  # External GE session identifier
    grading_part_id: str | None = None  # GE session part identifier
    pod_id: str | None = None  # GE pod assignment

    # Timestamps
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GradingSessionReadModel":
        """Create from API response dictionary."""
        return cls(
            id=data.get("id", ""),
            lablet_session_id=data.get("lablet_session_id", ""),
            status=data.get("status", ""),
            grading_session_id=data.get("grading_session_id"),
            grading_part_id=data.get("grading_part_id"),
            pod_id=data.get("pod_id"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )
