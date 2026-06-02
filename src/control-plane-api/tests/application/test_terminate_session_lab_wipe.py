"""Unit tests for session termination → lab record wipe (AD-WIPE-001).

Tests cover:
- Nominal: session with lab_record → unbind + wipe queued
- No lab_record_id: session without lab → no wipe attempted
- Lab already in terminal state → no wipe dispatched
- Lab has pending action → wipe skipped (no conflict)
- Lab record not found → graceful handling, session still terminates
- Wipe dispatch failure → session termination still succeeds

Pattern: pytest fixtures + MagicMock + AsyncMock, matching test_expire_lablet_session_command.py.
"""

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from application.commands.lab.wipe_lab_record_command import WipeLabRecordCommand
from application.commands.lablet_session.terminate_lablet_session_command import TerminateLabletSessionCommand, TerminateLabletSessionCommandHandler
from application.commands.worker.release_capacity_command import ReleaseCapacityCommand
from domain.entities.lab_record import LabRecord, LabRecordState
from domain.entities.lablet_definition import LabletDefinition, LabletDefinitionState
from domain.entities.lablet_session import LabletSession, LabletSessionState
from domain.enums import LabletSessionStatus
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.mediation import Mediator

# =============================================================================
# Shared fixtures
# =============================================================================


@pytest.fixture
def mock_mediator() -> MagicMock:
    mock = MagicMock(spec=Mediator)
    mock.execute_async = AsyncMock()
    return mock


