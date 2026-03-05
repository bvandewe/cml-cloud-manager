"""Unit tests for Phase 7D LabletSession CQRS command handlers.

Tests cover:
- CreateLabletSessionCommandHandler (5 tests)
- ScheduleLabletSessionCommandHandler (4 tests)
- TransitionLabletSessionCommandHandler (4 tests)
- TerminateLabletSessionCommandHandler (3 tests)

Pattern: pytest fixtures + MagicMock + AsyncMock, matching test_lab_commands.py style.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from application.commands.lablet_session.create_lablet_session_command import (
    CreateLabletSessionCommand,
    CreateLabletSessionCommandHandler,
)
from application.commands.lablet_session.schedule_lablet_session_command import (
    ScheduleLabletSessionCommand,
    ScheduleLabletSessionCommandHandler,
)
from application.commands.lablet_session.terminate_lablet_session_command import (
    TerminateLabletSessionCommand,
    TerminateLabletSessionCommandHandler,
)
from application.commands.lablet_session.transition_lablet_session_command import (
    TransitionLabletSessionCommand,
    TransitionLabletSessionCommandHandler,
)
from application.commands.worker.release_capacity_command import ReleaseCapacityCommand
from domain.entities.lablet_session import LabletSession, LabletSessionState
from domain.enums import CMLWorkerStatus, LabletDefinitionStatus, LabletSessionStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator

# =============================================================================
# Shared fixtures
# =============================================================================


@pytest.fixture
def mock_mediator() -> MagicMock:
    """Provide a mock Mediator."""
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
    mock.get_by_reservation_id_async = AsyncMock(return_value=None)
    mock.add_async = AsyncMock()
    mock.update_async = AsyncMock()
    return mock


@pytest.fixture
def mock_definition_repository() -> MagicMock:
    mock = MagicMock(spec=LabletDefinitionRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def mock_worker_repository() -> MagicMock:
    mock = MagicMock(spec=CMLWorkerRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    return mock


def _make_active_definition(definition_id: str = "def-001") -> MagicMock:
    """Create a mock LabletDefinition in ACTIVE state."""
    definition = MagicMock()
    definition.id.return_value = definition_id
    definition.state = MagicMock()
    definition.state.name = "Lab 101"
    definition.state.version = "1.0.0"
    definition.state.status = LabletDefinitionStatus.ACTIVE
    definition.state.resource_requirements = MagicMock(cpu_cores=2, memory_gb=4.0, storage_gb=20.0)
    return definition


def _make_session(
    session_id: str = "session-001",
    status: LabletSessionStatus = LabletSessionStatus.PENDING,
    definition_id: str = "def-001",
    worker_id: str | None = None,
    allocated_ports: dict[str, int] | None = None,
) -> MagicMock:
    """Create a mock LabletSession with configurable state."""
    session = MagicMock(spec=LabletSession)
    session.id.return_value = session_id

    state = MagicMock(spec=LabletSessionState)
    state.status = status
    state.definition_id = definition_id
    state.definition_name = "Lab 101"
    state.definition_version = "1.0.0"
    state.owner_id = "user-001"
    state.worker_id = worker_id
    state.allocated_ports = allocated_ports
    state.reservation_id = None
    state.timeslot_start = datetime.now(timezone.utc) + timedelta(hours=1)
    state.timeslot_end = datetime.now(timezone.utc) + timedelta(hours=2)
    state.created_at = datetime.now(timezone.utc)
    state.lab_record_id = None
    state.cml_lab_id = None
    state.user_session_id = None
    state.grading_session_id = None
    state.score_report_id = None
    state.grade_result = None
    state.started_at = None
    state.ended_at = None
    state.duration_seconds = None
    state.scheduled_at = None
    state.terminated_at = None
    state.state_history = []

    session.state = state

    # Mock transition methods
    session.schedule = MagicMock()
    session.start_instantiation = MagicMock()
    session.mark_ready = MagicMock()
    session.mark_running = MagicMock()
    session.start_collection = MagicMock()
    session.start_grading = MagicMock()
    session.start_stopping = MagicMock()
    session.mark_stopped = MagicMock()
    session.archive = MagicMock()
    session.terminate = MagicMock()
    session.release_ports = MagicMock()
    session.record_score = MagicMock()

    # Properties
    type(session).can_be_terminated = PropertyMock(return_value=True)

    return session


def _make_worker(
    worker_id: str = "worker-001",
    status: CMLWorkerStatus = CMLWorkerStatus.RUNNING,
) -> MagicMock:
    """Create a mock CMLWorker."""
    worker = MagicMock()
    worker.id.return_value = worker_id
    worker.state = MagicMock()
    worker.state.status = status
    worker.can_accommodate = MagicMock(return_value=True)
    worker.available_capacity = MagicMock()
    return worker


# =============================================================================
# CreateLabletSessionCommandHandler Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.command
class TestCreateLabletSessionCommandHandler:
    """Tests for creating a LabletSession."""

    def _make_handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
    ) -> CreateLabletSessionCommandHandler:
        return CreateLabletSessionCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lablet_session_repository=mock_session_repository,
            lablet_definition_repository=mock_definition_repository,
        )

    @pytest.mark.asyncio
    async def test_creates_session_with_valid_inputs(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
    ) -> None:
        """Verify successful session creation with all valid inputs."""
        definition = _make_active_definition()
        mock_definition_repository.get_by_id_async = AsyncMock(return_value=definition)

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_session_repository,
            mock_definition_repository,
        )

        now = datetime.now(timezone.utc)
        command = CreateLabletSessionCommand(
            definition_id="def-001",
            owner_id="user-001",
            timeslot_start=(now + timedelta(hours=1)).isoformat(),
            timeslot_end=(now + timedelta(hours=2)).isoformat(),
        )

        result = await handler.handle_async(command)
        assert result.is_success, f"Expected success, got: {result.error_message}"
        assert result.status_code == 201
        mock_session_repository.add_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_empty_definition_id(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
    ) -> None:
        """Verify bad_request when definition_id is empty."""
        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_session_repository,
            mock_definition_repository,
        )

        command = CreateLabletSessionCommand(
            definition_id="",
            owner_id="user-001",
            timeslot_start=datetime.now(timezone.utc).isoformat(),
            timeslot_end=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        )

        result = await handler.handle_async(command)
        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_definition(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
    ) -> None:
        """Verify not_found when definition doesn't exist."""
        mock_definition_repository.get_by_id_async = AsyncMock(return_value=None)

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_session_repository,
            mock_definition_repository,
        )

        now = datetime.now(timezone.utc)
        command = CreateLabletSessionCommand(
            definition_id="nonexistent",
            owner_id="user-001",
            timeslot_start=(now + timedelta(hours=1)).isoformat(),
            timeslot_end=(now + timedelta(hours=2)).isoformat(),
        )

        result = await handler.handle_async(command)
        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_rejects_inactive_definition(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
    ) -> None:
        """Verify bad_request when definition is not ACTIVE."""
        definition = _make_active_definition()
        definition.state.status = LabletDefinitionStatus.DEPRECATED
        mock_definition_repository.get_by_id_async = AsyncMock(return_value=definition)

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_session_repository,
            mock_definition_repository,
        )

        now = datetime.now(timezone.utc)
        command = CreateLabletSessionCommand(
            definition_id="def-001",
            owner_id="user-001",
            timeslot_start=(now + timedelta(hours=1)).isoformat(),
            timeslot_end=(now + timedelta(hours=2)).isoformat(),
        )

        result = await handler.handle_async(command)
        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_duplicate_reservation_id(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
    ) -> None:
        """Verify conflict when reservation_id already exists."""
        definition = _make_active_definition()
        mock_definition_repository.get_by_id_async = AsyncMock(return_value=definition)
        mock_session_repository.get_by_reservation_id_async = AsyncMock(return_value=_make_session())

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_session_repository,
            mock_definition_repository,
        )

        now = datetime.now(timezone.utc)
        command = CreateLabletSessionCommand(
            definition_id="def-001",
            owner_id="user-001",
            timeslot_start=(now + timedelta(hours=1)).isoformat(),
            timeslot_end=(now + timedelta(hours=2)).isoformat(),
            reservation_id="duplicate-res-001",
        )

        result = await handler.handle_async(command)
        assert not result.is_success
        assert result.status_code == 409


