"""Unit tests for PortMappingResolutionService (Phase 11).

Tests cover:
- Resolution from ExternalInterface definitions only
- Resolution with worker IP fallback
- Overlay of LabletSession allocated ports (dict + int forms)
- New nodes from allocated ports not in ExternalInterface
- Empty inputs / edge cases
- Host fallback logic
"""

import pytest
from application.services.port_mapping_resolution_service import PortMappingResolutionService


@pytest.fixture
def service() -> PortMappingResolutionService:
    """Create a PortMappingResolutionService instance."""
    return PortMappingResolutionService()


# =============================================================================
# Basic Resolution Tests
# =============================================================================


class TestBasicResolution:
    """Test resolution from ExternalInterface definitions."""

    def test_resolve_single_interface(self, service: PortMappingResolutionService):
        external_interfaces = [{"node_label": "router1", "protocol": "ssh", "port": 22, "host": "10.0.0.5"}]
        result = service.resolve(external_interfaces, worker_ip="54.81.105.239")

        assert "router1" in result
        assert result["router1"]["protocol"] == "ssh"
        assert result["router1"]["external_port"] == 22
        assert result["router1"]["internal_port"] == 22
        assert result["router1"]["host"] == "10.0.0.5"

    def test_resolve_multiple_interfaces(self, service: PortMappingResolutionService):
        external_interfaces = [
            {"node_label": "router1", "protocol": "ssh", "port": 22},
            {"node_label": "switch1", "protocol": "telnet", "port": 23},
        ]
        result = service.resolve(external_interfaces, worker_ip="54.81.105.239")

        assert len(result) == 2
        assert "router1" in result
        assert "switch1" in result
        assert result["router1"]["protocol"] == "ssh"
        assert result["switch1"]["protocol"] == "telnet"

    def test_resolve_empty_interfaces(self, service: PortMappingResolutionService):
        result = service.resolve([], worker_ip="54.81.105.239")
        assert result == {}

    def test_skip_interface_without_node_label(self, service: PortMappingResolutionService):
        external_interfaces = [
            {"node_label": "", "protocol": "ssh", "port": 22},
            {"node_label": "router1", "protocol": "ssh", "port": 22},
        ]
        result = service.resolve(external_interfaces, worker_ip="54.81.105.239")

        assert len(result) == 1
        assert "router1" in result


# =============================================================================
# Worker IP Fallback Tests
# =============================================================================


class TestWorkerIpFallback:
    """Test host fallback to worker IP."""

    def test_uses_worker_ip_when_no_host(self, service: PortMappingResolutionService):
        external_interfaces = [{"node_label": "router1", "protocol": "ssh", "port": 22}]
        result = service.resolve(external_interfaces, worker_ip="54.81.105.239")

        assert result["router1"]["host"] == "54.81.105.239"

    def test_keeps_interface_host_when_present(self, service: PortMappingResolutionService):
        external_interfaces = [{"node_label": "router1", "protocol": "ssh", "port": 22, "host": "10.0.0.5"}]
        result = service.resolve(external_interfaces, worker_ip="54.81.105.239")

        assert result["router1"]["host"] == "10.0.0.5"

    def test_none_worker_ip_and_no_host(self, service: PortMappingResolutionService):
        external_interfaces = [{"node_label": "router1", "protocol": "ssh", "port": 22}]
        result = service.resolve(external_interfaces, worker_ip=None)

        assert result["router1"]["host"] is None

    def test_step3_fallback_fills_missing_host(self, service: PortMappingResolutionService):
        """Step 3 in resolve() fills None hosts from worker_ip."""
        external_interfaces = [{"node_label": "router1", "protocol": "ssh", "port": 22, "host": None}]
        result = service.resolve(external_interfaces, worker_ip="54.81.105.239")

        assert result["router1"]["host"] == "54.81.105.239"


# =============================================================================
# Lablet Allocated Ports Overlay Tests
# =============================================================================


