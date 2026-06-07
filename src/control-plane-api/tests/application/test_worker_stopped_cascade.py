"""Unit tests for CMLWorkerStatusUpdatedDomainEventHandler stopped cascade.

Verifies that when a worker transitions to STOPPED, all its active lab records
are force-stopped and incomplete lablet sessions are terminated.

Covers:
- Nominal: active labs (BOOTED, STARTING, QUEUED, PAUSED, STOPPING) → STOPPED
- Already-stopped / terminal / non-active labs → skipped
- Incomplete sessions → terminated via TerminateLabletSessionCommand
- Already-ended sessions → skipped
- Non-STOPPED transitions (e.g., RUNNING) → no cascade
- Partial failure → best-effort (other labs still force-stopped)
- SSE broadcast always fires regardless of cascade outcome
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from application.events.domain.cml_worker_events import CMLWorkerStatusUpdatedDomainEventHandler
from application.services.sse_event_relay import SSEEventRelay
from domain.entities.lab_record import LabRecord
from domain.entities.lablet_session import LabletSession
from domain.enums import CMLWorkerStatus, LabletSessionStatus
from domain.events.cml_worker import CMLWorkerStatusUpdatedDomainEvent
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from lcm_core.domain.enums import LabRecordStatus

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_sse_relay() -> MagicMock:
    relay = MagicMock(spec=SSEEventRelay)
    relay.broadcast_event = AsyncMock()
    return relay


@pytest.fixture
def mock_worker_repository() -> MagicMock:
    repo = MagicMock(spec=CMLWorkerRepository)
    repo.get_by_id_async = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_serializer() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_lab_repository() -> MagicMock:
    repo = MagicMock(spec=LabRecordRepository)
    repo.get_all_by_worker_async = AsyncMock(return_value=[])
    repo.update_async = AsyncMock()
    return repo


@pytest.fixture
def mock_lablet_session_repository() -> MagicMock:
    repo = MagicMock(spec=LabletSessionRepository)
    repo.list_by_worker_async = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_mediator() -> MagicMock:
    mediator = MagicMock()
    result = MagicMock()
    result.is_success = True
    mediator.execute_async = AsyncMock(return_value=result)
    return mediator


@pytest.fixture
def handler(
    mock_sse_relay: MagicMock,
    mock_worker_repository: MagicMock,
    mock_serializer: MagicMock,
    mock_lab_repository: MagicMock,
    mock_lablet_session_repository: MagicMock,
    mock_mediator: MagicMock,
) -> CMLWorkerStatusUpdatedDomainEventHandler:
    return CMLWorkerStatusUpdatedDomainEventHandler(
        sse_relay=mock_sse_relay,
        repository=mock_worker_repository,
        serializer=mock_serializer,
        lab_record_repository=mock_lab_repository,
        lablet_session_repository=mock_lablet_session_repository,
        mediator=mock_mediator,
    )


def _make_status_event(
    worker_id: str = "worker-001",
    old_status: CMLWorkerStatus = CMLWorkerStatus.RUNNING,
    new_status: CMLWorkerStatus = CMLWorkerStatus.STOPPED,
) -> CMLWorkerStatusUpdatedDomainEvent:
    return CMLWorkerStatusUpdatedDomainEvent(
        aggregate_id=worker_id,
        old_status=old_status,
        new_status=new_status,
        updated_at=datetime.now(timezone.utc),
    )


def _make_lab(
    lab_id: str = "lab-001",
    worker_id: str = "worker-001",
    status: LabRecordStatus = LabRecordStatus.BOOTED,
) -> LabRecord:
    lab = LabRecord.discover(
        lab_id=lab_id,
        worker_id=worker_id,
        title=f"Lab {lab_id}",
        description="Test lab",
        state="BOOTED",
        owner_username="admin",
        node_count=3,
        link_count=2,
    )
    lab.state.status = status
    return lab


def _make_session(
    session_id: str = "session-001",
    worker_id: str = "worker-001",
    status: LabletSessionStatus = LabletSessionStatus.RUNNING,
) -> MagicMock:
    session = MagicMock(spec=LabletSession)
    session.id.return_value = session_id
    session.state = MagicMock()
    session.state.status = status
    session.state.worker_id = worker_id
    return session


# =============================================================================
# Tests: Lab Record Force-Stop Cascade
# =============================================================================


@pytest.mark.unit
class TestWorkerStoppedLabCascade:
    """Test cascade force-stop of lab records on worker STOPPED."""

    async def test_force_stops_booted_lab(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lab_repository: MagicMock) -> None:
        """BOOTED lab on stopped worker → STOPPED."""
        lab = _make_lab(status=LabRecordStatus.BOOTED)
        mock_lab_repository.get_all_by_worker_async.return_value = [lab]

        await handler.handle_async(_make_status_event())

        assert lab.state.status == LabRecordStatus.STOPPED
        mock_lab_repository.update_async.assert_called_once_with(lab)

    async def test_force_stops_starting_lab(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lab_repository: MagicMock) -> None:
        """STARTING lab on stopped worker → STOPPED."""
        lab = _make_lab(status=LabRecordStatus.STARTING)
        mock_lab_repository.get_all_by_worker_async.return_value = [lab]

        await handler.handle_async(_make_status_event())

        assert lab.state.status == LabRecordStatus.STOPPED
        mock_lab_repository.update_async.assert_called_once_with(lab)

    async def test_force_stops_queued_lab(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lab_repository: MagicMock) -> None:
        """QUEUED lab on stopped worker → STOPPED."""
        lab = _make_lab(status=LabRecordStatus.QUEUED)
        mock_lab_repository.get_all_by_worker_async.return_value = [lab]

        await handler.handle_async(_make_status_event())

        assert lab.state.status == LabRecordStatus.STOPPED
        mock_lab_repository.update_async.assert_called_once_with(lab)

    async def test_force_stops_paused_lab(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lab_repository: MagicMock) -> None:
        """PAUSED lab on stopped worker → STOPPED."""
        lab = _make_lab(status=LabRecordStatus.PAUSED)
        mock_lab_repository.get_all_by_worker_async.return_value = [lab]

        await handler.handle_async(_make_status_event())

        assert lab.state.status == LabRecordStatus.STOPPED
        mock_lab_repository.update_async.assert_called_once_with(lab)

    async def test_force_stops_stopping_lab(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lab_repository: MagicMock) -> None:
        """STOPPING lab on stopped worker → STOPPED."""
        lab = _make_lab(status=LabRecordStatus.STOPPING)
        mock_lab_repository.get_all_by_worker_async.return_value = [lab]

        await handler.handle_async(_make_status_event())

        assert lab.state.status == LabRecordStatus.STOPPED
        mock_lab_repository.update_async.assert_called_once_with(lab)

    async def test_force_stops_multiple_active_labs(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lab_repository: MagicMock) -> None:
        """Multiple active labs → all force-stopped."""
        labs = [
            _make_lab(lab_id="lab-booted", status=LabRecordStatus.BOOTED),
            _make_lab(lab_id="lab-starting", status=LabRecordStatus.STARTING),
            _make_lab(lab_id="lab-queued", status=LabRecordStatus.QUEUED),
            _make_lab(lab_id="lab-paused", status=LabRecordStatus.PAUSED),
            _make_lab(lab_id="lab-stopping", status=LabRecordStatus.STOPPING),
        ]
        mock_lab_repository.get_all_by_worker_async.return_value = labs

        await handler.handle_async(_make_status_event())

        for lab in labs:
            assert lab.state.status == LabRecordStatus.STOPPED, f"Lab {lab.state.lab_id} should be STOPPED but is {lab.state.status}"
        assert mock_lab_repository.update_async.call_count == 5

    async def test_skips_already_stopped_labs(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lab_repository: MagicMock) -> None:
        """Already-STOPPED labs are not re-processed."""
        lab = _make_lab(status=LabRecordStatus.STOPPED)
        mock_lab_repository.get_all_by_worker_async.return_value = [lab]

        await handler.handle_async(_make_status_event())

        assert lab.state.status == LabRecordStatus.STOPPED
        mock_lab_repository.update_async.assert_not_called()

    async def test_skips_terminal_labs(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lab_repository: MagicMock) -> None:
        """DELETED and ARCHIVED labs are not touched."""
        labs = [
            _make_lab(lab_id="lab-deleted", status=LabRecordStatus.DELETED),
            _make_lab(lab_id="lab-archived", status=LabRecordStatus.ARCHIVED),
            _make_lab(lab_id="lab-booted", status=LabRecordStatus.BOOTED),
        ]
        mock_lab_repository.get_all_by_worker_async.return_value = labs

        await handler.handle_async(_make_status_event())

        assert labs[0].state.status == LabRecordStatus.DELETED
        assert labs[1].state.status == LabRecordStatus.ARCHIVED
        assert labs[2].state.status == LabRecordStatus.STOPPED
        mock_lab_repository.update_async.assert_called_once_with(labs[2])

    async def test_skips_defined_and_wiped_labs(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lab_repository: MagicMock) -> None:
        """DEFINED and WIPED labs don't need force-stopping (not running)."""
        labs = [
            _make_lab(lab_id="lab-defined", status=LabRecordStatus.DEFINED),
            _make_lab(lab_id="lab-wiped", status=LabRecordStatus.WIPED),
        ]
        mock_lab_repository.get_all_by_worker_async.return_value = labs

        await handler.handle_async(_make_status_event())

        assert labs[0].state.status == LabRecordStatus.DEFINED
        assert labs[1].state.status == LabRecordStatus.WIPED
        mock_lab_repository.update_async.assert_not_called()

    async def test_skips_orphaned_labs(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lab_repository: MagicMock) -> None:
        """ORPHANED labs are not force-stopped."""
        lab = _make_lab(status=LabRecordStatus.ORPHANED)
        mock_lab_repository.get_all_by_worker_async.return_value = [lab]

        await handler.handle_async(_make_status_event())

        assert lab.state.status == LabRecordStatus.ORPHANED
        mock_lab_repository.update_async.assert_not_called()

    async def test_partial_failure_best_effort(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lab_repository: MagicMock) -> None:
        """If one lab fails to stop, others are still processed."""
        lab_ok = _make_lab(lab_id="lab-ok", status=LabRecordStatus.BOOTED)
        lab_fail = _make_lab(lab_id="lab-fail", status=LabRecordStatus.BOOTED)
        lab_ok2 = _make_lab(lab_id="lab-ok2", status=LabRecordStatus.STARTING)

        lab_fail.mark_stopped = MagicMock(side_effect=Exception("DB error"))

        mock_lab_repository.get_all_by_worker_async.return_value = [lab_ok, lab_fail, lab_ok2]

        await handler.handle_async(_make_status_event())

        assert lab_ok.state.status == LabRecordStatus.STOPPED
        assert lab_ok2.state.status == LabRecordStatus.STOPPED
        assert mock_lab_repository.update_async.call_count == 2

    async def test_no_labs_for_worker(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lab_repository: MagicMock) -> None:
        """Worker with no labs → no errors."""
        mock_lab_repository.get_all_by_worker_async.return_value = []

        await handler.handle_async(_make_status_event())

        mock_lab_repository.update_async.assert_not_called()