# =============================================================================
# ScheduleLabletSessionCommandHandler Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.command
class TestScheduleLabletSessionCommandHandler:
    """Tests for scheduling a LabletSession."""

    def _make_handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
        mock_worker_repository: MagicMock,
    ) -> ScheduleLabletSessionCommandHandler:
        return ScheduleLabletSessionCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lablet_session_repository=mock_session_repository,
            lablet_definition_repository=mock_definition_repository,
            cml_worker_repository=mock_worker_repository,
        )

    @pytest.mark.asyncio
    async def test_schedules_pending_session_on_running_worker(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
        mock_worker_repository: MagicMock,
    ) -> None:
        """Verify successful scheduling with valid inputs."""
        session = _make_session(status=LabletSessionStatus.PENDING)
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        worker = _make_worker(status=CMLWorkerStatus.RUNNING)
        mock_worker_repository.get_by_id_async = AsyncMock(return_value=worker)

        definition = _make_active_definition()
        mock_definition_repository.get_by_id_async = AsyncMock(return_value=definition)

        # Mock the capacity allocation (best-effort)
        alloc_result = MagicMock(is_success=True)
        mock_mediator.execute_async = AsyncMock(return_value=alloc_result)

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_session_repository,
            mock_definition_repository,
            mock_worker_repository,
        )

        command = ScheduleLabletSessionCommand(
            session_id="session-001",
            worker_id="worker-001",
            allocated_ports={"serial_1": 5041, "vnc_1": 5044},
            lab_record_id="lr-001",
        )

        result = await handler.handle_async(command)
        assert result.is_success, f"Expected success, got: {result.error_message}"
        session.schedule.assert_called_once()
        mock_session_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_scheduling_non_pending_session(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
        mock_worker_repository: MagicMock,
    ) -> None:
        """Verify conflict when session is not in PENDING state."""
        session = _make_session(status=LabletSessionStatus.RUNNING)
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_session_repository,
            mock_definition_repository,
            mock_worker_repository,
        )

        command = ScheduleLabletSessionCommand(
            session_id="session-001",
            worker_id="worker-001",
            allocated_ports={"serial_1": 5041},
            lab_record_id="lr-001",
        )

        result = await handler.handle_async(command)
        assert not result.is_success
        assert result.status_code == 409

    @pytest.mark.asyncio
    async def test_rejects_stopped_worker(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
        mock_worker_repository: MagicMock,
    ) -> None:
        """Verify conflict when worker is not RUNNING."""
        session = _make_session(status=LabletSessionStatus.PENDING)
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        worker = _make_worker(status=CMLWorkerStatus.STOPPED)
        mock_worker_repository.get_by_id_async = AsyncMock(return_value=worker)

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_session_repository,
            mock_definition_repository,
            mock_worker_repository,
        )

        command = ScheduleLabletSessionCommand(
            session_id="session-001",
            worker_id="worker-001",
            allocated_ports={"serial_1": 5041},
            lab_record_id="lr-001",
        )

        result = await handler.handle_async(command)
        assert not result.is_success
        assert result.status_code == 409

    @pytest.mark.asyncio
    async def test_rejects_insufficient_capacity(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
        mock_worker_repository: MagicMock,
    ) -> None:
        """Verify conflict when worker has insufficient capacity."""
        session = _make_session(status=LabletSessionStatus.PENDING)
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        worker = _make_worker(status=CMLWorkerStatus.RUNNING)
        worker.can_accommodate = MagicMock(return_value=False)
        mock_worker_repository.get_by_id_async = AsyncMock(return_value=worker)

        definition = _make_active_definition()
        mock_definition_repository.get_by_id_async = AsyncMock(return_value=definition)

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_session_repository,
            mock_definition_repository,
            mock_worker_repository,
        )

        command = ScheduleLabletSessionCommand(
            session_id="session-001",
            worker_id="worker-001",
            allocated_ports={"serial_1": 5041},
            lab_record_id="lr-001",
        )

        result = await handler.handle_async(command)
        assert not result.is_success
        assert result.status_code == 409


