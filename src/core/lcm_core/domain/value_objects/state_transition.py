"""Generic StateTransition value object for tracking resource state history.

ADR-036 §2.1.4: Part of the Resource abstraction layer (Layer 1).

This is the shared, generic version that uses `str` for states, making it
usable across all resource types (CMLWorker, LabRecord, LabletSession).
The CPA-specific version (using LabletSessionStatus enum) remains in
control-plane-api for backward compatibility during migration.

Records each state transition with timestamp, reason, and optional metadata
for audit trail and debugging purposes.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class StateTransition:
    """Immutable record of a state transition in a resource lifecycle.

    Each transition captures the before/after states, timing, and context
    for complete audit trail. Uses `str` for states to support polymorphic
    resource types (CMLWorkerStatus, LabRecordStatus, LabletSessionStatus
    all serialize to str at this level).

    Timeline example for a LabletSession:
        None → PENDING → SCHEDULED → INSTANTIATING → READY → RUNNING → ...
    """

    from_state: str | None  # None for initial creation
    to_state: str
    transitioned_at: datetime
    triggered_by: str  # User ID, system component, or "system"
    reason: str | None = None  # Human-readable reason for transition
    metadata: dict[str, Any] | None = None  # Additional context (error details, etc.)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "from_state": self.from_state,
            "to_state": self.to_state,
            "transitioned_at": self.transitioned_at.isoformat(),
            "triggered_by": self.triggered_by,
            "reason": self.reason,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "StateTransition":
        """Create from dictionary.

        Handles both ISO-format strings and datetime objects for
        transitioned_at. Missing optional fields default to None.
        """
        transitioned_at = data["transitioned_at"]
        if isinstance(transitioned_at, str):
            transitioned_at = datetime.fromisoformat(transitioned_at)
        return StateTransition(
            from_state=data.get("from_state"),
            to_state=data["to_state"],
            transitioned_at=transitioned_at,
            triggered_by=data.get("triggered_by", "system"),
            reason=data.get("reason"),
            metadata=data.get("metadata"),
        )

    def __str__(self) -> str:
        """Human-readable representation."""
        from_str = self.from_state if self.from_state else "None"
        return f"{from_str} → {self.to_state} at {self.transitioned_at.isoformat()}"
