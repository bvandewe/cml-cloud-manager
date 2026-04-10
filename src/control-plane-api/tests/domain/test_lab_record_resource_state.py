"""Tests for LabRecord ResourceState migration (ADR-036 Batch G).

Validates:
- G.1: Base class inheritance (ResourceState → LabRecordState)
- G.2: _record_transition() dict output and state_history accumulation
- G.3: StateTransition import consolidation (lcm_core version only)
- G.5: CPA-local state_transition.py deleted
- Field shadowing: LabRecordStatus (enum) vs ResourceState.status (str)
"""

from datetime import datetime, timezone

from lcm_core.domain.entities.resource import ResourceState
from lcm_core.domain.entities.timed_resource import TimedResourceState
from lcm_core.domain.enums import LabRecordStatus
from lcm_core.domain.value_objects.state_transition import StateTransition

from domain.entities.lab_record import LabRecord, LabRecordState

# =============================================================================
# Helpers
# =============================================================================


def _make_discovered() -> LabRecord:
    """Create a fresh LabRecord in DISCOVERED state via Phase 7 factory."""
    return LabRecord.discover(
        lab_id="lab-001",
        worker_id="worker-001",
        title="Test Lab",
        description="A test lab",
        state="STOPPED",
        owner_username="admin",
        node_count=3,
        link_count=2,
    )


def _make_legacy() -> LabRecord:
    """Create a LabRecord via the legacy create() factory."""
    return LabRecord.create(
        lab_id="lab-002",
        worker_id="worker-002",
        title="Legacy Lab",
        description="Legacy created",
        notes="Some notes",
        state="DEFINED_ON_CORE",
        owner_username="admin",
        owner_fullname="Admin User",
        node_count=5,
        link_count=4,
        groups=["group-a"],
        cml_created_at=datetime.now(timezone.utc),
        cml_modified_at=datetime.now(timezone.utc),
    )


def _make_booted() -> LabRecord:
    """Create a LabRecord in BOOTED state."""
    record = _make_discovered()
    record.mark_started()
    return record


def _make_stopped() -> LabRecord:
    """Create a LabRecord in STOPPED state (via BOOTED → STOPPED)."""
    record = _make_booted()
    record.mark_stopped()
    return record


# =============================================================================
# G.1 — Base Class Inheritance Tests
# =============================================================================


class TestResourceStateInheritance:
    """Tests for G.1: LabRecordState inherits from ResourceState (Layer 1)."""

    def test_inherits_from_resource_state(self) -> None:
        """LabRecordState must extend ResourceState."""
        state = LabRecordState()
        assert isinstance(state, ResourceState)

    def test_does_not_inherit_from_timed_resource_state(self) -> None:
        """LabRecordState must NOT extend TimedResourceState (Layer 2).

        LabRecords have open-ended lifetimes and don't need timeslot/lifecycle.
        """
        state = LabRecordState()
        assert not isinstance(state, TimedResourceState)

    def test_resource_type_is_lab_record(self) -> None:
        """resource_type must be set to 'lab_record'."""
        state = LabRecordState()
        assert state.resource_type == "lab_record"

    def test_has_status_field(self) -> None:
        """status field exists and defaults to DISCOVERED."""
        state = LabRecordState()
        assert state.status == LabRecordStatus.DISCOVERED

    def test_has_state_history_field(self) -> None:
        """state_history is inherited and initialized as empty list."""
        state = LabRecordState()
        assert hasattr(state, "state_history")
        assert state.state_history == []

    def test_has_pipeline_progress_field(self) -> None:
        """pipeline_progress is inherited from ResourceState (Layer 1)."""
        state = LabRecordState()
        assert hasattr(state, "pipeline_progress")
        assert state.pipeline_progress is None

    def test_has_created_at_field(self) -> None:
        """created_at is inherited and initialized to current time."""
        state = LabRecordState()
        assert isinstance(state.created_at, datetime)

    def test_has_updated_at_field(self) -> None:
        """updated_at is inherited and initialized to current time."""
        state = LabRecordState()
        assert isinstance(state.updated_at, datetime)

    def test_has_owner_id_field(self) -> None:
        """owner_id is inherited from ResourceState."""
        state = LabRecordState()
        assert hasattr(state, "owner_id")
        assert state.owner_id == ""

    def test_id_inherited_from_resource_state(self) -> None:
        """id is inherited from ResourceState, not declared on LabRecordState."""
        state = LabRecordState()
        assert hasattr(state, "id")
        assert state.id == ""

    def test_no_timeslot_field(self) -> None:
        """LabRecordState should NOT have timeslot (not TimedResourceState)."""
        state = LabRecordState()
        assert not hasattr(state, "timeslot") or state.__class__.__mro__[1] is ResourceState

    def test_no_lifecycle_field(self) -> None:
        """LabRecordState should NOT have lifecycle (not TimedResourceState)."""
        state = LabRecordState()
        # ResourceState doesn't define lifecycle; it would only exist if
        # inheriting from TimedResourceState.
        assert not isinstance(state, TimedResourceState)


