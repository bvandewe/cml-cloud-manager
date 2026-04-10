"""Tests for ContentSyncService static extraction methods.

Unit tests for:
- _extract_port_template(): CML node tag → PortTemplate parsing
- _extract_topology_metadata(): CML nodes → node_count + node_definitions
"""

import pytest  # noqa: F401

from application.hosted_services.content_sync_service import ContentSyncService


class TestExtractTopologyMetadata:
    """Tests for ContentSyncService._extract_topology_metadata()."""

    def test_standard_cml_yaml(self):
        """Extract node_count and node_definitions from a standard 2-node topology."""
        cml_yaml = """
lab:
  title: Test Lab
nodes:
  - id: n0
    label: vmanage-mock
    node_definition: mock-server
    tags: [serial:5041]
  - id: n1
    label: ubuntu-desktop
    node_definition: ubuntu-desktop-24-04-v2
    tags: [serial:5042, vnc:5044]
links:
  - id: l0
    n1: n0
    n2: n1
"""
        node_count, node_defs = ContentSyncService._extract_topology_metadata(cml_yaml)

        assert node_count == 2
        assert node_defs == ["mock-server", "ubuntu-desktop-24-04-v2"]

    def test_duplicate_node_definitions(self):
        """Duplicate node_definition values are deduplicated."""
        cml_yaml = """
nodes:
  - id: n0
    label: Router1
    node_definition: iosv
    tags: []
  - id: n1
    label: Router2
    node_definition: iosv
    tags: []
"""
        node_count, node_defs = ContentSyncService._extract_topology_metadata(cml_yaml)

        assert node_count == 2
        assert node_defs == ["iosv"]  # Deduplicated

    def test_many_nodes(self):
        """Extract from a multi-node topology with varied definitions."""
        cml_yaml = """
nodes:
  - id: n0
    label: R1
    node_definition: csr1000v
  - id: n1
    label: R2
    node_definition: csr1000v
  - id: n2
    label: SW1
    node_definition: iosvl2
  - id: n3
    label: SW2
    node_definition: iosvl2
  - id: n4
    label: PC
    node_definition: ubuntu-desktop-24-04-v2
"""
        node_count, node_defs = ContentSyncService._extract_topology_metadata(cml_yaml)

        assert node_count == 5
        assert node_defs == ["csr1000v", "iosvl2", "ubuntu-desktop-24-04-v2"]  # Sorted

    def test_no_nodes(self):
        """Empty nodes list returns zero count and None definitions."""
        cml_yaml = """
lab:
  title: Empty Lab
nodes: []
"""
        node_count, node_defs = ContentSyncService._extract_topology_metadata(cml_yaml)

        assert node_count == 0
        assert node_defs is None

    def test_missing_nodes_key(self):
        """Missing 'nodes' key returns 0 count and None definitions (valid YAML, no topology)."""
        cml_yaml = """
lab:
  title: No Nodes Key
"""
        node_count, node_defs = ContentSyncService._extract_topology_metadata(cml_yaml)

        assert node_count == 0
        assert node_defs is None

    def test_invalid_yaml(self):
        """Invalid YAML returns None, None."""
        node_count, node_defs = ContentSyncService._extract_topology_metadata("key: [unmatched")

        assert node_count is None
        assert node_defs is None

    def test_node_without_definition(self):
        """Nodes missing node_definition are counted but not in definitions list."""
        cml_yaml = """
nodes:
  - id: n0
    label: ExternalConnector
  - id: n1
    label: Router1
    node_definition: iosv
"""
        node_count, node_defs = ContentSyncService._extract_topology_metadata(cml_yaml)

        assert node_count == 2  # Both counted
        assert node_defs == ["iosv"]  # Only the one with definition

    def test_nodes_not_a_list(self):
        """'nodes' key that isn't a list returns None, None."""
        cml_yaml = """
nodes: "not a list"
"""
        node_count, node_defs = ContentSyncService._extract_topology_metadata(cml_yaml)

        assert node_count is None
        assert node_defs is None

    def test_non_dict_yaml(self):
        """YAML that parses to a non-dict returns None, None."""
        node_count, node_defs = ContentSyncService._extract_topology_metadata("just a string")

        assert node_count is None
        assert node_defs is None


class TestExtractPortTemplate:
    """Tests for ContentSyncService._extract_port_template()."""

    def test_standard_cml_tags(self):
        """Parse serial:port_number tags from CML nodes."""
        cml_yaml = """
nodes:
  - id: n0
    label: vmanage-mock
    node_definition: mock-server
    tags:
      - serial:5041
  - id: n1
    label: ubuntu-desktop
    node_definition: ubuntu-desktop-24-04-v2
    tags:
      - serial:5042
      - vnc:5044
"""
        result = ContentSyncService._extract_port_template(cml_yaml)

        assert result is not None
        assert "ports" in result
        port_names = [p["name"] for p in result["ports"]]
        assert "vmanage-mock_serial" in port_names
        assert "ubuntu-desktop_serial" in port_names
        assert "ubuntu-desktop_vnc" in port_names
        assert len(result["ports"]) == 3

    def test_no_tags(self):
        """Nodes with empty tags return None."""
        cml_yaml = """
nodes:
  - id: n0
    label: Router1
    node_definition: iosv
    tags: []
  - id: n1
    label: Router2
    node_definition: iosv
    tags: []
"""
        result = ContentSyncService._extract_port_template(cml_yaml)
        assert result is None

    def test_preserves_hyphens_in_labels(self):
        """Hyphens in node labels are preserved (from_cml_nodes convention)."""
        cml_yaml = """
nodes:
  - id: n0
    label: my-fancy-router
    node_definition: iosv
    tags:
      - serial:5000
"""
        result = ContentSyncService._extract_port_template(cml_yaml)
        assert result is not None
        assert result["ports"][0]["name"] == "my-fancy-router_serial"

    def test_deduplicates_ports(self):
        """Duplicate (label, protocol) pairs are silently deduplicated."""
        cml_yaml = """
nodes:
  - id: n0
    label: R1
    node_definition: iosv
    tags:
      - serial:5000
      - serial:5001
"""
        result = ContentSyncService._extract_port_template(cml_yaml)
        assert result is not None
        assert len(result["ports"]) == 1  # Deduplicated
