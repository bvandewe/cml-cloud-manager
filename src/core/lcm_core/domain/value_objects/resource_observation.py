"""Resource observation value object — aggregated runtime resource snapshot.

ADR-030: Resource & Port Observation — "Learn from Live"
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from lcm_core.domain.value_objects.node_observation import NodeObservation


@dataclass(frozen=True)
class ResourceObservation:
    """Aggregated resource observation from a live CML lab session.

    Assembled by the lablet-controller from multiple CML API calls
    (node details, interfaces, simulation_stats) and POSTed to CPA
    for storage on the LabletSession aggregate.

    The observed_ports dict maps PortTemplate-style names to actual
    CML-assigned port numbers (e.g., {"PC_serial": 5041, "PC_vnc": 5044}).
    This enables drift detection against allocated_ports.
    """

    observed_at: datetime  # When the observation was taken
    observer: str  # "lablet-controller" or "admin:{user_id}"

    # Aggregate resource consumption
    total_cpu_cores: float  # Sum of node cpu_limit values
    total_memory_mb: int  # Sum of node RAM allocations
    total_storage_mb: int | None  # From resource_pool_usage (future, P2)

    # Node-level detail
    nodes: tuple[NodeObservation, ...]  # Per-node observations
    actual_node_count: int  # Count of observed nodes
    node_definitions_used: tuple[str, ...]  # Unique node definition names

    # Port observations (actual runtime port allocations from node tags)
    observed_ports: dict[str, int]  # {port_name: port_number}

    # Simulation stats (runtime CPU/memory metrics — raw CML response)
    simulation_stats: dict[str, Any] | None  # Raw simulation_stats if available

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "observed_at": self.observed_at.isoformat(),
            "observer": self.observer,
            "total_cpu_cores": self.total_cpu_cores,
            "total_memory_mb": self.total_memory_mb,
            "total_storage_mb": self.total_storage_mb,
            "nodes": [n.to_dict() for n in self.nodes],
            "actual_node_count": self.actual_node_count,
            "node_definitions_used": list(self.node_definitions_used),
            "observed_ports": self.observed_ports,
            "simulation_stats": self.simulation_stats,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ResourceObservation":
        """Create from dictionary."""
        observed_at = data["observed_at"]
        if isinstance(observed_at, str):
            observed_at = datetime.fromisoformat(observed_at)
        return ResourceObservation(
            observed_at=observed_at,
            observer=data.get("observer", "lablet-controller"),
            total_cpu_cores=data.get("total_cpu_cores", 0.0),
            total_memory_mb=data.get("total_memory_mb", 0),
            total_storage_mb=data.get("total_storage_mb"),
            nodes=tuple(NodeObservation.from_dict(n) for n in data.get("nodes", [])),
            actual_node_count=data.get("actual_node_count", 0),
            node_definitions_used=tuple(data.get("node_definitions_used", [])),
            observed_ports=dict(data.get("observed_ports", {})),
            simulation_stats=data.get("simulation_stats"),
        )
