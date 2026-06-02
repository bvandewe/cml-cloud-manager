"""Unit tests for ExpireLabletSessionCommandHandler (ADR-031 / AD-TIMESLOT-001).

Tests cover:
- Nominal expiry: session expires, LabRecord unbound, capacity released
- NO port release at expiry — ports belong to LabRecord topology
- Idempotency — already expired returns ok
- Session not found → 404
- Expire fails (invalid transition) → 409
- No LabRecord bound → still succeeds (no unbind)
- No worker assigned → capacity release skipped
- Partial failure: LabRecord unbind ok, capacity release fails → still ok
- LabRecord.allocated_ports unchanged after unbind

Pattern: pytest fixtures + MagicMock + AsyncMock, matching test_resource_observation_commands.py.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from application.commands.lablet_session.expire_lablet_session_command import ExpireLabletSessionCommand, ExpireLabletSessionCommandHandler
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
def mock_lablet_definition_repository() -> MagicMock:
    mock = MagicMock(spec=LabletDefinitionRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    mock.update_async = AsyncMock()
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

    session.state = state
    session.expire = MagicMock()

    return session


def _make_lab_record(
    record_id: str = "lr-001", active_lablet_session_id: str | None = "session-001", active_binding_id: str | None = "binding-001", allocated_ports: dict[str, int] | None = None
) -> MagicMock:
    """Create a mock LabRecord with state."""
    lab_record = MagicMock(spec=LabRecord)
    lab_record.id.return_value = record_id

    state = MagicMock(spec=LabRecordState)
    state.active_lablet_session_id = active_lablet_session_id
    state.active_binding_id = active_binding_id
    state.allocated_ports = allocated_ports or {"serial_1": 5041, "vnc_1": 5044}

    lab_record.state = state
    lab_record.unbind_from_lablet = MagicMock()

    return lab_record


def _success_result() -> MagicMock:
    """Create a mock successful OperationResult for capacity release."""
    result = MagicMock()
    result.is_success = True
    return result


def _failure_result() -> MagicMock:
    """Create a mock failed OperationResult for capacity release."""
    result = MagicMock()
    result.is_success = False
    result.error_message = "Worker not found"
    return result


def _make_definition(definition_id: str = "def-001", cpu_cores: int = 4, memory_gb: int = 8, storage_gb: int = 50) -> MagicMock:
    """Create a mock LabletDefinition with resource requirements."""
    definition = MagicMock(spec=LabletDefinition)
    definition.id.return_value = definition_id

    state = MagicMock(spec=LabletDefinitionState)
    resource_reqs = MagicMock()
    resource_reqs.cpu_cores = cpu_cores
    resource_reqs.memory_gb = memory_gb
    resource_reqs.storage_gb = storage_gb
    state.resource_requirements = resource_reqs

    definition.state = state
    return definition


SAMPLE_PORTS = {"serial_1": 5041, "vnc_1": 5044}


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.command
class TestExpireLabletSessionCommandHandler:
    """Tests for session expiry command handler."""

    def _make_handler(
        self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock, mock_lablet_definition_repository: MagicMock | None = None
    ) -> ExpireLabletSessionCommandHandler:
        return ExpireLabletSessionCommandHandler(
            mediator=mock_mediator,
            lablet_session_repository=mock_session_repository,
            lab_record_repository=mock_lab_record_repository,
            lablet_definition_repository=mock_lablet_definition_repository or MagicMock(spec=LabletDefinitionRepository),
        )

    @pytest.mark.asyncio
    async def test_nominal_expiry(self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock, mock_lablet_definition_repository: MagicMock) -> None:
        """Nominal: expires session, unbinds LabRecord, releases capacity."""
        session = _make_session(allocated_ports=SAMPLE_PORTS, definition_id="def-001")
        lab_record = _make_lab_record(allocated_ports=SAMPLE_PORTS)
        definition = _make_definition(cpu_cores=4, memory_gb=8, storage_gb=50)

        mock_session_repository.get_by_id_async.return_value = session
        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_lablet_definition_repository.get_by_id_async.return_value = definition
        mock_mediator.execute_async.return_value = _success_result()

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_lab_record_repository, mock_lablet_definition_repository)
        command = ExpireLabletSessionCommand(session_id="session-001", reason="timeslot_expired")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.status_code == 200
        assert result.data["status"] == "expired"
        assert result.data["lab_record_unbound"] is True
        assert result.data["capacity_released"] is True

        # Verify session.expire() was called
        session.expire.assert_called_once_with(reason="timeslot_expired")
        mock_session_repository.update_async.assert_awaited_once_with(session)

        # Verify LabRecord unbinding
        lab_record.unbind_from_lablet.assert_called_once_with(lablet_session_id="session-001", binding_id="binding-001")
        mock_lab_record_repository.update_async.assert_awaited_once_with(lab_record)

        # Verify capacity release via mediator
        mock_mediator.execute_async.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_port_release_at_expiry(self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock) -> None:
        """Critical invariant: LabRecord.allocated_ports is NOT released at expiry."""
        session = _make_session(allocated_ports=SAMPLE_PORTS)
        lab_record = _make_lab_record(allocated_ports=SAMPLE_PORTS)

        mock_session_repository.get_by_id_async.return_value = session
        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_mediator.execute_async.return_value = _success_result()

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_lab_record_repository)
        command = ExpireLabletSessionCommand(session_id="session-001")
        await handler.handle_async(command)

        # LabRecord.allocated_ports must be UNCHANGED
        # The unbind_from_lablet() only clears active binding, not ports
        assert lab_record.state.allocated_ports == SAMPLE_PORTS

        # No port release service calls should have been made
        # (only capacity release via mediator)
        mediator_call = mock_mediator.execute_async.call_args[0][0]
        assert type(mediator_call).__name__ == "ReleaseCapacityCommand"

    @pytest.mark.asyncio
    async def test_capacity_release_uses_definition_resource_values(
        self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock, mock_lablet_definition_repository: MagicMock
    ) -> None:
        """Critical fix: ReleaseCapacityCommand must pass actual resource values, not zeros.

        Prior to the fix, expired sessions called ReleaseCapacityCommand with
        cpu_cores=0, memory_gb=0, storage_gb=0 (defaults), which removed the
        session_id from the worker's session_ids but left allocated_capacity
        inflated — a capacity leak causing phantom allocations.
        """
        session = _make_session(
            lab_record_id=None,  # Skip LabRecord unbinding for this test
            definition_id="def-001",
        )
        definition = _make_definition(cpu_cores=4, memory_gb=8, storage_gb=50)

        mock_session_repository.get_by_id_async.return_value = session
        mock_lablet_definition_repository.get_by_id_async.return_value = definition
        mock_mediator.execute_async.return_value = _success_result()

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_lab_record_repository, mock_lablet_definition_repository)
        command = ExpireLabletSessionCommand(session_id="session-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["capacity_released"] is True

        # Verify ReleaseCapacityCommand was called with ACTUAL resource values
        mediator_call = mock_mediator.execute_async.call_args[0][0]
        assert isinstance(mediator_call, ReleaseCapacityCommand)
        assert mediator_call.worker_id == "worker-001"
        assert mediator_call.session_id == "session-001"
        assert mediator_call.cpu_cores == 4
        assert mediator_call.memory_gb == 8
        assert mediator_call.storage_gb == 50

        # Verify definition was looked up
        mock_lablet_definition_repository.get_by_id_async.assert_awaited_once_with("def-001")

    @pytest.mark.asyncio
    async def test_capacity_release_falls_back_to_zeros_when_definition_not_found(
        self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock, mock_lablet_definition_repository: MagicMock
    ) -> None:
        """Falls back to zero resource values when LabletDefinition is not found."""
        session = _make_session(lab_record_id=None, definition_id="missing-def")

        mock_session_repository.get_by_id_async.return_value = session
        mock_lablet_definition_repository.get_by_id_async.return_value = None  # Not found
        mock_mediator.execute_async.return_value = _success_result()

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_lab_record_repository, mock_lablet_definition_repository)
        command = ExpireLabletSessionCommand(session_id="session-001")
        result = await handler.handle_async(command)

        assert result.is_success

        # Falls back to zeros when definition not found
        mediator_call = mock_mediator.execute_async.call_args[0][0]
        assert isinstance(mediator_call, ReleaseCapacityCommand)
        assert mediator_call.cpu_cores == 0
        assert mediator_call.memory_gb == 0
        assert mediator_call.storage_gb == 0

    @pytest.mark.asyncio
    async def test_idempotency_already_expired(self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock) -> None:
        """Idempotent: returns ok when session is already expired."""
        session = _make_session(status=LabletSessionStatus.EXPIRED)
        mock_session_repository.get_by_id_async.return_value = session

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_lab_record_repository)
        command = ExpireLabletSessionCommand(session_id="session-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["already_expired"] is True

        # No mutations
        session.expire.assert_not_called()
        mock_mediator.execute_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_session_not_found(self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock) -> None:
        """Returns 404 when session does not exist."""
        mock_session_repository.get_by_id_async.return_value = None

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_lab_record_repository)
        command = ExpireLabletSessionCommand(session_id="nonexistent")
        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_expire_invalid_state_returns_conflict(self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock) -> None:
        """Returns 409 when expire() raises due to invalid state transition."""
        session = _make_session(status=LabletSessionStatus.TERMINATED)
        session.expire.side_effect = Exception("Cannot expire a terminated session")
        mock_session_repository.get_by_id_async.return_value = session

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_lab_record_repository)
        command = ExpireLabletSessionCommand(session_id="session-001")
        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 409

    @pytest.mark.asyncio
    async def test_no_lab_record_still_succeeds(self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock) -> None:
        """Succeeds when session has no bound LabRecord."""
        session = _make_session(lab_record_id=None)
        mock_session_repository.get_by_id_async.return_value = session
        mock_mediator.execute_async.return_value = _success_result()

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_lab_record_repository)
        command = ExpireLabletSessionCommand(session_id="session-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["lab_record_unbound"] is False

        # LabRecord repo not queried
        mock_lab_record_repository.get_by_id_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_worker_skips_capacity_release(self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock) -> None:
        """Capacity release is skipped when no worker is assigned."""
        session = _make_session(worker_id=None, lab_record_id=None)
        mock_session_repository.get_by_id_async.return_value = session

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_lab_record_repository)
        command = ExpireLabletSessionCommand(session_id="session-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["capacity_released"] is False

        # No mediator call for capacity release
        mock_mediator.execute_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_capacity_release_failure_still_succeeds(self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock) -> None:
        """Session still expires even if capacity release fails."""
        session = _make_session(lab_record_id=None)
        mock_session_repository.get_by_id_async.return_value = session
        mock_mediator.execute_async.return_value = _failure_result()

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_lab_record_repository)
        command = ExpireLabletSessionCommand(session_id="session-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["capacity_released"] is False

    @pytest.mark.asyncio
    async def test_capacity_release_exception_still_succeeds(self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock) -> None:
        """Session still expires even if capacity release throws an exception."""
        session = _make_session(lab_record_id=None)
        mock_session_repository.get_by_id_async.return_value = session
        mock_mediator.execute_async.side_effect = RuntimeError("etcd unavailable")

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_lab_record_repository)
        command = ExpireLabletSessionCommand(session_id="session-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["capacity_released"] is False

    @pytest.mark.asyncio
    async def test_custom_reason_propagated(self, mock_mediator: MagicMock, mock_session_repository: MagicMock, mock_lab_record_repository: MagicMock) -> None:
        """Custom expiry reason is propagated to the session and response."""
        session = _make_session(lab_record_id=None, worker_id=None)
        mock_session_repository.get_by_id_async.return_value = session

        handler = self._make_handler(mock_mediator, mock_session_repository, mock_lab_record_repository)
        command = ExpireLabletSessionCommand(session_id="session-001", reason="admin_override")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["reason"] == "admin_override"
        session.expire.assert_called_once_with(reason="admin_override")
