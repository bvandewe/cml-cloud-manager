"""Unit tests for resource observation command handlers (ADR-030).

Tests cover:
- RecordResourceObservationCommandHandler (4 tests)
- RequestResourceObservationCommandHandler (5 tests)

Pattern: pytest fixtures + MagicMock + AsyncMock, matching test_lablet_session_commands.py.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator

from application.commands.lablet_session.record_resource_observation_command import (
    RecordResourceObservationCommand,
    RecordResourceObservationCommandHandler,
)
from application.commands.lablet_session.request_resource_observation_command import (
    RequestResourceObservationCommand,
    RequestResourceObservationCommandHandler,
)
from domain.entities.lablet_session import LabletSession, LabletSessionState
from domain.enums import LabletSessionStatus
from domain.repositories.lablet_session_repository import LabletSessionRepository

# =============================================================================
# Shared fixtures
# =============================================================================

NOW = datetime.now(timezone.utc)


@pytest.fixture
def mock_mediator() -> MagicMock:
    mock = MagicMock(spec=Mediator)
    mock.execute_async = AsyncMock()
    return mock


@pytest.fixture
def mock_mapper() -> MagicMock:
    return MagicMock(spec=Mapper)


@pytest.fixture
def mock_cloud_event_bus() -> MagicMock:
    return MagicMock(spec=CloudEventBus)


@pytest.fixture
def mock_cloud_event_publishing_options() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_session_repository() -> MagicMock:
    mock = MagicMock(spec=LabletSessionRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    mock.update_async = AsyncMock()
    return mock


def _make_session(
    session_id: str = "session-001",
    status: LabletSessionStatus = LabletSessionStatus.RUNNING,
    worker_id: str = "worker-01",
    cml_lab_id: str = "cml-lab-99",
    allocated_ports: dict[str, int] | None = None,
) -> MagicMock:
    """Create a mock LabletSession for observation tests."""
    session = MagicMock(spec=LabletSession)
    session.id.return_value = session_id

    state = MagicMock(spec=LabletSessionState)
    state.status = status
    state.worker_id = worker_id
    state.cml_lab_id = cml_lab_id
    state.allocated_ports = allocated_ports or {"PC_serial": 5041}
    state.observation_count = 0
    state.observed_at = None
    state.port_drift_detected = False

    session.state = state
    session.record_resource_observation = MagicMock()
    session.request_resource_observation = MagicMock()

    return session


SAMPLE_RESOURCES = {"total_cpu_cores": 4.0, "total_memory_mb": 8192, "nodes": []}
SAMPLE_PORTS = {"PC_serial": 5041, "PC_vnc": 5044}


# =============================================================================
# RecordResourceObservationCommandHandler Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.command
class TestRecordResourceObservationCommandHandler:
    """Tests for recording resource observations."""

    def _make_handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
    ) -> RecordResourceObservationCommandHandler:
        return RecordResourceObservationCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lablet_session_repository=mock_session_repository,
        )

    @pytest.mark.asyncio
    async def test_running_session_ok(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Recording observations on a RUNNING session succeeds."""
        session = _make_session(status=LabletSessionStatus.RUNNING)
        session.state.observation_count = 1
        session.state.observed_at = NOW
        session.state.port_drift_detected = False
        mock_session_repository.get_by_id_async.return_value = session

        handler = self._make_handler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_publishing_options, mock_session_repository)

        command = RecordResourceObservationCommand(
            session_id="session-001",
            observed_resources=SAMPLE_RESOURCES,
            observed_ports=SAMPLE_PORTS,
        )
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.status_code == 200
        session.record_resource_observation.assert_called_once_with(
            observed_resources=SAMPLE_RESOURCES,
            observed_ports=SAMPLE_PORTS,
        )
        mock_session_repository.update_async.assert_called_once_with(session)

    @pytest.mark.asyncio
    async def test_collecting_session_ok(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Recording observations on a COLLECTING session succeeds."""
        session = _make_session(status=LabletSessionStatus.COLLECTING)
        session.state.observation_count = 1
        session.state.observed_at = NOW
        session.state.port_drift_detected = False
        mock_session_repository.get_by_id_async.return_value = session

        handler = self._make_handler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_publishing_options, mock_session_repository)

        command = RecordResourceObservationCommand(
            session_id="session-001",
            observed_resources=SAMPLE_RESOURCES,
            observed_ports=SAMPLE_PORTS,
        )
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_wrong_state_fails(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Recording observations on a PENDING session returns 400."""
        session = _make_session(status=LabletSessionStatus.PENDING)
        mock_session_repository.get_by_id_async.return_value = session

        handler = self._make_handler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_publishing_options, mock_session_repository)

        command = RecordResourceObservationCommand(
            session_id="session-001",
            observed_resources=SAMPLE_RESOURCES,
            observed_ports=SAMPLE_PORTS,
        )
        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400
        session.record_resource_observation.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_found_fails(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Recording observations for non-existent session returns 404."""
        mock_session_repository.get_by_id_async.return_value = None

        handler = self._make_handler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_publishing_options, mock_session_repository)

        command = RecordResourceObservationCommand(
            session_id="nonexistent",
            observed_resources=SAMPLE_RESOURCES,
            observed_ports=SAMPLE_PORTS,
        )
        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 404


# =============================================================================
# RequestResourceObservationCommandHandler Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.command
class TestRequestResourceObservationCommandHandler:
    """Tests for requesting resource observation (manual trigger)."""

    def _make_handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
    ) -> RequestResourceObservationCommandHandler:
        return RequestResourceObservationCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lablet_session_repository=mock_session_repository,
        )

    @pytest.mark.asyncio
    async def test_running_session_ok(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Requesting observation on a RUNNING session succeeds."""
        session = _make_session(status=LabletSessionStatus.RUNNING)
        mock_session_repository.get_by_id_async.return_value = session

        handler = self._make_handler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_publishing_options, mock_session_repository)

        command = RequestResourceObservationCommand(session_id="session-001", requested_by="admin")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.status_code == 202
        session.request_resource_observation.assert_called_once_with(requested_by="admin")
        mock_session_repository.update_async.assert_called_once_with(session)

    @pytest.mark.asyncio
    async def test_wrong_state_fails(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Requesting observation on a STOPPED session returns 400."""
        session = _make_session(status=LabletSessionStatus.STOPPED)
        mock_session_repository.get_by_id_async.return_value = session

        handler = self._make_handler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_publishing_options, mock_session_repository)

        command = RequestResourceObservationCommand(session_id="session-001", requested_by="admin")
        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400
        session.request_resource_observation.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_found_fails(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Requesting observation for non-existent session returns 404."""
        mock_session_repository.get_by_id_async.return_value = None

        handler = self._make_handler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_publishing_options, mock_session_repository)

        command = RequestResourceObservationCommand(session_id="nonexistent", requested_by="admin")
        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_no_cml_lab_fails(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Requesting observation without CML lab returns 400."""
        session = _make_session(status=LabletSessionStatus.RUNNING, cml_lab_id=None)
        mock_session_repository.get_by_id_async.return_value = session

        handler = self._make_handler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_publishing_options, mock_session_repository)

        command = RequestResourceObservationCommand(session_id="session-001", requested_by="admin")
        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_no_worker_fails(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Requesting observation without worker returns 400."""
        session = _make_session(status=LabletSessionStatus.RUNNING, worker_id=None)
        mock_session_repository.get_by_id_async.return_value = session

        handler = self._make_handler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_publishing_options, mock_session_repository)

        command = RequestResourceObservationCommand(session_id="session-001", requested_by="admin")
        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400
