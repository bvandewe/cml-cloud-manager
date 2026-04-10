"""Tests for ADR-036 ResourceState and TimedResourceState base classes.

Validates field initialization, inheritance chain, helper methods,
VO accessors, and Neuroglia AggregateState compatibility.
"""

from datetime import UTC, datetime, timedelta

from lcm_core.domain.entities.resource import ResourceState
from lcm_core.domain.entities.timed_resource import TimedResourceState
from lcm_core.domain.value_objects.managed_lifecycle import LifecyclePhase, ManagedLifecycle
from lcm_core.domain.value_objects.state_transition import StateTransition
from lcm_core.domain.value_objects.timeslot import Timeslot
from neuroglia.data.abstractions import AggregateState

# =============================================================================
# ResourceState
# =============================================================================


class TestResourceStateInit:
    """Field initialization and defaults for ResourceState."""

    def test_extends_aggregate_state(self):
        """ResourceState is a subclass of AggregateState."""
        assert issubclass(ResourceState, AggregateState)

    def test_default_field_values(self):
        """All fields initialized with safe defaults."""
        state = ResourceState()
        assert state.id == ""
        assert state.resource_type == ""
        assert state.status == ""
        assert state.desired_status is None
        assert state.owner_id == ""
        assert state.state_history == []
        assert state.pipeline_progress is None
        assert isinstance(state.created_at, datetime)
        assert isinstance(state.updated_at, datetime)

    def test_created_at_is_utc(self):
        """created_at is set to UTC on creation."""
        state = ResourceState()
        assert state.created_at.tzinfo is not None

    def test_state_history_is_mutable_list(self):
        """state_history is a mutable list (not tuple — aggregates append)."""
        state = ResourceState()
        assert isinstance(state.state_history, list)
        state.state_history.append("test")
        assert len(state.state_history) == 1

    def test_independent_state_history_per_instance(self):
        """Each instance gets its own state_history list (no shared mutable default)."""
        state1 = ResourceState()
        state2 = ResourceState()
        state1.state_history.append("only-in-state1")
        assert len(state2.state_history) == 0


class TestResourceStateRecordTransition:
    """_record_transition() helper method."""

    def test_record_transition_appends(self):
        """_record_transition appends a StateTransition to state_history."""
        state = ResourceState()
        state._record_transition(
            from_state="pending",
            to_state="running",
            triggered_by="test",
            reason="Test transition",
        )
        assert len(state.state_history) == 1
        t = state.state_history[0]
        assert isinstance(t, StateTransition)
        assert t.from_state == "pending"
        assert t.to_state == "running"
        assert t.triggered_by == "test"
        assert t.reason == "Test transition"

    def test_record_transition_updates_updated_at(self):
        """_record_transition updates the updated_at timestamp."""
        state = ResourceState()
        original = state.updated_at
        state._record_transition(from_state=None, to_state="pending")
        assert state.updated_at >= original

    def test_record_transition_none_from_state(self):
        """First transition has from_state=None."""
        state = ResourceState()
        state._record_transition(from_state=None, to_state="pending")
        assert state.state_history[0].from_state is None

    def test_record_transition_with_metadata(self):
        """Metadata dict preserved in transition."""
        state = ResourceState()
        metadata = {"worker_id": "w-123"}
        state._record_transition(
            from_state="pending",
            to_state="scheduled",
            metadata=metadata,
        )
        assert state.state_history[0].metadata == metadata

    def test_multiple_transitions_build_history(self):
        """Multiple transitions create ordered history."""
        state = ResourceState()
        state._record_transition(from_state=None, to_state="pending")
        state._record_transition(from_state="pending", to_state="scheduled")
        state._record_transition(from_state="scheduled", to_state="running")
        assert len(state.state_history) == 3
        assert state.state_history[0].to_state == "pending"
        assert state.state_history[1].to_state == "scheduled"
        assert state.state_history[2].to_state == "running"


