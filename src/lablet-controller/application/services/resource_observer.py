"""Resource observation service — observes live CML lab resources.

Queries CML API for runtime resource consumption, port allocations,
and simulation statistics, then assembles a ResourceObservation.

AD-OLR-006: Uses simulation_stats + node details + interfaces.
ADR-030: Resource & Port Observation — "Learn from Live"
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any

from integration.services.cml_labs_spi import CmlLabsSpiClient
from lcm_core.domain.value_objects.interface_observation import InterfaceObservation
from lcm_core.domain.value_objects.node_observation import NodeObservation
from lcm_core.domain.value_objects.resource_observation import ResourceObservation

logger = logging.getLogger(__name__)

# Same protocols as PortTemplate (ADR-029)
CML_TCP_PROTOCOLS = frozenset({"serial", "vnc", "ssh", "telnet", "tcp", "http", "https"})
TAG_PATTERN = re.compile(r"^([a-zA-Z][a-zA-Z0-9_-]*):(\d+)$")


class ResourceObserver:
    """Observes live CML lab resources and assembles ResourceObservation.

    Pure observation service — all writes go through CPA via ControlPlaneApiClient.
    Failures are logged but never raised (best-effort observation).
    """

    def __init__(self, cml_labs_client: CmlLabsSpiClient):
        self._cml = cml_labs_client

    async def observe(
        self,
        host: str,
        lab_id: str,
        username: str | None = None,
        password: str | None = None,
        observer: str = "lablet-controller",
    ) -> ResourceObservation | None:
        """Observe resource consumption for a running CML lab.

        Queries:
        1. GET /labs/{id}/nodes (+ per-node detail) → cpu_limit, ram, tags
        2. GET /labs/{id}/nodes/{nid}/interfaces → interface details
        3. GET /labs/{id}/simulation_stats → runtime CPU metrics

        Returns None if observation fails entirely (e.g., lab not accessible).
        Partial failures (e.g., simulation_stats unavailable) are tolerated.

        Args:
            host: CML worker host/IP.
            lab_id: CML lab ID.
            username: CML API username.
            password: CML API password.
            observer: Identity of the observer (for audit trail).

        Returns:
            ResourceObservation or None on failure.
        """
        try:
            # 1. Get all nodes with details
            nodes = await self._cml.get_lab_nodes(host, lab_id, username, password)
            if not nodes:
                logger.warning(f"No nodes found for lab {lab_id} on {host}")
                return None

            # 2. Get interfaces for each node and build observations
            node_observations: list[NodeObservation] = []
            total_cpu = 0.0
            total_memory = 0
            observed_ports: dict[str, int] = {}
            node_definitions: set[str] = set()

            for node in nodes:
                # Fetch interfaces
                interfaces = await self._cml.get_node_interfaces(host, lab_id, node.id, username, password)

                iface_observations = tuple(
                    InterfaceObservation(
                        interface_id=iface.id,
                        label=iface.label,
                        slot=iface.slot or 0,
                        state=iface.state or "UNKNOWN",
                        mac_address=iface.mac_address,
                        ip4=tuple(iface.ip4 or []),
                    )
                    for iface in interfaces
                )

                node_obs = NodeObservation(
                    node_id=node.id,
                    label=node.label,
                    node_definition=node.node_definition,
                    state=node.state,
                    cpu_limit=node.cpu_limit,
                    ram_mb=node.ram,
                    tags=tuple(node.tags or []),
                    interfaces=iface_observations,
                )
                node_observations.append(node_obs)

                # Aggregate resources
                if node.cpu_limit:
                    total_cpu += node.cpu_limit
                if node.ram:
                    total_memory += node.ram
                node_definitions.add(node.node_definition)

                # Extract ports from tags (same logic as PortTemplate.from_cml_nodes)
                for tag in node.tags or []:
                    match = TAG_PATTERN.match(tag.strip())
                    if match:
                        protocol = match.group(1).lower()
                        port_number = int(match.group(2))
                        if protocol in CML_TCP_PROTOCOLS:
                            safe_label = re.sub(r"[^a-zA-Z0-9_-]", "_", node.label)
                            port_name = f"{safe_label}_{protocol}"
                            observed_ports[port_name] = port_number

            # 3. Get simulation stats (best-effort)
            sim_stats_raw: dict[str, Any] | None = None
            try:
                sim_stats = await self._cml.get_lab_simulation_stats(host, lab_id, username, password)
                if sim_stats:
                    sim_stats_raw = sim_stats.raw
            except Exception as e:
                logger.debug(f"Could not fetch simulation_stats for lab {lab_id}: {e}")

            return ResourceObservation(
                observed_at=datetime.now(timezone.utc),
                observer=observer,
                total_cpu_cores=total_cpu,
                total_memory_mb=total_memory,
                total_storage_mb=None,  # Future: resource_pool_usage (P2)
                nodes=tuple(node_observations),
                actual_node_count=len(node_observations),
                node_definitions_used=tuple(sorted(node_definitions)),
                observed_ports=observed_ports,
                simulation_stats=sim_stats_raw,
            )

        except Exception as e:
            logger.error(f"Failed to observe resources for lab {lab_id} on {host}: {e}")
            return None

    @classmethod
    def configure(cls, services: Any) -> None:
        """Configure DI registration.

        Args:
            services: Neuroglia service collection.
        """
        services.add_singleton(
            cls,
            implementation_factory=lambda sp: cls(
                cml_labs_client=sp.get_required_service(CmlLabsSpiClient),
            ),
        )
