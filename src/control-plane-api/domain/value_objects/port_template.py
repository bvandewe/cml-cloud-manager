"""Port Template value object for LabletDefinition."""

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Protocols that CML uses over TCP connections
CML_TCP_PROTOCOLS = frozenset({"serial", "vnc", "ssh", "telnet", "tcp", "http", "https"})


@dataclass(frozen=True)
class PortDefinition:
    """A single port definition within a port template.

    Defines a named port that will be allocated when a LabletSession is scheduled.
    """

    name: str  # Logical name (e.g., "serial_1", "vnc_1", "http")
    protocol: str = "tcp"  # Protocol: "tcp" or "udp"
    description: str | None = None  # Human-readable description

    def __post_init__(self) -> None:
        """Validate port definition on creation."""
        if not self.name:
            raise ValueError("Port name cannot be empty")
        if self.protocol not in ("tcp", "udp"):
            raise ValueError(f"Invalid protocol '{self.protocol}'. Must be 'tcp' or 'udp'")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "protocol": self.protocol,
            "description": self.description,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "PortDefinition":
        """Create from dictionary."""
        return PortDefinition(
            name=data["name"],
            protocol=data.get("protocol", "tcp"),
            description=data.get("description"),
        )


@dataclass(frozen=True)
class PortTemplate:
    """Template for port allocation with placeholders.

    A PortTemplate defines the ports that need to be allocated when a
    LabletSession is scheduled on a worker. Actual port numbers are
    assigned dynamically by the PortAllocationService from the worker's
    available port pool.

    Example usage:
        template = PortTemplate(ports=(
            PortDefinition(name="serial_1", protocol="tcp", description="Serial console"),
            PortDefinition(name="vnc_1", protocol="tcp", description="VNC display"),
            PortDefinition(name="http", protocol="tcp", description="HTTP service"),
        ))

        # When allocated, becomes:
        # {"serial_1": 5041, "vnc_1": 5042, "http": 5043}
    """

    ports: tuple[PortDefinition, ...]  # Immutable tuple of port definitions

    def __post_init__(self) -> None:
        """Validate port template on creation."""
        # Check for duplicate port names
        names = [p.name for p in self.ports]
        if len(names) != len(set(names)):
            raise ValueError("Port names must be unique within a template")

    @property
    def port_count(self) -> int:
        """Return the number of ports in this template."""
        return len(self.ports)

    @property
    def port_names(self) -> tuple[str, ...]:
        """Return the names of all ports in this template."""
        return tuple(p.name for p in self.ports)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "ports": [p.to_dict() for p in self.ports],
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "PortTemplate":
        """Create from dictionary."""
        ports = [PortDefinition.from_dict(p) for p in data.get("ports", [])]
        return PortTemplate(ports=tuple(ports))

    @staticmethod
    def empty() -> "PortTemplate":
        """Create an empty port template."""
        return PortTemplate(ports=())

    @staticmethod
    def from_cml_nodes(nodes: list[dict[str, Any]]) -> "PortTemplate":
        """Build a PortTemplate by extracting protocol tags from CML topology nodes.

        Parses each node's ``tags`` list for entries in ``protocol:port`` format
        (CML's colon-separated port serialization convention).  The port *number*
        is intentionally ignored — it is a placeholder in the topology file.
        Actual port numbers are allocated at scheduling time by the
        PortAllocationService.

        Naming convention for generated :class:`PortDefinition` entries::

            {node_label}_{protocol}   e.g. "PC_serial", "PC_vnc", "iosv-0_serial"

        Only recognised TCP-based protocols are included (see
        :data:`CML_TCP_PROTOCOLS`).  Duplicate ``(label, protocol)`` pairs within
        the same node are silently de-duplicated; unrecognised tag formats are
        logged at DEBUG level and skipped.

        Args:
            nodes: List of CML topology node dicts, each with at least
                ``label`` (str) and ``tags`` (list[str]).  Missing or empty
                ``tags`` lists are tolerated.

        Returns:
            A PortTemplate containing one :class:`PortDefinition` per
            unique ``(node_label, protocol)`` pair found.
        """
        # Matches "protocol:port_number" — port number may be absent
        tag_pattern = re.compile(r"^([a-zA-Z][a-zA-Z0-9_-]*):(\d+)?$")
        ports: list[PortDefinition] = []
        seen: set[str] = set()  # track "label_protocol" to avoid duplicates

        for node in nodes:
            label = node.get("label", "")
            if not label:
                continue

            tags: list[str] = node.get("tags") or []
            for tag in tags:
                match = tag_pattern.match(tag.strip())
                if not match:
                    logger.debug("Skipping unrecognised CML tag '%s' on node '%s'", tag, label)
                    continue

                protocol = match.group(1).lower()
                if protocol not in CML_TCP_PROTOCOLS:
                    logger.debug("Skipping non-TCP protocol '%s' on node '%s'", protocol, label)
                    continue

                # Sanitise label for use in port name (spaces → underscores, strip special chars)
                safe_label = re.sub(r"[^a-zA-Z0-9_-]", "_", label)
                port_name = f"{safe_label}_{protocol}"

                if port_name in seen:
                    continue
                seen.add(port_name)

                ports.append(
                    PortDefinition(
                        name=port_name,
                        protocol="tcp",  # All CML console protocols run over TCP
                        description=f"{protocol} on {label}",
                    )
                )

        return PortTemplate(ports=tuple(ports))
