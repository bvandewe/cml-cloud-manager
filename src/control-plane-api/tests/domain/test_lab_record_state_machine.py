"""Unit tests for LabRecord state machine (Phase 7).

Tests cover:
- Aggregate creation (legacy + Phase 7 factory)
- State transitions (valid and invalid per LAB_RECORD_VALID_TRANSITIONS)
- CML state → typed status mapping
- Topology and revision tracking
- Run history
- External interfaces
- Binding events
- Error and orphan states
- Computed properties
- Backward compatibility with legacy sync events
"""

from datetime import datetime, timedelta, timezone

import pytest
from lcm_core.domain.enums import LabRecordStatus

from domain.entities.lab_record import InvalidLabRecordTransitionError, LabRecord
from domain.value_objects.external_interface import ExternalInterface
from domain.value_objects.lab_run_record import LabRunRecord
from domain.value_objects.lab_topology_spec import LabTopologySpec, TopologyLink, TopologyNode

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def legacy_lab_record() -> LabRecord:
    """Create a LabRecord via the create() factory with raw CML data."""
    return LabRecord.create(
        lab_id="lab-001",
        worker_id="worker-001",
        title="Test Lab",
        description="A test lab",
        notes="Some notes",
        state="DEFINED_ON_CORE",
        owner_username="admin",
        owner_fullname="Admin User",
        node_count=3,
        link_count=2,
        groups=["group-a"],
        cml_created_at=datetime.now(timezone.utc),
        cml_modified_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def discovered_lab_record() -> LabRecord:
    """Create a LabRecord via the Phase 7 discover factory."""
    return LabRecord.discover(
        lab_id="lab-002",
        worker_id="worker-002",
        title="Discovered Lab",
        description="Found on worker",
        state="STOPPED",
        owner_username="admin",
        node_count=5,
        link_count=4,
    )


@pytest.fixture
def sample_topology() -> LabTopologySpec:
    """Create a sample lab topology."""
    return LabTopologySpec(
        nodes=[
            TopologyNode(label="router-1", node_definition="iosv", x=0, y=0),
            TopologyNode(label="router-2", node_definition="iosv", x=100, y=0),
        ],
        links=[
            TopologyLink(source_node="router-1", source_interface="GigabitEthernet0/0", target_node="router-2", target_interface="GigabitEthernet0/0"),
        ],
    )


# =============================================================================
# Legacy Factory Tests
# =============================================================================


class TestLabRecordLegacyFactory:
    """Test legacy create() factory method."""

    def test_create_sets_identity(self, legacy_lab_record: LabRecord):
        assert legacy_lab_record.state.id != ""
        assert legacy_lab_record.state.worker_id == "worker-001"
        assert legacy_lab_record.state.lab_id == "lab-001"

    def test_create_sets_metadata(self, legacy_lab_record: LabRecord):
        assert legacy_lab_record.state.title == "Test Lab"
        assert legacy_lab_record.state.description == "A test lab"
        assert legacy_lab_record.state.node_count == 3

    def test_create_maps_cml_state_to_typed_status(self, legacy_lab_record: LabRecord):
        assert legacy_lab_record.state.status == LabRecordStatus.DEFINED

    def test_create_initializes_runtime_binding(self, legacy_lab_record: LabRecord):
        assert legacy_lab_record.state.runtime_binding is not None
        assert legacy_lab_record.state.runtime_binding["worker_id"] == "worker-001"
        assert legacy_lab_record.state.runtime_binding["runtime_lab_id"] == "lab-001"

    def test_create_sets_source_discovery(self, legacy_lab_record: LabRecord):
        assert legacy_lab_record.state.source == "discovery"


# =============================================================================
# Phase 7 Discovery Factory Tests
# =============================================================================


class TestLabRecordDiscoverFactory:
    """Test Phase 7 discover() factory method."""

    def test_discover_sets_identity(self, discovered_lab_record: LabRecord):
        assert discovered_lab_record.state.id != ""
        assert discovered_lab_record.state.worker_id == "worker-002"
        assert discovered_lab_record.state.lab_id == "lab-002"

    def test_discover_sets_status_discovered(self, discovered_lab_record: LabRecord):
        assert discovered_lab_record.state.status == LabRecordStatus.DISCOVERED

    def test_discover_sets_source(self, discovered_lab_record: LabRecord):
        assert discovered_lab_record.state.source == "discovery"

    def test_discover_creates_runtime_binding(self, discovered_lab_record: LabRecord):
        assert discovered_lab_record.state.runtime_binding is not None
        binding = discovered_lab_record.runtime_binding_vo
        assert binding is not None
        assert binding.worker_id == "worker-002"


# =============================================================================
# Valid State Transitions
# =============================================================================


def _force_status(lab_record: LabRecord, status: LabRecordStatus) -> None:
    """Helper to force a LabRecord into a specific status for testing.

    The aggregate's mark_* methods only expose end-state transitions
    (BOOTED, STOPPED, WIPED, DELETED). Intermediate states (STARTING,
    STOPPING, WIPING, DELETING) have no public methods yet, so we
    manipulate state directly for testing the transition table.
    """
    lab_record.state.status = status


class TestLabRecordValidTransitions:
    """Test valid state machine transitions per Architecture §4.3.

    Note: mark_started() validates to BOOTED, mark_stopped() to STOPPED, etc.
    Since the transition table uses intermediate states (STARTING→BOOTED,
    STOPPING→STOPPED), tests that need these paths use _force_status() to
    set the intermediate state before calling the mark_* method.
    """

    def test_discovered_to_defined_via_import(self, discovered_lab_record: LabRecord):
        discovered_lab_record.mark_imported(
            lab_id="lab-new",
            worker_id="worker-002",
            title="Imported",
            topology_checksum="abc123",
            imported_by="admin",
        )
        assert discovered_lab_record.state.status == LabRecordStatus.DEFINED

    def test_discovered_to_deleted(self, discovered_lab_record: LabRecord):
        discovered_lab_record.mark_deleted()
        assert discovered_lab_record.state.status == LabRecordStatus.DELETED

    def test_discovered_to_orphaned(self, discovered_lab_record: LabRecord):
        discovered_lab_record.mark_orphaned()
        assert discovered_lab_record.state.status == LabRecordStatus.ORPHANED

    def test_starting_to_booted(self, discovered_lab_record: LabRecord):
        _force_status(discovered_lab_record, LabRecordStatus.STARTING)
        discovered_lab_record.mark_started()
        assert discovered_lab_record.state.status == LabRecordStatus.BOOTED

    def test_queued_to_booted(self, discovered_lab_record: LabRecord):
        _force_status(discovered_lab_record, LabRecordStatus.QUEUED)
        discovered_lab_record.mark_started()
        assert discovered_lab_record.state.status == LabRecordStatus.BOOTED

    def test_stopping_to_stopped(self, discovered_lab_record: LabRecord):
        _force_status(discovered_lab_record, LabRecordStatus.STOPPING)
        discovered_lab_record.mark_stopped()
        assert discovered_lab_record.state.status == LabRecordStatus.STOPPED

    def test_wiping_to_wiped(self, discovered_lab_record: LabRecord):
        _force_status(discovered_lab_record, LabRecordStatus.WIPING)
        discovered_lab_record.mark_wiped()
        assert discovered_lab_record.state.status == LabRecordStatus.WIPED

    def test_deleting_to_deleted(self, discovered_lab_record: LabRecord):
        _force_status(discovered_lab_record, LabRecordStatus.DELETING)
        discovered_lab_record.mark_deleted()
        assert discovered_lab_record.state.status == LabRecordStatus.DELETED

    def test_stopped_to_archived(self, discovered_lab_record: LabRecord):
        _force_status(discovered_lab_record, LabRecordStatus.STOPPED)
        discovered_lab_record.mark_archived(archived_by="admin")
        assert discovered_lab_record.state.status == LabRecordStatus.ARCHIVED

    def test_wiped_to_archived(self, discovered_lab_record: LabRecord):
        _force_status(discovered_lab_record, LabRecordStatus.WIPED)
        discovered_lab_record.mark_archived()
        assert discovered_lab_record.state.status == LabRecordStatus.ARCHIVED

    def test_defined_to_error(self, discovered_lab_record: LabRecord):
        discovered_lab_record.mark_imported(lab_id="lab-x", worker_id="w-x", title="T", topology_checksum="cs", imported_by="a")
        assert discovered_lab_record.state.status == LabRecordStatus.DEFINED
        discovered_lab_record.mark_error("CML API timeout")
        assert discovered_lab_record.state.status == LabRecordStatus.ERROR

    def test_starting_to_error(self, discovered_lab_record: LabRecord):
        _force_status(discovered_lab_record, LabRecordStatus.STARTING)
        discovered_lab_record.mark_error("Node boot failed")
        assert discovered_lab_record.state.status == LabRecordStatus.ERROR

    def test_booted_to_error(self, discovered_lab_record: LabRecord):
        _force_status(discovered_lab_record, LabRecordStatus.BOOTED)
        discovered_lab_record.mark_error("Network failure")
        assert discovered_lab_record.state.status == LabRecordStatus.ERROR

    def test_error_recovery_to_defined(self, discovered_lab_record: LabRecord):
        _force_status(discovered_lab_record, LabRecordStatus.ERROR)
        discovered_lab_record.mark_imported(lab_id="lab-x", worker_id="w-x", title="T", topology_checksum="cs")
        assert discovered_lab_record.state.status == LabRecordStatus.DEFINED

    def test_orphaned_to_deleted(self, discovered_lab_record: LabRecord):
        discovered_lab_record.mark_orphaned()
        discovered_lab_record.mark_deleted()
        assert discovered_lab_record.state.status == LabRecordStatus.DELETED

    def test_orphaned_to_archived(self, discovered_lab_record: LabRecord):
        discovered_lab_record.mark_orphaned()
        discovered_lab_record.mark_archived()
        assert discovered_lab_record.state.status == LabRecordStatus.ARCHIVED


# =============================================================================
# Invalid State Transitions
# =============================================================================


class TestLabRecordInvalidTransitions:
    """Test that invalid transitions raise InvalidLabRecordTransitionError."""

    def test_deleted_is_terminal(self, discovered_lab_record: LabRecord):
        """DELETED is terminal — no transitions allowed."""
        discovered_lab_record.mark_deleted()
        with pytest.raises(InvalidLabRecordTransitionError):
            discovered_lab_record.mark_started()

    def test_archived_is_terminal(self, discovered_lab_record: LabRecord):
        _force_status(discovered_lab_record, LabRecordStatus.STOPPED)
        discovered_lab_record.mark_archived()
        with pytest.raises(InvalidLabRecordTransitionError):
            discovered_lab_record.mark_stopped()

    def test_discovered_can_go_to_booted(self, discovered_lab_record: LabRecord):
        """DISCOVERED → BOOTED is valid (lab may already be running on CML when discovered)."""
        discovered_lab_record.mark_started()
        assert discovered_lab_record.state.status == LabRecordStatus.BOOTED

    def test_discovered_can_go_to_stopped(self, discovered_lab_record: LabRecord):
        """DISCOVERED → STOPPED is valid (lab may be stopped on CML when discovered)."""
        discovered_lab_record.mark_stopped()
        assert discovered_lab_record.state.status == LabRecordStatus.STOPPED

    def test_discovered_can_go_to_wiped(self, discovered_lab_record: LabRecord):
        """DISCOVERED → WIPED is valid (lab may be wiped on CML when discovered)."""
        discovered_lab_record.mark_wiped()
        assert discovered_lab_record.state.status == LabRecordStatus.WIPED

    def test_discovered_cannot_go_to_error(self, discovered_lab_record: LabRecord):
        """DISCOVERED does not allow ERROR transition."""
        with pytest.raises(InvalidLabRecordTransitionError):
            discovered_lab_record.mark_error("Should fail")

    # --- Direct transitions for CompleteLabActionCommand (AD-024) ---

    def test_booted_direct_to_stopped(self, discovered_lab_record: LabRecord):
        """BOOTED → STOPPED is valid (direct stop via CompleteLabActionCommand)."""
        _force_status(discovered_lab_record, LabRecordStatus.BOOTED)
        discovered_lab_record.mark_stopped()
        assert discovered_lab_record.state.status == LabRecordStatus.STOPPED

    def test_booted_direct_to_wiped(self, discovered_lab_record: LabRecord):
        """BOOTED → WIPED is valid (direct wipe via CompleteLabActionCommand)."""
        _force_status(discovered_lab_record, LabRecordStatus.BOOTED)
        discovered_lab_record.mark_wiped()
        assert discovered_lab_record.state.status == LabRecordStatus.WIPED

    def test_stopped_direct_to_booted(self, discovered_lab_record: LabRecord):
        """STOPPED → BOOTED is valid (direct start via CompleteLabActionCommand)."""
        _force_status(discovered_lab_record, LabRecordStatus.STOPPED)
        discovered_lab_record.mark_started()
        assert discovered_lab_record.state.status == LabRecordStatus.BOOTED

    def test_stopped_direct_to_wiped(self, discovered_lab_record: LabRecord):
        """STOPPED → WIPED is valid (direct wipe via CompleteLabActionCommand)."""
        _force_status(discovered_lab_record, LabRecordStatus.STOPPED)
        discovered_lab_record.mark_wiped()
        assert discovered_lab_record.state.status == LabRecordStatus.WIPED

    def test_stopped_direct_to_deleted(self, discovered_lab_record: LabRecord):
        """STOPPED → DELETED is valid (direct delete via CompleteLabActionCommand)."""
        _force_status(discovered_lab_record, LabRecordStatus.STOPPED)
        discovered_lab_record.mark_deleted()
        assert discovered_lab_record.state.status == LabRecordStatus.DELETED

    def test_defined_direct_to_booted(self, discovered_lab_record: LabRecord):
        """DEFINED → BOOTED is valid (direct start via CompleteLabActionCommand)."""
        _force_status(discovered_lab_record, LabRecordStatus.DEFINED)
        discovered_lab_record.mark_started()
        assert discovered_lab_record.state.status == LabRecordStatus.BOOTED

    def test_defined_direct_to_deleted(self, discovered_lab_record: LabRecord):
        """DEFINED → DELETED is valid (direct delete via CompleteLabActionCommand)."""
        _force_status(discovered_lab_record, LabRecordStatus.DEFINED)
        discovered_lab_record.mark_deleted()
        assert discovered_lab_record.state.status == LabRecordStatus.DELETED

    def test_wiped_direct_to_booted(self, discovered_lab_record: LabRecord):
        """WIPED → BOOTED is valid (direct start via CompleteLabActionCommand)."""
        _force_status(discovered_lab_record, LabRecordStatus.WIPED)
        discovered_lab_record.mark_started()
        assert discovered_lab_record.state.status == LabRecordStatus.BOOTED

    def test_wiped_direct_to_deleted(self, discovered_lab_record: LabRecord):
        """WIPED → DELETED is valid (direct delete via CompleteLabActionCommand)."""
        _force_status(discovered_lab_record, LabRecordStatus.WIPED)
        discovered_lab_record.mark_deleted()
        assert discovered_lab_record.state.status == LabRecordStatus.DELETED

    def test_error_direct_to_wiped(self, discovered_lab_record: LabRecord):
        """ERROR → WIPED is valid (direct wipe via CompleteLabActionCommand)."""
        _force_status(discovered_lab_record, LabRecordStatus.ERROR)
        discovered_lab_record.mark_wiped()
        assert discovered_lab_record.state.status == LabRecordStatus.WIPED

    def test_error_direct_to_deleted(self, discovered_lab_record: LabRecord):
        """ERROR → DELETED is valid (direct delete via CompleteLabActionCommand)."""
        _force_status(discovered_lab_record, LabRecordStatus.ERROR)
        discovered_lab_record.mark_deleted()
        assert discovered_lab_record.state.status == LabRecordStatus.DELETED

    def test_transition_error_contains_states(self, discovered_lab_record: LabRecord):
        discovered_lab_record.mark_deleted()
        with pytest.raises(InvalidLabRecordTransitionError) as exc_info:
            discovered_lab_record.mark_started()
        assert exc_info.value.from_status == LabRecordStatus.DELETED
        assert exc_info.value.to_status == LabRecordStatus.BOOTED


# =============================================================================
# CML Data Sync (create/update from raw CML data)
# =============================================================================


class TestLabRecordLegacySync:
    """Test create/update from raw CML data."""

    def test_update_from_cml_changes_state_and_status(self, legacy_lab_record: LabRecord):
        legacy_lab_record.update_from_cml(
            title="Updated",
            description="Updated desc",
            notes=None,
            state="STARTED",
            owner_username="admin",
            owner_fullname="Admin",
            node_count=4,
            link_count=3,
            groups=[],
            cml_modified_at=datetime.now(timezone.utc),
        )
        assert legacy_lab_record.state.state == "STARTED"
        assert legacy_lab_record.state.status == LabRecordStatus.BOOTED
        assert legacy_lab_record.state.title == "Updated"

    def test_update_from_cml_records_state_change(self, legacy_lab_record: LabRecord):
        legacy_lab_record.update_from_cml(
            title="Test Lab",
            description="A test lab",
            notes=None,
            state="STARTED",
            owner_username="admin",
            owner_fullname="Admin",
            node_count=3,
            link_count=2,
            groups=[],
            cml_modified_at=datetime.now(timezone.utc),
        )
        assert legacy_lab_record.state.state == "STARTED"
        assert legacy_lab_record.state.status == LabRecordStatus.BOOTED

    def test_update_from_cml_unknown_state_maps_to_defined(self, legacy_lab_record: LabRecord):
        """Unknown CML states should map to DEFINED (safe default)."""
        legacy_lab_record.update_from_cml(
            title="Test Lab",
            description="A test lab",
            notes=None,
            state="SOME_UNKNOWN_STATE",
            owner_username="admin",
            owner_fullname="Admin",
            node_count=3,
            link_count=2,
            groups=[],
            cml_modified_at=datetime.now(timezone.utc),
        )
        assert legacy_lab_record.state.status == LabRecordStatus.DEFINED


# =============================================================================
# Topology & Revision Tests
# =============================================================================


class TestLabRecordTopology:
    """Test topology and revision tracking."""

    def test_update_topology_stores_spec(self, discovered_lab_record: LabRecord, sample_topology: LabTopologySpec):
        discovered_lab_record.update_topology(sample_topology)
        assert discovered_lab_record.state.topology_spec is not None
        assert discovered_lab_record.state.node_count == 2
        assert discovered_lab_record.state.link_count == 1

    def test_update_topology_creates_revision(self, discovered_lab_record: LabRecord, sample_topology: LabTopologySpec):
        discovered_lab_record.update_topology(sample_topology, change_summary="Initial topology")
        assert discovered_lab_record.state.revision == 2
        assert len(discovered_lab_record.state.revision_history) == 1

    def test_same_topology_no_new_revision(self, discovered_lab_record: LabRecord, sample_topology: LabTopologySpec):
        discovered_lab_record.update_topology(sample_topology)
        rev_after_first = discovered_lab_record.state.revision
        discovered_lab_record.update_topology(sample_topology)  # Same topology
        assert discovered_lab_record.state.revision == rev_after_first

    def test_revision_history_vo_deserialization(self, discovered_lab_record: LabRecord, sample_topology: LabTopologySpec):
        discovered_lab_record.update_topology(sample_topology)
        revisions = discovered_lab_record.revision_history_vo
        assert len(revisions) == 1
        assert revisions[0].revision == 2


# =============================================================================
# External Interfaces Tests
# =============================================================================


class TestLabRecordExternalInterfaces:
    """Test external interface management."""

    def test_set_external_interfaces(self, discovered_lab_record: LabRecord):
        interfaces = [
            ExternalInterface(node_label="router-1", protocol="ssh", port=22, host="10.0.0.1"),
            ExternalInterface(node_label="router-1", protocol="vnc", port=5900, host="10.0.0.1"),
        ]
        discovered_lab_record.set_external_interfaces(interfaces)
        assert len(discovered_lab_record.state.external_interfaces) == 2

    def test_external_interfaces_vo_deserialization(self, discovered_lab_record: LabRecord):
        interfaces = [ExternalInterface(node_label="sw-1", protocol="telnet", port=23, host="10.0.0.2")]
        discovered_lab_record.set_external_interfaces(interfaces)
        result = discovered_lab_record.external_interfaces_vo
        assert len(result) == 1
        assert result[0].node_label == "sw-1"


# =============================================================================
# Run History Tests
# =============================================================================


class TestLabRecordRunHistory:
    """Test run history tracking."""

    def test_record_run(self, discovered_lab_record: LabRecord):
        run = LabRunRecord(
            run_id="run-001",
            started_at=datetime.now(timezone.utc) - timedelta(hours=1),
            stopped_at=datetime.now(timezone.utc),
            duration_seconds=3600,
            started_by="admin",
            stop_reason="Timeslot ended",
        )
        discovered_lab_record.record_run(run)
        assert len(discovered_lab_record.state.run_history_v2) == 1

    def test_run_history_cap(self, discovered_lab_record: LabRecord):
        for i in range(55):
            run = LabRunRecord(
                run_id=f"run-{i:03d}",
                started_at=datetime.now(timezone.utc),
                stopped_at=datetime.now(timezone.utc),
                duration_seconds=60,
            )
            discovered_lab_record.record_run(run)
        assert len(discovered_lab_record.state.run_history_v2) == 50

    def test_run_history_vo_deserialization(self, discovered_lab_record: LabRecord):
        run = LabRunRecord(
            run_id="run-002",
            started_at=datetime.now(timezone.utc),
            duration_seconds=0,
        )
        discovered_lab_record.record_run(run)
        runs = discovered_lab_record.run_history_vo
        assert len(runs) == 1
        assert runs[0].run_id == "run-002"


# =============================================================================
# Binding Event Tests
# =============================================================================


class TestLabRecordBindingEvents:
    """Test binding and unbinding events."""

    def test_bind_to_lablet(self, discovered_lab_record: LabRecord):
        discovered_lab_record.bind_to_lablet(
            lablet_session_id="inst-001",
            binding_id="bind-001",
            binding_role="primary",
        )
        # Binding state is managed externally — event is just recorded
        assert discovered_lab_record.state.status == LabRecordStatus.DISCOVERED

    def test_unbind_from_lablet(self, discovered_lab_record: LabRecord):
        discovered_lab_record.unbind_from_lablet(
            lablet_session_id="inst-001",
            binding_id="bind-001",
        )
        assert discovered_lab_record.state.status == LabRecordStatus.DISCOVERED


# =============================================================================
# Error & Orphan Tests
# =============================================================================


class TestLabRecordErrorAndOrphan:
    """Test error and orphan state handling."""

    def test_error_records_previous_status(self, discovered_lab_record: LabRecord):
        _force_status(discovered_lab_record, LabRecordStatus.BOOTED)
        discovered_lab_record.mark_error("CML API timeout")
        assert discovered_lab_record.state.previous_status_before_error == "booted"
        assert discovered_lab_record.state.last_error == "CML API timeout"
        assert discovered_lab_record.state.last_error_at is not None

    def test_orphaned_records_state(self, discovered_lab_record: LabRecord):
        discovered_lab_record.mark_orphaned()
        assert discovered_lab_record.state.status == LabRecordStatus.ORPHANED
        assert discovered_lab_record.state.state == "ORPHANED"


# =============================================================================
# Pending Action Tests (ADR-017)
# =============================================================================


class TestLabRecordPendingActions:
    """Test ADR-017 reconciliation pattern."""

    def test_request_start(self, discovered_lab_record: LabRecord):
        discovered_lab_record.request_start()
        assert discovered_lab_record.state.pending_action == "start"
        assert discovered_lab_record.state.pending_action_at is not None

    def test_complete_pending_action(self, discovered_lab_record: LabRecord):
        discovered_lab_record.request_stop()
        discovered_lab_record.complete_pending_action()
        assert discovered_lab_record.state.pending_action is None

    def test_fail_pending_action(self, discovered_lab_record: LabRecord):
        discovered_lab_record.request_wipe()
        discovered_lab_record.fail_pending_action("CML unreachable")
        assert discovered_lab_record.state.pending_action_error == "CML unreachable"
        assert discovered_lab_record.state.pending_action is None
        assert discovered_lab_record.state.pending_action_at is None

    def test_clear_pending_action(self, discovered_lab_record: LabRecord):
        discovered_lab_record.request_delete()
        discovered_lab_record.clear_pending_action()
        assert discovered_lab_record.state.pending_action is None
        assert discovered_lab_record.state.pending_action_at is None


# =============================================================================
# Computed Properties
# =============================================================================


class TestLabRecordComputedProperties:
    """Test computed properties."""

    def test_is_terminal_deleted(self, discovered_lab_record: LabRecord):
        discovered_lab_record.mark_deleted()
        assert discovered_lab_record.is_terminal is True

    def test_is_terminal_archived(self, discovered_lab_record: LabRecord):
        _force_status(discovered_lab_record, LabRecordStatus.STOPPED)
        discovered_lab_record.mark_archived()
        assert discovered_lab_record.is_terminal is True

    def test_is_running(self, discovered_lab_record: LabRecord):
        _force_status(discovered_lab_record, LabRecordStatus.BOOTED)
        assert discovered_lab_record.is_running is True

    def test_is_reusable_defined(self, discovered_lab_record: LabRecord):
        _force_status(discovered_lab_record, LabRecordStatus.DEFINED)
        assert discovered_lab_record.is_reusable is True

    def test_is_reusable_stopped(self, discovered_lab_record: LabRecord):
        _force_status(discovered_lab_record, LabRecordStatus.STOPPED)
        assert discovered_lab_record.is_reusable is True

    def test_is_reusable_wiped(self, discovered_lab_record: LabRecord):
        _force_status(discovered_lab_record, LabRecordStatus.WIPED)
        assert discovered_lab_record.is_reusable is True

    def test_is_error(self, discovered_lab_record: LabRecord):
        _force_status(discovered_lab_record, LabRecordStatus.DEFINED)
        discovered_lab_record.mark_error("Error")
        assert discovered_lab_record.is_error is True

    def test_is_orphaned(self, discovered_lab_record: LabRecord):
        discovered_lab_record.mark_orphaned()
        assert discovered_lab_record.is_orphaned is True

    def test_not_terminal_when_running(self, discovered_lab_record: LabRecord):
        _force_status(discovered_lab_record, LabRecordStatus.BOOTED)
        assert discovered_lab_record.is_terminal is False
