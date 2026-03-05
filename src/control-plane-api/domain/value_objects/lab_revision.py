"""LabRevision value object for LabRecord aggregate.

Records a topology revision — created whenever the lab topology
changes (detected via checksum comparison during discovery).

Architecture ref: §4.1 Value Objects.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class LabRevision:
    """A single topology revision of a lab.

    Attributes:
        revision: Monotonically increasing revision number (1-based).
        topology_checksum: SHA-256 hash of the canonical topology.
        created_at: When this revision was recorded.
        created_by: Who/what created this revision (e.g., "discovery", "import", "user").
        change_summary: Human-readable summary of changes.
        node_count: Node count at this revision.
        link_count: Link count at this revision.
    """

    revision: int
    topology_checksum: str
    created_at: datetime
    created_by: str = "system"
    change_summary: str | None = None
    node_count: int = 0
    link_count: int = 0

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ValueError("revision must be >= 1")
        if not self.topology_checksum:
            raise ValueError("topology_checksum cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "revision": self.revision,
            "topology_checksum": self.topology_checksum,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "change_summary": self.change_summary,
            "node_count": self.node_count,
            "link_count": self.link_count,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "LabRevision":
        """Create from dictionary."""
        created_at_raw = data.get("created_at")
        if isinstance(created_at_raw, str):
            created_at = datetime.fromisoformat(created_at_raw)
        elif isinstance(created_at_raw, datetime):
            created_at = created_at_raw
        else:
            created_at = datetime.now(timezone.utc)

        return LabRevision(
            revision=data["revision"],
            topology_checksum=data["topology_checksum"],
            created_at=created_at,
            created_by=data.get("created_by", "system"),
            change_summary=data.get("change_summary"),
            node_count=data.get("node_count", 0),
            link_count=data.get("link_count", 0),
        )

    @staticmethod
    def initial(topology_checksum: str, node_count: int = 0, link_count: int = 0) -> "LabRevision":
        """Create the initial revision (revision 1)."""
        return LabRevision(
            revision=1,
            topology_checksum=topology_checksum,
            created_at=datetime.now(timezone.utc),
            created_by="system",
            change_summary="Initial topology",
            node_count=node_count,
            link_count=link_count,
        )
