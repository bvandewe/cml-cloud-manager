"""Unit tests for session expiry → lab record wipe (AD-WIPE-001).

Tests cover:
- Nominal: expired session → unbind + wipe queued
- Lab already in terminal state → no wipe dispatched
- Lab has pending action → wipe skipped
- Wipe failure does not block expiry completion
- No lab_record_id → wipe not attempted
- Response payload includes lab_wipe_queued field

Pattern: pytest fixtures + MagicMock + AsyncMock, matching test_expire_lablet_session_command.py.
"""

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from application.commands.lab.wipe_lab_record_command import WipeLabRecordCommand
from application.commands.lablet_session.expire_lablet_session_command import ExpireLabletSessionCommand, ExpireLabletSessionCommandHandler
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
    definition_id: str | None = "def-001",
) -> MagicMock:
    """Create a mock LabletSession with state."""
    session = MagicMock(spec=LabletSession)
    session.id.return_value = session_id

    state = MagicMock(spec=LabletSessionState)
    state.status = status
    state.worker_id = worker_id
    state.lab_record_id = lab_record_id
    state.definition_id = definition_id
    state.allocated_ports = {"serial_1": 5041}

    session.state = state
    session.expire = MagicMock()

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
    state.allocated_ports = {"serial_1": 5041, "vnc_1": 5044}

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
    result = MagicMock()
    result.is_success = True
    return result


def _failure_result(msg: str = "Error") -> MagicMock:
    result = MagicMock()
    result.is_success = False
    result.error_message = msg
    return result


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.command
class TestExpireSessionLabWipe:
    """Tests for session expiry → lab record wipe (AD-WIPE-001)."""

    def _make_handler(
        self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock, mock_definition_repository: MagicMock
    ) -> ExpireLabletSessionCommandHandler:
        return ExpireLabletSessionCommandHandler(
            mediator=mock_mediator, lablet_session_repository=mock_session_repository, lab_record_repository=mock_lab_record_repository, lablet_definition_repository=mock_definition_repository
        )

    @pytest.mark.asyncio
    async def test_nominal_expiry_queues_wipe(self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock, mock_definition_repository: MagicMock) -> None:
        """Nominal: expired session queues wipe for linked lab record."""
        session = _make_session(lab_record_id="lr-001", definition_id="def-001")
        lab_record = _make_lab_record()
        definition = _make_definition()

        mock_session_repository.get_by_id_async.return_value = session
        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_definition_repository.get_by_id_async.return_value = definition
        mock_mediator.execute_async = AsyncMock(return_value=_success_result())

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_lab_record_repository, mock_definition_repository)

        command = ExpireLabletSessionCommand(session_id="session-001", reason="timeslot_expired")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["lab_wipe_queued"] is True
        assert result.data["lab_record_unbound"] is True

        # Verify WipeLabRecordCommand was dispatched
        mediator_calls = mock_mediator.execute_async.call_args_list
        wipe_calls = [c for c in mediator_calls if isinstance(c[0][0], WipeLabRecordCommand)]
        assert len(wipe_calls) == 1
        assert wipe_calls[0][0][0].lab_record_id == "lr-001"

    @pytest.mark.asyncio
    async def test_lab_terminal_state_skips_wipe(
        self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock, mock_definition_repository: MagicMock
    ) -> None:
        """Lab in terminal state (DELETED/ARCHIVED) → no wipe dispatched."""
        session = _make_session(lab_record_id="lr-001")
        lab_record = _make_lab_record(is_terminal=True)
        definition = _make_definition()

        mock_session_repository.get_by_id_async.return_value = session
        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_definition_repository.get_by_id_async.return_value = definition
        mock_mediator.execute_async = AsyncMock(return_value=_success_result())

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_lab_record_repository, mock_definition_repository)

        command = ExpireLabletSessionCommand(session_id="session-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["lab_wipe_queued"] is False

        # Only capacity release, no wipe
        wipe_calls = [c for c in mock_mediator.execute_async.call_args_list if isinstance(c[0][0], WipeLabRecordCommand)]
        assert len(wipe_calls) == 0

    @pytest.mark.asyncio
    async def test_lab_pending_action_skips_wipe(
        self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock, mock_definition_repository: MagicMock
    ) -> None:
        """Lab with existing pending_action → wipe skipped."""
        session = _make_session(lab_record_id="lr-001")
        lab_record = _make_lab_record(pending_action="stop")
        definition = _make_definition()

        mock_session_repository.get_by_id_async.return_value = session
        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_definition_repository.get_by_id_async.return_value = definition
        mock_mediator.execute_async = AsyncMock(return_value=_success_result())

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_lab_record_repository, mock_definition_repository)

        command = ExpireLabletSessionCommand(session_id="session-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["lab_wipe_queued"] is False

    @pytest.mark.asyncio
    async def test_wipe_failure_does_not_block_expiry(
        self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock, mock_definition_repository: MagicMock
    ) -> None:
        """Wipe failure → expiry still completes successfully."""
        session = _make_session(lab_record_id="lr-001")
        lab_record = _make_lab_record()
        definition = _make_definition()

        mock_session_repository.get_by_id_async.return_value = session
        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_definition_repository.get_by_id_async.return_value = definition
        # Wipe fails, capacity release succeeds
        mock_mediator.execute_async = AsyncMock(side_effect=[_failure_result("Wipe conflict"), _success_result()])

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_lab_record_repository, mock_definition_repository)

        command = ExpireLabletSessionCommand(session_id="session-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["lab_wipe_queued"] is False
        assert result.data["capacity_released"] is True

    @pytest.mark.asyncio
    async def test_no_lab_record_skips_wipe(self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock, mock_definition_repository: MagicMock) -> None:
        """Session without lab_record_id → wipe not attempted."""
        session = _make_session(lab_record_id=None)
        definition = _make_definition()

        mock_session_repository.get_by_id_async.return_value = session
        mock_definition_repository.get_by_id_async.return_value = definition
        mock_mediator.execute_async = AsyncMock(return_value=_success_result())

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_lab_record_repository, mock_definition_repository)

        command = ExpireLabletSessionCommand(session_id="session-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["lab_wipe_queued"] is False
        mock_lab_record_repository.get_by_id_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_response_includes_lab_wipe_queued_field(
        self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock, mock_definition_repository: MagicMock
    ) -> None:
        """Response payload includes lab_wipe_queued boolean field."""
        session = _make_session(lab_record_id="lr-001")
        lab_record = _make_lab_record()
        definition = _make_definition()

        mock_session_repository.get_by_id_async.return_value = session
        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_definition_repository.get_by_id_async.return_value = definition
        mock_mediator.execute_async = AsyncMock(return_value=_success_result())

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_lab_record_repository, mock_definition_repository)

        command = ExpireLabletSessionCommand(session_id="session-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert "lab_wipe_queued" in result.data
        assert isinstance(result.data["lab_wipe_queued"], bool)
