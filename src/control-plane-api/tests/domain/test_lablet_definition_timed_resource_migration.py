"""Tests for LabletDefinition TimedResourceState migration (ADR-036 Batch I).

Validates:
- I.1: Base class inheritance (TimedResourceState → LabletDefinitionState)
- I.2: _record_transition() dict output and state_history accumulation
- I.3: Conditional transitions (non-status-changing events don't record)
- I.4: LabletDefinitionStatus shadows ResourceState.status (str)
- I.5: created_by → owner_id mapping
- I.6: StateTransition import consolidation (lcm_core version only)
"""

from datetime import datetime, timezone

from lcm_core.domain.entities.resource import ResourceState
from lcm_core.domain.entities.timed_resource import TimedResourceState
from lcm_core.domain.value_objects.state_transition import StateTransition

from domain.entities.lablet_definition import LabletDefinition, LabletDefinitionState
from domain.enums import LabletDefinitionStatus
from domain.value_objects.port_template import PortTemplate
from domain.value_objects.resource_requirements import ResourceRequirements

# =============================================================================
# Helpers
# =============================================================================


def _make_definition() -> LabletDefinition:
    """Create a fresh LabletDefinition in PENDING_SYNC state."""
    return LabletDefinition.create(
        name="test-definition",
        version="1.0.0",
        form_qualified_name="Track Level ACR v1 Module Form",
        resource_requirements=ResourceRequirements(cpu_cores=2, memory_gb=4, storage_gb=10),
        license_affinity=[],
        node_count=3,
        port_template=PortTemplate.empty(),
        created_by="test-user",
    )


def _make_active_definition() -> LabletDefinition:
    """Create a LabletDefinition in ACTIVE state (after successful sync)."""
    definition = _make_definition()
    definition.record_content_sync(
        lab_yaml_hash="abc123",
        sync_status="success",
        content_package_hash="pkg-hash",
    )
    return definition


def _make_deprecated_definition() -> LabletDefinition:
    """Create a LabletDefinition in DEPRECATED state."""
    definition = _make_active_definition()
    definition.deprecate(
        deprecated_by="admin-user",
        deprecation_reason="Replaced by v2.0.0",
        replacement_version="2.0.0",
    )
    return definition


def _make_version() -> LabletDefinition:
    """Create a LabletDefinition via the create_version() factory."""
    return LabletDefinition.create_version(
        name="test-definition",
        version="2.0.0",
        previous_version="1.0.0",
        lab_artifact_uri="s3://bucket/artifact.yaml",
        lab_yaml_hash="hash-v2",
        resource_requirements=ResourceRequirements(cpu_cores=2, memory_gb=4, storage_gb=10),
        node_count=5,
        port_template=PortTemplate.empty(),
        created_by="version-author",
    )


# =============================================================================
# I.1 — Base Class Inheritance Tests
# =============================================================================


class TestTimedResourceStateInheritance:
    """Tests for I.1: LabletDefinitionState inherits from TimedResourceState (Layer 2)."""

    def test_inherits_from_timed_resource_state(self) -> None:
        """LabletDefinitionState must be a subclass of TimedResourceState."""
        state = LabletDefinitionState()
        assert isinstance(state, TimedResourceState)

    def test_inherits_from_resource_state(self) -> None:
        """LabletDefinitionState must also be a subclass of ResourceState (Layer 1)."""
        state = LabletDefinitionState()
        assert isinstance(state, ResourceState)

    def test_resource_type_is_lablet_definition(self) -> None:
        """resource_type must be set to 'lablet_definition'."""
        state = LabletDefinitionState()
        assert state.resource_type == "lablet_definition"

    def test_has_desired_status_none_by_default(self) -> None:
        """desired_status defaults to None."""
        state = LabletDefinitionState()
        assert state.desired_status is None

    def test_has_state_history_empty_by_default(self) -> None:
        """state_history is inherited and initialized as empty list."""
        state = LabletDefinitionState()
        assert hasattr(state, "state_history")
        assert state.state_history == []

    def test_has_owner_id_field(self) -> None:
        """owner_id field inherited from ResourceState."""
        state = LabletDefinitionState()
        assert hasattr(state, "owner_id")
        assert state.owner_id == ""

    def test_has_timeslot_none_by_default(self) -> None:
        """timeslot defaults to None (no timeslot assigned at creation)."""
        state = LabletDefinitionState()
        assert state.timeslot is None

    def test_has_lifecycle_none_by_default(self) -> None:
        """lifecycle defaults to None."""
        state = LabletDefinitionState()
        assert state.lifecycle is None

    def test_has_timed_fields(self) -> None:
        """started_at, ended_at, duration_seconds, terminated_at default to None."""
        state = LabletDefinitionState()
        assert state.started_at is None
        assert state.ended_at is None
        assert state.duration_seconds is None
        assert state.terminated_at is None

    def test_has_pipeline_progress_none_by_default(self) -> None:
        """pipeline_progress defaults to None (distinct from pipelines config)."""
        state = LabletDefinitionState()
        assert state.pipeline_progress is None

    def test_has_created_at_field(self) -> None:
        """created_at is inherited and initialized to current time."""
        state = LabletDefinitionState()
        assert isinstance(state.created_at, datetime)

    def test_has_updated_at_field(self) -> None:
        """updated_at is inherited and initialized to current time."""
        state = LabletDefinitionState()
        assert isinstance(state.updated_at, datetime)

    def test_pipelines_distinct_from_pipeline_progress(self) -> None:
        """pipelines (config) and pipeline_progress (runtime) are distinct fields."""
        state = LabletDefinitionState()
        assert state.pipelines is None  # Definition config (ADR-034)
        assert state.pipeline_progress is None  # Runtime state (inherited from ResourceState)


