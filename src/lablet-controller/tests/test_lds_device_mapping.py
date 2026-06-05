"""Tests for LDS device mapping — AD-LDS-001 Phase 2, AD-LDS-002.

Unit tests for:
- build_device_access_from_allocated_ports(): port name parsing + visibility filtering + multi-port dedup
- step_lds_provision: filtered device mapping with allocated ports and fallback
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from application.services.reconciler_helpers.lds_helpers import (
    DEFAULT_PROTOCOL_PRIORITY,
    build_device_access_from_allocated_ports,
)

# =============================================================================
# Tests for build_device_access_from_allocated_ports
# =============================================================================


class TestBuildDeviceAccessFromAllocatedPorts:
    """Tests for build_device_access_from_allocated_ports() — AD-LDS-001."""

    def test_standard_parsing(self):
        """Standard port names are parsed correctly."""
        allocated_ports = {
            "Router1_serial": 5041,
            "Switch1_ssh": 5042,
            "Server1_vnc": 5043,
        }

        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
        )

        assert len(devices) == 3
        labels = {d.device_label for d in devices}
        assert labels == {"Router1", "Switch1", "Server1"}

        # Check specific device
        router = next(d for d in devices if d.device_label == "Router1")
        assert router.protocol == "serial"
        assert router.host == "10.0.0.1"
        assert router.port == 5041

    def test_filtering_by_visible_labels(self):
        """Only devices in user_visible_labels are included."""
        allocated_ports = {
            "Router1_serial": 5041,
            "backbone-sw_ssh": 5042,  # Hidden infra
            "Desktop1_vnc": 5043,
        }
        visible_labels = {"Router1", "Desktop1"}

        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
            user_visible_labels=visible_labels,
        )

        assert len(devices) == 2
        labels = {d.device_label for d in devices}
        assert labels == {"Router1", "Desktop1"}
        assert "backbone-sw" not in labels

    def test_label_with_underscores(self):
        """Labels containing underscores are handled via rsplit."""
        allocated_ports = {
            "ubuntu_desktop_1_serial": 5041,
            "my_router_ssh": 5042,
        }

        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
        )

        assert len(devices) == 2
        labels = {d.device_label for d in devices}
        assert "ubuntu_desktop_1" in labels
        assert "my_router" in labels

    def test_empty_allocated_ports(self):
        """Empty allocated_ports returns empty list."""
        devices = build_device_access_from_allocated_ports(
            allocated_ports={},
            worker_ip="10.0.0.1",
            user_visible_labels={"Router1"},
        )

        assert devices == []

    def test_none_visible_labels_includes_all(self):
        """When user_visible_labels is None, all devices are included."""
        allocated_ports = {
            "Router1_serial": 5041,
            "backbone-sw_ssh": 5042,
            "Desktop1_vnc": 5043,
        }

        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
            user_visible_labels=None,
        )

        assert len(devices) == 3

    def test_unparseable_port_name_skipped(self):
        """Port names without underscore are skipped with warning."""
        allocated_ports = {
            "Router1_serial": 5041,
            "badportname": 5042,  # No underscore
        }

        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
        )

        assert len(devices) == 1
        assert devices[0].device_label == "Router1"

    def test_empty_visible_labels_set_filters_all(self):
        """An empty visible_labels set (not None) filters out everything."""
        allocated_ports = {
            "Router1_serial": 5041,
        }

        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
            user_visible_labels=set(),
        )

        assert devices == []


# =============================================================================
# Tests for multi-port device deduplication (AD-LDS-002)
# =============================================================================


class TestMultiPortDeviceDedup:
    """Tests for multi-port device resolution via protocol priority — AD-LDS-002."""

    def test_multi_port_picks_highest_priority(self):
        """When a device has serial + vnc, vnc wins (higher in default priority)."""
        allocated_ports = {
            "ubuntu-desktop_serial": 2003,
            "ubuntu-desktop_vnc": 2004,
        }

        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
        )

        assert len(devices) == 1
        assert devices[0].device_label == "ubuntu-desktop"
        assert devices[0].protocol == "vnc"
        assert devices[0].port == 2004

    def test_multi_port_custom_priority(self):
        """Custom priority order changes which protocol wins."""
        allocated_ports = {
            "ubuntu-desktop_serial": 2003,
            "ubuntu-desktop_vnc": 2004,
        }

        # serial first in custom priority
        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
            protocol_priority=["serial", "vnc", "ssh"],
        )

        assert len(devices) == 1
        assert devices[0].device_label == "ubuntu-desktop"
        assert devices[0].protocol == "serial"
        assert devices[0].port == 2003

    def test_single_port_device_unaffected(self):
        """Devices with a single port pass through unchanged."""
        allocated_ports = {
            "Router1_serial": 5041,
            "Desktop1_vnc": 5043,
        }

        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
        )

        assert len(devices) == 2
        labels = {d.device_label for d in devices}
        assert labels == {"Router1", "Desktop1"}

    def test_multi_port_with_visibility_filter(self):
        """Multi-port dedup applies after visibility filtering."""
        allocated_ports = {
            "ubuntu-desktop_serial": 2003,
            "ubuntu-desktop_vnc": 2004,
            "hidden-router_serial": 2005,
        }

        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
            user_visible_labels={"ubuntu-desktop"},
        )

        assert len(devices) == 1
        assert devices[0].device_label == "ubuntu-desktop"
        assert devices[0].protocol == "vnc"

    def test_unknown_protocol_lowest_priority(self):
        """Protocol not in priority list loses to any known protocol."""
        allocated_ports = {
            "device1_exotic": 3001,
            "device1_serial": 3002,
        }

        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
        )

        assert len(devices) == 1
        assert devices[0].protocol == "serial"
        assert devices[0].port == 3002

    def test_all_unknown_protocols_picks_first(self):
        """When all protocols are unknown, first encountered wins."""
        allocated_ports = {
            "device1_foo": 3001,
            "device1_bar": 3002,
        }

        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
        )

        assert len(devices) == 1
        assert devices[0].device_label == "device1"

    def test_three_ports_same_device(self):
        """Three annotations on same device — highest priority wins."""
        allocated_ports = {
            "workstation_serial": 3001,
            "workstation_vnc": 3002,
            "workstation_ssh": 3003,
        }

        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
        )

        assert len(devices) == 1
        assert devices[0].protocol == "vnc"
        assert devices[0].port == 3002

    def test_mixed_single_and_multi_port_devices(self):
        """Mix of single-port and multi-port devices resolves correctly."""
        allocated_ports = {
            "router_serial": 3001,
            "desktop_serial": 3002,
            "desktop_vnc": 3003,
            "server_ssh": 3004,
        }

        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
        )

        assert len(devices) == 3
        device_map = {d.device_label: d for d in devices}
        assert device_map["router"].protocol == "serial"
        assert device_map["desktop"].protocol == "vnc"
        assert device_map["server"].protocol == "ssh"

    def test_default_protocol_priority_constant(self):
        """DEFAULT_PROTOCOL_PRIORITY has expected order."""
        assert DEFAULT_PROTOCOL_PRIORITY[0] == "vnc"
        assert "serial" in DEFAULT_PROTOCOL_PRIORITY
        assert "telnet" in DEFAULT_PROTOCOL_PRIORITY
        assert DEFAULT_PROTOCOL_PRIORITY.index("vnc") < DEFAULT_PROTOCOL_PRIORITY.index("serial")


class TestPortPreferencesOverride:
    """Tests for user-configurable port preferences — AD-LDS-002 Phase 3."""

    def test_preference_overrides_priority(self):
        """User preference selects serial even though vnc has higher priority."""
        allocated_ports = {
            "ubuntu-desktop_serial": 2003,
            "ubuntu-desktop_vnc": 2004,
        }

        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
            port_preferences={"ubuntu-desktop": "ubuntu-desktop_serial"},
        )

        assert len(devices) == 1
        assert devices[0].device_label == "ubuntu-desktop"
        assert devices[0].protocol == "serial"
        assert devices[0].port == 2003

    def test_preference_with_no_conflict_ignored(self):
        """Preferences for single-port devices are harmless (no conflict to resolve)."""
        allocated_ports = {
            "router_serial": 5041,
        }

        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
            port_preferences={"router": "router_serial"},
        )

        assert len(devices) == 1
        assert devices[0].protocol == "serial"

    def test_preference_for_nonexistent_protocol_falls_back(self):
        """If preference references a protocol not in candidates, fall back to priority."""
        allocated_ports = {
            "desktop_serial": 2003,
            "desktop_vnc": 2004,
        }

        # Preference says "desktop_ssh" but ssh is not allocated
        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
            port_preferences={"desktop": "desktop_ssh"},
        )

        assert len(devices) == 1
        # Falls back to priority → vnc wins
        assert devices[0].protocol == "vnc"
        assert devices[0].port == 2004

    def test_preference_only_applies_to_specified_device(self):
        """Preferences only affect the specified device; others use priority."""
        allocated_ports = {
            "desktop_serial": 2003,
            "desktop_vnc": 2004,
            "workstation_serial": 3001,
            "workstation_vnc": 3002,
        }

        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
            port_preferences={"desktop": "desktop_serial"},
        )

        assert len(devices) == 2
        device_map = {d.device_label: d for d in devices}
        # desktop: user preference → serial
        assert device_map["desktop"].protocol == "serial"
        assert device_map["desktop"].port == 2003
        # workstation: no preference → priority → vnc
        assert device_map["workstation"].protocol == "vnc"
        assert device_map["workstation"].port == 3002

    def test_empty_preferences_uses_priority(self):
        """Empty preferences dict behaves same as None (priority-based)."""
        allocated_ports = {
            "desktop_serial": 2003,
            "desktop_vnc": 2004,
        }

        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
            port_preferences={},
        )

        assert len(devices) == 1
        assert devices[0].protocol == "vnc"

    def test_preference_with_three_ports(self):
        """User can pick any of three available protocols."""
        allocated_ports = {
            "workstation_serial": 3001,
            "workstation_vnc": 3002,
            "workstation_ssh": 3003,
        }

        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
            port_preferences={"workstation": "workstation_ssh"},
        )

        assert len(devices) == 1
        assert devices[0].protocol == "ssh"
        assert devices[0].port == 3003

    def test_preference_combined_with_custom_priority(self):
        """Preference takes precedence even when custom priority is also set."""
        allocated_ports = {
            "desktop_serial": 2003,
            "desktop_vnc": 2004,
        }

        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip="10.0.0.1",
            protocol_priority=["serial", "vnc"],  # serial would win by priority
            port_preferences={"desktop": "desktop_vnc"},  # but user wants vnc
        )

        assert len(devices) == 1
        assert devices[0].protocol == "vnc"
        assert devices[0].port == 2004


# =============================================================================
# Tests for step_lds_provision (filtered)
# =============================================================================


@dataclass
class _FakeSessionInfo:
    session_id: str = "lds-session-123"


@dataclass
class _FakeDefinition:
    form_qualified_name: str | None = "com.cisco.lablet.test"
    user_visible_devices: list[dict[str, str]] | None = None


@dataclass
class _FakeInstance:
    id: str = "session-001"
    name: str = "test-user"
    worker_id: str = "worker-001"
    worker_aws_region: str = "us-east-1"


def _make_context(
    definition: _FakeDefinition | None = None,
    allocated_ports: dict[str, int] | None = None,
) -> MagicMock:
    """Build a mock PipelineContext."""
    ctx = MagicMock()
    ctx.definition = definition or _FakeDefinition()
    ctx.worker_ip = "10.0.0.1"
    ctx.worker_cml_username = "admin"
    ctx.worker_cml_password = "secret"  # noqa: S105  # pragma: allowlist secret

    # AD-LDS-002: Protocol priority for multi-port device resolution
    ctx.lds_protocol_priority = DEFAULT_PROTOCOL_PRIORITY

    # LDS mock
    ctx.lds = AsyncMock()
    ctx.lds.create_session = AsyncMock(return_value=_FakeSessionInfo())
    ctx.lds.set_devices = AsyncMock()
    ctx.lds.get_lablet_launch_url = AsyncMock(return_value="https://lds.example.com/launch/abc")

    # CML mock
    ctx.cml = AsyncMock()
    ctx.cml.get_lab_nodes = AsyncMock(return_value=[])

    # CPA API mock
    ctx.api = AsyncMock()
    ctx.api.create_user_session = AsyncMock(return_value={"id": "user-session-001"})

    # Build device access list callable (legacy)
    ctx.build_device_access_list = None

    return ctx


def _make_progress(
    cml_lab_id: str = "lab-001",
    allocated_ports: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build a mock progress dict with lab_resolve and optional ports_alloc."""
    progress: dict[str, Any] = {
        "lab_resolve": {
            "status": "completed",
            "result_data": {
                "cml_lab_id": cml_lab_id,
                "lab_record_id": "lr-001",
                "cml_lab_title": "Test Lab",
            },
        },
    }
    if allocated_ports is not None:
        progress["ports_alloc"] = {
            "status": "completed",
            "result_data": {
                "allocated_ports": allocated_ports,
            },
        }
    return progress


