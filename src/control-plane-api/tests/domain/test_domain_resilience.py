"""Unit tests for domain resilience hardening measures (R1–R6).

Tests cover:
- R2: CMLWorker transition table (valid/invalid transitions, warning on invalid)
- R4: clear_pending_action emits LabActionClearedDomainEvent
- R6: update_from_cml freshness guard skips stale data

R1 (OCC in update_many_async) requires MongoDB integration tests and is not
covered here.  R5 (TimeoutStalePendingActionsCommand) has its own test file.
"""

from datetime import datetime, timedelta, timezone

import pytest
from domain.entities.cml_worker import CMLWorker, InvalidCMLWorkerTransitionError
from domain.entities.lab_record import LabRecord
from domain.events.lab_record_events import LabActionClearedDomainEvent
from lcm_core.domain.enums import CML_WORKER_VALID_TRANSITIONS, CMLWorkerStatus, LabRecordStatus


# Helper to access the aggregate's internal pending events list.
# Neuroglia stores them in _pending_events (private attribute).
def _get_pending_events(aggregate) -> list:
    return aggregate._pending_events


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def worker() -> CMLWorker:
    """Create a default CMLWorker in PENDING status."""
    return CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")


@pytest.fixture
def running_worker() -> CMLWorker:
    """Create a CMLWorker in RUNNING status."""
    w = CMLWorker(name="running-worker", aws_region="us-east-1", instance_type="m5zn.metal")
    w.update_status(CMLWorkerStatus.PROVISIONING)
    w.update_status(CMLWorkerStatus.RUNNING)
    return w


@pytest.fixture
def discovered_lab_record() -> LabRecord:
    """Create a LabRecord via the discover factory (DISCOVERED status)."""
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


def _force_status(lab_record: LabRecord, status: LabRecordStatus) -> None:
    """Force a LabRecord into a specific status for testing."""
    lab_record.state.status = status


# =============================================================================
# R2: CMLWorker Transition Table
# =============================================================================


class TestCMLWorkerTransitionTable:
    """Test CML_WORKER_VALID_TRANSITIONS and _validate_transition()."""

    def test_all_statuses_have_entries(self):
        """Every CMLWorkerStatus must have an entry in the transition table."""
        for status in CMLWorkerStatus:
            assert status in CML_WORKER_VALID_TRANSITIONS, f"Missing transition entry for {status.value}"

    def test_terminal_states_have_no_outbound(self):
        """TERMINATED should have no outbound transitions."""
        assert CML_WORKER_VALID_TRANSITIONS[CMLWorkerStatus.TERMINATED] == []

    def test_failed_can_retry_or_terminate(self):
        """FAILED can transition to PENDING (retry) or TERMINATED."""
        targets = CML_WORKER_VALID_TRANSITIONS[CMLWorkerStatus.FAILED]
        assert CMLWorkerStatus.PENDING in targets
        assert CMLWorkerStatus.TERMINATED in targets

    def test_unknown_can_go_anywhere(self):
        """UNKNOWN status should be able to transition to any status."""
        targets = CML_WORKER_VALID_TRANSITIONS[CMLWorkerStatus.UNKNOWN]
        for status in CMLWorkerStatus:
            assert status in targets

    def test_valid_transition_pending_to_provisioning(self, worker: CMLWorker):
        """PENDING → PROVISIONING should succeed without warning."""
        assert worker.state.status == CMLWorkerStatus.PENDING
        result = worker._validate_transition(CMLWorkerStatus.PROVISIONING)
        assert result is True

    def test_valid_transition_running_to_stopping(self, running_worker: CMLWorker):
        """RUNNING → STOPPING is a valid transition."""
        assert running_worker.state.status == CMLWorkerStatus.RUNNING
        result = running_worker._validate_transition(CMLWorkerStatus.STOPPING)
        assert result is True

    def test_invalid_transition_logs_warning(self, worker: CMLWorker, caplog):
        """PENDING → STOPPED is invalid and should log a warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            result = worker._validate_transition(CMLWorkerStatus.STOPPED)
        assert result is False
        assert "unexpected transition" in caplog.text
        assert "pending" in caplog.text.lower()
        assert "stopped" in caplog.text.lower()

    def test_update_status_calls_validate(self, worker: CMLWorker, caplog):
        """update_status should still succeed on invalid transition (non-blocking)."""
        import logging

        with caplog.at_level(logging.WARNING):
            changed = worker.update_status(CMLWorkerStatus.STOPPED)
        # Transition still goes through (reconciler must not be blocked)
        assert changed is True
        assert worker.state.status == CMLWorkerStatus.STOPPED
        assert "unexpected transition" in caplog.text

    def test_update_status_no_op_same_status(self, worker: CMLWorker):
        """update_status returns False when status is already the same."""
        assert worker.update_status(CMLWorkerStatus.PENDING) is False

    def test_update_status_valid_transition_no_warning(self, worker: CMLWorker, caplog):
        """Valid transition should not produce a warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            changed = worker.update_status(CMLWorkerStatus.PROVISIONING)
        assert changed is True
        assert "unexpected transition" not in caplog.text

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            (CMLWorkerStatus.PENDING, CMLWorkerStatus.PROVISIONING),
            (CMLWorkerStatus.PROVISIONING, CMLWorkerStatus.RUNNING),
            (CMLWorkerStatus.RUNNING, CMLWorkerStatus.STOPPING),
            (CMLWorkerStatus.STOPPING, CMLWorkerStatus.STOPPED),
            (CMLWorkerStatus.STOPPED, CMLWorkerStatus.STARTING),
            (CMLWorkerStatus.STARTING, CMLWorkerStatus.RUNNING),
            (CMLWorkerStatus.RUNNING, CMLWorkerStatus.DRAINING),
            (CMLWorkerStatus.DRAINING, CMLWorkerStatus.STOPPING),
            (CMLWorkerStatus.RUNNING, CMLWorkerStatus.TERMINATING),
            (CMLWorkerStatus.TERMINATING, CMLWorkerStatus.TERMINATED),
            (CMLWorkerStatus.STOPPED, CMLWorkerStatus.TERMINATING),
            (CMLWorkerStatus.PROVISIONING, CMLWorkerStatus.FAILED),
        ],
        ids=lambda x: x.value if hasattr(x, "value") else str(x),
    )
    def test_common_valid_transitions(self, from_status, to_status):
        """Parametrized test for common valid lifecycle transitions."""
        w = CMLWorker(name="test", aws_region="us-east-1", instance_type="m5zn.metal")
        w.state.status = from_status
        result = w._validate_transition(to_status)
        assert result is True, f"{from_status.value} → {to_status.value} should be valid"