# =============================================================================
# I.2 — _record_transition() and State History Tests
# =============================================================================


class TestStateHistory:
    """Tests for I.2: state_history tracking via _record_transition()."""

    def test_created_event_records_initial_transition(self) -> None:
        """Creating a definition should add a transition from None → pending_sync."""
        definition = _make_definition()
        assert len(definition.state.state_history) >= 1
        entry = definition.state.state_history[0]
        assert entry["from_state"] is None
        assert entry["to_state"] == "pending_sync"

    def test_created_transition_has_triggered_by(self) -> None:
        """Created transition should record the created_by user."""
        definition = _make_definition()
        entry = definition.state.state_history[0]
        assert entry["triggered_by"] == "test-user"

    def test_created_transition_has_reason(self) -> None:
        """Created transition should have a descriptive reason."""
        definition = _make_definition()
        entry = definition.state.state_history[0]
        assert entry["reason"] == "Definition created"

    def test_content_sync_records_transition_to_active(self) -> None:
        """Successful content sync should record → active transition."""
        definition = _make_active_definition()
        last = definition.state.state_history[-1]
        assert last["from_state"] == "pending_sync"
        assert last["to_state"] == "active"

    def test_content_sync_transition_has_reason(self) -> None:
        """Content sync transition should have descriptive reason."""
        definition = _make_active_definition()
        last = definition.state.state_history[-1]
        assert last["reason"] == "Content sync completed successfully"

    def test_deprecation_records_transition(self) -> None:
        """Deprecating should record current → deprecated transition."""
        definition = _make_deprecated_definition()
        last = definition.state.state_history[-1]
        assert last["from_state"] == "active"
        assert last["to_state"] == "deprecated"

    def test_deprecation_records_triggered_by(self) -> None:
        """Deprecation transition should record who deprecated."""
        definition = _make_deprecated_definition()
        last = definition.state.state_history[-1]
        assert last["triggered_by"] == "admin-user"

    def test_deprecation_records_reason(self) -> None:
        """Deprecation transition should record the deprecation reason."""
        definition = _make_deprecated_definition()
        last = definition.state.state_history[-1]
        assert last["reason"] == "Replaced by v2.0.0"

    def test_deprecation_without_reason_uses_default(self) -> None:
        """Deprecation without reason should use default message."""
        definition = _make_active_definition()
        definition.deprecate(deprecated_by="admin", deprecation_reason=None)
        last = definition.state.state_history[-1]
        assert last["reason"] == "Definition deprecated"

    def test_sync_requested_records_transition(self) -> None:
        """Requesting sync on ACTIVE definition should record → pending_sync."""
        definition = _make_active_definition()
        initial_count = len(definition.state.state_history)
        definition.request_sync()
        assert len(definition.state.state_history) == initial_count + 1
        last = definition.state.state_history[-1]
        assert last["from_state"] == "active"
        assert last["to_state"] == "pending_sync"
        assert last["reason"] == "Sync requested"

    def test_sync_requested_no_transition_if_already_pending(self) -> None:
        """Requesting sync on PENDING_SYNC definition should NOT add transition."""
        definition = _make_definition()  # Already PENDING_SYNC
        initial_count = len(definition.state.state_history)
        definition.request_sync()
        # Status didn't change (PENDING_SYNC → PENDING_SYNC), so no transition
        assert len(definition.state.state_history) == initial_count

    def test_state_history_stores_dicts(self) -> None:
        """Each entry in state_history should be a plain dict."""
        definition = _make_definition()
        entry = definition.state.state_history[0]
        assert isinstance(entry, dict)

    def test_state_history_dict_has_required_keys(self) -> None:
        """Each dict must have from_state, to_state, transitioned_at, triggered_by."""
        definition = _make_definition()
        entry = definition.state.state_history[0]
        assert "from_state" in entry
        assert "to_state" in entry
        assert "transitioned_at" in entry
        assert "triggered_by" in entry

    def test_state_history_accumulates(self) -> None:
        """Multiple transitions should accumulate in state_history list."""
        definition = _make_definition()
        assert len(definition.state.state_history) == 1  # Created
        definition.record_content_sync(lab_yaml_hash="h1", sync_status="success")
        assert len(definition.state.state_history) == 2  # + Active
        definition.deprecate(deprecated_by="admin", deprecation_reason="EOL")
        assert len(definition.state.state_history) == 3  # + Deprecated

    def test_updated_at_tracks_transitions(self) -> None:
        """updated_at should be updated on each transition."""
        state = LabletDefinitionState()
        old_updated = state.updated_at
        state._record_transition(
            from_state=None,
            to_state="pending_sync",
            triggered_by="system",
        )
        assert state.updated_at >= old_updated

    def test_version_created_records_initial_transition(self) -> None:
        """Creating a version should add transition from None → pending_sync."""
        definition = _make_version()
        assert len(definition.state.state_history) >= 1
        entry = definition.state.state_history[0]
        assert entry["from_state"] is None
        assert entry["to_state"] == "pending_sync"
        assert entry["triggered_by"] == "version-author"
        assert entry["reason"] == "New version created"