# =============================================================================
# TransitionLabletSessionCommandHandler Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.command
class TestTransitionLabletSessionCommandHandler:
    """Tests for generic session transitions."""

    def _make_handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock | None = None,
    ) -> TransitionLabletSessionCommandHandler:
        if mock_definition_repository is None:
            mock_definition_repository = MagicMock(spec=LabletDefinitionRepository)
            mock_definition_repository.get_by_id_async = AsyncMock(return_value=None)
        return TransitionLabletSessionCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lablet_session_repository=mock_session_repository,
            lablet_definition_repository=mock_definition_repository,
        )

    @pytest.mark.asyncio
    async def test_transitions_to_running(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Verify transition to RUNNING succeeds."""
        session = _make_session(status=LabletSessionStatus.READY)
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_session_repository,
        )

        command = TransitionLabletSessionCommand(session_id="session-001", target_status="running")
        result = await handler.handle_async(command)

        assert result.is_success
        session.mark_running.assert_called_once()
        mock_session_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_transitions_to_collecting(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Verify transition to COLLECTING succeeds."""
        session = _make_session(status=LabletSessionStatus.RUNNING)
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_session_repository,
        )

        command = TransitionLabletSessionCommand(session_id="session-001", target_status="collecting")
        result = await handler.handle_async(command)

        assert result.is_success
        session.start_collection.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_invalid_target_status(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Verify bad_request for invalid status value."""
        session = _make_session()
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_session_repository,
        )

        command = TransitionLabletSessionCommand(session_id="session-001", target_status="invalid_status")
        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_grading_without_dedicated_endpoint(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Verify GRADING transition is blocked (requires dedicated endpoint)."""
        session = _make_session(status=LabletSessionStatus.COLLECTING)
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_session_repository,
        )

        command = TransitionLabletSessionCommand(session_id="session-001", target_status="grading")
        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_stopping_releases_capacity(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
    ) -> None:
        """Verify STOPPING transition releases worker capacity using definition resources."""
        session = _make_session(
            status=LabletSessionStatus.COLLECTING,
            worker_id="worker-001",
            definition_id="def-001",
        )
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        definition = _make_active_definition("def-001")
        mock_definition_repository.get_by_id_async = AsyncMock(return_value=definition)

        release_result = MagicMock()
        release_result.is_success = True
        mock_mediator.execute_async = AsyncMock(return_value=release_result)

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_session_repository,
            mock_definition_repository,
        )

        command = TransitionLabletSessionCommand(session_id="session-001", target_status="stopping")
        result = await handler.handle_async(command)

        assert result.is_success
        session.start_stopping.assert_called_once()

        # Verify ReleaseCapacityCommand was dispatched with definition resources
        release_call = mock_mediator.execute_async.call_args
        release_cmd = release_call[0][0]
        assert isinstance(release_cmd, ReleaseCapacityCommand)
        assert release_cmd.worker_id == "worker-001"
        assert release_cmd.session_id == "session-001"
        assert release_cmd.cpu_cores == 2
        assert release_cmd.memory_gb == 4.0
        assert release_cmd.storage_gb == 20.0

        # Verify response includes capacity_released flag
        assert result.data["capacity_released"] is True