@pytest.mark.asyncio
class TestStepLdsProvisionFiltered:
    """Tests for step_lds_provision with visibility filtering — AD-LDS-001."""

    async def test_filters_by_visible_devices(self):
        """Only user-visible devices from allocated_ports are set on LDS."""
        from application.services.step_handlers.lds_provision_step import step_lds_provision

        definition = _FakeDefinition(
            user_visible_devices=[
                {"device_label": "Router1", "user_access_mode": "ssh"},
                {"device_label": "Desktop1", "user_access_mode": "vnc"},
            ]
        )
        context = _make_context(definition=definition)
        progress = _make_progress(
            allocated_ports={
                "Router1_serial": 5041,
                "backbone-sw_ssh": 5042,  # Hidden
                "Desktop1_vnc": 5043,
            }
        )

        result = await step_lds_provision(
            instance=_FakeInstance(),
            progress=progress,
            context=context,
        )

        assert result.status == "completed"
        assert result.result_data["device_count"] == 2

        # Verify set_devices was called with only visible devices
        call_args = context.lds.set_devices.call_args
        devices = call_args.kwargs.get("devices") or call_args[1].get("devices")
        labels = {d.device_label for d in devices}
        assert labels == {"Router1", "Desktop1"}
        assert "backbone-sw" not in labels

    async def test_no_allocated_ports_uses_fallback(self):
        """When ports_alloc is absent, falls back to tag-based path."""
        from application.services.step_handlers.lds_provision_step import step_lds_provision

        @dataclass
        class FakeNode:
            label: str
            tags: list[str]

        definition = _FakeDefinition(
            user_visible_devices=[
                {"device_label": "Router1", "user_access_mode": "ssh"},
            ]
        )
        context = _make_context(definition=definition)
        context.cml.get_lab_nodes = AsyncMock(
            return_value=[
                FakeNode(label="Router1", tags=["serial:5041"]),
                FakeNode(label="backbone-sw", tags=["ssh:22"]),
            ]
        )
        # No ports_alloc in progress
        progress = _make_progress(allocated_ports=None)

        result = await step_lds_provision(
            instance=_FakeInstance(),
            progress=progress,
            context=context,
        )

        assert result.status == "completed"
        assert result.result_data["device_count"] == 1  # Only Router1

    async def test_backward_compat_no_user_visible_devices(self):
        """When user_visible_devices is None, all devices from allocated_ports are included."""
        from application.services.step_handlers.lds_provision_step import step_lds_provision

        definition = _FakeDefinition(user_visible_devices=None)
        context = _make_context(definition=definition)
        progress = _make_progress(
            allocated_ports={
                "Router1_serial": 5041,
                "backbone-sw_ssh": 5042,
                "Desktop1_vnc": 5043,
            }
        )

        result = await step_lds_provision(
            instance=_FakeInstance(),
            progress=progress,
            context=context,
        )

        assert result.status == "completed"
        assert result.result_data["device_count"] == 3  # All devices included

    async def test_fallback_no_visible_devices_all_included(self):
        """Fallback path with no user_visible_devices includes all tagged nodes."""
        from application.services.step_handlers.lds_provision_step import step_lds_provision

        @dataclass
        class FakeNode:
            label: str
            tags: list[str]

        definition = _FakeDefinition(user_visible_devices=None)
        context = _make_context(definition=definition)
        context.cml.get_lab_nodes = AsyncMock(
            return_value=[
                FakeNode(label="Router1", tags=["serial:5041"]),
                FakeNode(label="Switch1", tags=["ssh:22"]),
            ]
        )
        progress = _make_progress(allocated_ports=None)

        result = await step_lds_provision(
            instance=_FakeInstance(),
            progress=progress,
            context=context,
        )

        assert result.status == "completed"
        assert result.result_data["device_count"] == 2  # Both included (no filter)

    async def test_skipped_when_no_form_qualified_name(self):
        """Step is skipped when definition has no form_qualified_name."""
        from application.services.step_handlers.lds_provision_step import step_lds_provision

        definition = _FakeDefinition(form_qualified_name=None)
        context = _make_context(definition=definition)
        progress = _make_progress()

        result = await step_lds_provision(
            instance=_FakeInstance(),
            progress=progress,
            context=context,
        )

        assert result.status == "skipped"

    async def test_skipped_when_no_lds_client(self):
        """Step is skipped when LDS client is not configured."""
        from application.services.step_handlers.lds_provision_step import step_lds_provision

        context = _make_context()
        context.lds = None
        progress = _make_progress()

        result = await step_lds_provision(
            instance=_FakeInstance(),
            progress=progress,
            context=context,
        )

        assert result.status == "skipped"


