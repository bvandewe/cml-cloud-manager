"""Node observation value object — observed CML node resource usage at runtime.

ADR-030: Resource & Port Observation — "Learn from Live"
"""

from dataclasses import dataclass
from typing import Any

from lcm_core.domain.value_objects.interface_observation import InterfaceObservation


@dataclass(frozen=True)
class NodeObservation:
    """Observed state of a single CML node during a live session.

    Captures the runtime resource allocation (cpu_limit, ram), node
    definition, tags (which encode port mappings), and interface details.
    """

    node_id: str  # CML node ID
    label: str  # Node label (e.g., "PC", "iosv-0")
    node_definition: str  # Node definition name (e.g., "iosv", "csr1000v")
    state: str  # "BOOTED", "STOPPED", etc.
    cpu_limit: int | None  # CPU limit assigned to this node
    ram_mb: int | None  # RAM in MB assigned to this node
    tags: tuple[str, ...]  # Raw CML tags (e.g., ("serial:5041", "vnc:5044"))
    interfaces: tuple[InterfaceObservation, ...]  # Observed interfaces

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "node_id": self.node_id,
            "label": self.label,
            "node_definition": self.node_definition,
            "state": self.state,
            "cpu_limit": self.cpu_limit,
            "ram_mb": self.ram_mb,
            "tags": list(self.tags),
            "interfaces": [i.to_dict() for i in self.interfaces],
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "NodeObservation":
        """Create from dictionary."""
        return NodeObservation(
            node_id=data["node_id"],
            label=data["label"],
            node_definition=data.get("node_definition", ""),
            state=data.get("state", "UNKNOWN"),
            cpu_limit=data.get("cpu_limit"),
            ram_mb=data.get("ram_mb"),
            tags=tuple(data.get("tags", [])),
            interfaces=tuple(InterfaceObservation.from_dict(i) for i in data.get("interfaces", [])),
        )