class TestInvalidCMLWorkerTransitionError:
    """Test the error class itself."""

    def test_error_message(self):
        err = InvalidCMLWorkerTransitionError(CMLWorkerStatus.PENDING, CMLWorkerStatus.TERMINATED)
        assert "pending" in str(err).lower()
        assert "terminated" in str(err).lower()
        assert err.from_status == CMLWorkerStatus.PENDING
        assert err.to_status == CMLWorkerStatus.TERMINATED

    def test_custom_message(self):
        err = InvalidCMLWorkerTransitionError(CMLWorkerStatus.RUNNING, CMLWorkerStatus.PENDING, message="custom msg")
        assert str(err) == "custom msg"


# =============================================================================
# R4: clear_pending_action emits domain event
# =============================================================================


class TestClearPendingActionEvent:
    """Test that clear_pending_action emits LabActionClearedDomainEvent."""

    def test_clear_emits_event(self, discovered_lab_record: LabRecord):
        """clear_pending_action should emit LabActionClearedDomainEvent."""
        discovered_lab_record.request_delete()
        initial_events = len(_get_pending_events(discovered_lab_record))

        discovered_lab_record.clear_pending_action()

        # One new event should have been added
        new_events = _get_pending_events(discovered_lab_record)[initial_events:]
        assert len(new_events) == 1
        event = new_events[0]
        assert isinstance(event, LabActionClearedDomainEvent)
        assert event.lab_id == "lab-001"
        assert event.action == "delete"
        assert event.cleared_at is not None

    def test_clear_resets_all_pending_fields(self, discovered_lab_record: LabRecord):
        """After clear, all pending_action* fields should be None."""
        discovered_lab_record.request_start()
        discovered_lab_record.clear_pending_action()

        assert discovered_lab_record.state.pending_action is None
        assert discovered_lab_record.state.pending_action_at is None
        assert discovered_lab_record.state.pending_action_error is None

    def test_clear_noop_when_no_pending_action(self, discovered_lab_record: LabRecord):
        """clear_pending_action should be a no-op when no pending action exists."""
        assert discovered_lab_record.state.pending_action is None
        initial_events = len(_get_pending_events(discovered_lab_record))

        discovered_lab_record.clear_pending_action()

        # No new events
        assert len(_get_pending_events(discovered_lab_record)) == initial_events

    def test_clear_after_fail_resets_error(self, discovered_lab_record: LabRecord):
        """clear should be a no-op after a failed action already cleared pending state."""
        discovered_lab_record.request_wipe()
        discovered_lab_record.fail_pending_action("CML unreachable")
        assert discovered_lab_record.state.pending_action_error == "CML unreachable"
        assert discovered_lab_record.state.pending_action is None
        assert discovered_lab_record.state.pending_action_at is None

        discovered_lab_record.clear_pending_action()

        assert discovered_lab_record.state.pending_action is None
        assert discovered_lab_record.state.pending_action_at is None
        assert discovered_lab_record.state.pending_action_error == "CML unreachable"


