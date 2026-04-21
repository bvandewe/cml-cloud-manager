"""Focused tests for worker termination domain event handling."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from application.commands.lablet_session import TerminateLabletSessionCommand
from application.events.domain.cml_worker_events import CMLWorkerTerminatedDomainEventHandler
from domain.enums import LabletSessionStatus
from domain.events.cml_worker import CMLWorkerTerminatedDomainEvent


def make_lab_record(*, is_terminal: bool, is_orphaned: bool, lab_id: str, status: str) -> MagicMock:
    """Create a minimal lab record mock for orphan-cascade tests."""
    record = MagicMock()
    record.is_terminal = is_terminal
    record.is_orphaned = is_orphaned
    record.state = SimpleNamespace(
        lab_id=lab_id,
        status=SimpleNamespace(value=status),
    )
    return record


def make_session(session_id: str, status: LabletSessionStatus) -> MagicMock:
    """Create a minimal session mock for worker termination cascade tests."""
    session = MagicMock()
    session.id.return_value = session_id
    session.state = SimpleNamespace(status=status)
    return session


@pytest.mark.asyncio
async def test_worker_terminated_cascades_labs_and_incomplete_sessions() -> None:
    sse_relay = AsyncMock()
    worker_repo = AsyncMock()
    serializer = MagicMock()
    lab_repo = AsyncMock()
    session_repo = AsyncMock()
    mediator = AsyncMock()
    mediator.execute_async.return_value = SimpleNamespace(is_success=True, error_message=None)

    active_lab = make_lab_record(is_terminal=False, is_orphaned=False, lab_id="lab-1", status="booted")
    terminal_lab = make_lab_record(is_terminal=True, is_orphaned=False, lab_id="lab-2", status="deleted")
    orphaned_lab = make_lab_record(is_terminal=False, is_orphaned=True, lab_id="lab-3", status="orphaned")
    lab_repo.get_all_by_worker_async.return_value = [active_lab, terminal_lab, orphaned_lab]

    scheduled_session = make_session("sess-1", LabletSessionStatus.SCHEDULED)
    running_session = make_session("sess-2", LabletSessionStatus.RUNNING)
    stopped_session = make_session("sess-3", LabletSessionStatus.STOPPED)
    session_repo.list_by_worker_async.return_value = [scheduled_session, running_session, stopped_session]

    handler = CMLWorkerTerminatedDomainEventHandler(
        sse_relay=sse_relay,
        repository=worker_repo,
        serializer=serializer,
        lab_record_repository=lab_repo,
        lablet_session_repository=session_repo,
        mediator=mediator,
    )
    event = CMLWorkerTerminatedDomainEvent(
        aggregate_id="worker-1",
        name="worker-one",
        terminated_at=datetime.now(timezone.utc),
        terminated_by="worker-controller-discovery",
    )

    with patch("application.events.domain.cml_worker_events._broadcast_worker_snapshot", new=AsyncMock()):
        await handler.handle_async(event)

    active_lab.mark_orphaned.assert_called_once_with()
    lab_repo.update_async.assert_awaited_once_with(active_lab)

    assert mediator.execute_async.await_count == 2
    scheduled_command = mediator.execute_async.await_args_list[0].args[0]
    running_command = mediator.execute_async.await_args_list[1].args[0]
    assert isinstance(scheduled_command, TerminateLabletSessionCommand)
    assert scheduled_command.session_id == "sess-1"
    assert scheduled_command.terminated_by == "worker-termination-cascade"
    assert scheduled_command.reason == "worker_terminated_before_session_start"
    assert isinstance(running_command, TerminateLabletSessionCommand)
    assert running_command.session_id == "sess-2"
    assert running_command.reason == "worker_terminated_during_active_session"


@pytest.mark.asyncio
async def test_worker_terminated_skips_failed_session_termination_and_continues() -> None:
    session_repo = AsyncMock()
    execute_async = AsyncMock(return_value=SimpleNamespace(is_success=False, error_message="boom"))
    mediator = MagicMock()
    mediator.execute_async = execute_async
    handler = CMLWorkerTerminatedDomainEventHandler(
        sse_relay=AsyncMock(),
        repository=AsyncMock(),
        serializer=MagicMock(),
        lab_record_repository=AsyncMock(),
        lablet_session_repository=session_repo,
        mediator=mediator,
    )
    failed_session = make_session("sess-1", LabletSessionStatus.READY)
    skipped_session = make_session("sess-2", LabletSessionStatus.ARCHIVED)
    session_repo.list_by_worker_async.return_value = [failed_session, skipped_session]

    terminated = await handler._terminate_worker_sessions("worker-1")

    assert terminated == 0
    execute_async.assert_awaited_once()
