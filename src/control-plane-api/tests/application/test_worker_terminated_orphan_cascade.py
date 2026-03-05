"""Unit tests for CMLWorkerTerminatedDomainEventHandler lab orphan cascade.

Verifies that when a worker is terminated, all its non-terminal lab records
are cascade-orphaned. This is the reactive counterpart to the per-worker
orphan detection in LabDiscoveryService (which only processes RUNNING workers).

Covers:
- Nominal: multiple labs in various states → all orphaned
- Terminal labs (DELETED, ARCHIVED) → skipped
- Already-orphaned labs → skipped
- No labs for worker → no-op (no errors)
- Partial failure → best-effort (other labs still orphaned)
- SSE broadcast still fires regardless of lab cascade
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from application.events.domain.cml_worker_events import CMLWorkerTerminatedDomainEventHandler
from application.services.sse_event_relay import SSEEventRelay
from domain.entities.lab_record import LabRecord
from domain.events.cml_worker import CMLWorkerTerminatedDomainEvent
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.lab_record_repository import LabRecordRepository
from lcm_core.domain.enums import LabRecordStatus

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_sse_relay() -> MagicMock:
    """Provide a mock SSEEventRelay."""
    relay = MagicMock(spec=SSEEventRelay)
    relay.broadcast_event = AsyncMock()
    return relay


@pytest.fixture
def mock_worker_repository() -> MagicMock:
    """Provide a mock CMLWorkerRepository."""
    repo = MagicMock(spec=CMLWorkerRepository)
    repo.get_by_id_async = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_serializer() -> MagicMock:
    """Provide a mock JsonSerializer."""
    return MagicMock()


@pytest.fixture
def mock_lab_repository() -> MagicMock:
    """Provide a mock LabRecordRepository."""
    repo = MagicMock(spec=LabRecordRepository)
    repo.get_all_by_worker_async = AsyncMock(return_value=[])
    repo.update_async = AsyncMock()
    return repo


@pytest.fixture
def handler(
    mock_sse_relay: MagicMock,
    mock_worker_repository: MagicMock,
    mock_serializer: MagicMock,
    mock_lab_repository: MagicMock,
) -> CMLWorkerTerminatedDomainEventHandler:
    """Create the handler under test with all mocked deps."""
    return CMLWorkerTerminatedDomainEventHandler(
        sse_relay=mock_sse_relay,
        repository=mock_worker_repository,
        serializer=mock_serializer,
        lab_record_repository=mock_lab_repository,
    )


def _make_terminated_event(worker_id: str = "worker-001") -> CMLWorkerTerminatedDomainEvent:
    """Create a CMLWorkerTerminatedDomainEvent for testing."""
    return CMLWorkerTerminatedDomainEvent(
        aggregate_id=worker_id,
        name="Test Worker",
        terminated_at=datetime.now(timezone.utc),
        terminated_by="admin",
    )


def _make_lab(
    lab_id: str = "lab-001",
    worker_id: str = "worker-001",
    status: LabRecordStatus = LabRecordStatus.DISCOVERED,
) -> LabRecord:
    """Create a LabRecord via the discover factory and optionally force state."""
    lab = LabRecord.discover(
        lab_id=lab_id,
        worker_id=worker_id,
        title=f"Lab {lab_id}",
        description="Test lab",
        state="DEFINED_ON_CORE",
        owner_username="admin",
        node_count=3,
        link_count=2,
    )
    lab.state.status = status
    return lab


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.unit
class TestWorkerTerminatedOrphanCascade:
    """Test cascade-orphaning of lab records on worker termination."""

    async def test_orphans_discovered_lab(
        self,
        handler: CMLWorkerTerminatedDomainEventHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """DISCOVERED lab on terminated worker → ORPHANED."""
        lab = _make_lab(status=LabRecordStatus.DISCOVERED)
        mock_lab_repository.get_all_by_worker_async.return_value = [lab]

        await handler.handle_async(_make_terminated_event())

        assert lab.state.status == LabRecordStatus.ORPHANED
        mock_lab_repository.update_async.assert_called_once_with(lab)

    async def test_orphans_booted_lab(
        self,
        handler: CMLWorkerTerminatedDomainEventHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """BOOTED lab on terminated worker → ORPHANED (force-majeure transition)."""
        lab = _make_lab(status=LabRecordStatus.BOOTED)
        mock_lab_repository.get_all_by_worker_async.return_value = [lab]

        await handler.handle_async(_make_terminated_event())

        assert lab.state.status == LabRecordStatus.ORPHANED
        mock_lab_repository.update_async.assert_called_once_with(lab)

    async def test_orphans_multiple_labs_in_various_states(
        self,
        handler: CMLWorkerTerminatedDomainEventHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Multiple labs in different states → all non-terminal become ORPHANED."""
        labs = [
            _make_lab(lab_id="lab-discovered", status=LabRecordStatus.DISCOVERED),
            _make_lab(lab_id="lab-booted", status=LabRecordStatus.BOOTED),
            _make_lab(lab_id="lab-stopped", status=LabRecordStatus.STOPPED),
            _make_lab(lab_id="lab-defined", status=LabRecordStatus.DEFINED),
            _make_lab(lab_id="lab-starting", status=LabRecordStatus.STARTING),
            _make_lab(lab_id="lab-error", status=LabRecordStatus.ERROR),
        ]
        mock_lab_repository.get_all_by_worker_async.return_value = labs

        await handler.handle_async(_make_terminated_event())

        for lab in labs:
            assert lab.state.status == LabRecordStatus.ORPHANED, f"Lab {lab.state.lab_id} should be ORPHANED but is {lab.state.status}"
        assert mock_lab_repository.update_async.call_count == 6

    async def test_skips_terminal_labs(
        self,
        handler: CMLWorkerTerminatedDomainEventHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """DELETED and ARCHIVED labs are not re-orphaned."""
        labs = [
            _make_lab(lab_id="lab-deleted", status=LabRecordStatus.DELETED),
            _make_lab(lab_id="lab-archived", status=LabRecordStatus.ARCHIVED),
            _make_lab(lab_id="lab-booted", status=LabRecordStatus.BOOTED),
        ]
        mock_lab_repository.get_all_by_worker_async.return_value = labs

        await handler.handle_async(_make_terminated_event())

        assert labs[0].state.status == LabRecordStatus.DELETED  # untouched
        assert labs[1].state.status == LabRecordStatus.ARCHIVED  # untouched
        assert labs[2].state.status == LabRecordStatus.ORPHANED  # orphaned
        mock_lab_repository.update_async.assert_called_once_with(labs[2])

    async def test_skips_already_orphaned_labs(
        self,
        handler: CMLWorkerTerminatedDomainEventHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Already-ORPHANED labs are not re-processed."""
        lab = _make_lab(status=LabRecordStatus.ORPHANED)
        mock_lab_repository.get_all_by_worker_async.return_value = [lab]

        await handler.handle_async(_make_terminated_event())

        assert lab.state.status == LabRecordStatus.ORPHANED
        mock_lab_repository.update_async.assert_not_called()

    async def test_no_labs_for_worker(
        self,
        handler: CMLWorkerTerminatedDomainEventHandler,
        mock_lab_repository: MagicMock,
        mock_sse_relay: MagicMock,
    ) -> None:
        """Worker with no labs → SSE fires, no orphan errors."""
        mock_lab_repository.get_all_by_worker_async.return_value = []

        await handler.handle_async(_make_terminated_event())

        mock_lab_repository.update_async.assert_not_called()
        # SSE broadcast still happens
        mock_sse_relay.broadcast_event.assert_called()

    async def test_partial_failure_best_effort(
        self,
        handler: CMLWorkerTerminatedDomainEventHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """If one lab fails to orphan, others are still processed."""
        lab_ok = _make_lab(lab_id="lab-ok", status=LabRecordStatus.DISCOVERED)
        lab_fail = _make_lab(lab_id="lab-fail", status=LabRecordStatus.STOPPED)
        lab_ok2 = _make_lab(lab_id="lab-ok2", status=LabRecordStatus.BOOTED)

        # Make lab_fail raise on mark_orphaned
        original_mark = lab_fail.mark_orphaned
        lab_fail.mark_orphaned = MagicMock(side_effect=Exception("DB error"))

        mock_lab_repository.get_all_by_worker_async.return_value = [lab_ok, lab_fail, lab_ok2]

        await handler.handle_async(_make_terminated_event())

        # lab_ok and lab_ok2 should be orphaned despite lab_fail's exception
        assert lab_ok.state.status == LabRecordStatus.ORPHANED
        assert lab_ok2.state.status == LabRecordStatus.ORPHANED
        # lab_fail was not actually orphaned (exception thrown before state change)
        assert mock_lab_repository.update_async.call_count == 2

    async def test_sse_fires_before_cascade(
        self,
        handler: CMLWorkerTerminatedDomainEventHandler,
        mock_lab_repository: MagicMock,
        mock_sse_relay: MagicMock,
    ) -> None:
        """SSE worker.terminated event is always broadcast, even if cascade fails."""
        mock_lab_repository.get_all_by_worker_async.side_effect = Exception("DB down")

        await handler.handle_async(_make_terminated_event())

        # SSE was still called (it fires before cascade)
        broadcast_calls = mock_sse_relay.broadcast_event.call_args_list
        event_types = [call.kwargs.get("event_type") for call in broadcast_calls]
        assert "worker.terminated" in event_types

    async def test_cascade_uses_correct_worker_id(
        self,
        handler: CMLWorkerTerminatedDomainEventHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Cascade queries labs for the correct worker_id from the event."""
        event = _make_terminated_event(worker_id="specific-worker-xyz")

        await handler.handle_async(event)

        mock_lab_repository.get_all_by_worker_async.assert_called_once_with("specific-worker-xyz")
