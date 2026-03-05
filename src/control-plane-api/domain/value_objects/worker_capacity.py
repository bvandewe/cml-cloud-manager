"""Worker Capacity value object for CMLWorker aggregate.

Represents the compute capacity of a CML worker for lablet scheduling.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkerCapacity:
    """Immutable value object representing worker compute capacity.

    Used to track declared capacity (from template) and allocated capacity
    (sum of lablet requirements) for a CML worker.

    Attributes:
        cpu_cores: Number of CPU cores (logical cores)
        memory_gb: Memory in gigabytes
        storage_gb: Storage in gigabytes
        max_nodes: Maximum CML node count (optional soft limit)
    """

    cpu_cores: int
    memory_gb: int
    storage_gb: int
    max_nodes: int | None = None

    def __post_init__(self) -> None:
        """Validate capacity values on creation."""
        if self.cpu_cores < 0:
            raise ValueError("cpu_cores cannot be negative")
        if self.memory_gb < 0:
            raise ValueError("memory_gb cannot be negative")
        if self.storage_gb < 0:
            raise ValueError("storage_gb cannot be negative")
        if self.max_nodes is not None and self.max_nodes < 0:
            raise ValueError("max_nodes cannot be negative")

    @staticmethod
    def zero() -> "WorkerCapacity":
        """Create a zero-capacity instance (for allocated capacity initialization).

        Returns:
            WorkerCapacity with all values set to zero
        """
        return WorkerCapacity(cpu_cores=0, memory_gb=0, storage_gb=0, max_nodes=0)

    def can_fit(self, required: "WorkerCapacity") -> bool:
        """Check if the required capacity can fit within this capacity.

        Args:
            required: Required capacity to fit

        Returns:
            True if required capacity fits, False otherwise
        """
        if required.cpu_cores > self.cpu_cores:
            return False
        if required.memory_gb > self.memory_gb:
            return False
        if required.storage_gb > self.storage_gb:
            return False
        if self.max_nodes is not None and required.max_nodes is not None:
            if required.max_nodes > self.max_nodes:
                return False
        return True

    def subtract(self, other: "WorkerCapacity") -> "WorkerCapacity":
        """Subtract another capacity from this one (for available calculation).

        Args:
            other: Capacity to subtract

        Returns:
            New WorkerCapacity with remaining values (minimum 0)

        Note:
            Does not raise on negative results - clamps to 0.
        """
        return WorkerCapacity(
            cpu_cores=max(0, self.cpu_cores - other.cpu_cores),
            memory_gb=max(0, self.memory_gb - other.memory_gb),
            storage_gb=max(0, self.storage_gb - other.storage_gb),
            max_nodes=(max(0, self.max_nodes - (other.max_nodes or 0)) if self.max_nodes is not None else None),
        )

    def add(self, other: "WorkerCapacity") -> "WorkerCapacity":
        """Add another capacity to this one (for allocation aggregation).

        Args:
            other: Capacity to add

        Returns:
            New WorkerCapacity with summed values
        """
        return WorkerCapacity(
            cpu_cores=self.cpu_cores + other.cpu_cores,
            memory_gb=self.memory_gb + other.memory_gb,
            storage_gb=self.storage_gb + other.storage_gb,
            max_nodes=((self.max_nodes or 0) + (other.max_nodes or 0) if self.max_nodes is not None or other.max_nodes is not None else None),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation suitable for MongoDB storage
        """
        return {
            "cpu_cores": self.cpu_cores,
            "memory_gb": self.memory_gb,
            "storage_gb": self.storage_gb,
            "max_nodes": self.max_nodes,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "WorkerCapacity":
        """Create from dictionary (deserialization).

        Args:
            data: Dictionary with capacity fields

        Returns:
            WorkerCapacity instance
        """
        return WorkerCapacity(
            cpu_cores=data.get("cpu_cores", 0),
            memory_gb=data.get("memory_gb", 0),
            storage_gb=data.get("storage_gb", 0),
            max_nodes=data.get("max_nodes"),
        )

    def __str__(self) -> str:
        """Human-readable string representation."""
        nodes_str = f", max_nodes={self.max_nodes}" if self.max_nodes is not None else ""
        return f"WorkerCapacity(cpu={self.cpu_cores}, mem={self.memory_gb}GB, storage={self.storage_gb}GB{nodes_str})"
