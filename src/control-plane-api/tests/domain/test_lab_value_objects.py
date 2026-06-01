"""Unit tests for Phase 7 value objects.

Tests cover:
- RuntimeBinding: construction, for_cml factory, serialization
- ExternalInterface: construction, serialization
- LabTopologySpec: nodes, links, checksum, computed properties
- LabRevision: construction, initial factory, serialization
- LabRunRecord: construction, is_running, calculated_duration_seconds
"""

from datetime import datetime, timedelta, timezone

import pytest

from domain.value_objects.external_interface import ExternalInterface
from domain.value_objects.lab_revision import LabRevision
from domain.value_objects.lab_run_record import LabRunRecord
from domain.value_objects.lab_topology_spec import (
    LabTopologySpec,
    TopologyAnnotation,
    TopologyLink,
    TopologyNode,
)
from domain.value_objects.runtime_binding import RuntimeBinding

# =============================================================================
# RuntimeBinding
# =============================================================================


class TestRuntimeBinding:
    """Test RuntimeBinding frozen value object."""

    def test_construction(self):
        rb = RuntimeBinding(
            runtime_type="cml",
            worker_id="w-001",
            runtime_lab_id="lab-001",
        )
        assert rb.runtime_type == "cml"
        assert rb.worker_id == "w-001"
        assert rb.runtime_lab_id == "lab-001"

    def test_for_cml_factory(self):
        rb = RuntimeBinding.for_cml(worker_id="w-002", lab_id="lab-002")
        assert rb.runtime_type == "cml"
        assert rb.worker_id == "w-002"
        assert rb.runtime_lab_id == "lab-002"

    def test_to_dict(self):
        rb = RuntimeBinding.for_cml(worker_id="w-003", lab_id="lab-003")
        d = rb.to_dict()
        assert d["runtime_type"] == "cml"
        assert d["worker_id"] == "w-003"

    def test_from_dict_round_trip(self):
        rb = RuntimeBinding.for_cml(worker_id="w-004", lab_id="lab-004")
        d = rb.to_dict()
        restored = RuntimeBinding.from_dict(d)
        assert restored == rb

    def test_immutability(self):
        rb = RuntimeBinding.for_cml(worker_id="w-005", lab_id="lab-005")
        with pytest.raises(AttributeError):
            rb.worker_id = "changed"


# =============================================================================
# ExternalInterface
# =============================================================================


class TestExternalInterface:
    """Test ExternalInterface frozen value object."""

    def test_construction(self):
        ei = ExternalInterface(
            node_label="router-1",
            protocol="ssh",
            port=22,
            host="10.0.0.1",
        )
        assert ei.node_label == "router-1"
        assert ei.protocol == "ssh"
        assert ei.port == 22
        assert ei.host == "10.0.0.1"

    def test_to_dict(self):
        ei = ExternalInterface(node_label="sw-1", protocol="vnc", port=5900, host="10.0.0.2")
        d = ei.to_dict()
        assert d["node_label"] == "sw-1"
        assert d["protocol"] == "vnc"
        assert d["port"] == 5900

    def test_from_dict_round_trip(self):
        ei = ExternalInterface(node_label="r-1", protocol="telnet", port=23, host="10.0.0.3")
        d = ei.to_dict()
        restored = ExternalInterface.from_dict(d)
        assert restored == ei

    def test_immutability(self):
        ei = ExternalInterface(node_label="x", protocol="ssh", port=22, host="h")
        with pytest.raises(AttributeError):
            ei.port = 9999


# =============================================================================
# LabTopologySpec
# =============================================================================


class TestLabTopologySpec:
    """Test LabTopologySpec frozen value object."""

    @pytest.fixture
    def sample_spec(self) -> LabTopologySpec:
        return LabTopologySpec(
            nodes=[
                TopologyNode(label="r1", node_definition="iosv", x=0, y=0),
                TopologyNode(label="r2", node_definition="iosv", x=100, y=0),
                TopologyNode(label="sw1", node_definition="iosvl2", x=50, y=100),
            ],
            links=[
                TopologyLink(source_node="r1", source_interface="Gi0/0", target_node="sw1", target_interface="Gi0/0"),
                TopologyLink(source_node="r2", source_interface="Gi0/0", target_node="sw1", target_interface="Gi0/1"),
            ],
            annotations=[
                TopologyAnnotation(text="Core Switch", x=50, y=120),
            ],
        )

    def test_node_count(self, sample_spec: LabTopologySpec):
        assert sample_spec.node_count == 3

    def test_link_count(self, sample_spec: LabTopologySpec):
        assert sample_spec.link_count == 2

    def test_checksum_deterministic(self, sample_spec: LabTopologySpec):
        cs1 = sample_spec.checksum()
        cs2 = sample_spec.checksum()
        assert cs1 == cs2

    def test_checksum_changes_with_different_topology(self, sample_spec: LabTopologySpec):
        different = LabTopologySpec(
            nodes=[TopologyNode(label="only-one", node_definition="csr1000v", x=0, y=0)],
            links=[],
        )
        assert sample_spec.checksum() != different.checksum()

    def test_to_dict_round_trip(self, sample_spec: LabTopologySpec):
        d = sample_spec.to_dict()
        restored = LabTopologySpec.from_dict(d)
        assert restored.node_count == sample_spec.node_count
        assert restored.link_count == sample_spec.link_count
        assert restored.checksum() == sample_spec.checksum()

    def test_empty_topology(self):
        empty = LabTopologySpec(nodes=[], links=[])
        assert empty.node_count == 0
        assert empty.link_count == 0