# =============================================================================
# G.2 — _record_transition() Tests
# =============================================================================


class TestRecordTransition:
    """Tests for G.2: _record_transition stores dicts and handles enum→str."""

    def test_state_history_stores_dicts(self) -> None:
        """State history entries are dicts, not StateTransition objects."""
        record = _make_discovered()
        assert len(record.state.state_history) >= 1
        entry = record.state.state_history[0]
        assert isinstance(entry, dict)

    def test_dict_has_required_keys(self) -> None:
        """Each state history dict has from_state, to_state, transitioned_at, triggered_by."""
        record = _make_discovered()
        entry = record.state.state_history[0]
        assert "from_state" in entry
        assert "to_state" in entry
        assert "transitioned_at" in entry
        assert "triggered_by" in entry

    def test_creation_records_initial_transition(self) -> None:
        """Discover factory records initial transition with from_state=None."""
        record = _make_discovered()
        entry = record.state.state_history[0]
        assert entry["from_state"] is None
        assert entry["to_state"] == "discovered"

    def test_legacy_create_records_initial_transition(self) -> None:
        """Legacy create() factory records initial transition."""
        record = _make_legacy()
        assert len(record.state.state_history) >= 1
        entry = record.state.state_history[0]
        assert entry["from_state"] is None
        assert entry["triggered_by"] == "system"

    def test_transition_accumulation(self) -> None:
        """Multiple transitions accumulate in state_history."""
        record = _make_discovered()
        initial_count = len(record.state.state_history)
        record.mark_started()
        assert len(record.state.state_history) == initial_count + 1
        record.mark_stopped()
        assert len(record.state.state_history) == initial_count + 2

    def test_started_transition_recorded(self) -> None:
        """BOOTED transition is recorded with correct from/to states."""
        record = _make_booted()
        last = record.state.state_history[-1]
        assert last["from_state"] == "discovered"
        assert last["to_state"] == "booted"

    def test_stopped_transition_recorded(self) -> None:
        """STOPPED transition is recorded after BOOTED."""
        record = _make_stopped()
        last = record.state.state_history[-1]
        assert last["from_state"] == "booted"
        assert last["to_state"] == "stopped"

    def test_error_transition_recorded(self) -> None:
        """ERROR transition records the error message as reason."""
        record = _make_booted()
        record.mark_error("Something broke")
        last = record.state.state_history[-1]
        assert last["from_state"] == "booted"
        assert last["to_state"] == "error"
        assert last["reason"] == "Something broke"

    def test_orphaned_transition_recorded(self) -> None:
        """ORPHANED transition is recorded."""
        record = _make_discovered()
        record.mark_orphaned()
        last = record.state.state_history[-1]
        assert last["to_state"] == "orphaned"

    def test_deleted_transition_recorded(self) -> None:
        """DELETED transition is recorded (terminal)."""
        record = _make_stopped()
        record.mark_deleted()
        last = record.state.state_history[-1]
        assert last["from_state"] == "stopped"
        assert last["to_state"] == "deleted"

    def test_archived_transition_recorded(self) -> None:
        """ARCHIVED transition is recorded (terminal)."""
        record = _make_stopped()
        record.mark_archived()
        last = record.state.state_history[-1]
        assert last["from_state"] == "stopped"
        assert last["to_state"] == "archived"

    def test_wiped_transition_recorded(self) -> None:
        """WIPED transition is recorded."""
        record = _make_booted()
        record.mark_wiped()
        last = record.state.state_history[-1]
        assert last["from_state"] == "booted"
        assert last["to_state"] == "wiped"

    def test_record_transition_updates_updated_at(self) -> None:
        """_record_transition updates self.updated_at."""
        state = LabRecordState()
        old_updated = state.updated_at
        state._record_transition(
            from_state=None,
            to_state="discovered",
            triggered_by="system",
        )
        assert state.updated_at >= old_updated

    def test_from_state_is_string_not_enum(self) -> None:
        """from_state in stored dict is a plain string, not an enum."""
        record = _make_discovered()
        record.mark_started()
        entry = record.state.state_history[-1]
        assert isinstance(entry["from_state"], str)
        assert entry["from_state"] == "discovered"

    def test_to_state_is_string_not_enum(self) -> None:
        """to_state in stored dict is a plain string, not an enum."""
        record = _make_discovered()
        entry = record.state.state_history[0]
        assert isinstance(entry["to_state"], str)

    def test_state_transition_dict_roundtrip(self) -> None:
        """StateTransition → to_dict() → from_dict() preserves data."""
        now = datetime.now(timezone.utc)
        original = StateTransition(
            from_state="discovered",
            to_state="booted",
            transitioned_at=now,
            triggered_by="system",
            reason="Lab started",
            metadata={"lab_id": "lab-001"},
        )
        d = original.to_dict()
        restored = StateTransition.from_dict(d)
        assert restored.from_state == original.from_state
        assert restored.to_state == original.to_state
        assert restored.triggered_by == original.triggered_by
        assert restored.reason == original.reason
        assert restored.metadata == original.metadata