# =============================================================================
# I.3 — Conditional Transitions (Non-Status-Changing Events)
# =============================================================================


class TestConditionalTransitions:
    """Verify no spurious transitions on non-status-changing events."""

    def test_warm_pool_update_no_transition(self) -> None:
        """WarmPoolUpdated should NOT add to state_history."""
        definition = _make_active_definition()
        initial_count = len(definition.state.state_history)
        definition.update_warm_pool_depth(5, updated_by="admin")
        assert len(definition.state.state_history) == initial_count

    def test_artifact_sync_no_transition(self) -> None:
        """ArtifactSynced should NOT add to state_history."""
        definition = _make_active_definition()
        initial_count = len(definition.state.state_history)
        definition.record_artifact_sync(
            lab_yaml_hash="new-hash",
            sync_status="success",
        )
        assert len(definition.state.state_history) == initial_count

    def test_generic_update_no_transition(self) -> None:
        """Updated event should NOT add to state_history."""
        definition = _make_active_definition()
        initial_count = len(definition.state.state_history)
        definition.update(
            changes={"max_duration_minutes": 120},
            updated_by="admin",
        )
        assert len(definition.state.state_history) == initial_count

    def test_failed_content_sync_no_transition(self) -> None:
        """Failed content sync should NOT add to state_history."""
        definition = _make_definition()  # PENDING_SYNC
        initial_count = len(definition.state.state_history)
        definition.record_content_sync(
            lab_yaml_hash="hash",
            sync_status="failed",
            error_message="Download failed",
        )
        # sync_status != "success", so no status change, no transition
        assert len(definition.state.state_history) == initial_count

    def test_content_sync_on_active_no_transition(self) -> None:
        """Content sync on already-ACTIVE definition should NOT add transition."""
        definition = _make_active_definition()
        initial_count = len(definition.state.state_history)
        # Sync again with success — but status is already ACTIVE, condition fails
        definition.record_content_sync(
            lab_yaml_hash="updated-hash",
            sync_status="success",
        )
        assert len(definition.state.state_history) == initial_count


# =============================================================================
# I.4 — Status Shadowing Tests
# =============================================================================


