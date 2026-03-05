"""Port Allocation value object for CMLWorker aggregate.

Represents port allocations for lablet sessions on a CML worker.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class PortAllocation:
    """Immutable value object representing port allocation for a lablet session.

    Each lablet session may require specific ports for console access,
    API endpoints, or other external connectivity. This tracks which
    ports are allocated to which session.

    Attributes:
        session_id: LabletSession ID that owns this allocation
        ports: Mapping of logical port names to allocated port numbers
               e.g., {"console": 2000, "api": 2001, "vnc": 2002}
        allocated_at: Timestamp when ports were allocated
    """

    session_id: str
    ports: dict[str, int] = field(default_factory=dict)
    allocated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        """Validate port allocation values."""
        if not self.session_id:
            raise ValueError("session_id cannot be empty")

        # Validate port numbers are in valid range (2000-65535)
        for port_name, port_number in self.ports.items():
            if not isinstance(port_number, int):
                raise ValueError(f"Port number for '{port_name}' must be an integer")
            if port_number < 2000 or port_number > 65535:
                raise ValueError(f"Port number {port_number} for '{port_name}' must be between 2000 and 65535")

    def get_port(self, port_name: str) -> int | None:
        """Get allocated port by logical name.

        Args:
            port_name: Logical port name (e.g., "console", "api")

        Returns:
            Port number if found, None otherwise
        """
        return self.ports.get(port_name)

    def get_all_ports(self) -> list[int]:
        """Get all allocated port numbers.

        Returns:
            List of allocated port numbers
        """
        return list(self.ports.values())

    def port_count(self) -> int:
        """Get number of ports in this allocation.

        Returns:
            Number of allocated ports
        """
        return len(self.ports)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation suitable for MongoDB storage
        """
        return {
            "session_id": self.session_id,
            "ports": dict(self.ports),  # Convert to regular dict for serialization
            "allocated_at": self.allocated_at.isoformat() if self.allocated_at else None,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "PortAllocation":
        """Create from dictionary (deserialization).

        Args:
            data: Dictionary with port allocation fields

        Returns:
            PortAllocation instance
        """
        allocated_at_raw = data.get("allocated_at")
        if isinstance(allocated_at_raw, str):
            allocated_at = datetime.fromisoformat(allocated_at_raw)
        elif isinstance(allocated_at_raw, datetime):
            allocated_at = allocated_at_raw
        else:
            allocated_at = datetime.now(timezone.utc)

        return PortAllocation(
            session_id=data.get("session_id", data.get("instance_id", "")),
            ports=dict(data.get("ports", {})),
            allocated_at=allocated_at,
        )

    def __str__(self) -> str:
        """Human-readable string representation."""
        ports_str = ", ".join(f"{k}:{v}" for k, v in sorted(self.ports.items()))
        return f"PortAllocation(session={self.session_id}, ports=[{ports_str}])"
