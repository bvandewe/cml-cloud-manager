"""Read model for LabRecord entities.

Immutable DTO used by controllers, schedulers, and the lablet-controller
to represent the current state of a LabRecord without requiring the
full aggregate reconstruction.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LabRecordReadModel:
    """Read model for a LabRecord from the Control Plane API.

    Used by:
    - lablet-controller for lab lifecycle reconciliation
    - resource-scheduler for lab reuse decisions
    - UI for lab status display
    """

    id: str
    worker_id: str
    lab_id: str
    status: str
    title: str | None = None
    description: str | None = None
    state: str | None = None  # Legacy raw CML state
    owner_username: str | None = None
    owner_fullname: str | None = None
    node_count: int = 0
    link_count: int = 0
    groups: list[str] = field(default_factory=list)

    # Provenance
    source: str = "discovery"
    based_on_definition_id: str | None = None

    # Runtime binding (serialized RuntimeBinding dict)
    runtime_binding: dict[str, Any] | None = None

    # Versioning
    revision: int = 1

    # Timestamps
    cml_created_at: str | None = None
    modified_at: str | None = None
    last_synced_at: str | None = None
    first_seen_at: str | None = None

    # Pending action (ADR-017)
    pending_action: str | None = None
    pending_action_at: str | None = None
    pending_action_error: str | None = None

    # Error tracking
    last_error: str | None = None
    last_error_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LabRecordReadModel":
        """Create from API response dictionary."""
        return cls(
            id=data.get("id", ""),
            worker_id=data.get("worker_id", ""),
            lab_id=data.get("lab_id", ""),
            status=data.get("status", "discovered"),
            title=data.get("title"),
            description=data.get("description"),
            state=data.get("state"),
            owner_username=data.get("owner_username"),
            owner_fullname=data.get("owner_fullname"),
            node_count=data.get("node_count", 0),
            link_count=data.get("link_count", 0),
            groups=data.get("groups", []),
            source=data.get("source", "discovery"),
            based_on_definition_id=data.get("based_on_definition_id"),
            runtime_binding=data.get("runtime_binding"),
            revision=data.get("revision", 1),
            cml_created_at=_safe_str(data.get("cml_created_at")),
            modified_at=_safe_str(data.get("modified_at")),
            last_synced_at=_safe_str(data.get("last_synced_at")),
            first_seen_at=_safe_str(data.get("first_seen_at")),
            pending_action=data.get("pending_action"),
            pending_action_at=_safe_str(data.get("pending_action_at")),
            pending_action_error=data.get("pending_action_error"),
            last_error=data.get("last_error"),
            last_error_at=_safe_str(data.get("last_error_at")),
        )

    @property
    def is_terminal(self) -> bool:
        """Check if lab is in a terminal state."""
        return self.status in ("deleted", "archived")

    @property
    def is_running(self) -> bool:
        """Check if lab is running."""
        return self.status == "booted"

    @property
    def is_reusable(self) -> bool:
        """Check if lab can be reused."""
        return self.status in ("wiped", "stopped")

    @property
    def has_pending_action(self) -> bool:
        """Check if lab has a pending action."""
        return self.pending_action is not None


def _safe_str(value: Any) -> str | None:
    """Convert a value to string if not None (handles datetime objects)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)