# =============================================================================
# Tests for build_device_access_list with user_visible_labels filter (Step 6)
# =============================================================================


class TestBuildDeviceAccessListFiltered:
    """Tests for build_device_access_list() visibility filter — AD-LDS-001 Step 6."""

    def test_filter_excludes_hidden_nodes(self):
        """Nodes not in user_visible_labels are excluded."""
        from application.services.reconciler_helpers.lds_helpers import build_device_access_list
        from integration.services.cml_labs_spi import NodeInfo

        nodes = [
            NodeInfo(id="n0", label="Router1", node_definition="iosv", state="BOOTED", tags=["serial:5041"]),
            NodeInfo(id="n1", label="backbone-sw", node_definition="iosvl2", state="BOOTED", tags=["ssh:22"]),
            NodeInfo(id="n2", label="Desktop1", node_definition="ubuntu", state="BOOTED", tags=["vnc:5043"]),
        ]

        devices = build_device_access_list(nodes, "10.0.0.1", user_visible_labels={"Router1", "Desktop1"})

        labels = {d.device_label for d in devices}
        assert "Router1" in labels
        assert "Desktop1" in labels
        assert "backbone-sw" not in labels
        assert len(devices) == 2

    def test_none_filter_includes_all(self):
        """When user_visible_labels is None, all tagged nodes are included."""
        from application.services.reconciler_helpers.lds_helpers import build_device_access_list
        from integration.services.cml_labs_spi import NodeInfo

        nodes = [
            NodeInfo(id="n0", label="Router1", node_definition="iosv", state="BOOTED", tags=["serial:5041"]),
            NodeInfo(id="n1", label="backbone-sw", node_definition="iosvl2", state="BOOTED", tags=["ssh:22"]),
        ]

        devices = build_device_access_list(nodes, "10.0.0.1", user_visible_labels=None)

        assert len(devices) == 2

    def test_multi_tag_node_filtered(self):
        """Multi-tag node excluded when its label isn't in visible set."""
        from application.services.reconciler_helpers.lds_helpers import build_device_access_list
        from integration.services.cml_labs_spi import NodeInfo

        nodes = [
            NodeInfo(id="n0", label="hidden-router", node_definition="iosv", state="BOOTED", tags=["serial:5041", "ssh:22"]),
            NodeInfo(id="n1", label="Desktop1", node_definition="ubuntu", state="BOOTED", tags=["vnc:5043"]),
        ]

        devices = build_device_access_list(nodes, "10.0.0.1", user_visible_labels={"Desktop1"})

        assert len(devices) == 1
        assert devices[0].device_label == "Desktop1"