class TestResourceStateTypeAnnotations:
    """Type annotations for Neuroglia serialization discovery."""

    def test_has_required_annotations(self):
        """All expected fields have class-level type annotations."""
        hints = ResourceState.__annotations__
        assert "id" in hints
        assert "resource_type" in hints
        assert "status" in hints
        assert "desired_status" in hints
        assert "owner_id" in hints
        assert "state_history" in hints
        assert "pipeline_progress" in hints
        assert "created_at" in hints
        assert "updated_at" in hints


# =============================================================================
# TimedResourceState
# =============================================================================


class TestTimedResourceStateInit:
    """Field initialization and defaults for TimedResourceState."""

    def test_extends_resource_state(self):
        """TimedResourceState is a subclass of ResourceState."""
        assert issubclass(TimedResourceState, ResourceState)

    def test_extends_aggregate_state(self):
        """TimedResourceState is transitively a subclass of AggregateState."""
        assert issubclass(TimedResourceState, AggregateState)

    def test_inherits_resource_state_defaults(self):
        """Inherits all ResourceState field defaults."""
        state = TimedResourceState()
        assert state.id == ""
        assert state.resource_type == ""
        assert state.status == ""
        assert state.desired_status is None
        assert state.owner_id == ""
        assert state.state_history == []
        assert state.pipeline_progress is None

    def test_timed_resource_specific_defaults(self):
        """TimedResourceState-specific fields default correctly."""
        state = TimedResourceState()
        assert state.timeslot is None
        assert state.lifecycle is None
        assert state.started_at is None
        assert state.ended_at is None
        assert state.duration_seconds is None
        assert state.terminated_at is None

    def test_has_required_annotations(self):
        """All expected fields have class-level type annotations."""
        hints = TimedResourceState.__annotations__
        assert "timeslot" in hints
        assert "lifecycle" in hints
        assert "started_at" in hints
        assert "ended_at" in hints
        assert "duration_seconds" in hints
        assert "terminated_at" in hints


class TestTimedResourceStateTimeslotAccessors:
    """get_timeslot() / set_timeslot() VO accessor methods."""

    def test_get_timeslot_none(self):
        """Returns None when no timeslot set."""
        state = TimedResourceState()
        assert state.get_timeslot() is None

    def test_set_and_get_timeslot(self):
        """Set a Timeslot VO, get it back."""
        state = TimedResourceState()
        ts = Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
            lead_time=timedelta(minutes=20),
            teardown_buffer=timedelta(minutes=5),
        )
        state.set_timeslot(ts)
        restored = state.get_timeslot()
        assert restored == ts

    def test_set_timeslot_stores_dict(self):
        """set_timeslot stores as dict (Neuroglia-compatible)."""
        state = TimedResourceState()
        ts = Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
        )
        state.set_timeslot(ts)
        assert isinstance(state.timeslot, dict)
        assert "start" in state.timeslot
        assert "end" in state.timeslot

    def test_set_timeslot_updates_updated_at(self):
        """set_timeslot updates the updated_at timestamp."""
        state = TimedResourceState()
        original = state.updated_at
        ts = Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
        )
        state.set_timeslot(ts)
        assert state.updated_at >= original


class TestTimedResourceStateLifecycleAccessors:
    """get_lifecycle() / set_lifecycle() VO accessor methods."""

    def test_get_lifecycle_none(self):
        """Returns None when no lifecycle set."""
        state = TimedResourceState()
        assert state.get_lifecycle() is None

    def test_set_and_get_lifecycle(self):
        """Set a ManagedLifecycle VO, get it back."""
        state = TimedResourceState()
        lifecycle = ManagedLifecycle(
            phases=(
                LifecyclePhase(name="provision", trigger_on_status="provisioning"),
                LifecyclePhase(name="teardown", trigger_on_status="stopping"),
            ),
            current_phase="provision",
        )
        state.set_lifecycle(lifecycle)
        restored = state.get_lifecycle()
        assert restored == lifecycle

    def test_set_lifecycle_stores_dict(self):
        """set_lifecycle stores as dict (Neuroglia-compatible)."""
        state = TimedResourceState()
        lifecycle = ManagedLifecycle(
            phases=(LifecyclePhase(name="provision"),),
        )
        state.set_lifecycle(lifecycle)
        assert isinstance(state.lifecycle, dict)
        assert "phases" in state.lifecycle

    def test_set_lifecycle_updates_updated_at(self):
        """set_lifecycle updates the updated_at timestamp."""
        state = TimedResourceState()
        original = state.updated_at
        lifecycle = ManagedLifecycle(phases=())
        state.set_lifecycle(lifecycle)
        assert state.updated_at >= original


