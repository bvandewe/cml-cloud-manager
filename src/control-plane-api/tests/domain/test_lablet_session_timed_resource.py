"""Tests for LabletSession TimedResource migration (ADR-036 Batch F).

Validates:
- F.1: Base class inheritance (TimedResourceState → LabletSessionState)
- F.2: Timeslot VO migration (timeslot_start/end → Timeslot)
- F.3: StateTransition consolidation (lcm_core version, dict storage)
- F.4: LABLET_SESSION_LIFECYCLE constant
- F.5: Lifecycle wiring (Created event → lifecycle + Timeslot)
- F.6: _record_transition reconciliation (dict storage, enum→str)
"""

from datetime import datetime, timedelta, timezone

from lcm_core.domain.entities.resource import ResourceState
from lcm_core.domain.entities.timed_resource import TimedResourceState
from lcm_core.domain.value_objects.managed_lifecycle import ManagedLifecycle
from lcm_core.domain.value_objects.state_transition import StateTransition
from lcm_core.domain.value_objects.timeslot import Timeslot

from domain.entities.lablet_session import LabletSession, LabletSessionState
from domain.enums import LABLET_SESSION_VALID_TRANSITIONS, LabletSessionStatus
from domain.lifecycles import LABLET_SESSION_LIFECYCLE

# =============================================================================
# Helpers
# =============================================================================

NOW = datetime.now(timezone.utc)
FUTURE_START = NOW + timedelta(hours=1)
FUTURE_END = NOW + timedelta(hours=2)

DEFAULT_PORTS = {"serial_1": 5041, "vnc_1": 5044}


def _make_pending() -> LabletSession:
    """Create a fresh LabletSession in PENDING state."""
    return LabletSession.create(
        definition_id="def-001",
        definition_name="Test Lablet",
        definition_version="1.0",
        owner_id="user-42",
        timeslot_start=FUTURE_START,
        timeslot_end=FUTURE_END,
        reservation_id="rsv-001",
    )


def _make_running() -> LabletSession:
    """Create a LabletSession in RUNNING state."""
    session = _make_pending()
    session.schedule("worker-01", DEFAULT_PORTS, "lr-001", "scheduler")
    session.start_instantiation()
    session.mark_ready(user_session_id="us-001", cml_lab_id="cml-lab-99")
    session.mark_running()
    return session


def _make_stopped() -> LabletSession:
    """Create a LabletSession in STOPPED state."""
    session = _make_running()
    session.start_stopping(reason="Done")
    session.mark_stopped()
    return session


# =============================================================================
# F.1 — Base Class Inheritance Tests
# =============================================================================


class TestTimedResourceInheritance:
    """Tests for F.1: LabletSessionState inherits from TimedResourceState."""

    def test_inherits_from_timed_resource_state(self) -> None:
        """LabletSessionState must extend TimedResourceState."""
        state = LabletSessionState()
        assert isinstance(state, TimedResourceState)

    def test_inherits_from_resource_state(self) -> None:
        """LabletSessionState must also extend ResourceState (Layer 1)."""
        state = LabletSessionState()
        assert isinstance(state, ResourceState)

    def test_resource_type_is_lablet_session(self) -> None:
        """resource_type must be set to 'lablet_session'."""
        state = LabletSessionState()
        assert state.resource_type == "lablet_session"

    def test_has_timeslot_field(self) -> None:
        """TimedResourceState provides timeslot (dict | None)."""
        state = LabletSessionState()
        assert hasattr(state, "timeslot")
        assert state.timeslot is None  # Default before event applied

    def test_has_lifecycle_field(self) -> None:
        """TimedResourceState provides lifecycle (dict | None)."""
        state = LabletSessionState()
        assert hasattr(state, "lifecycle")
        assert state.lifecycle is None  # Default before event applied

    def test_started_at_inherited(self) -> None:
        """started_at is inherited from TimedResourceState (Layer 2)."""
        state = LabletSessionState()
        assert state.started_at is None

    def test_ended_at_inherited(self) -> None:
        """ended_at is inherited from TimedResourceState (Layer 2)."""
        state = LabletSessionState()
        assert state.ended_at is None

    def test_duration_seconds_inherited(self) -> None:
        """duration_seconds is inherited from TimedResourceState (Layer 2)."""
        state = LabletSessionState()
        assert state.duration_seconds is None

    def test_terminated_at_inherited(self) -> None:
        """terminated_at is inherited from TimedResourceState (Layer 2)."""
        state = LabletSessionState()
        assert state.terminated_at is None

    def test_created_at_initialized(self) -> None:
        """created_at is set to current time in __init__."""
        state = LabletSessionState()
        assert isinstance(state.created_at, datetime)

    def test_updated_at_initialized(self) -> None:
        """updated_at is set to current time in __init__ (CMLWorker pattern)."""
        state = LabletSessionState()
        assert isinstance(state.updated_at, datetime)

    def test_pipeline_progress_inherited(self) -> None:
        """pipeline_progress is inherited from ResourceState (Layer 1)."""
        state = LabletSessionState()
        assert state.pipeline_progress is None