# =============================================================================
# Tests: LabletSession Termination Cascade
# =============================================================================


@pytest.mark.unit
class TestWorkerStoppedSessionCascade:
    """Test cascade termination of lablet sessions on worker STOPPED."""

    async def test_terminates_running_session(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lablet_session_repository: MagicMock, mock_mediator: MagicMock) -> None:
        """RUNNING session on stopped worker → terminated."""
        session = _make_session(status=LabletSessionStatus.RUNNING)
        mock_lablet_session_repository.list_by_worker_async.return_value = [session]

        await handler.handle_async(_make_status_event())

        mock_mediator.execute_async.assert_called_once()
        cmd = mock_mediator.execute_async.call_args[0][0]
        assert cmd.session_id == "session-001"
        assert cmd.terminated_by == "worker-stopped-cascade"
        assert "worker_stopped_during_active_session" in cmd.reason

    async def test_terminates_pending_session(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lablet_session_repository: MagicMock, mock_mediator: MagicMock) -> None:
        """PENDING session on stopped worker → terminated with pre-start reason."""
        session = _make_session(status=LabletSessionStatus.PENDING)
        mock_lablet_session_repository.list_by_worker_async.return_value = [session]

        await handler.handle_async(_make_status_event())

        cmd = mock_mediator.execute_async.call_args[0][0]
        assert "worker_stopped_before_session_start" in cmd.reason

    async def test_skips_already_stopped_session(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lablet_session_repository: MagicMock, mock_mediator: MagicMock) -> None:
        """Already-STOPPED session is not re-terminated."""
        session = _make_session(status=LabletSessionStatus.STOPPED)
        mock_lablet_session_repository.list_by_worker_async.return_value = [session]

        await handler.handle_async(_make_status_event())

        mock_mediator.execute_async.assert_not_called()

    async def test_skips_terminated_session(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lablet_session_repository: MagicMock, mock_mediator: MagicMock) -> None:
        """Already-TERMINATED session is not re-terminated."""
        session = _make_session(status=LabletSessionStatus.TERMINATED)
        mock_lablet_session_repository.list_by_worker_async.return_value = [session]

        await handler.handle_async(_make_status_event())

        mock_mediator.execute_async.assert_not_called()

    async def test_terminates_multiple_incomplete_sessions(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lablet_session_repository: MagicMock, mock_mediator: MagicMock) -> None:
        """Multiple incomplete sessions → all terminated."""
        sessions = [
            _make_session(session_id="s1", status=LabletSessionStatus.PENDING),
            _make_session(session_id="s2", status=LabletSessionStatus.RUNNING),
            _make_session(session_id="s3", status=LabletSessionStatus.COLLECTING),
            _make_session(session_id="s4", status=LabletSessionStatus.STOPPED),  # skip
        ]
        mock_lablet_session_repository.list_by_worker_async.return_value = sessions

        await handler.handle_async(_make_status_event())

        assert mock_mediator.execute_async.call_count == 3


