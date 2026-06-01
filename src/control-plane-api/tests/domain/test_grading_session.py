"""Domain tests for GradingSession entity.

Phase 7C: Tests lifecycle transitions, validation, computed properties,
and factory for the GradingSession child entity (ADR-021 §2).
"""

import pytest
from lcm_core.domain.enums import GradingSessionStatus

from domain.entities.grading_session import GradingSession

# =============================================================================
# Helpers
# =============================================================================


def _make_pending() -> GradingSession:
    """Create a fresh GradingSession in PENDING state."""
    return GradingSession.create(
        grading_session_id="gs-001",
        lablet_session_id="ls-001",
        external_grading_session_id="ext-gs-001",
        grading_part_id="gp-01",
        pod_id="pod-42",
        form_qualified_name="cisco.ccna.grade.v1",
        grading_rules_uri="s3://bucket/rules/ccna-v1.json",
        devices=[{"name": "router1", "type": "CSR1000v"}],
    )


def _make_collecting() -> GradingSession:
    """Create a GradingSession in COLLECTING state."""
    session = _make_pending()
    session.start_collecting()
    return session


def _make_grading() -> GradingSession:
    """Create a GradingSession in GRADING state."""
    session = _make_collecting()
    session.start_grading()
    return session


def _make_reviewing() -> GradingSession:
    """Create a GradingSession in REVIEWING state."""
    session = _make_grading()
    session.start_reviewing()
    return session


# =============================================================================
# Tests — Creation
# =============================================================================


class TestGradingSessionCreation:
    """Tests for GradingSession.create() factory method."""

    def test_create_sets_pending_status(self) -> None:
        session = _make_pending()
        assert session.status == GradingSessionStatus.PENDING

    def test_create_sets_identity_fields(self) -> None:
        session = _make_pending()
        assert session.id == "gs-001"
        assert session.lablet_session_id == "ls-001"
        assert session.grading_session_id == "ext-gs-001"

    def test_create_sets_grading_config(self) -> None:
        session = _make_pending()
        assert session.grading_part_id == "gp-01"
        assert session.pod_id == "pod-42"
        assert session.form_qualified_name == "cisco.ccna.grade.v1"
        assert session.grading_rules_uri == "s3://bucket/rules/ccna-v1.json"
        assert session.devices == [{"name": "router1", "type": "CSR1000v"}]

    def test_create_initialises_null_fields(self) -> None:
        session = _make_pending()
        assert session.started_at is None
        assert session.completed_at is None
        assert session.error_message is None


# =============================================================================
# Tests — Happy Path Lifecycle
# =============================================================================


class TestGradingSessionLifecycle:
    """Tests for PENDING → COLLECTING → GRADING → REVIEWING → SUBMITTED lifecycle."""

    def test_start_collecting(self) -> None:
        session = _make_collecting()
        assert session.status == GradingSessionStatus.COLLECTING
        assert session.started_at is not None

    def test_start_grading(self) -> None:
        session = _make_grading()
        assert session.status == GradingSessionStatus.GRADING

    def test_start_reviewing(self) -> None:
        session = _make_reviewing()
        assert session.status == GradingSessionStatus.REVIEWING

    def test_submit(self) -> None:
        session = _make_reviewing()
        session.submit()
        assert session.status == GradingSessionStatus.SUBMITTED
        assert session.completed_at is not None

    def test_duration_seconds_after_submit(self) -> None:
        session = _make_reviewing()
        session.submit()
        # Duration should be computed (>= 0)
        assert session.duration_seconds is not None
        assert session.duration_seconds >= 0.0


# =============================================================================
# Tests — Fault Handling
# =============================================================================


class TestGradingSessionFaults:
    """Tests for fault() transitions."""

    @pytest.mark.parametrize(
        "make_fn",
        [_make_pending, _make_collecting, _make_grading, _make_reviewing],
    )
    def test_fault_from_non_terminal_states(self, make_fn) -> None:
        session = make_fn()
        session.fault(error_message="Grading engine error")
        assert session.status == GradingSessionStatus.FAULTED
        assert session.error_message == "Grading engine error"
        assert session.completed_at is not None

    def test_fault_from_submitted_raises(self) -> None:
        session = _make_reviewing()
        session.submit()
        with pytest.raises(ValueError, match="Cannot fault a session in terminal state"):
            session.fault("Should fail")

    def test_fault_from_faulted_raises(self) -> None:
        session = _make_pending()
        session.fault("First error")
        with pytest.raises(ValueError, match="Cannot fault a session in terminal state"):
            session.fault("Second error")


# =============================================================================
# Tests — Invalid Transitions
# =============================================================================


class TestGradingSessionInvalidTransitions:
    """Tests that invalid transitions raise ValueError."""

    def test_cannot_grade_from_pending(self) -> None:
        session = _make_pending()
        with pytest.raises(ValueError, match="Invalid transition"):
            session.start_grading()

    def test_cannot_submit_from_collecting(self) -> None:
        session = _make_collecting()
        with pytest.raises(ValueError, match="Invalid transition"):
            session.submit()

    def test_cannot_collect_after_submitted(self) -> None:
        session = _make_reviewing()
        session.submit()
        with pytest.raises(ValueError, match="Invalid transition"):
            session.start_collecting()


# =============================================================================
# Tests — Computed Properties
# =============================================================================


class TestGradingSessionProperties:
    """Tests for computed properties."""

    def test_is_pending(self) -> None:
        assert _make_pending().is_pending
        assert not _make_collecting().is_pending

    def test_is_active(self) -> None:
        assert not _make_pending().is_active
        assert _make_collecting().is_active
        assert _make_grading().is_active
        assert _make_reviewing().is_active

    def test_is_terminal(self) -> None:
        session = _make_reviewing()
        assert not session.is_terminal
        session.submit()
        assert session.is_terminal

    def test_is_terminal_on_faulted(self) -> None:
        session = _make_pending()
        session.fault("Error")
        assert session.is_terminal

    def test_duration_none_when_not_started(self) -> None:
        session = _make_pending()
        assert session.duration_seconds is None
