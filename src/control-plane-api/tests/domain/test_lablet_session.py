"""Domain tests for LabletSession aggregate.

Phase 7C: Tests state machine transitions, event emission, state recording,
computed properties, and edge cases for the LabletSession aggregate.

Tests follow the same structure as the former test_lablet_instance.py.
"""

from datetime import datetime, timedelta, timezone

import pytest

from domain.entities.lablet_session import InvalidStateTransitionError, LabletSession, LabletSessionState
from domain.enums import LABLET_SESSION_VALID_TRANSITIONS, LabletSessionStatus
from domain.events.lablet_session_events import (
    LabletSessionCreatedDomainEvent,
    LabletSessionPortsReleasedDomainEvent,
    LabletSessionScheduledDomainEvent,
    LabletSessionTerminatedDomainEvent,
    LabletSessionTimeslotExtendedDomainEvent,
)

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


def _make_scheduled() -> LabletSession:
    """Create a LabletSession in SCHEDULED state."""
    session = _make_pending()
    session.schedule(
        worker_id="worker-01",
        allocated_ports=DEFAULT_PORTS,
        lab_record_id="lr-001",
        scheduled_by="scheduler",
    )
    return session


def _make_instantiating() -> LabletSession:
    """Create a LabletSession in INSTANTIATING state."""
    session = _make_scheduled()
    session.start_instantiation()
    return session


def _make_ready() -> LabletSession:
    """Create a LabletSession in READY state."""
    session = _make_instantiating()
    session.mark_ready(user_session_id="us-001", cml_lab_id="cml-lab-99")
    return session


def _make_running() -> LabletSession:
    """Create a LabletSession in RUNNING state."""
    session = _make_ready()
    session.mark_running()
    return session


def _make_collecting() -> LabletSession:
    """Create a LabletSession in COLLECTING state."""
    session = _make_running()
    session.start_collection()
    return session


def _make_grading() -> LabletSession:
    """Create a LabletSession in GRADING state."""
    session = _make_collecting()
    session.start_grading(grading_session_id="gs-001")
    return session


def _make_stopping() -> LabletSession:
    """Create a LabletSession in STOPPING state."""
    session = _make_running()
    session.start_stopping(reason="User finished")
    return session


def _make_stopped() -> LabletSession:
    """Create a LabletSession in STOPPED state."""
    session = _make_stopping()
    session.mark_stopped()
    return session


# =============================================================================
# Tests — Creation
# =============================================================================


class TestLabletSessionCreation:
    """Tests for LabletSession.create() factory method."""

    def test_create_sets_pending_status(self) -> None:
        session = _make_pending()
        assert session.state.status == LabletSessionStatus.PENDING

    def test_create_sets_definition_fields(self) -> None:
        session = _make_pending()
        assert session.state.definition_id == "def-001"
        assert session.state.definition_name == "Test Lablet"
        assert session.state.definition_version == "1.0"

    def test_create_sets_owner_and_reservation(self) -> None:
        session = _make_pending()
        assert session.state.owner_id == "user-42"
        assert session.state.reservation_id == "rsv-001"

    def test_create_sets_timeslot(self) -> None:
        session = _make_pending()
        assert session.state.timeslot_start == FUTURE_START
        assert session.state.timeslot_end == FUTURE_END

    def test_create_initialises_null_fields(self) -> None:
        session = _make_pending()
        assert session.state.worker_id is None
        assert session.state.lab_record_id is None
        assert session.state.cml_lab_id is None
        assert session.state.allocated_ports is None
        assert session.state.started_at is None
        assert session.state.ended_at is None
        assert session.state.duration_seconds is None
        assert session.state.user_session_id is None
        assert session.state.grading_session_id is None
        assert session.state.score_report_id is None
        assert session.state.grade_result is None

    def test_create_records_one_transition(self) -> None:
        session = _make_pending()
        assert session.transition_count == 1
        assert session.last_transition is not None
        assert session.last_transition.to_state == LabletSessionStatus.PENDING

    def test_create_emits_created_event(self) -> None:
        session = _make_pending()
        events = session._pending_events
        assert len(events) == 1
        assert isinstance(events[0], LabletSessionCreatedDomainEvent)

    def test_create_rejects_invalid_timeslot(self) -> None:
        with pytest.raises(ValueError, match="timeslot_end must be after timeslot_start"):
            LabletSession.create(
                definition_id="def-001",
                definition_name="Test",
                definition_version="1.0",
                owner_id="user-42",
                timeslot_start=FUTURE_END,
                timeslot_end=FUTURE_START,
            )

    def test_create_without_reservation(self) -> None:
        session = LabletSession.create(
            definition_id="def-001",
            definition_name="Test",
            definition_version="1.0",
            owner_id="user-42",
            timeslot_start=FUTURE_START,
            timeslot_end=FUTURE_END,
        )
        assert session.state.reservation_id is None