@pytest.fixture
def mock_session_repository() -> MagicMock:
    mock = MagicMock(spec=LabletSessionRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    mock.update_async = AsyncMock()
    return mock


@pytest.fixture
def mock_lab_record_repository() -> MagicMock:
    mock = MagicMock(spec=LabRecordRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    mock.update_async = AsyncMock()
    return mock


@pytest.fixture
def mock_definition_repository() -> MagicMock:
    mock = MagicMock(spec=LabletDefinitionRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    return mock


# =============================================================================
# Helpers
# =============================================================================


def _make_session(
    session_id: str = "session-001",
    status: LabletSessionStatus = LabletSessionStatus.RUNNING,
    worker_id: str | None = "worker-001",
    lab_record_id: str | None = "lr-001",
    allocated_ports: dict[str, int] | None = None,
    definition_id: str | None = "def-001",
) -> MagicMock:
    """Create a mock LabletSession with state."""
    session = MagicMock(spec=LabletSession)
    session.id.return_value = session_id

    state = MagicMock(spec=LabletSessionState)
    state.status = status
    state.worker_id = worker_id
    state.lab_record_id = lab_record_id
    state.allocated_ports = allocated_ports or {"serial_1": 5041}
    state.definition_id = definition_id
    state.terminated_at = None

    session.state = state
    session.terminate = MagicMock()
    session.release_ports = MagicMock()

    # Properties
    type(session).can_be_terminated = PropertyMock(return_value=True)

    return session


def _make_lab_record(
    record_id: str = "lr-001", active_lablet_session_id: str | None = "session-001", active_binding_id: str | None = "binding-001", is_terminal: bool = False, pending_action: str | None = None
) -> MagicMock:
    """Create a mock LabRecord with state."""
    lab_record = MagicMock(spec=LabRecord)
    lab_record.id.return_value = record_id

    state = MagicMock(spec=LabRecordState)
    state.active_lablet_session_id = active_lablet_session_id
    state.active_binding_id = active_binding_id
    state.pending_action = pending_action

    lab_record.state = state
    lab_record.unbind_from_lablet = MagicMock()
    type(lab_record).is_terminal = PropertyMock(return_value=is_terminal)

    return lab_record


def _make_definition(cpu_cores: int = 4, memory_gb: int = 8, storage_gb: int = 50) -> MagicMock:
    """Create a mock LabletDefinition with resource requirements."""
    definition = MagicMock(spec=LabletDefinition)

    state = MagicMock(spec=LabletDefinitionState)
    resource_reqs = MagicMock()
    resource_reqs.cpu_cores = cpu_cores
    resource_reqs.memory_gb = memory_gb
    resource_reqs.storage_gb = storage_gb
    state.resource_requirements = resource_reqs

    definition.state = state
    return definition


def _success_result() -> MagicMock:
    """Create a mock successful OperationResult."""
    result = MagicMock()
    result.is_success = True
    return result


def _failure_result(msg: str = "Error") -> MagicMock:
    """Create a mock failed OperationResult."""
    result = MagicMock()
    result.is_success = False
    result.error_message = msg
    return result


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.command
class TestTerminateSessionLabWipe:
    """Tests for session termination → lab record unbind + wipe (AD-WIPE-001)."""

    def _make_handler(
        self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_definition_repository: MagicMock, mock_lab_record_repository: MagicMock
    ) -> TerminateLabletSessionCommandHandler:
        return TerminateLabletSessionCommandHandler(
            mediator=mock_mediator, lablet_session_repository=mock_session_repository, lablet_definition_repository=mock_definition_repository, lab_record_repository=mock_lab_record_repository
        )

    @pytest.mark.asyncio
    async def test_nominal_terminate_unbinds_and_queues_wipe(
        self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock, mock_definition_repository: MagicMock
    ) -> None:
        """Nominal: terminate unbinds the lab record and queues a wipe."""
        session = _make_session(lab_record_id="lr-001", definition_id="def-001")
        lab_record = _make_lab_record(active_lablet_session_id="session-001")
        definition = _make_definition()

        mock_session_repository.get_by_id_async.return_value = session
        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_definition_repository.get_by_id_async.return_value = definition
        # First call: ReleaseCapacityCommand, Second call: WipeLabRecordCommand
        mock_mediator.execute_async = AsyncMock(return_value=_success_result())

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_definition_repository, mock_lab_record_repository)

        command = TerminateLabletSessionCommand(session_id="session-001", terminated_by="admin", reason="test")
        result = await handler.handle_async(command)

        assert result.is_success

        # Verify session was terminated
        session.terminate.assert_called_once()

        # Verify lab record was unbound
        lab_record.unbind_from_lablet.assert_called_once_with(lablet_session_id="session-001", binding_id="binding-001")
        mock_lab_record_repository.update_async.assert_awaited_once_with(lab_record)

        # Verify wipe was queued (second mediator call)
        mediator_calls = mock_mediator.execute_async.call_args_list
        assert len(mediator_calls) == 2
        wipe_call = mediator_calls[1][0][0]
        assert isinstance(wipe_call, WipeLabRecordCommand)
        assert wipe_call.lab_record_id == "lr-001"

    @pytest.mark.asyncio
    async def test_no_lab_record_skips_unbind_and_wipe(
        self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock, mock_definition_repository: MagicMock
    ) -> None:
        """Session without lab_record_id → no unbind or wipe attempted."""
        session = _make_session(lab_record_id=None)
        definition = _make_definition()

        mock_session_repository.get_by_id_async.return_value = session
        mock_definition_repository.get_by_id_async.return_value = definition
        mock_mediator.execute_async = AsyncMock(return_value=_success_result())

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_definition_repository, mock_lab_record_repository)

        command = TerminateLabletSessionCommand(session_id="session-001", terminated_by="admin")
        result = await handler.handle_async(command)

        assert result.is_success
        # Lab record repo not called
        mock_lab_record_repository.get_by_id_async.assert_not_awaited()
        # Only capacity release call to mediator (no wipe)
        assert mock_mediator.execute_async.call_count == 1
        mediator_call = mock_mediator.execute_async.call_args[0][0]
        assert isinstance(mediator_call, ReleaseCapacityCommand)

    @pytest.mark.asyncio
    async def test_lab_in_terminal_state_skips_wipe(
        self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock, mock_definition_repository: MagicMock
    ) -> None:
        """Lab already in terminal state (DELETED/ARCHIVED) → no wipe dispatched."""
        session = _make_session(lab_record_id="lr-001")
        lab_record = _make_lab_record(is_terminal=True)
        definition = _make_definition()

        mock_session_repository.get_by_id_async.return_value = session
        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_definition_repository.get_by_id_async.return_value = definition
        mock_mediator.execute_async = AsyncMock(return_value=_success_result())

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_definition_repository, mock_lab_record_repository)

        command = TerminateLabletSessionCommand(session_id="session-001", terminated_by="admin")
        result = await handler.handle_async(command)

        assert result.is_success
        # Only capacity release (no wipe due to terminal state)
        assert mock_mediator.execute_async.call_count == 1
        mediator_call = mock_mediator.execute_async.call_args[0][0]
        assert isinstance(mediator_call, ReleaseCapacityCommand)

    @pytest.mark.asyncio
    async def test_lab_with_pending_action_skips_wipe(
        self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock, mock_definition_repository: MagicMock
    ) -> None:
        """Lab has existing pending_action → wipe skipped (avoid conflict)."""
        session = _make_session(lab_record_id="lr-001")
        lab_record = _make_lab_record(pending_action="stop")
        definition = _make_definition()

        mock_session_repository.get_by_id_async.return_value = session
        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_definition_repository.get_by_id_async.return_value = definition
        mock_mediator.execute_async = AsyncMock(return_value=_success_result())

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_definition_repository, mock_lab_record_repository)

        command = TerminateLabletSessionCommand(session_id="session-001", terminated_by="admin")
        result = await handler.handle_async(command)

        assert result.is_success
        # Only capacity release (no wipe due to pending action)
        assert mock_mediator.execute_async.call_count == 1

    @pytest.mark.asyncio
    async def test_lab_record_not_found_still_succeeds(
        self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock, mock_definition_repository: MagicMock
    ) -> None:
        """Lab record not found → session still terminates successfully."""
        session = _make_session(lab_record_id="lr-missing")
        definition = _make_definition()

        mock_session_repository.get_by_id_async.return_value = session
        mock_lab_record_repository.get_by_id_async.return_value = None  # Not found
        mock_definition_repository.get_by_id_async.return_value = definition
        mock_mediator.execute_async = AsyncMock(return_value=_success_result())

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_definition_repository, mock_lab_record_repository)

        command = TerminateLabletSessionCommand(session_id="session-001", terminated_by="admin")
        result = await handler.handle_async(command)

        assert result.is_success
        session.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_wipe_failure_does_not_block_termination(
        self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock, mock_definition_repository: MagicMock
    ) -> None:
        """Wipe command failure → termination still succeeds (best-effort)."""
        session = _make_session(lab_record_id="lr-001")
        lab_record = _make_lab_record()
        definition = _make_definition()

        mock_session_repository.get_by_id_async.return_value = session
        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_definition_repository.get_by_id_async.return_value = definition
        # Capacity release succeeds, wipe fails
        mock_mediator.execute_async = AsyncMock(side_effect=[_success_result(), _failure_result("Wipe conflict")])

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_definition_repository, mock_lab_record_repository)

        command = TerminateLabletSessionCommand(session_id="session-001", terminated_by="admin")
        result = await handler.handle_async(command)

        # Termination still succeeds even though wipe failed
        assert result.is_success
        session.terminate.assert_called_once()