# =============================================================================
# F.2 — Timeslot VO Migration Tests
# =============================================================================


class TestTimeslotVO:
    """Tests for F.2: Timeslot VO replaces timeslot_start/timeslot_end fields."""

    def test_timeslot_set_on_creation(self) -> None:
        """Created event sets Timeslot VO via set_timeslot()."""
        session = _make_pending()
        ts = session.state.get_timeslot()
        assert ts is not None
        assert isinstance(ts, Timeslot)

    def test_timeslot_start_property(self) -> None:
        """Backward-compatible timeslot_start property reads from Timeslot VO."""
        session = _make_pending()
        assert session.state.timeslot_start == FUTURE_START

    def test_timeslot_end_property(self) -> None:
        """Backward-compatible timeslot_end property reads from Timeslot VO."""
        session = _make_pending()
        assert session.state.timeslot_end == FUTURE_END

    def test_timeslot_extended_updates_vo(self) -> None:
        """TimeslotExtended event updates the Timeslot VO."""
        session = _make_running()
        new_end = FUTURE_END + timedelta(hours=1)
        session.extend_timeslot(new_end=new_end, extended_by="proctor")

        ts = session.state.get_timeslot()
        assert ts is not None
        assert ts.end == new_end
        # Backward-compat property
        assert session.state.timeslot_end == new_end

    def test_timeslot_get_returns_vo_with_defaults(self) -> None:
        """Timeslot VO has default lead_time and teardown_buffer."""
        session = _make_pending()
        ts = session.state.get_timeslot()
        assert ts is not None
        assert ts.lead_time == timedelta(minutes=15)
        assert ts.teardown_buffer == timedelta(minutes=10)

    def test_duration_minutes_from_timeslot_vo(self) -> None:
        """duration_minutes computed from Timeslot VO duration property."""
        session = _make_pending()
        # FUTURE_END - FUTURE_START = 1 hour = 60 minutes
        assert session.duration_minutes == 60

    def test_timeslot_stored_as_dict(self) -> None:
        """Timeslot is stored as dict for Neuroglia serialization."""
        session = _make_pending()
        raw = session.state.timeslot
        assert isinstance(raw, dict)
        assert "start" in raw
        assert "end" in raw
        assert "lead_time_seconds" in raw
        assert "teardown_buffer_seconds" in raw

    def test_timeslot_before_creation_returns_defaults(self) -> None:
        """State timeslot_start/end properties return created_at before event."""
        state = LabletSessionState()
        # Before any event, timeslot is None, so properties return created_at
        assert state.timeslot_start == state.created_at
        assert state.timeslot_end == state.created_at

    def test_legacy_setter_stores_value_for_fallback(self) -> None:
        """Legacy setter stores value in __dict__ for get_timeslot fallback."""
        state = LabletSessionState()
        ts_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        ts_end = datetime(2025, 1, 1, 2, tzinfo=timezone.utc)
        state.timeslot_start = ts_start
        state.timeslot_end = ts_end
        # get_timeslot should construct from legacy values
        ts = state.get_timeslot()
        assert ts is not None
        assert ts.start == ts_start
        assert ts.end == ts_end


# =============================================================================
# F.4 — Lifecycle Constant Tests
# =============================================================================


