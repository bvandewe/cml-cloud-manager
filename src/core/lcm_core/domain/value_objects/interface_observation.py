"""Interface observation value object — observed CML node interface at runtime.

ADR-030: Resource & Port Observation — "Learn from Live"
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InterfaceObservation:
    """Observed state of a single CML node interface during a live session.

    Captures the runtime interface configuration including IP addresses
    assigned by DHCP or static config — data only available when the lab is booted.
    """

    interface_id: str  # CML interface ID
    label: str  # Interface label (e.g., "GigabitEthernet0/0")
    slot: int  # Interface slot number
    state: str  # "UP", "DOWN", etc.
    mac_address: str | None  # MAC address if available
    ip4: tuple[str, ...]  # L3 IPv4 addresses (may be empty)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "interface_id": self.interface_id,
            "label": self.label,
            "slot": self.slot,
            "state": self.state,
            "mac_address": self.mac_address,
            "ip4": list(self.ip4),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "InterfaceObservation":
        """Create from dictionary."""
        return InterfaceObservation(
            interface_id=data["interface_id"],
            label=data["label"],
            slot=data.get("slot", 0),
            state=data.get("state", "UNKNOWN"),
            mac_address=data.get("mac_address"),
            ip4=tuple(data.get("ip4", [])),
        )
