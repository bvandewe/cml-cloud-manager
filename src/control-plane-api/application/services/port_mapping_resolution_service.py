"""Port Mapping Resolution Service — resolves port allocations for LabletRecordRun.

Resolves port allocations from three sources (Architecture §3.4):
1. LabRecord.external_interfaces  (parsed from CML node tags)
2. CML Worker IP                  (EC2 instance reachable address)
3. LabletSession.allocated_ports  (existing port mapping from PortAllocationService)

The resolved mapping is frozen at run creation time for LDS/grading stability.

Phase 11 (P11-4).
"""

import logging
from typing import Any

log = logging.getLogger(__name__)


class PortMappingResolutionService:
    """Resolves and freezes port allocations for a LabletRecordRun.

    Merges ExternalInterface definitions from the LabRecord with
    the worker's IP address and the LabletSession's allocated ports
    to produce a stable ``allocated_ports`` dict keyed by node_label.

    Each entry has the shape::

        {
            "protocol": "ssh",
            "external_port": 5041,
            "internal_port": 22,
            "host": "54.81.105.239"
        }
    """

    def resolve(
        self,
        external_interfaces: list[dict[str, Any]],
        worker_ip: str | None,
        lablet_allocated_ports: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resolve port allocations from all sources.

        Args:
            external_interfaces: List of ExternalInterface dicts from
                LabRecord.state.external_interfaces.
            worker_ip: Reachable IP address of the CML worker (EC2).
            lablet_allocated_ports: Existing port mapping from
                LabletSession.state.allocated_ports (optional).

        Returns:
            Dict keyed by ``node_label`` with resolved port mapping.
            Example::

                {
                    "router1": {
                        "protocol": "ssh",
                        "external_port": 5041,
                        "internal_port": 22,
                        "host": "54.81.105.239"
                    },
                    "switch1": {
                        "protocol": "telnet",
                        "external_port": 5042,
                        "internal_port": 23,
                        "host": "54.81.105.239"
                    }
                }
        """
        resolved: dict[str, Any] = {}

        # Step 1: Build base mapping from ExternalInterface definitions
        for iface in external_interfaces:
            node_label = iface.get("node_label", "")
            if not node_label:
                log.warning("Skipping ExternalInterface with empty node_label: %s", iface)
                continue

            resolved[node_label] = {
                "protocol": iface.get("protocol", "unknown"),
                "external_port": iface.get("port", 0),
                "internal_port": iface.get("port", 0),
                "host": iface.get("host") or worker_ip,
            }

        # Step 2: Overlay LabletSession allocated ports (if available)
        # These come from the PortAllocationService and may override
        # external_port values with dynamically allocated ports.
        if lablet_allocated_ports:
            for node_label, port_info in lablet_allocated_ports.items():
                if node_label in resolved:
                    # Override external port with dynamically allocated port
                    if isinstance(port_info, dict):
                        if "external_port" in port_info:
                            resolved[node_label]["external_port"] = port_info["external_port"]
                        if "host" in port_info:
                            resolved[node_label]["host"] = port_info["host"]
                    elif isinstance(port_info, int):
                        resolved[node_label]["external_port"] = port_info
                else:
                    # New node from lablet allocation not in ExternalInterface
                    if isinstance(port_info, dict):
                        resolved[node_label] = {
                            "protocol": port_info.get("protocol", "unknown"),
                            "external_port": port_info.get("external_port", 0),
                            "internal_port": port_info.get("internal_port", 0),
                            "host": port_info.get("host") or worker_ip,
                        }
                    elif isinstance(port_info, int):
                        resolved[node_label] = {
                            "protocol": "unknown",
                            "external_port": port_info,
                            "internal_port": port_info,
                            "host": worker_ip,
                        }

        # Step 3: Ensure all entries have a host (fallback to worker_ip)
        for node_label, mapping in resolved.items():
            if not mapping.get("host") and worker_ip:
                mapping["host"] = worker_ip

        log.debug("Resolved port mapping for %d nodes: %s", len(resolved), list(resolved.keys()))
        return resolved