# =============================================================================
# LabRevision
# =============================================================================


class TestLabRevision:
    """Test LabRevision frozen value object."""

    def test_construction(self):
        lr = LabRevision(
            revision=1,
            created_at=datetime.now(timezone.utc),
            topology_checksum="abc123",
            change_summary="Initial",
        )
        assert lr.revision == 1
        assert lr.topology_checksum == "abc123"

    def test_validation_revision_must_be_positive(self):
        with pytest.raises(ValueError, match="revision must be >= 1"):
            LabRevision(
                revision=0,
                topology_checksum="abc",
                created_at=datetime.now(timezone.utc),
            )

    def test_validation_checksum_required(self):
        with pytest.raises(ValueError, match="topology_checksum cannot be empty"):
            LabRevision(
                revision=1,
                topology_checksum="",
                created_at=datetime.now(timezone.utc),
            )

    def test_to_dict(self):
        lr = LabRevision(
            revision=1,
            topology_checksum="abc123",
            created_at=datetime.now(timezone.utc),
        )
        d = lr.to_dict()
        assert d["revision"] == 1
        assert "created_at" in d
        assert d["topology_checksum"] == "abc123"

    def test_from_dict_round_trip(self):
        lr = LabRevision(
            revision=5,
            created_at=datetime.now(timezone.utc),
            topology_checksum="def456",
            change_summary="Updated links",
            created_by="admin",
        )
        d = lr.to_dict()
        restored = LabRevision.from_dict(d)
        assert restored.revision == lr.revision
        assert restored.topology_checksum == lr.topology_checksum
        assert restored.created_by == lr.created_by


# =============================================================================
# LabRunRecord
# =============================================================================


class TestLabRunRecord:
    """Test LabRunRecord frozen value object."""

    def test_construction(self):
        now = datetime.now(timezone.utc)
        lrr = LabRunRecord(
            run_id="run-001",
            started_at=now,
            stopped_at=now + timedelta(hours=1),
            duration_seconds=3600,
            started_by="admin",
            stop_reason="Timeslot ended",
        )
        assert lrr.run_id == "run-001"
        assert lrr.duration_seconds == 3600
        assert lrr.stop_reason == "Timeslot ended"

    def test_is_running_with_no_stopped_at(self):
        lrr = LabRunRecord(
            run_id="run-002",
            started_at=datetime.now(timezone.utc),
            duration_seconds=0,
        )
        assert lrr.is_running is True

    def test_is_running_false_when_stopped(self):
        lrr = LabRunRecord(
            run_id="run-003",
            started_at=datetime.now(timezone.utc),
            stopped_at=datetime.now(timezone.utc),
            duration_seconds=60,
        )
        assert lrr.is_running is False

    def test_calculated_duration_when_running(self):
        started = datetime.now(timezone.utc) - timedelta(minutes=30)
        lrr = LabRunRecord(
            run_id="run-004",
            started_at=started,
            duration_seconds=0,
        )
        calc = lrr.calculated_duration_seconds
        assert calc >= 1790  # ~30 minutes, allowing for slight time drift

    def test_to_dict(self):
        lrr = LabRunRecord(
            run_id="run-005",
            started_at=datetime.now(timezone.utc),
            duration_seconds=120,
            started_by="student",
        )
        d = lrr.to_dict()
        assert d["run_id"] == "run-005"
        assert d["started_by"] == "student"

    def test_from_dict_round_trip(self):
        lrr = LabRunRecord(
            run_id="run-006",
            started_at=datetime.now(timezone.utc),
            stopped_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            duration_seconds=300,
            started_by="admin",
            stop_reason="Manual stop",
        )
        d = lrr.to_dict()
        restored = LabRunRecord.from_dict(d)
        assert restored.run_id == lrr.run_id
        assert restored.duration_seconds == 300
        assert restored.stop_reason == "Manual stop"