# =============================================================================
# Integration-style test: full pipeline scenario
# =============================================================================


@pytest.mark.asyncio
class TestLdsProvisionIntegration:
    """Integration-style test simulating realistic pipeline data flow."""

    async def test_full_pipeline_visible_and_hidden_devices(self):
        """Simulate a realistic pipeline where content.xml defines 2 visible
        devices out of 4 total CML nodes, with allocated ports for all 4.

        Expected: Only the 2 visible devices are provisioned to LDS.
        When a visible device has multiple ports (ubuntu-desktop-1: vnc + web),
        only the highest-priority protocol is sent (AD-LDS-002).
        """
        from application.services.step_handlers.lds_provision_step import step_lds_provision

        # Realistic content.xml extraction (what Phase 1 produces)
        user_visible_devices = [
            {"device_label": "ubuntu-desktop-1", "user_access_mode": "web", "category": "NA"},
            {"device_label": "csr1000v-1", "user_access_mode": "ssh", "category": "router"},
        ]

        # Realistic allocated_ports (from ports_alloc step — all nodes get ports)
        allocated_ports = {
            "ubuntu-desktop-1_vnc": 30001,
            "ubuntu-desktop-1_web": 30002,
            "csr1000v-1_serial": 30003,
            "backbone-rtr_serial": 30004,  # Hidden infra
            "ext-connector_serial": 30005,  # Hidden infra
        }

        definition = _FakeDefinition(user_visible_devices=user_visible_devices)
        context = _make_context(definition=definition)
        progress = _make_progress(allocated_ports=allocated_ports)

        result = await step_lds_provision(
            instance=_FakeInstance(),
            progress=progress,
            context=context,
        )

        # Verify outcome — only 2 devices (one per visible device_label)
        assert result.status == "completed"
        assert result.result_data["device_count"] == 2
        assert result.result_data["lds_session_id"] == "lds-session-123"

        # Verify set_devices call
        call_args = context.lds.set_devices.call_args
        devices = call_args.kwargs.get("devices") or call_args[1].get("devices")
        labels = {d.device_label for d in devices}
        assert labels == {"ubuntu-desktop-1", "csr1000v-1"}
        assert "backbone-rtr" not in labels
        assert "ext-connector" not in labels

        # Verify multi-port resolution: vnc wins over web (higher in default priority)
        ubuntu_device = next(d for d in devices if d.device_label == "ubuntu-desktop-1")
        assert ubuntu_device.protocol == "vnc"
        assert ubuntu_device.port == 30001

    async def test_full_pipeline_empty_content_xml(self):
        """When content.xml has no devices (empty list), no devices provisioned.

        This is distinct from None (backward compat) — empty means
        the content.xml was parsed but had no <device> elements.
        """
        from application.services.step_handlers.lds_provision_step import step_lds_provision

        definition = _FakeDefinition(user_visible_devices=[])  # Empty, not None
        context = _make_context(definition=definition)
        progress = _make_progress(
            allocated_ports={
                "Router1_serial": 5041,
                "Desktop1_vnc": 5043,
            }
        )

        result = await step_lds_provision(
            instance=_FakeInstance(),
            progress=progress,
            context=context,
        )

        assert result.status == "completed"
        assert result.result_data["device_count"] == 0
        # set_devices should NOT be called when device list is empty
        context.lds.set_devices.assert_not_called()
