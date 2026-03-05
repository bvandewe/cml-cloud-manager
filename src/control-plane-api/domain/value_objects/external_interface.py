"""ExternalInterface value object for LabRecord aggregate.

Represents a reachable external interface on a lab node, typically
derived from CML node tags (e.g., ``i1_protocol=ssh``, ``i1_port=22``).

These interfaces are used by LabletRecordRun (Phase 11) to build
port mapping tables for LDS and grading integration.

Architecture ref: §4.1 Value Objects.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExternalInterface:
    """A reachable external interface on a lab node.

    Attributes:
        node_label: CML node label (e.g., "router1", "switch2").
        protocol: Access protocol (e.g., "ssh", "telnet", "https", "vnc").
        port: Port number on the node for this protocol.
        host: Hostname or IP to reach this interface (resolved at runtime).
        password: Optional access credential (e.g., console password).
    """

    node_label: str
    protocol: str
    port: int
    host: str | None = None
    password: str | None = None

    def __post_init__(self) -> None:
        if not self.node_label:
            raise ValueError("node_label cannot be empty")
        if not self.protocol:
            raise ValueError("protocol cannot be empty")
        if self.port < 1 or self.port > 65535:
            raise ValueError(f"port must be between 1 and 65535, got {self.port}")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "node_label": self.node_label,
            "protocol": self.protocol,
            "port": self.port,
            "host": self.host,
            "password": self.password,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ExternalInterface":
        """Create from dictionary."""
        return ExternalInterface(
            node_label=data["node_label"],
            protocol=data["protocol"],
            port=data["port"],
            host=data.get("host"),
            password=data.get("password"),
        )

    def __str__(self) -> str:
        host_str = f"@{self.host}" if self.host else ""
        return f"{self.node_label}:{self.protocol}/{self.port}{host_str}"
