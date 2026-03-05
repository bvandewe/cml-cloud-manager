"""Tests for ADR-030 resource observation value objects.

Validates round-trip serialization (to_dict / from_dict) for:
- InterfaceObservation
- NodeObservation
- ResourceObservation

These frozen dataclasses are shared between lablet-controller (constructs)
and control-plane-api (stores/reads).
"""

from datetime import UTC, datetime

from lcm_core.domain.value_objects.interface_observation import InterfaceObservation
from lcm_core.domain.value_objects.node_observation import NodeObservation
from lcm_core.domain.value_objects.resource_observation import ResourceObservation

# =============================================================================
# InterfaceObservation
# =============================================================================


class TestInterfaceObservation:
    """Round-trip serialization for InterfaceObservation."""

    def test_round_trip_full(self):
        """All fields populated — from_dict(to_dict(x)) == x."""
        obs = InterfaceObservation(
            interface_id="i0",
            label="GigabitEthernet0/0",
            slot=1,
            state="UP",
            mac_address="aa:bb:cc:dd:ee:ff",
            ip4=("10.0.0.1", "10.0.0.2"),
        )
        restored = InterfaceObservation.from_dict(obs.to_dict())
        assert restored == obs

    def test_round_trip_minimal(self):
        """Minimal fields — mac_address=None, empty ip4."""
        obs = InterfaceObservation(
            interface_id="i1",
            label="Loopback0",
            slot=0,
            state="DOWN",
            mac_address=None,
            ip4=(),
        )
        restored = InterfaceObservation.from_dict(obs.to_dict())
        assert restored == obs

    def test_to_dict_ip4_is_list(self):
        """ip4 serialized as list (not tuple) for JSON compatibility."""
        obs = InterfaceObservation(
            interface_id="i0",
            label="eth0",
            slot=0,
            state="UP",
            mac_address=None,
            ip4=("192.168.1.1",),
        )
        d = obs.to_dict()
        assert isinstance(d["ip4"], list)
        assert d["ip4"] == ["192.168.1.1"]

    def test_from_dict_defaults(self):
        """Missing optional fields get sensible defaults."""
        obs = InterfaceObservation.from_dict(
            {
                "interface_id": "i0",
                "label": "eth0",
            }
        )
        assert obs.slot == 0
        assert obs.state == "UNKNOWN"
        assert obs.mac_address is None
        assert obs.ip4 == ()


# =============================================================================
# NodeObservation
# =============================================================================


class TestNodeObservation:
    """Round-trip serialization for NodeObservation."""

    def _make_node_obs(self) -> NodeObservation:
        return NodeObservation(
            node_id="n0",
            label="PC",
            node_definition="ubuntu-desktop-24-04-v2",
            state="BOOTED",
            cpu_limit=2,
            ram_mb=4096,
            tags=("serial:5041", "vnc:5044"),
            interfaces=(
                InterfaceObservation(
                    interface_id="i0",
                    label="eth0",
                    slot=0,
                    state="UP",
                    mac_address="aa:bb:cc:dd:ee:ff",
                    ip4=("10.0.0.1",),
                ),
            ),
        )

    def test_round_trip_full(self):
        """Full NodeObservation round-trip with nested interfaces."""
        obs = self._make_node_obs()
        restored = NodeObservation.from_dict(obs.to_dict())
        assert restored == obs

    def test_round_trip_empty_interfaces(self):
        """NodeObservation with no interfaces."""
        obs = NodeObservation(
            node_id="n1",
            label="router",
            node_definition="iosv",
            state="STOPPED",
            cpu_limit=None,
            ram_mb=None,
            tags=(),
            interfaces=(),
        )
        restored = NodeObservation.from_dict(obs.to_dict())
        assert restored == obs

    def test_to_dict_tags_is_list(self):
        """tags serialized as list for JSON compatibility."""
        obs = self._make_node_obs()
        d = obs.to_dict()
        assert isinstance(d["tags"], list)

    def test_to_dict_interfaces_is_list_of_dicts(self):
        """interfaces serialized as list of dicts."""
        obs = self._make_node_obs()
        d = obs.to_dict()
        assert isinstance(d["interfaces"], list)
        assert isinstance(d["interfaces"][0], dict)

    def test_from_dict_defaults(self):
        """Missing optional fields get defaults."""
        obs = NodeObservation.from_dict(
            {
                "node_id": "n0",
                "label": "router",
            }
        )
        assert obs.node_definition == ""
        assert obs.state == "UNKNOWN"
        assert obs.cpu_limit is None
        assert obs.ram_mb is None
        assert obs.tags == ()
        assert obs.interfaces == ()