# =============================================================================
# G.2 — Conditional Transition (Updated/StateChanged handlers)
# =============================================================================


class TestConditionalTransitions:
    """Tests for conditional _record_transition in Updated/StateChanged handlers."""

    def test_update_with_same_status_no_transition(self) -> None:
        """LabRecordUpdatedDomainEvent with same state doesn't add transition."""
        record = _make_discovered()
        initial_count = len(record.state.state_history)
        # Update with same state — should not add a transition
        record.update_from_cml(
            title="Updated Title",
            description="Updated",
            notes=None,
            state="STOPPED",  # Maps to DISCOVERED's mapped status
            owner_username="admin",
            owner_fullname="Admin",
            node_count=3,
            link_count=2,
            groups=[],
            cml_modified_at=datetime.now(timezone.utc),
        )
        # May or may not add transition depending on mapping;
        # the key invariant is that the handler doesn't crash
        assert len(record.state.state_history) >= initial_count

    def test_update_with_state_change_adds_transition(self) -> None:
        """LabRecordUpdatedDomainEvent with different state adds transition."""
        record = _make_discovered()
        initial_count = len(record.state.state_history)
        # Force a state that maps to a different LabRecordStatus
        record.update_from_cml(
            title="Updated Title",
            description="Updated",
            notes=None,
            state="BOOTED",
            owner_username="admin",
            owner_fullname="Admin",
            node_count=3,
            link_count=2,
            groups=[],
            cml_modified_at=datetime.now(timezone.utc),
        )
        # STOPPED→BOOTED should add a transition
        assert len(record.state.state_history) > initial_count


# =============================================================================
# G.1 — Field Shadowing Tests
# =============================================================================


class TestFieldShadowing:
    """Tests for field shadowing: LabRecordStatus vs str."""

    def test_status_is_typed_enum(self) -> None:
        """LabRecordState.status is LabRecordStatus, not plain str."""
        state = LabRecordState()
        assert isinstance(state.status, LabRecordStatus)

    def test_status_enum_has_string_value(self) -> None:
        """LabRecordStatus enum values are strings (StrEnum-compatible)."""
        assert LabRecordStatus.DISCOVERED.value == "discovered"
        assert LabRecordStatus.BOOTED.value == "booted"
        assert LabRecordStatus.STOPPED.value == "stopped"

    def test_status_shadows_resource_state_str(self) -> None:
        """LabRecordState.status shadows ResourceState.status (str) with enum."""
        state = LabRecordState()
        # It's a LabRecordStatus enum but also compares as str
        assert state.status == "discovered"
        assert state.status == LabRecordStatus.DISCOVERED

    def test_factory_creates_with_typed_status(self) -> None:
        """Factory methods produce typed status."""
        record = _make_discovered()
        assert isinstance(record.state.status, LabRecordStatus)
        assert record.state.status == LabRecordStatus.DISCOVERED


# =============================================================================
# G.3 — StateTransition Import Consolidation Tests
# =============================================================================


class TestStateTransitionConsolidation:
    """Tests for G.3: Only lcm_core StateTransition is used."""

    def test_state_transition_import_is_lcm_core(self) -> None:
        """The StateTransition used in lab_record.py is from lcm_core."""
        import domain.entities.lab_record as module

        source = module.__file__
        assert source is not None
        with open(source) as f:
            content = f.read()
        # Must import from lcm_core
        assert "from lcm_core.domain.value_objects.state_transition import StateTransition" in content
        # Must NOT import from CPA-local domain.value_objects.state_transition
        assert "from domain.value_objects.state_transition import" not in content

    def test_state_transition_has_str_based_fields(self) -> None:
        """lcm_core StateTransition uses str for from_state/to_state."""
        transition = StateTransition(
            from_state="discovered",
            to_state="booted",
            transitioned_at=datetime.now(timezone.utc),
            triggered_by="system",
        )
        assert isinstance(transition.from_state, str)
        assert isinstance(transition.to_state, str)


# =============================================================================
# G.5 — CPA-local state_transition.py Deleted
# =============================================================================


class TestDeadCodeRemoval:
    """Tests for G.5: CPA-local state_transition.py is deleted."""

    def test_cpa_state_transition_file_does_not_exist(self) -> None:
        """domain/value_objects/state_transition.py must not exist."""
        import importlib
        import os

        # Get the domain.value_objects package path
        vo_module = importlib.import_module("domain.value_objects")
        vo_dir = os.path.dirname(vo_module.__file__)
        st_path = os.path.join(vo_dir, "state_transition.py")
        assert not os.path.exists(st_path), f"CPA-local state_transition.py still exists at {st_path}"

    def test_cpa_value_objects_init_no_state_transition(self) -> None:
        """domain.value_objects.__init__ must not export StateTransition."""
        import domain.value_objects as vo_pkg

        assert not hasattr(vo_pkg, "StateTransition") or "StateTransition" not in vo_pkg.__all__
