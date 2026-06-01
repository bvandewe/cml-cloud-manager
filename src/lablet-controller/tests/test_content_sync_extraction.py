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


class TestExtractUserVisibleDevices:
    """Tests for ContentSyncService._extract_user_visible_devices() — AD-LDS-001."""

    def test_multiple_devices(self):
        """Standard content.xml with multiple user-visible devices."""
        content_xml = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<lab_content version="3">
    <title>Lablet</title>
    <device>
        <device category="R2" device_label="R2" coords="128,271,192,307" user_access_mode="web"/>
        <device category="R1" device_label="R1" coords="128,87,192,123" user_access_mode="web"/>
    </device>
</lab_content>
"""
        result = ContentSyncService._extract_user_visible_devices(content_xml)

        assert len(result) == 2
        assert result[0] == {"device_label": "R2", "user_access_mode": "web", "category": "R2"}
        assert result[1] == {"device_label": "R1", "user_access_mode": "web", "category": "R1"}

    def test_single_device(self):
        """Single device as in exam-associate-auto-v1.1-lab-lab-2.9.1/content.xml."""
        content_xml = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<lab_content version="3">
    <title>Lablet</title>
    <timing>
        <min_length_minutes>0</min_length_minutes>
        <max_length_minutes>0</max_length_minutes>
    </timing>
    <device>
        <device category="NA" device_label="ubuntu-desktop-1" coords="31,41,186,147" user_access_mode="web"/>
    </device>
    <feedback enabled="false"/>
</lab_content>
"""
        result = ContentSyncService._extract_user_visible_devices(content_xml)

        assert len(result) == 1
        assert result[0] == {
            "device_label": "ubuntu-desktop-1",
            "user_access_mode": "web",
            "category": "NA",
        }

    def test_malformed_xml_returns_empty_list(self):
        """Malformed XML does not crash — returns empty list."""
        malformed = "<lab_content><device><device device_label='x' unclosed"
        result = ContentSyncService._extract_user_visible_devices(malformed)

        assert result == []

    def test_missing_device_label_skipped(self):
        """Elements without device_label attribute are skipped."""
        content_xml = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<lab_content version="3">
    <device>
        <device category="R1" device_label="R1" user_access_mode="ssh"/>
        <device category="hidden" coords="0,0,10,10"/>
        <device device_label="R2" user_access_mode="telnet"/>
    </device>
</lab_content>
"""
        result = ContentSyncService._extract_user_visible_devices(content_xml)

        assert len(result) == 2
        assert result[0]["device_label"] == "R1"
        assert result[1]["device_label"] == "R2"

    def test_empty_content_xml(self):
        """Empty string returns empty list without crash."""
        result = ContentSyncService._extract_user_visible_devices("")

        assert result == []

    def test_no_device_elements(self):
        """Valid XML with no <device> wrapper returns empty list."""
        content_xml = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<lab_content version="3">
    <title>Lablet</title>
</lab_content>
"""
        result = ContentSyncService._extract_user_visible_devices(content_xml)

        assert result == []

    def test_missing_access_mode_defaults_to_empty(self):
        """Missing user_access_mode attribute defaults to empty string."""
        content_xml = """\
<lab_content>
    <device>
        <device device_label="SW1" category="switch"/>
    </device>
</lab_content>
"""
        result = ContentSyncService._extract_user_visible_devices(content_xml)

        assert len(result) == 1
        assert result[0] == {"device_label": "SW1", "user_access_mode": "", "category": "switch"}