# =============================================================================
# Tests: Non-STOPPED Transitions (No Cascade)
# =============================================================================


@pytest.mark.unit
class TestWorkerStatusNoCascade:
    """Verify that non-STOPPED transitions do not trigger cascade."""

    async def test_running_status_no_cascade(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lab_repository: MagicMock, mock_lablet_session_repository: MagicMock) -> None:
        """Transition to RUNNING does not cascade."""
        event = _make_status_event(
            old_status=CMLWorkerStatus.STARTING,
            new_status=CMLWorkerStatus.RUNNING,
        )

        await handler.handle_async(event)

        mock_lab_repository.get_all_by_worker_async.assert_not_called()
        mock_lablet_session_repository.list_by_worker_async.assert_not_called()

    async def test_stopping_status_no_cascade(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lab_repository: MagicMock, mock_lablet_session_repository: MagicMock) -> None:
        """Transition to STOPPING does not cascade (wait for actual STOPPED)."""
        event = _make_status_event(
            old_status=CMLWorkerStatus.RUNNING,
            new_status=CMLWorkerStatus.STOPPING,
        )

        await handler.handle_async(event)

        mock_lab_repository.get_all_by_worker_async.assert_not_called()
        mock_lablet_session_repository.list_by_worker_async.assert_not_called()

    async def test_starting_status_no_cascade(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lab_repository: MagicMock, mock_lablet_session_repository: MagicMock) -> None:
        """Transition to STARTING does not cascade."""
        event = _make_status_event(
            old_status=CMLWorkerStatus.STOPPED,
            new_status=CMLWorkerStatus.STARTING,
        )

        await handler.handle_async(event)

        mock_lab_repository.get_all_by_worker_async.assert_not_called()
        mock_lablet_session_repository.list_by_worker_async.assert_not_called()

    async def test_sse_always_broadcasts(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_sse_relay: MagicMock) -> None:
        """SSE broadcast fires for any status change (not just STOPPED)."""
        event = _make_status_event(
            old_status=CMLWorkerStatus.STARTING,
            new_status=CMLWorkerStatus.RUNNING,
        )

        await handler.handle_async(event)

        broadcast_calls = mock_sse_relay.broadcast_event.call_args_list
        event_types = [call.kwargs.get("event_type") for call in broadcast_calls]
        assert "worker.status.updated" in event_types

    async def test_cascade_uses_correct_worker_id(self, handler: CMLWorkerStatusUpdatedDomainEventHandler, mock_lab_repository: MagicMock) -> None:
        """Cascade queries labs for the correct worker_id from the event."""
        event = _make_status_event(worker_id="specific-worker-xyz")

        await handler.handle_async(event)

        mock_lab_repository.get_all_by_worker_async.assert_called_once_with("specific-worker-xyz")
