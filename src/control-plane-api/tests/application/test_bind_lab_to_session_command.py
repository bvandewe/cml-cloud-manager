"""Unit tests for BindLabToSessionCommandHandler (ADR-031 / ADR-032).

Tests cover:
- Nominal binding: LabRunRecord creation (NO port fields), LabRecord state
  update (active_lablet_session_id, active_binding_id), session port
  denormalization from LabRecord.allocated_ports
- Idempotency — already bound to same session returns ok
- LabRecord not found → 404
- LabletSession not found → 404
- LabRecord already bound to different session → 409
- Lab binding without allocated ports → empty dict denormalized

Pattern: pytest fixtures + MagicMock + AsyncMock, matching test_resource_observation_commands.py.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from application.commands.lablet_session.bind_lab_to_session_command import BindLabToSessionCommand, BindLabToSessionCommandHandler
from domain.entities.lab_record import LabRecord, LabRecordState
from domain.entities.lablet_session import LabletSession, LabletSessionState
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository

# =============================================================================
# Shared fixtures
# =============================================================================


@pytest.fixture
def mock_lab_record_repository() -> MagicMock:
    mock = MagicMock(spec=LabRecordRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    mock.update_async = AsyncMock()
    return mock


@pytest.fixture
def mock_session_repository() -> MagicMock:
    mock = MagicMock(spec=LabletSessionRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    mock.update_async = AsyncMock()
    return mock


# =============================================================================
# Helpers
# =============================================================================


def _make_lab_record(record_id: str = "lr-001", active_lablet_session_id: str | None = None, active_binding_id: str | None = None, allocated_ports: dict[str, int] | None = None) -> MagicMock:
    """Create a mock LabRecord with state."""
    lab_record = MagicMock(spec=LabRecord)
    lab_record.id.return_value = record_id

    state = MagicMock(spec=LabRecordState)
    state.active_lablet_session_id = active_lablet_session_id
    state.active_binding_id = active_binding_id
    state.allocated_ports = allocated_ports

    lab_record.state = state
    lab_record.record_run = MagicMock()
    lab_record.bind_to_lablet = MagicMock()

    return lab_record


def _make_session(session_id: str = "session-001", lab_record_id: str | None = None, allocated_ports: dict[str, int] | None = None) -> MagicMock:
    """Create a mock LabletSession with state."""
    session = MagicMock(spec=LabletSession)
    session.id.return_value = session_id

    state = MagicMock(spec=LabletSessionState)
    state.lab_record_id = lab_record_id
    state.allocated_ports = allocated_ports

    session.state = state
    session.bind_lab = MagicMock()

    return session


SAMPLE_PORTS = {"serial_1": 5041, "vnc_1": 5044}


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.command
class TestBindLabToSessionCommandHandler:
    """Tests for lab-to-session binding command handler."""

    def _make_handler(self, mock_lab_record_repository: MagicMock, mock_session_repository: MagicMock) -> BindLabToSessionCommandHandler:
        return BindLabToSessionCommandHandler(lab_record_repository=mock_lab_record_repository, lablet_session_repository=mock_session_repository)

    @pytest.mark.asyncio
    async def test_nominal_binding(self, mock_lab_record_repository: MagicMock, mock_session_repository: MagicMock) -> None:
        """Nominal: creates LabRunRecord, binds LabRecord, denormalizes ports to session."""
        lab_record = _make_lab_record(allocated_ports=SAMPLE_PORTS)
        session = _make_session()

        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_session_repository.get_by_id_async.return_value = session

        handler = self._make_handler(mock_lab_record_repository, mock_session_repository)
        command = BindLabToSessionCommand(session_id="session-001", worker_id="w-001", lab_record_id="lr-001")

        with patch("application.commands.lablet_session.bind_lab_to_session_command.uuid4") as mock_uuid:
            mock_uuid.return_value = MagicMock(__str__=lambda _: "run-uuid-001")
            result = await handler.handle_async(command)

        assert result.is_success
        assert result.status_code == 200
        assert result.data["lab_record_id"] == "lr-001"
        assert result.data["allocated_ports"] == SAMPLE_PORTS

        # Verify LabRunRecord was created (NO port fields per ADR-032)
        lab_record.record_run.assert_called_once()
        run_arg = lab_record.record_run.call_args[0][0]
        assert run_arg.lablet_session_id == "session-001"
        assert run_arg.started_by == "lablet-controller"
        # LabRunRecord should NOT have port fields
        assert not hasattr(run_arg, "allocated_ports")

        # Verify LabRecord bound to session
        lab_record.bind_to_lablet.assert_called_once_with(lablet_session_id="session-001", binding_id=run_arg.run_id, binding_role="instantiation")
        mock_lab_record_repository.update_async.assert_awaited_once_with(lab_record)

        # Verify session port denormalization + cml_lab_id/cml_lab_title threading
        session.bind_lab.assert_called_once_with(lab_record_id="lr-001", allocated_ports=SAMPLE_PORTS, cml_lab_id=None, cml_lab_title=None)
        mock_session_repository.update_async.assert_awaited_once_with(session)

    @pytest.mark.asyncio
    async def test_denormalization_without_ports(self, mock_lab_record_repository: MagicMock, mock_session_repository: MagicMock) -> None:
        """Binding without allocated ports denormalizes empty dict."""
        lab_record = _make_lab_record(allocated_ports=None)
        session = _make_session()

        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_session_repository.get_by_id_async.return_value = session

        handler = self._make_handler(mock_lab_record_repository, mock_session_repository)
        command = BindLabToSessionCommand(session_id="session-001", worker_id="w-001", lab_record_id="lr-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["allocated_ports"] == {}

        # Session gets empty port dict + cml_lab_id/cml_lab_title threading
        session.bind_lab.assert_called_once_with(lab_record_id="lr-001", allocated_ports={}, cml_lab_id=None, cml_lab_title=None)

    @pytest.mark.asyncio
    async def test_idempotency_already_bound(self, mock_lab_record_repository: MagicMock, mock_session_repository: MagicMock) -> None:
        """Idempotent: returns ok when already bound to the same session."""
        lab_record = _make_lab_record(active_lablet_session_id="session-001", allocated_ports=SAMPLE_PORTS)
        session = _make_session(lab_record_id="lr-001")

        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_session_repository.get_by_id_async.return_value = session

        handler = self._make_handler(mock_lab_record_repository, mock_session_repository)
        command = BindLabToSessionCommand(session_id="session-001", worker_id="w-001", lab_record_id="lr-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["already_bound"] is True
        assert result.data["allocated_ports"] == SAMPLE_PORTS

        # No new run or binding
        lab_record.record_run.assert_not_called()
        lab_record.bind_to_lablet.assert_not_called()

    @pytest.mark.asyncio
    async def test_lab_record_not_found(self, mock_lab_record_repository: MagicMock, mock_session_repository: MagicMock) -> None:
        """Returns 404 when LabRecord does not exist."""
        mock_lab_record_repository.get_by_id_async.return_value = None

        handler = self._make_handler(mock_lab_record_repository, mock_session_repository)
        command = BindLabToSessionCommand(session_id="session-001", worker_id="w-001", lab_record_id="nonexistent")
        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_session_not_found(self, mock_lab_record_repository: MagicMock, mock_session_repository: MagicMock) -> None:
        """Returns 404 when LabletSession does not exist."""
        lab_record = _make_lab_record()
        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_session_repository.get_by_id_async.return_value = None

        handler = self._make_handler(mock_lab_record_repository, mock_session_repository)
        command = BindLabToSessionCommand(session_id="nonexistent", worker_id="w-001", lab_record_id="lr-001")
        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_already_bound_to_different_session_conflict(self, mock_lab_record_repository: MagicMock, mock_session_repository: MagicMock) -> None:
        """Returns 409 when LabRecord is bound to a different session."""
        lab_record = _make_lab_record(active_lablet_session_id="other-session-999")
        session = _make_session()

        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_session_repository.get_by_id_async.return_value = session

        handler = self._make_handler(mock_lab_record_repository, mock_session_repository)
        command = BindLabToSessionCommand(session_id="session-001", worker_id="w-001", lab_record_id="lr-001")
        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 409

        # Nothing should have been modified
        lab_record.record_run.assert_not_called()
        lab_record.bind_to_lablet.assert_not_called()
        session.bind_lab.assert_not_called()
