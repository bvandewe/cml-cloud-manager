"""StateTransition value object for tracking LabletSession state history.

Records each state transition with timestamp, reason, and optional metadata
for audit trail and debugging purposes.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from domain.enums import LabletSessionStatus


@dataclass(frozen=True)
class StateTransition:
    """Immutable record of a state transition in LabletSession lifecycle.

    Each transition captures the before/after states, timing, and context
    for complete audit trail of session lifecycle.
    """

    from_state: LabletSessionStatus | None  # None for initial creation
    to_state: LabletSessionStatus
    transitioned_at: datetime
    triggered_by: str  # User ID, system component, or "system"
    reason: str | None = None  # Human-readable reason for transition
    metadata: dict[str, Any] | None = None  # Additional context (error details, etc.)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "from_state": self.from_state.value if self.from_state else None,
            "to_state": self.to_state.value,
            "transitioned_at": self.transitioned_at.isoformat(),
            "triggered_by": self.triggered_by,
            "reason": self.reason,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "StateTransition":
        """Create from dictionary."""
        from_state_value = data.get("from_state")
        return StateTransition(
            from_state=LabletSessionStatus(from_state_value) if from_state_value else None,
            to_state=LabletSessionStatus(data["to_state"]),
            transitioned_at=datetime.fromisoformat(data["transitioned_at"]),
            triggered_by=data["triggered_by"],
            reason=data.get("reason"),
            metadata=data.get("metadata"),
        )

    @property
    def duration_from_previous(self) -> None:
        """Duration calculation requires access to previous transition - computed externally."""
        return None

    def __str__(self) -> str:
        """Human-readable representation."""
        from_str = self.from_state.value if self.from_state else "None"
        return f"{from_str} → {self.to_state.value} at {self.transitioned_at.isoformat()}"
