"""Tests for multi-port device conflict detection at content sync time — AD-LDS-002 Phase 2.

Unit tests for:
- _detect_port_conflicts(): cross-referencing port_template with user_visible_devices
- _resolve_port_by_priority(): selecting highest-priority port from a set of candidates
"""

from __future__ import annotations

from application.hosted_services.content_sync_service import (
    ContentSyncService,
    _resolve_port_by_priority,
)

DEFAULT_PRIORITY = ["vnc", "http", "https", "rdp", "ssh", "serial", "telnet"]


# =============================================================================
# Tests for _resolve_port_by_priority (module-level helper)
# =============================================================================


class TestResolvePortByPriority:
    """Tests for the port priority resolution helper."""

    def test_vnc_wins_over_serial(self):
        """VNC has higher priority than serial in default order."""
        ports = ["ubuntu-desktop_serial", "ubuntu-desktop_vnc"]
        result = _resolve_port_by_priority(ports, "ubuntu-desktop_", DEFAULT_PRIORITY)
        assert result == "ubuntu-desktop_vnc"

    def test_http_wins_over_ssh(self):
        """HTTP has higher priority than SSH."""
        ports = ["server_ssh", "server_http"]
        result = _resolve_port_by_priority(ports, "server_", DEFAULT_PRIORITY)
        assert result == "server_http"

    def test_single_port_returns_itself(self):
        """A single port is returned directly."""
        ports = ["router_serial"]
        result = _resolve_port_by_priority(ports, "router_", DEFAULT_PRIORITY)
        assert result == "router_serial"

    def test_custom_priority_order(self):
        """Custom priority list changes the winner."""
        custom_priority = ["ssh", "serial", "vnc"]
        ports = ["ws_vnc", "ws_ssh", "ws_serial"]
        result = _resolve_port_by_priority(ports, "ws_", custom_priority)
        assert result == "ws_ssh"

    def test_unknown_protocol_lowest_priority(self):
        """Protocols not in the priority list get lowest priority."""
        ports = ["device_unknown_proto", "device_telnet"]
        result = _resolve_port_by_priority(ports, "device_", DEFAULT_PRIORITY)
        assert result == "device_telnet"

    def test_all_unknown_returns_first(self):
        """When all protocols are unknown, returns the first port."""
        ports = ["device_foo", "device_bar"]
        result = _resolve_port_by_priority(ports, "device_", DEFAULT_PRIORITY)
        assert result == "device_foo"


# =============================================================================
# Tests for ContentSyncService._detect_port_conflicts (static method)
# =============================================================================