class TestAllocatedPortsOverlay:
    """Test overlay of LabletSession allocated ports."""

    def test_override_external_port_with_dict(self, service: PortMappingResolutionService):
        external_interfaces = [{"node_label": "router1", "protocol": "ssh", "port": 22}]
        lablet_ports = {"router1": {"external_port": 5041}}
        result = service.resolve(external_interfaces, worker_ip="54.81.105.239", lablet_allocated_ports=lablet_ports)

        assert result["router1"]["external_port"] == 5041
        assert result["router1"]["internal_port"] == 22  # unchanged
        assert result["router1"]["protocol"] == "ssh"  # unchanged

    def test_override_host_with_dict(self, service: PortMappingResolutionService):
        external_interfaces = [{"node_label": "router1", "protocol": "ssh", "port": 22}]
        lablet_ports = {"router1": {"external_port": 5041, "host": "192.168.1.100"}}
        result = service.resolve(external_interfaces, worker_ip="54.81.105.239", lablet_allocated_ports=lablet_ports)

        assert result["router1"]["host"] == "192.168.1.100"

    def test_override_external_port_with_int(self, service: PortMappingResolutionService):
        external_interfaces = [{"node_label": "router1", "protocol": "ssh", "port": 22}]
        lablet_ports = {"router1": 5041}
        result = service.resolve(external_interfaces, worker_ip="54.81.105.239", lablet_allocated_ports=lablet_ports)

        assert result["router1"]["external_port"] == 5041

    def test_new_node_from_allocated_ports_dict(self, service: PortMappingResolutionService):
        external_interfaces = [{"node_label": "router1", "protocol": "ssh", "port": 22}]
        lablet_ports = {"server1": {"protocol": "http", "external_port": 8080, "internal_port": 80, "host": "10.0.0.10"}}
        result = service.resolve(external_interfaces, worker_ip="54.81.105.239", lablet_allocated_ports=lablet_ports)

        assert len(result) == 2
        assert "server1" in result
        assert result["server1"]["protocol"] == "http"
        assert result["server1"]["external_port"] == 8080
        assert result["server1"]["internal_port"] == 80
        assert result["server1"]["host"] == "10.0.0.10"

    def test_new_node_from_allocated_ports_int(self, service: PortMappingResolutionService):
        external_interfaces = []
        lablet_ports = {"server1": 8080}
        result = service.resolve(external_interfaces, worker_ip="54.81.105.239", lablet_allocated_ports=lablet_ports)

        assert len(result) == 1
        assert result["server1"]["protocol"] == "unknown"
        assert result["server1"]["external_port"] == 8080
        assert result["server1"]["internal_port"] == 8080
        assert result["server1"]["host"] == "54.81.105.239"

    def test_none_allocated_ports(self, service: PortMappingResolutionService):
        external_interfaces = [{"node_label": "router1", "protocol": "ssh", "port": 22}]
        result = service.resolve(external_interfaces, worker_ip="54.81.105.239", lablet_allocated_ports=None)

        assert len(result) == 1


# =============================================================================
# Defaults and Edge Cases
# =============================================================================


class TestDefaults:
    """Test default values and edge cases."""

    def test_missing_protocol_defaults_unknown(self, service: PortMappingResolutionService):
        external_interfaces = [{"node_label": "router1", "port": 22}]
        result = service.resolve(external_interfaces, worker_ip="54.81.105.239")

        assert result["router1"]["protocol"] == "unknown"

    def test_missing_port_defaults_zero(self, service: PortMappingResolutionService):
        external_interfaces = [{"node_label": "router1", "protocol": "ssh"}]
        result = service.resolve(external_interfaces, worker_ip="54.81.105.239")

        assert result["router1"]["external_port"] == 0
        assert result["router1"]["internal_port"] == 0

    def test_new_node_dict_missing_fields_use_defaults(self, service: PortMappingResolutionService):
        lablet_ports = {
            "server1": {"external_port": 8080}  # missing protocol, internal_port, host
        }
        result = service.resolve([], worker_ip="54.81.105.239", lablet_allocated_ports=lablet_ports)

        assert result["server1"]["protocol"] == "unknown"
        assert result["server1"]["external_port"] == 8080
        assert result["server1"]["internal_port"] == 0
        assert result["server1"]["host"] == "54.81.105.239"

    def test_completely_empty_inputs(self, service: PortMappingResolutionService):
        result = service.resolve([], worker_ip=None, lablet_allocated_ports=None)
        assert result == {}