# =============================================================================
# Tests — Happy Path Lifecycle
# =============================================================================


class TestLabletSessionLifecycle:
    """Tests for the standard PENDING → ... → STOPPED lifecycle."""

    def test_schedule_sets_worker_and_ports(self) -> None:
        session = _make_scheduled()
        assert session.state.status == LabletSessionStatus.SCHEDULED
        assert session.state.worker_id == "worker-01"
        assert session.state.allocated_ports == DEFAULT_PORTS

    def test_schedule_sets_lab_record_id(self) -> None:
        session = _make_scheduled()
        assert session.state.lab_record_id == "lr-001"

    def test_schedule_emits_scheduled_event(self) -> None:
        session = _make_scheduled()
        events = [e for e in session._pending_events if isinstance(e, LabletSessionScheduledDomainEvent)]
        assert len(events) == 1
        assert events[0].lab_record_id == "lr-001"

    def test_start_instantiation(self) -> None:
        session = _make_instantiating()
        assert session.state.status == LabletSessionStatus.INSTANTIATING

    def test_mark_ready_sets_user_session_and_cml_lab(self) -> None:
        session = _make_ready()
        assert session.state.status == LabletSessionStatus.READY
        assert session.state.user_session_id == "us-001"
        assert session.state.cml_lab_id == "cml-lab-99"

    def test_mark_running_sets_started_at(self) -> None:
        session = _make_running()
        assert session.state.status == LabletSessionStatus.RUNNING
        assert session.state.started_at is not None

    def test_start_collection(self) -> None:
        session = _make_collecting()
        assert session.state.status == LabletSessionStatus.COLLECTING

    def test_start_grading_sets_grading_session_id(self) -> None:
        session = _make_grading()
        assert session.state.status == LabletSessionStatus.GRADING
        assert session.state.grading_session_id == "gs-001"

    def test_record_score_does_not_change_status(self) -> None:
        session = _make_grading()
        session.record_score(score_report_id="sr-001", grade_result="pass")
        # Status should stay GRADING
        assert session.state.status == LabletSessionStatus.GRADING
        assert session.state.score_report_id == "sr-001"
        assert session.state.grade_result == "pass"

    def test_stopping_from_running(self) -> None:
        session = _make_running()
        session.start_stopping(reason="Done")
        assert session.state.status == LabletSessionStatus.STOPPING

    def test_stopping_from_grading(self) -> None:
        session = _make_grading()
        session.start_stopping(reason="Grading complete")
        assert session.state.status == LabletSessionStatus.STOPPING

    def test_stopped_computes_duration(self) -> None:
        session = _make_stopped()
        assert session.state.status == LabletSessionStatus.STOPPED
        assert session.state.ended_at is not None
        # Duration should be computed (>= 0.0 since times are very close)
        assert session.state.duration_seconds is not None
        assert session.state.duration_seconds >= 0.0

    def test_archive_from_stopped(self) -> None:
        session = _make_stopped()
        session.archive(archived_by="admin")
        assert session.state.status == LabletSessionStatus.ARCHIVED

    def test_full_happy_path_event_count(self) -> None:
        """Verify event count through a full lifecycle."""
        session = _make_pending()
        session.schedule("w-01", {"p": 1}, "lr-01", "sched")
        session.start_instantiation()
        session.mark_ready("us-01", "cml-01")
        session.mark_running()
        session.start_collection()
        session.start_grading("gs-01")
        session.record_score("sr-01", "pass")
        session.start_stopping("Complete")
        session.mark_stopped()
        session.archive("admin")
        # 11 events: created, scheduled, instantiating, ready, running,
        #            collecting, grading, score_recorded, stopping, stopped, archived
        assert len(session._pending_events) == 11