class TestDetectPortConflicts:
    """Tests for multi-port device conflict detection — AD-LDS-002 Phase 2."""

    def test_no_conflicts_single_port_per_device(self):
        """Devices with a single port produce no conflicts."""
        port_template = {
            "ports": [
                {"name": "router_serial", "protocol": "tcp", "description": "serial on router"},
                {"name": "switch_ssh", "protocol": "tcp", "description": "ssh on switch"},
            ]
        }
        devices = [
            {"device_label": "router", "user_access_mode": "web", "category": "networking"},
            {"device_label": "switch", "user_access_mode": "web", "category": "networking"},
        ]
        result = ContentSyncService._detect_port_conflicts(port_template, devices, DEFAULT_PRIORITY)
        assert result == []

    def test_conflict_detected_for_multi_port_device(self):
        """A device with multiple ports is flagged as a conflict."""
        port_template = {
            "ports": [
                {"name": "ubuntu-desktop_serial", "protocol": "tcp", "description": "serial on ubuntu-desktop"},
                {"name": "ubuntu-desktop_vnc", "protocol": "tcp", "description": "vnc on ubuntu-desktop"},
                {"name": "router_serial", "protocol": "tcp", "description": "serial on router"},
            ]
        }
        devices = [
            {"device_label": "ubuntu-desktop", "user_access_mode": "web", "category": "server"},
            {"device_label": "router", "user_access_mode": "web", "category": "networking"},
        ]
        result = ContentSyncService._detect_port_conflicts(port_template, devices, DEFAULT_PRIORITY)
        assert len(result) == 1
        conflict = result[0]
        assert conflict["device_label"] == "ubuntu-desktop"
        assert sorted(conflict["available_ports"]) == ["ubuntu-desktop_serial", "ubuntu-desktop_vnc"]
        assert conflict["resolved_port"] == "ubuntu-desktop_vnc"  # vnc > serial

    def test_multiple_devices_with_conflicts(self):
        """Multiple devices can have conflicts simultaneously."""
        port_template = {
            "ports": [
                {"name": "ws1_serial", "protocol": "tcp", "description": "serial on ws1"},
                {"name": "ws1_vnc", "protocol": "tcp", "description": "vnc on ws1"},
                {"name": "ws2_ssh", "protocol": "tcp", "description": "ssh on ws2"},
                {"name": "ws2_http", "protocol": "tcp", "description": "http on ws2"},
                {"name": "router_serial", "protocol": "tcp", "description": "serial on router"},
            ]
        }
        devices = [
            {"device_label": "ws1", "user_access_mode": "web", "category": "server"},
            {"device_label": "ws2", "user_access_mode": "web", "category": "server"},
            {"device_label": "router", "user_access_mode": "web", "category": "networking"},
        ]
        result = ContentSyncService._detect_port_conflicts(port_template, devices, DEFAULT_PRIORITY)
        assert len(result) == 2
        labels = {c["device_label"] for c in result}
        assert labels == {"ws1", "ws2"}

    def test_empty_port_template(self):
        """Empty port template produces no conflicts."""
        result = ContentSyncService._detect_port_conflicts({"ports": []}, [{"device_label": "x"}], DEFAULT_PRIORITY)
        assert result == []

    def test_empty_devices(self):
        """Empty device list produces no conflicts."""
        port_template = {"ports": [{"name": "x_serial", "protocol": "tcp", "description": ""}]}
        result = ContentSyncService._detect_port_conflicts(port_template, [], DEFAULT_PRIORITY)
        assert result == []

    def test_device_not_in_port_template(self):
        """Device with no matching ports in port_template is not a conflict."""
        port_template = {
            "ports": [
                {"name": "other_serial", "protocol": "tcp", "description": "serial on other"},
            ]
        }
        devices = [{"device_label": "unmatched", "user_access_mode": "web", "category": ""}]
        result = ContentSyncService._detect_port_conflicts(port_template, devices, DEFAULT_PRIORITY)
        assert result == []

    def test_special_chars_in_device_label(self):
        """Device labels with special characters are sanitised to match port names."""
        port_template = {
            "ports": [
                {"name": "my_server_serial", "protocol": "tcp", "description": "serial on my server"},
                {"name": "my_server_vnc", "protocol": "tcp", "description": "vnc on my server"},
            ]
        }
        # The device label has a space which is sanitised to underscore
        devices = [{"device_label": "my server", "user_access_mode": "web", "category": ""}]
        result = ContentSyncService._detect_port_conflicts(port_template, devices, DEFAULT_PRIORITY)
        assert len(result) == 1
        assert result[0]["device_label"] == "my server"
        assert result[0]["resolved_port"] == "my_server_vnc"

    def test_three_ports_on_one_device(self):
        """A device with three port annotations picks highest priority."""
        port_template = {
            "ports": [
                {"name": "workstation_serial", "protocol": "tcp", "description": "serial on workstation"},
                {"name": "workstation_vnc", "protocol": "tcp", "description": "vnc on workstation"},
                {"name": "workstation_ssh", "protocol": "tcp", "description": "ssh on workstation"},
            ]
        }
        devices = [{"device_label": "workstation", "user_access_mode": "web", "category": ""}]
        result = ContentSyncService._detect_port_conflicts(port_template, devices, DEFAULT_PRIORITY)
        assert len(result) == 1
        assert len(result[0]["available_ports"]) == 3
        assert result[0]["resolved_port"] == "workstation_vnc"  # vnc > ssh > serial

    def test_available_ports_are_sorted(self):
        """Conflict available_ports list is sorted alphabetically."""
        port_template = {
            "ports": [
                {"name": "dev_vnc", "protocol": "tcp", "description": ""},
                {"name": "dev_serial", "protocol": "tcp", "description": ""},
                {"name": "dev_http", "protocol": "tcp", "description": ""},
            ]
        }
        devices = [{"device_label": "dev", "user_access_mode": "web", "category": ""}]
        result = ContentSyncService._detect_port_conflicts(port_template, devices, DEFAULT_PRIORITY)
        assert result[0]["available_ports"] == ["dev_http", "dev_serial", "dev_vnc"]