class TestLifecycleConstant:
    """Tests for F.4: LABLET_SESSION_LIFECYCLE definition."""

    def test_lifecycle_exists(self) -> None:
        """LABLET_SESSION_LIFECYCLE is defined."""
        assert LABLET_SESSION_LIFECYCLE is not None
        assert isinstance(LABLET_SESSION_LIFECYCLE, ManagedLifecycle)

    def test_lifecycle_phase_count(self) -> None:
        """LabletSession lifecycle has 10 phases."""
        assert len(LABLET_SESSION_LIFECYCLE.phases) == 10

    def test_lifecycle_phase_names(self) -> None:
        """All 10 phase names are correct and in order."""
        expected = [
            "schedule",
            "instantiate",
            "activate",
            "monitor",
            "collect_evidence",
            "compute_grading",
            "teardown",
            "archive",
            "expire",
            "terminate",
        ]
        assert LABLET_SESSION_LIFECYCLE.phase_names() == expected

    def test_lifecycle_required_phases(self) -> None:
        """Required phases are schedule, instantiate, activate, monitor, teardown, expire, terminate."""
        required = [p.name for p in LABLET_SESSION_LIFECYCLE.get_active_phases()]
        assert "schedule" in required
        assert "instantiate" in required
        assert "activate" in required
        assert "monitor" in required
        assert "teardown" in required
        assert "expire" in required
        assert "terminate" in required

    def test_lifecycle_optional_phases(self) -> None:
        """Optional phases are collect_evidence, compute_grading, archive."""
        optional = [p.name for p in LABLET_SESSION_LIFECYCLE.phases if not p.is_required]
        assert "collect_evidence" in optional
        assert "compute_grading" in optional
        assert "archive" in optional

    def test_lifecycle_all_phases_use_pipeline_engine(self) -> None:
        """All lifecycle phases use the 'pipeline' engine."""
        for phase in LABLET_SESSION_LIFECYCLE.phases:
            assert phase.engine == "pipeline", f"{phase.name} uses {phase.engine}"

    def test_lifecycle_trigger_status_mapping(self) -> None:
        """Each phase's trigger_on_status maps to a valid LabletSessionStatus."""
        for phase in LABLET_SESSION_LIFECYCLE.phases:
            assert phase.trigger_on_status is not None, f"{phase.name} has no trigger"
            status = LabletSessionStatus(phase.trigger_on_status)
            assert status in LABLET_SESSION_VALID_TRANSITIONS, f"{phase.name} trigger '{phase.trigger_on_status}' is not a valid status"

    def test_lifecycle_serialization_roundtrip(self) -> None:
        """Lifecycle serializes to dict and back correctly."""
        as_dict = LABLET_SESSION_LIFECYCLE.to_dict()
        restored = ManagedLifecycle.from_dict(as_dict)
        assert len(restored.phases) == len(LABLET_SESSION_LIFECYCLE.phases)
        assert restored.phase_names() == LABLET_SESSION_LIFECYCLE.phase_names()


# =============================================================================
# F.5 — Lifecycle Wiring Tests
# =============================================================================


class TestLifecycleWiring:
    """Tests for F.5: Lifecycle assignment in event handlers."""

    def test_lifecycle_set_on_creation(self) -> None:
        """Created event wires lifecycle into state."""
        session = _make_pending()
        lifecycle = session.state.get_lifecycle()
        assert lifecycle is not None
        assert isinstance(lifecycle, ManagedLifecycle)

    def test_lifecycle_current_phase_on_creation(self) -> None:
        """Created event sets current_phase to 'schedule'."""
        session = _make_pending()
        lifecycle = session.state.get_lifecycle()
        assert lifecycle is not None
        assert lifecycle.current_phase == "schedule"

    def test_lifecycle_phases_match_constant(self) -> None:
        """Lifecycle phases match LABLET_SESSION_LIFECYCLE."""
        session = _make_pending()
        lifecycle = session.state.get_lifecycle()
        assert lifecycle is not None
        assert lifecycle.phase_names() == LABLET_SESSION_LIFECYCLE.phase_names()

    def test_started_at_set_on_running(self) -> None:
        """started_at is set when session transitions to RUNNING."""
        session = _make_running()
        assert session.state.started_at is not None
        assert isinstance(session.state.started_at, datetime)

    def test_ended_at_set_on_stopped(self) -> None:
        """ended_at is set when session transitions to STOPPED."""
        session = _make_stopped()
        assert session.state.ended_at is not None

    def test_compute_duration_on_stopped(self) -> None:
        """duration_seconds computed via _compute_duration() on STOPPED."""
        session = _make_stopped()
        assert session.state.duration_seconds is not None
        assert session.state.duration_seconds >= 0.0

    def test_compute_duration_on_terminated(self) -> None:
        """duration_seconds computed via _compute_duration() on TERMINATED."""
        session = _make_running()
        session.terminate(terminated_by="admin", reason="Force kill")
        assert session.state.ended_at is not None
        assert session.state.duration_seconds is not None
        assert session.state.duration_seconds >= 0.0

    def test_compute_duration_not_set_when_not_started(self) -> None:
        """duration_seconds is None when terminated before RUNNING."""
        session = _make_pending()
        session.terminate(terminated_by="admin", reason="Cancel")
        # started_at was never set (never reached RUNNING)
        assert session.state.started_at is None
        assert session.state.duration_seconds is None