class TestStatusShadowing:
    """Verify LabletDefinitionStatus enum shadows ResourceState.status correctly."""

    def test_status_is_lablet_definition_status_enum(self) -> None:
        """After creation, status should be LabletDefinitionStatus instance."""
        definition = _make_definition()
        assert isinstance(definition.state.status, LabletDefinitionStatus)

    def test_status_is_str_comparable(self) -> None:
        """Status should be comparable to plain strings (CaseInsensitiveStrEnum)."""
        definition = _make_definition()
        assert definition.state.status == "pending_sync"
        assert definition.state.status == LabletDefinitionStatus.PENDING_SYNC

    def test_status_transitions_preserve_enum_type(self) -> None:
        """Status after transitions should still be LabletDefinitionStatus."""
        definition = _make_active_definition()
        assert isinstance(definition.state.status, LabletDefinitionStatus)
        assert definition.state.status == LabletDefinitionStatus.ACTIVE

    def test_default_init_status_is_active_enum(self) -> None:
        """LabletDefinitionState __init__ sets status to ACTIVE (pre-event default)."""
        state = LabletDefinitionState()
        assert isinstance(state.status, LabletDefinitionStatus)
        assert state.status == LabletDefinitionStatus.ACTIVE


# =============================================================================
# I.5 — Owner Mapping Tests
# =============================================================================


class TestOwnerMapping:
    """Verify created_by → owner_id mapping."""

    def test_owner_id_set_on_create(self) -> None:
        """owner_id should equal created_by after creation."""
        definition = _make_definition()
        assert definition.state.owner_id == "test-user"

    def test_created_by_still_available(self) -> None:
        """created_by field should still be populated (backward compat)."""
        definition = _make_definition()
        assert definition.state.created_by == "test-user"

    def test_owner_id_equals_created_by(self) -> None:
        """owner_id and created_by should be the same value."""
        definition = _make_definition()
        assert definition.state.owner_id == definition.state.created_by

    def test_version_create_sets_owner_id(self) -> None:
        """create_version sets owner_id from created_by."""
        definition = _make_version()
        assert definition.state.owner_id == "version-author"
        assert definition.state.created_by == "version-author"


# =============================================================================
# I.6 — StateTransition Import Consolidation Tests
# =============================================================================


class TestStateTransitionConsolidation:
    """Tests for I.6: StateTransition from lcm_core is used."""

    def test_state_transition_import_is_lcm_core(self) -> None:
        """The StateTransition used in lablet_definition.py is from lcm_core."""
        import domain.entities.lablet_definition as module

        source = module.__file__
        assert source is not None
        with open(source) as f:
            content = f.read()
        assert "from lcm_core.domain.value_objects.state_transition import StateTransition" in content

    def test_state_transition_has_str_based_fields(self) -> None:
        """lcm_core StateTransition uses str for from_state/to_state."""
        transition = StateTransition(
            from_state="pending_sync",
            to_state="active",
            transitioned_at=datetime.now(timezone.utc),
            triggered_by="system",
        )
        assert isinstance(transition.from_state, str)
        assert isinstance(transition.to_state, str)

    def test_state_transition_round_trip(self) -> None:
        """StateTransition.to_dict() and from_dict() should round-trip correctly."""
        now = datetime.now(timezone.utc)
        original = StateTransition(
            from_state="pending_sync",
            to_state="active",
            transitioned_at=now,
            triggered_by="system",
            reason="Content sync completed",
            metadata={"definition_id": "def-001"},
        )
        d = original.to_dict()
        restored = StateTransition.from_dict(d)
        assert restored.from_state == original.from_state
        assert restored.to_state == original.to_state
        assert restored.triggered_by == original.triggered_by
        assert restored.reason == original.reason
        assert restored.metadata == original.metadata

    def test_from_state_is_string_not_enum(self) -> None:
        """from_state in stored dict is a plain string, not an enum."""
        definition = _make_active_definition()
        # Last transition is PENDING_SYNC → ACTIVE
        entry = definition.state.state_history[-1]
        assert isinstance(entry["from_state"], str)
        assert entry["from_state"] == "pending_sync"

    def test_to_state_is_string_not_enum(self) -> None:
        """to_state in stored dict is a plain string, not an enum."""
        definition = _make_definition()
        entry = definition.state.state_history[0]
        assert isinstance(entry["to_state"], str)