# =============================================================================
# Tests — Termination
# =============================================================================


class TestLabletSessionTermination:
    """Tests for terminate() from various states."""

    @pytest.mark.parametrize(
        "make_fn,expected_from",
        [
            (_make_pending, LabletSessionStatus.PENDING),
            (_make_scheduled, LabletSessionStatus.SCHEDULED),
            (_make_instantiating, LabletSessionStatus.INSTANTIATING),
            (_make_ready, LabletSessionStatus.READY),
            (_make_running, LabletSessionStatus.RUNNING),
            (_make_collecting, LabletSessionStatus.COLLECTING),
            (_make_grading, LabletSessionStatus.GRADING),
            (_make_stopping, LabletSessionStatus.STOPPING),
            (_make_stopped, LabletSessionStatus.STOPPED),
        ],
    )
    def test_terminate_from_valid_states(self, make_fn, expected_from) -> None:
        session = make_fn()
        session.terminate(terminated_by="admin", reason="Force kill")
        assert session.state.status == LabletSessionStatus.TERMINATED
        assert session.state.terminated_at is not None

    def test_terminate_cannot_double_terminate(self) -> None:
        session = _make_running()
        session.terminate(terminated_by="admin")
        with pytest.raises(InvalidStateTransitionError):
            session.terminate(terminated_by="admin")


# =============================================================================
# Tests — Invalid Transitions
# =============================================================================


class TestLabletSessionInvalidTransitions:
    """Tests that invalid transitions raise InvalidStateTransitionError."""

    def test_cannot_schedule_twice(self) -> None:
        session = _make_scheduled()
        with pytest.raises(InvalidStateTransitionError):
            session.schedule("w-02", {"p": 2}, "lr-02", "sched")

    def test_cannot_mark_running_from_pending(self) -> None:
        session = _make_pending()
        with pytest.raises(InvalidStateTransitionError):
            session.mark_running()

    def test_cannot_start_grading_from_running(self) -> None:
        session = _make_running()
        with pytest.raises(InvalidStateTransitionError):
            session.start_grading("gs-001")

    def test_cannot_mark_stopped_from_running(self) -> None:
        session = _make_running()
        with pytest.raises(InvalidStateTransitionError):
            session.mark_stopped()

    def test_cannot_archive_from_running(self) -> None:
        session = _make_running()
        with pytest.raises(InvalidStateTransitionError):
            session.archive(archived_by="admin")


# =============================================================================
# Tests — Port Management
# =============================================================================


class TestLabletSessionPortManagement:
    """Tests for port allocation and release."""

    def test_release_ports_clears_allocated_ports(self) -> None:
        session = _make_scheduled()
        assert session.state.allocated_ports is not None
        session.release_ports()
        assert session.state.allocated_ports is None

    def test_release_ports_emits_event(self) -> None:
        session = _make_scheduled()
        session.release_ports()
        events = [e for e in session._pending_events if isinstance(e, LabletSessionPortsReleasedDomainEvent)]
        assert len(events) == 1
        assert events[0].released_ports == DEFAULT_PORTS

    def test_release_ports_noop_when_no_ports(self) -> None:
        session = _make_pending()
        event_count_before = len(session._pending_events)
        session.release_ports()
        # No new event emitted (no ports to release)
        assert len(session._pending_events) == event_count_before


# =============================================================================
# Tests — Timeslot Extension
# =============================================================================


class TestLabletSessionTimeslotExtension:
    """Tests for timeslot extension."""

    def test_extend_timeslot(self) -> None:
        session = _make_running()
        new_end = FUTURE_END + timedelta(hours=1)
        session.extend_timeslot(new_end=new_end, extended_by="proctor")
        assert session.state.timeslot_end == new_end

    def test_extend_timeslot_emits_event(self) -> None:
        session = _make_running()
        new_end = FUTURE_END + timedelta(hours=1)
        session.extend_timeslot(new_end=new_end, extended_by="proctor")
        events = [e for e in session._pending_events if isinstance(e, LabletSessionTimeslotExtendedDomainEvent)]
        assert len(events) == 1
        assert events[0].new_timeslot_end == new_end

    def test_extend_timeslot_rejects_earlier_end(self) -> None:
        session = _make_running()
        earlier = FUTURE_START  # Before current end
        with pytest.raises(ValueError, match="new_end must be after current timeslot_end"):
            session.extend_timeslot(new_end=earlier, extended_by="proctor")