class TestTimedResourceStateComputeDuration:
    """_compute_duration() helper method."""

    def test_compute_duration_both_set(self):
        """Computes duration from started_at and ended_at."""
        state = TimedResourceState()
        state.started_at = datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC)
        state.ended_at = datetime(2026, 3, 9, 12, 30, 0, tzinfo=UTC)
        state._compute_duration()
        assert state.duration_seconds == 9000.0  # 2.5 hours in seconds

    def test_compute_duration_not_ended(self):
        """Does not compute if ended_at is None."""
        state = TimedResourceState()
        state.started_at = datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC)
        state._compute_duration()
        assert state.duration_seconds is None

    def test_compute_duration_not_started(self):
        """Does not compute if started_at is None."""
        state = TimedResourceState()
        state.ended_at = datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC)
        state._compute_duration()
        assert state.duration_seconds is None

    def test_compute_duration_naive_started_aware_ended(self):
        """Handles naive started_at (MongoDB rehydration) with aware ended_at."""
        state = TimedResourceState()
        # MongoDB returns naive datetimes (UTC without tzinfo)
        state.started_at = datetime(2026, 3, 9, 10, 0, 0)
        # New events use tz-aware timestamps
        state.ended_at = datetime(2026, 3, 9, 12, 30, 0, tzinfo=UTC)
        state._compute_duration()
        assert state.duration_seconds == 9000.0

    def test_compute_duration_both_naive(self):
        """Handles both timestamps naive (full MongoDB rehydration)."""
        state = TimedResourceState()
        state.started_at = datetime(2026, 3, 9, 10, 0, 0)
        state.ended_at = datetime(2026, 3, 9, 12, 30, 0)
        state._compute_duration()
        assert state.duration_seconds == 9000.0


class TestTimedResourceStateInheritedMethods:
    """Inherited ResourceState methods work on TimedResourceState."""

    def test_record_transition(self):
        """_record_transition works on TimedResourceState."""
        state = TimedResourceState()
        state._record_transition(from_state=None, to_state="provisioning")
        assert len(state.state_history) == 1
        assert state.state_history[0].to_state == "provisioning"

    def test_full_lifecycle_simulation(self):
        """Simulate a complete resource lifecycle."""
        state = TimedResourceState()
        state.resource_type = "lablet-session"
        state.owner_id = "user-42"

        # Set timeslot
        ts = Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
        )
        state.set_timeslot(ts)

        # Set lifecycle
        lifecycle = ManagedLifecycle(
            phases=(
                LifecyclePhase(name="instantiate", trigger_on_status="instantiating"),
                LifecyclePhase(name="teardown", trigger_on_status="stopping"),
            ),
        )
        state.set_lifecycle(lifecycle)

        # Record transitions
        state._record_transition(from_state=None, to_state="pending")
        state.status = "pending"

        state._record_transition(from_state="pending", to_state="scheduled")
        state.status = "scheduled"

        state._record_transition(from_state="scheduled", to_state="running")
        state.status = "running"
        state.started_at = datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC)

        state._record_transition(from_state="running", to_state="completed")
        state.status = "completed"
        state.ended_at = datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC)
        state._compute_duration()

        # Verify final state
        assert state.resource_type == "lablet-session"
        assert state.status == "completed"
        assert len(state.state_history) == 4
        assert state.duration_seconds == 7200.0
        assert state.get_timeslot() == ts
        assert state.get_lifecycle() == lifecycle


class TestTimedResourceStateImports:
    """Verify imports from lcm_core.domain.entities work."""

    def test_import_from_entities(self):
        """Can import from the entities package."""
        from lcm_core.domain.entities import ResourceState as RS
        from lcm_core.domain.entities import TimedResourceState as TRS

        assert RS is ResourceState
        assert TRS is TimedResourceState