# =============================================================================
# R6: Freshness Guard in update_from_cml
# =============================================================================


class TestUpdateFromCMLFreshnessGuard:
    """Test R6: stale data rejection in update_from_cml."""

    def test_skip_stale_update(self, discovered_lab_record: LabRecord):
        """update_from_cml should skip when incoming timestamp is older."""
        now = datetime.now(timezone.utc)
        old = now - timedelta(hours=1)

        # First update — sets modified_at
        discovered_lab_record.update_from_cml(
            title="Fresh Title",
            description="desc",
            notes=None,
            state="STOPPED",
            owner_username="admin",
            owner_fullname=None,
            node_count=3,
            link_count=2,
            groups=None,
            cml_modified_at=now,
        )
        assert discovered_lab_record.state.title == "Fresh Title"

        # Stale update — should be silently skipped
        events_before = len(_get_pending_events(discovered_lab_record))
        discovered_lab_record.update_from_cml(
            title="Stale Title",
            description="desc",
            notes=None,
            state="STOPPED",
            owner_username="admin",
            owner_fullname=None,
            node_count=5,
            link_count=4,
            groups=None,
            cml_modified_at=old,
        )
        assert discovered_lab_record.state.title == "Fresh Title"  # Unchanged
        assert discovered_lab_record.state.node_count == 3  # Unchanged
        assert len(_get_pending_events(discovered_lab_record)) == events_before  # No new events

    def test_skip_equal_timestamp(self, discovered_lab_record: LabRecord):
        """update_from_cml should also skip when timestamps are equal (idempotent)."""
        ts = datetime.now(timezone.utc)

        discovered_lab_record.update_from_cml(
            title="Title A",
            description="desc",
            notes=None,
            state="STOPPED",
            owner_username="admin",
            owner_fullname=None,
            node_count=3,
            link_count=2,
            groups=None,
            cml_modified_at=ts,
        )

        events_before = len(_get_pending_events(discovered_lab_record))
        discovered_lab_record.update_from_cml(
            title="Title B",
            description="desc",
            notes=None,
            state="STOPPED",
            owner_username="admin",
            owner_fullname=None,
            node_count=5,
            link_count=4,
            groups=None,
            cml_modified_at=ts,
        )
        assert discovered_lab_record.state.title == "Title A"  # Unchanged
        assert len(_get_pending_events(discovered_lab_record)) == events_before

    def test_accept_newer_timestamp(self, discovered_lab_record: LabRecord):
        """update_from_cml should accept data with a newer timestamp."""
        now = datetime.now(timezone.utc)
        later = now + timedelta(hours=1)

        discovered_lab_record.update_from_cml(
            title="Old Title",
            description="desc",
            notes=None,
            state="STOPPED",
            owner_username="admin",
            owner_fullname=None,
            node_count=3,
            link_count=2,
            groups=None,
            cml_modified_at=now,
        )

        discovered_lab_record.update_from_cml(
            title="New Title",
            description="desc",
            notes=None,
            state="STOPPED",
            owner_username="admin",
            owner_fullname=None,
            node_count=5,
            link_count=4,
            groups=None,
            cml_modified_at=later,
        )
        assert discovered_lab_record.state.title == "New Title"
        assert discovered_lab_record.state.node_count == 5

    def test_accept_when_no_existing_timestamp(self, discovered_lab_record: LabRecord):
        """update_from_cml should accept data when modified_at is None (first sync)."""
        assert discovered_lab_record.state.modified_at is None

        discovered_lab_record.update_from_cml(
            title="First Sync",
            description="desc",
            notes=None,
            state="STOPPED",
            owner_username="admin",
            owner_fullname=None,
            node_count=3,
            link_count=2,
            groups=None,
            cml_modified_at=datetime.now(timezone.utc),
        )
        assert discovered_lab_record.state.title == "First Sync"

    def test_accept_when_incoming_timestamp_is_none(self, discovered_lab_record: LabRecord):
        """update_from_cml should accept data when cml_modified_at is None."""
        # Set an existing modified_at
        discovered_lab_record.update_from_cml(
            title="Existing",
            description="desc",
            notes=None,
            state="STOPPED",
            owner_username="admin",
            owner_fullname=None,
            node_count=3,
            link_count=2,
            groups=None,
            cml_modified_at=datetime.now(timezone.utc),
        )

        # Update with None timestamp should go through
        discovered_lab_record.update_from_cml(
            title="No Timestamp",
            description="desc",
            notes=None,
            state="STOPPED",
            owner_username="admin",
            owner_fullname=None,
            node_count=5,
            link_count=4,
            groups=None,
            cml_modified_at=None,
        )
        assert discovered_lab_record.state.title == "No Timestamp"
