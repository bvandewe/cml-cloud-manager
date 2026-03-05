"""Unit tests for ResourceObserver — ADR-030 CML runtime observation.

Tests cover:
- observe() happy path: nodes, interfaces, simulation_stats → full ResourceObservation
- observe() partial: sim_stats unavailable → still returns observation
- observe() total failure: get_lab_nodes fails → returns None
- observe() no nodes: empty lab → returns None
- observe() port extraction: tags parsed into observed_ports
- observe() resource aggregation: CPU, memory summed from nodes

Pattern: object.__new__(ResourceObserver) to bypass DI, matching lablet-controller test conventions.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from application.services.resource_observer import ResourceObserver
from integration.services.cml_labs_spi import (
    CmlLabsSpiClient,
    InterfaceInfo,
    NodeInfo,
    SimulationStats,
)

# =============================================================================
# Fixtures
# =============================================================================


def _make_observer(cml_client: MagicMock | None = None) -> ResourceObserver:
    """Create a ResourceObserver with a mock CML client."""
    observer = object.__new__(ResourceObserver)
    observer._cml = cml_client or MagicMock(spec=CmlLabsSpiClient)
    return observer


def _make_node(
    node_id: str = "n0",
    label: str = "router1",
    node_definition: str = "iosv",
    state: str = "BOOTED",
    cpu_limit: int = 1,
    ram: int = 2048,
    tags: list[str] | None = None,
) -> NodeInfo:
    """Create a NodeInfo fixture."""
    return NodeInfo(
        id=node_id,
        label=label,
        node_definition=node_definition,
        state=state,
        cpu_limit=cpu_limit,
        ram=ram,
        tags=tags or [],
    )


def _make_interface(
    iface_id: str = "i0",
    label: str = "GigabitEthernet0/0",
    node_id: str = "n0",
    slot: int = 0,
    state: str = "UP",
    mac_address: str | None = "52:54:00:01:02:03",
    ip4: list[str] | None = None,
) -> InterfaceInfo:
    return InterfaceInfo(
        id=iface_id,
        label=label,
        node_id=node_id,
        slot=slot,
        state=state,
        mac_address=mac_address,
        ip4=ip4 or [],
    )


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.unit
class TestResourceObserver:
    """Tests for ResourceObserver.observe()."""

    @pytest.mark.asyncio
    async def test_happy_path_full_observation(self) -> None:
        """Full observation with nodes, interfaces, and sim_stats."""
        cml = MagicMock(spec=CmlLabsSpiClient)
        cml.get_lab_nodes = AsyncMock(
            return_value=[
                _make_node(node_id="n0", label="PC", cpu_limit=1, ram=512, tags=["serial:5041", "vnc:5044"]),
                _make_node(node_id="n1", label="iosv-0", cpu_limit=2, ram=4096, tags=["serial:5042"]),
            ]
        )
        cml.get_node_interfaces = AsyncMock(
            side_effect=[
                [_make_interface(iface_id="i0", label="eth0", node_id="n0")],
                [_make_interface(iface_id="i1", label="Gi0/0", node_id="n1")],
            ]
        )
        cml.get_lab_simulation_stats = AsyncMock(
            return_value=SimulationStats(
                lab_id="lab-99",
                nodes={"n0": {"state": "BOOTED"}},
                links={},
                raw={"nodes": {"n0": {"state": "BOOTED"}}},
            )
        )

        observer = _make_observer(cml)
        result = await observer.observe(host="10.0.0.1", lab_id="lab-99")

        assert result is not None
        assert result.total_cpu_cores == 3.0  # 1 + 2
        assert result.total_memory_mb == 4608  # 512 + 4096
        assert result.actual_node_count == 2
        assert len(result.nodes) == 2
        assert "iosv" in result.node_definitions_used
        assert result.simulation_stats is not None
        assert result.observer == "lablet-controller"
        assert result.observed_at is not None

    @pytest.mark.asyncio
    async def test_port_extraction_from_tags(self) -> None:
        """Tags with valid protocols are extracted as observed_ports."""
        cml = MagicMock(spec=CmlLabsSpiClient)
        cml.get_lab_nodes = AsyncMock(
            return_value=[
                _make_node(node_id="n0", label="PC", tags=["serial:5041", "vnc:5044"]),
                _make_node(node_id="n1", label="iosv-0", tags=["serial:5042"]),
            ]
        )
        cml.get_node_interfaces = AsyncMock(return_value=[])
        cml.get_lab_simulation_stats = AsyncMock(return_value=None)

        observer = _make_observer(cml)
        result = await observer.observe(host="10.0.0.1", lab_id="lab-99")

        assert result is not None
        assert result.observed_ports["PC_serial"] == 5041
        assert result.observed_ports["PC_vnc"] == 5044
        assert result.observed_ports["iosv-0_serial"] == 5042
        assert len(result.observed_ports) == 3

    @pytest.mark.asyncio
    async def test_sim_stats_unavailable_still_returns_observation(self) -> None:
        """When simulation_stats raises, observation still returned."""
        cml = MagicMock(spec=CmlLabsSpiClient)
        cml.get_lab_nodes = AsyncMock(return_value=[_make_node(node_id="n0", label="PC")])
        cml.get_node_interfaces = AsyncMock(return_value=[])
        cml.get_lab_simulation_stats = AsyncMock(side_effect=Exception("503 Service Unavailable"))

        observer = _make_observer(cml)
        result = await observer.observe(host="10.0.0.1", lab_id="lab-99")

        assert result is not None
        assert result.simulation_stats is None
        assert result.actual_node_count == 1

    @pytest.mark.asyncio
    async def test_total_failure_returns_none(self) -> None:
        """When get_lab_nodes raises, returns None."""
        cml = MagicMock(spec=CmlLabsSpiClient)
        cml.get_lab_nodes = AsyncMock(side_effect=Exception("Connection refused"))

        observer = _make_observer(cml)
        result = await observer.observe(host="10.0.0.1", lab_id="lab-99")

        assert result is None

    @pytest.mark.asyncio
    async def test_no_nodes_returns_none(self) -> None:
        """When lab has no nodes, returns None."""
        cml = MagicMock(spec=CmlLabsSpiClient)
        cml.get_lab_nodes = AsyncMock(return_value=[])

        observer = _make_observer(cml)
        result = await observer.observe(host="10.0.0.1", lab_id="lab-99")

        assert result is None

    @pytest.mark.asyncio
    async def test_resource_aggregation(self) -> None:
        """CPU and memory are summed across all nodes."""
        cml = MagicMock(spec=CmlLabsSpiClient)
        cml.get_lab_nodes = AsyncMock(
            return_value=[
                _make_node(node_id="n0", cpu_limit=2, ram=1024, node_definition="ubuntu-desktop-24-04-v2"),
                _make_node(node_id="n1", cpu_limit=4, ram=8192, node_definition="iosv"),
                _make_node(node_id="n2", cpu_limit=1, ram=512, node_definition="iosv"),
            ]
        )
        cml.get_node_interfaces = AsyncMock(return_value=[])
        cml.get_lab_simulation_stats = AsyncMock(return_value=None)

        observer = _make_observer(cml)
        result = await observer.observe(host="10.0.0.1", lab_id="lab-99")

        assert result is not None
        assert result.total_cpu_cores == 7.0  # 2 + 4 + 1
        assert result.total_memory_mb == 9728  # 1024 + 8192 + 512
        assert result.actual_node_count == 3
        assert set(result.node_definitions_used) == {"ubuntu-desktop-24-04-v2", "iosv"}

    @pytest.mark.asyncio
    async def test_node_observations_include_interfaces(self) -> None:
        """NodeObservation includes interface details."""
        cml = MagicMock(spec=CmlLabsSpiClient)
        cml.get_lab_nodes = AsyncMock(return_value=[_make_node(node_id="n0", label="router1")])
        cml.get_node_interfaces = AsyncMock(
            return_value=[
                _make_interface(iface_id="i0", label="Gi0/0", node_id="n0", state="UP"),
                _make_interface(iface_id="i1", label="Gi0/1", node_id="n0", state="DOWN"),
            ]
        )
        cml.get_lab_simulation_stats = AsyncMock(return_value=None)

        observer = _make_observer(cml)
        result = await observer.observe(host="10.0.0.1", lab_id="lab-99")

        assert result is not None
        assert len(result.nodes[0].interfaces) == 2
        assert result.nodes[0].interfaces[0].label == "Gi0/0"
        assert result.nodes[0].interfaces[1].state == "DOWN"

    @pytest.mark.asyncio
    async def test_non_protocol_tags_ignored(self) -> None:
        """Tags that don't match CML_TCP_PROTOCOLS are ignored."""
        cml = MagicMock(spec=CmlLabsSpiClient)
        cml.get_lab_nodes = AsyncMock(
            return_value=[
                _make_node(node_id="n0", label="PC", tags=["serial:5041", "foobar:9999", "group:lab101"]),
            ]
        )
        cml.get_node_interfaces = AsyncMock(return_value=[])
        cml.get_lab_simulation_stats = AsyncMock(return_value=None)

        observer = _make_observer(cml)
        result = await observer.observe(host="10.0.0.1", lab_id="lab-99")

        assert result is not None
        # Only "serial" is a valid protocol, "foobar" and "group" are not
        assert "PC_serial" in result.observed_ports
        assert "PC_foobar" not in result.observed_ports
        assert "PC_group" not in result.observed_ports