# =============================================================================
# TerminateLabletSessionCommandHandler Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.command
class TestTerminateLabletSessionCommandHandler:
    """Tests for terminating a LabletSession."""

    def _make_handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
    ) -> TerminateLabletSessionCommandHandler:
        return TerminateLabletSessionCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lablet_session_repository=mock_session_repository,
            lablet_definition_repository=mock_definition_repository,
        )

    @pytest.mark.asyncio
    async def test_terminates_running_session(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
    ) -> None:
        """Verify successful termination of a running session."""
        session = _make_session(
            status=LabletSessionStatus.RUNNING,
            worker_id="worker-001",
        )
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        # Mock mediator for ReleaseCapacityCommand (best-effort)
        mock_mediator.execute_async = AsyncMock(return_value=MagicMock(is_success=True))

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_session_repository,
            mock_definition_repository,
        )

        command = TerminateLabletSessionCommand(
            session_id="session-001",
            terminated_by="admin",
            reason="Manual termination",
        )

        result = await handler.handle_async(command)
        assert result.is_success, f"Expected success, got: {result.error_message}"
        session.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_terminating_already_terminated(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
    ) -> None:
        """Verify conflict when session is already terminated."""
        session = _make_session(status=LabletSessionStatus.TERMINATED)
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_session_repository,
            mock_definition_repository,
        )

        command = TerminateLabletSessionCommand(
            session_id="session-001",
            terminated_by="admin",
        )

        result = await handler.handle_async(command)
        assert not result.is_success
        assert result.status_code == 409

    @pytest.mark.asyncio
    async def test_rejects_empty_session_id(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
    ) -> None:
        """Verify bad_request when session_id is empty."""
        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_session_repository,
            mock_definition_repository,
        )

        command = TerminateLabletSessionCommand(session_id="", terminated_by="admin")
        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400