# =============================================================================
# Tests — Computed Properties
# =============================================================================


class TestLabletSessionProperties:
    """Tests for computed properties."""

    def test_is_terminal_only_when_terminated(self) -> None:
        session = _make_stopped()
        assert not session.is_terminal
        session = _make_running()
        session.terminate(terminated_by="admin")
        assert session.is_terminal

    def test_is_active(self) -> None:
        assert _make_running().is_active
        assert _make_collecting().is_active
        assert _make_grading().is_active
        assert not _make_pending().is_active
        assert not _make_scheduled().is_active
        assert not _make_stopped().is_active

    def test_is_pending_execution(self) -> None:
        assert _make_pending().is_pending_execution
        assert _make_scheduled().is_pending_execution
        assert not _make_running().is_pending_execution

    def test_can_be_terminated(self) -> None:
        # Most states can transition to TERMINATED
        assert _make_pending().can_be_terminated
        assert _make_running().can_be_terminated
        # Already terminated cannot
        session = _make_running()
        session.terminate(terminated_by="admin")
        assert not session.can_be_terminated

    def test_duration_minutes(self) -> None:
        session = _make_pending()
        # FUTURE_END - FUTURE_START = 1 hour = 60 minutes
        assert session.duration_minutes == 60

    def test_has_user_session(self) -> None:
        assert not _make_instantiating().has_user_session
        assert _make_ready().has_user_session

    def test_has_grading_session(self) -> None:
        assert not _make_running().has_grading_session
        assert _make_grading().has_grading_session

    def test_has_score_report(self) -> None:
        session = _make_grading()
        assert not session.has_score_report
        session.record_score("sr-01", "pass")
        assert session.has_score_report

    def test_transition_count_increments(self) -> None:
        session = _make_pending()
        assert session.transition_count == 1
        session.schedule("w-01", {"p": 1}, "lr-01", "sched")
        assert session.transition_count == 2
        session.start_instantiation()
        assert session.transition_count == 3


# =============================================================================
# Tests — State History
# =============================================================================


class TestLabletSessionStateHistory:
    """Tests for state transition history recording."""

    def test_state_history_records_from_and_to(self) -> None:
        session = _make_pending()
        session.schedule("w-01", {"p": 1}, "lr-01", "sched")
        last = session.last_transition
        assert last is not None
        assert last.from_state == LabletSessionStatus.PENDING
        assert last.to_state == LabletSessionStatus.SCHEDULED

    def test_state_history_records_triggered_by(self) -> None:
        session = _make_scheduled()
        # The last transition was schedule → triggered by "scheduler"
        assert session.last_transition is not None
        assert session.last_transition.triggered_by == "scheduler"

    def test_terminate_records_from_state_in_event(self) -> None:
        session = _make_running()
        session.terminate(terminated_by="admin", reason="Emergency")
        events = [e for e in session._pending_events if isinstance(e, LabletSessionTerminatedDomainEvent)]
        assert len(events) == 1
        assert events[0].from_state == LabletSessionStatus.RUNNING.value


# =============================================================================
# Tests — LabletSessionState Initialisation
# =============================================================================


class TestLabletSessionState:
    """Tests for LabletSessionState default initialisation."""

    def test_default_state_initialisation(self) -> None:
        state = LabletSessionState()
        assert state.status == LabletSessionStatus.PENDING
        assert state.state_history == []
        assert state.worker_id is None
        assert state.lab_record_id is None

    def test_valid_transitions_cover_all_statuses(self) -> None:
        """Ensure every LabletSessionStatus appears as a key in transitions."""
        for status in LabletSessionStatus:
            assert status in LABLET_SESSION_VALID_TRANSITIONS, f"{status} missing from transitions"