# =============================================================================
# F.6 — _record_transition Reconciliation Tests
# =============================================================================


class TestRecordTransitionReconciliation:
    """Tests for F.6: _record_transition stores dicts and handles enum→str."""

    def test_state_history_stores_dicts(self) -> None:
        """State history entries are dicts, not StateTransition objects."""
        session = _make_pending()
        assert len(session.state.state_history) == 1
        entry = session.state.state_history[0]
        assert isinstance(entry, dict)
        assert "from_state" in entry
        assert "to_state" in entry
        assert "transitioned_at" in entry
        assert "triggered_by" in entry

    def test_record_transition_updates_updated_at(self) -> None:
        """_record_transition updates self.updated_at."""
        state = LabletSessionState()
        old_updated = state.updated_at
        state._record_transition(
            from_state=None,
            to_state="pending",
            triggered_by="system",
        )
        assert state.updated_at >= old_updated

    def test_record_transition_from_state_is_string(self) -> None:
        """from_state in stored dict is a plain string (not enum)."""
        session = _make_pending()
        session.schedule("w-01", {"p": 1}, "lr-01", "sched")
        entry = session.state.state_history[-1]
        assert isinstance(entry["from_state"], str)
        assert entry["from_state"] == "pending"

    def test_record_transition_to_state_is_string(self) -> None:
        """to_state in stored dict is a plain string (not enum)."""
        session = _make_pending()
        entry = session.state.state_history[0]
        assert isinstance(entry["to_state"], str)
        assert entry["to_state"] == "pending"

    def test_last_transition_returns_state_transition_object(self) -> None:
        """last_transition reconstructs a StateTransition from dict."""
        session = _make_pending()
        last = session.last_transition
        assert last is not None
        assert isinstance(last, StateTransition)
        assert last.to_state == "pending"
        assert last.triggered_by == "system"

    def test_last_transition_from_state_compatible_with_enum(self) -> None:
        """Reconstructed StateTransition from_state compares equal with StrEnum."""
        session = _make_pending()
        session.schedule("w-01", {"p": 1}, "lr-01", "sched")
        last = session.last_transition
        assert last is not None
        # StrEnum comparison: "pending" == LabletSessionStatus.PENDING
        assert last.from_state == LabletSessionStatus.PENDING
        assert last.to_state == LabletSessionStatus.SCHEDULED

    def test_state_transition_dict_roundtrip(self) -> None:
        """StateTransition → to_dict() → from_dict() preserves data."""
        now = datetime.now(timezone.utc)
        original = StateTransition(
            from_state="pending",
            to_state="scheduled",
            transitioned_at=now,
            triggered_by="scheduler",
            reason="Assigned to worker",
            metadata={"worker_id": "w-01"},
        )
        d = original.to_dict()
        restored = StateTransition.from_dict(d)
        assert restored.from_state == original.from_state
        assert restored.to_state == original.to_state
        assert restored.triggered_by == original.triggered_by
        assert restored.reason == original.reason
        assert restored.metadata == original.metadata


# =============================================================================
# F.3 — No CPA-local StateTransition imports remain
# =============================================================================


class TestStateTransitionConsolidation:
    """Tests for F.3: Only lcm_core StateTransition is used."""

    def test_state_transition_import_is_lcm_core(self) -> None:
        """The StateTransition used in lablet_session.py is from lcm_core."""
        import domain.entities.lablet_session as module

        # The module should NOT import from domain.value_objects.state_transition
        source = module.__file__
        assert source is not None
        with open(source) as f:
            content = f.read()
        assert "from domain.value_objects.state_transition import" not in content
        assert "from lcm_core.domain.value_objects.state_transition import StateTransition" in content

    def test_state_transition_has_str_based_fields(self) -> None:
        """lcm_core StateTransition uses str for from_state/to_state."""
        transition = StateTransition(
            from_state="pending",
            to_state="scheduled",
            transitioned_at=datetime.now(timezone.utc),
            triggered_by="system",
        )
        assert isinstance(transition.from_state, str)
        assert isinstance(transition.to_state, str)
