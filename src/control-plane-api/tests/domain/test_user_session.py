"""Domain tests for UserSession entity.

Phase 7C: Tests lifecycle transitions, validation, computed properties,
and factory for the UserSession child entity (ADR-021 §1).
"""

import pytest
from domain.entities.user_session import UserSession
from lcm_core.domain.enums import UserSessionStatus

# =============================================================================
# Helpers
# =============================================================================


def _make_provisioning() -> UserSession:
    """Create a fresh UserSession in PROVISIONING state."""
    return UserSession.create(
        user_session_id="us-001",
        lablet_session_id="ls-001",
        lds_session_id="lds-001",
        lds_part_id="part-01",
        form_qualified_name="cisco.ccna.lab.v1",
    )


def _make_provisioned() -> UserSession:
    """Create a UserSession in PROVISIONED state."""
    session = _make_provisioning()
    session.mark_provisioned(login_url="https://lds.example.com/login?t=abc123", devices=[{"name": "router1"}])
    return session


def _make_active() -> UserSession:
    """Create a UserSession in ACTIVE state."""
    session = _make_provisioned()
    session.activate()
    return session


# =============================================================================
# Tests — Creation
# =============================================================================


class TestUserSessionCreation:
    """Tests for UserSession.create() factory method."""

    def test_create_sets_provisioning_status(self) -> None:
        session = _make_provisioning()
        assert session.status == UserSessionStatus.PROVISIONING

    def test_create_sets_identity_fields(self) -> None:
        session = _make_provisioning()
        assert session.id == "us-001"
        assert session.lablet_session_id == "ls-001"
        assert session.lds_session_id == "lds-001"
        assert session.lds_part_id == "part-01"
        assert session.form_qualified_name == "cisco.ccna.lab.v1"

    def test_create_initialises_null_fields(self) -> None:
        session = _make_provisioning()
        assert session.login_url is None
        assert session.devices == []
        assert session.started_at is None
        assert session.ended_at is None
        assert session.error_message is None


# =============================================================================
# Tests — Happy Path Lifecycle
# =============================================================================


class TestUserSessionLifecycle:
    """Tests for PROVISIONING → PROVISIONED → ACTIVE → ENDED lifecycle."""

    def test_mark_provisioned_sets_login_url(self) -> None:
        session = _make_provisioned()
        assert session.status == UserSessionStatus.PROVISIONED
        assert session.login_url == "https://lds.example.com/login?t=abc123"
        assert session.devices == [{"name": "router1"}]

    def test_activate_sets_started_at(self) -> None:
        session = _make_active()
        assert session.status == UserSessionStatus.ACTIVE
        assert session.started_at is not None

    def test_pause_from_active(self) -> None:
        session = _make_active()
        session.pause()
        assert session.status == UserSessionStatus.PAUSED

    def test_resume_from_paused(self) -> None:
        session = _make_active()
        session.pause()
        session.resume()
        assert session.status == UserSessionStatus.ACTIVE

    def test_end_from_active(self) -> None:
        session = _make_active()
        session.end()
        assert session.status == UserSessionStatus.ENDED
        assert session.ended_at is not None

    def test_expire_from_active(self) -> None:
        session = _make_active()
        session.expire()
        assert session.status == UserSessionStatus.EXPIRED
        assert session.ended_at is not None


# =============================================================================
# Tests — Fault Handling
# =============================================================================


class TestUserSessionFaults:
    """Tests for fault() transitions."""

    @pytest.mark.parametrize(
        "make_fn",
        [_make_provisioning, _make_provisioned, _make_active],
    )
    def test_fault_from_non_terminal_states(self, make_fn) -> None:
        session = make_fn()
        session.fault(error_message="LDS connection failed")
        assert session.status == UserSessionStatus.FAULTED
        assert session.error_message == "LDS connection failed"
        assert session.ended_at is not None

    def test_fault_from_terminal_raises(self) -> None:
        session = _make_active()
        session.end()
        with pytest.raises(ValueError, match="Cannot fault a session in terminal state"):
            session.fault("Should fail")


# =============================================================================
# Tests — Invalid Transitions
# =============================================================================


class TestUserSessionInvalidTransitions:
    """Tests that invalid transitions raise ValueError."""

    def test_cannot_activate_from_provisioning(self) -> None:
        session = _make_provisioning()
        with pytest.raises(ValueError, match="Invalid transition"):
            session.activate()

    def test_cannot_pause_from_provisioning(self) -> None:
        session = _make_provisioning()
        with pytest.raises(ValueError, match="Invalid transition"):
            session.pause()

    def test_cannot_end_from_provisioning(self) -> None:
        session = _make_provisioning()
        with pytest.raises(ValueError, match="Invalid transition"):
            session.end()

    def test_cannot_activate_after_ended(self) -> None:
        session = _make_active()
        session.end()
        with pytest.raises(ValueError, match="Invalid transition"):
            session.activate()


# =============================================================================
# Tests — Computed Properties
# =============================================================================


class TestUserSessionProperties:
    """Tests for computed properties."""

    def test_is_active(self) -> None:
        assert not _make_provisioning().is_active
        assert not _make_provisioned().is_active
        assert _make_active().is_active

    def test_is_terminal(self) -> None:
        session = _make_active()
        assert not session.is_terminal
        session.end()
        assert session.is_terminal

    def test_is_terminal_on_expired(self) -> None:
        session = _make_active()
        session.expire()
        assert session.is_terminal

    def test_is_terminal_on_faulted(self) -> None:
        session = _make_active()
        session.fault("Error")
        assert session.is_terminal

    def test_has_login_url(self) -> None:
        assert not _make_provisioning().has_login_url
        assert _make_provisioned().has_login_url
