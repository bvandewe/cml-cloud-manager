"""Tests for LDS device mapping — AD-LDS-001 Phase 2.

Unit tests for:
- build_device_access_from_allocated_ports(): port name parsing + visibility filtering
- step_lds_provision: filtered device mapping with allocated ports and fallback
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from application.services.reconciler_helpers.lds_helpers import build_device_access_from_allocated_ports

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
        from application.services.step_handlers.binding_steps import step_lds_provision

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
        from application.services.step_handlers.binding_steps import step_lds_provision

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
        from application.services.step_handlers.binding_steps import step_lds_provision

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
        from application.services.step_handlers.binding_steps import step_lds_provision

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
        from application.services.step_handlers.binding_steps import step_lds_provision

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
        from application.services.step_handlers.binding_steps import step_lds_provision

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
        """
        from application.services.step_handlers.binding_steps import step_lds_provision

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

        # Verify outcome
        assert result.status == "completed"
        assert result.result_data["device_count"] == 3  # 2 for ubuntu-desktop-1, 1 for csr1000v-1
        assert result.result_data["lds_session_id"] == "lds-session-123"

        # Verify set_devices call
        call_args = context.lds.set_devices.call_args
        devices = call_args.kwargs.get("devices") or call_args[1].get("devices")
        labels = {d.device_label for d in devices}
        assert "ubuntu-desktop-1" in labels
        assert "csr1000v-1" in labels
        assert "backbone-rtr" not in labels
        assert "ext-connector" not in labels

        # Verify protocols are correct
        protocols = {(d.device_label, d.protocol) for d in devices}
        assert ("ubuntu-desktop-1", "vnc") in protocols
        assert ("ubuntu-desktop-1", "web") in protocols
        assert ("csr1000v-1", "serial") in protocols

    async def test_full_pipeline_empty_content_xml(self):
        """When content.xml has no devices (empty list), no devices provisioned.

        This is distinct from None (backward compat) — empty means
        the content.xml was parsed but had no <device> elements.
        """
        from application.services.step_handlers.binding_steps import step_lds_provision

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