# =============================================================================
# ResourceObservation
# =============================================================================


class TestResourceObservation:
    """Round-trip serialization for ResourceObservation."""

    def _make_resource_obs(self) -> ResourceObservation:
        now = datetime(2026, 2, 28, 14, 30, 0, tzinfo=UTC)
        return ResourceObservation(
            observed_at=now,
            observer="lablet-controller",
            total_cpu_cores=4.0,
            total_memory_mb=8192,
            total_storage_mb=None,
            nodes=(
                NodeObservation(
                    node_id="n0",
                    label="PC",
                    node_definition="ubuntu-desktop-24-04-v2",
                    state="BOOTED",
                    cpu_limit=2,
                    ram_mb=4096,
                    tags=("serial:5041",),
                    interfaces=(
                        InterfaceObservation(
                            interface_id="i0",
                            label="eth0",
                            slot=0,
                            state="UP",
                            mac_address=None,
                            ip4=("10.0.0.1",),
                        ),
                    ),
                ),
                NodeObservation(
                    node_id="n1",
                    label="iosv-0",
                    node_definition="iosv",
                    state="BOOTED",
                    cpu_limit=2,
                    ram_mb=4096,
                    tags=("serial:5042",),
                    interfaces=(),
                ),
            ),
            actual_node_count=2,
            node_definitions_used=("iosv", "ubuntu-desktop-24-04-v2"),
            observed_ports={"PC_serial": 5041, "iosv-0_serial": 5042},
            simulation_stats={"nodes": {"n0": {"cpu_usage": 12.5}}},
        )

    def test_round_trip_full(self):
        """Full ResourceObservation round-trip with nested nodes."""
        obs = self._make_resource_obs()
        restored = ResourceObservation.from_dict(obs.to_dict())
        assert restored == obs

    def test_round_trip_minimal(self):
        """Minimal ResourceObservation — no nodes, no ports, no stats."""
        now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        obs = ResourceObservation(
            observed_at=now,
            observer="test",
            total_cpu_cores=0.0,
            total_memory_mb=0,
            total_storage_mb=None,
            nodes=(),
            actual_node_count=0,
            node_definitions_used=(),
            observed_ports={},
            simulation_stats=None,
        )
        restored = ResourceObservation.from_dict(obs.to_dict())
        assert restored == obs

    def test_to_dict_observed_at_is_isoformat(self):
        """observed_at serialized as ISO format string."""
        obs = self._make_resource_obs()
        d = obs.to_dict()
        assert isinstance(d["observed_at"], str)
        assert "2026-02-28" in d["observed_at"]

    def test_from_dict_parses_iso_datetime(self):
        """observed_at deserialized from ISO format string."""
        d = self._make_resource_obs().to_dict()
        restored = ResourceObservation.from_dict(d)
        assert isinstance(restored.observed_at, datetime)
        assert restored.observed_at.tzinfo is not None

    def test_from_dict_accepts_datetime_object(self):
        """observed_at already a datetime passes through."""
        now = datetime(2026, 2, 28, 14, 30, 0, tzinfo=UTC)
        d = self._make_resource_obs().to_dict()
        d["observed_at"] = now  # Pass datetime directly
        restored = ResourceObservation.from_dict(d)
        assert restored.observed_at == now

    def test_nodes_preserved_in_order(self):
        """Nodes maintain their original order after round-trip."""
        obs = self._make_resource_obs()
        restored = ResourceObservation.from_dict(obs.to_dict())
        assert len(restored.nodes) == 2
        assert restored.nodes[0].node_id == "n0"
        assert restored.nodes[1].node_id == "n1"

    def test_observed_ports_preserved(self):
        """observed_ports dict preserved after round-trip."""
        obs = self._make_resource_obs()
        restored = ResourceObservation.from_dict(obs.to_dict())
        assert restored.observed_ports == {"PC_serial": 5041, "iosv-0_serial": 5042}
