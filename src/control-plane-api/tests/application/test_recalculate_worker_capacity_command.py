"""Unit tests for RecalculateWorkerCapacityCommandHandler.

Tests cover:
- Nominal recalculation: stale sessions removed, capacity reset to active-only sum
- Worker not found → 404
- All sessions active → capacity recalculated from definitions
- All sessions stale → capacity reset to zero, session_ids cleared
- Mixed active/stale → correct separation
- Missing definition → session counted as active but with zero capacity
- Session not found in DB → treated as stale

Pattern: pytest fixtures + MagicMock + AsyncMock, matching test_expire_lablet_session_command.py.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator

from application.commands.worker.recalculate_worker_capacity_command import (
    RecalculateWorkerCapacityCommand,
    RecalculateWorkerCapacityCommandHandler,
)
from domain.entities.cml_worker import CMLWorker, CMLWorkerState
from domain.entities.lablet_definition import LabletDefinition, LabletDefinitionState
from domain.entities.lablet_session import LabletSession, LabletSessionState
from domain.enums import LabletSessionStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from domain.value_objects.worker_capacity import WorkerCapacity

# =============================================================================
# Fixtures
# =============================================================================


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
def mock_worker_repository() -> MagicMock:
    mock = MagicMock(spec=CMLWorkerRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    mock.update_async = AsyncMock()
    return mock


@pytest.fixture
def mock_session_repository() -> MagicMock:
    mock = MagicMock(spec=LabletSessionRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def mock_definition_repository() -> MagicMock:
    mock = MagicMock(spec=LabletDefinitionRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    return mock


# =============================================================================
# Helpers
# =============================================================================


def _make_worker(
    worker_id: str = "worker-001",
    session_ids: list[str] | None = None,
    allocated_cpu: int = 24,
    allocated_memory: int = 48,
    allocated_storage: int = 240,
) -> MagicMock:
    """Create a mock CMLWorker with state."""
    worker = MagicMock(spec=CMLWorker)
    worker.id.return_value = worker_id

    state = MagicMock(spec=CMLWorkerState)
    state.session_ids = session_ids or []
    state.allocated_capacity = WorkerCapacity(
        cpu_cores=allocated_cpu,
        memory_gb=allocated_memory,
        storage_gb=allocated_storage,
    )

    worker.state = state
    worker.recalculate_capacity = MagicMock()

    # After recalculate, simulate the capacity being updated
    def simulate_recalculate(**kwargs):
        new_capacity = WorkerCapacity(
            cpu_cores=kwargs.get("recalculated_cpu_cores", 0),
            memory_gb=kwargs.get("recalculated_memory_gb", 0),
            storage_gb=kwargs.get("recalculated_storage_gb", 0),
            max_nodes=kwargs.get("recalculated_max_nodes"),
        )
        state.allocated_capacity = new_capacity
        state.session_ids = kwargs.get("active_session_ids", [])
        worker.available_capacity = MagicMock()
        worker.available_capacity.to_dict.return_value = {"cpu_cores": 48 - new_capacity.cpu_cores, "memory_gb": 188 - new_capacity.memory_gb, "storage_gb": 247 - new_capacity.storage_gb}

    worker.recalculate_capacity.side_effect = simulate_recalculate
    worker.available_capacity = MagicMock()
    worker.available_capacity.to_dict.return_value = {"cpu_cores": 24, "memory_gb": 140, "storage_gb": 7}

    return worker


def _make_session(
    session_id: str,
    status: LabletSessionStatus = LabletSessionStatus.RUNNING,
    definition_id: str = "def-001",
) -> MagicMock:
    """Create a mock LabletSession with state."""
    session = MagicMock(spec=LabletSession)
    session.id.return_value = session_id

    state = MagicMock(spec=LabletSessionState)
    state.status = status
    state.definition_id = definition_id

    session.state = state
    return session


def _make_definition(
    definition_id: str = "def-001",
    cpu_cores: int = 4,
    memory_gb: int = 8,
    storage_gb: int = 50,
    node_count: int | None = None,
) -> MagicMock:
    """Create a mock LabletDefinition with resource requirements."""
    definition = MagicMock(spec=LabletDefinition)
    definition.id.return_value = definition_id

    state = MagicMock(spec=LabletDefinitionState)
    resource_reqs = MagicMock()
    resource_reqs.cpu_cores = cpu_cores
    resource_reqs.memory_gb = memory_gb
    resource_reqs.storage_gb = storage_gb
    resource_reqs.max_nodes = None
    state.resource_requirements = resource_reqs
    state.node_count = node_count

    definition.state = state
    return definition


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.command
class TestRecalculateWorkerCapacityCommandHandler:
    """Tests for worker capacity recalculation command handler."""

    def _make_handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_worker_repository: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
    ) -> RecalculateWorkerCapacityCommandHandler:
        return RecalculateWorkerCapacityCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            cml_worker_repository=mock_worker_repository,
            lablet_session_repository=mock_session_repository,
            lablet_definition_repository=mock_definition_repository,
        )

    @pytest.mark.asyncio
    async def test_worker_not_found(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_worker_repository: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
    ) -> None:
        """Returns 404 when worker does not exist."""
        mock_worker_repository.get_by_id_async.return_value = None

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_worker_repository,
            mock_session_repository,
            mock_definition_repository,
        )
        command = RecalculateWorkerCapacityCommand(worker_id="nonexistent")
        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_no_sessions_resets_to_zero(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_worker_repository: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
    ) -> None:
        """Worker with no tracked sessions gets capacity reset to zero."""
        worker = _make_worker(session_ids=[])
        mock_worker_repository.get_by_id_async.return_value = worker

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_worker_repository,
            mock_session_repository,
            mock_definition_repository,
        )
        command = RecalculateWorkerCapacityCommand(worker_id="worker-001")
        result = await handler.handle_async(command)

        assert result.is_success
        worker.recalculate_capacity.assert_called_once_with(
            recalculated_cpu_cores=0,
            recalculated_memory_gb=0,
            recalculated_storage_gb=0,
            recalculated_max_nodes=None,
            active_session_ids=[],
            stale_session_ids=[],
        )

    @pytest.mark.asyncio
    async def test_all_sessions_stale_resets_to_zero(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_worker_repository: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
    ) -> None:
        """All tracked sessions in terminal states → capacity reset to zero."""
        worker = _make_worker(
            session_ids=["s1", "s2", "s3"],
            allocated_cpu=12,
            allocated_memory=24,
            allocated_storage=150,
        )
        mock_worker_repository.get_by_id_async.return_value = worker

        # All sessions in terminal states
        mock_session_repository.get_by_id_async.side_effect = [
            _make_session("s1", LabletSessionStatus.EXPIRED),
            _make_session("s2", LabletSessionStatus.TERMINATED),
            _make_session("s3", LabletSessionStatus.ARCHIVED),
        ]

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_worker_repository,
            mock_session_repository,
            mock_definition_repository,
        )
        command = RecalculateWorkerCapacityCommand(worker_id="worker-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["stale_sessions_removed"] == ["s1", "s2", "s3"]
        assert result.data["active_session_ids"] == []

        worker.recalculate_capacity.assert_called_once_with(
            recalculated_cpu_cores=0,
            recalculated_memory_gb=0,
            recalculated_storage_gb=0,
            recalculated_max_nodes=None,
            active_session_ids=[],
            stale_session_ids=["s1", "s2", "s3"],
        )

    @pytest.mark.asyncio
    async def test_mixed_active_and_stale_sessions(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_worker_repository: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
    ) -> None:
        """Mixed active and stale sessions: only active sessions contribute capacity."""
        worker = _make_worker(
            session_ids=["active-1", "expired-1", "active-2"],
            allocated_cpu=24,
            allocated_memory=48,
            allocated_storage=240,
        )
        mock_worker_repository.get_by_id_async.return_value = worker

        mock_session_repository.get_by_id_async.side_effect = [
            _make_session("active-1", LabletSessionStatus.RUNNING, "def-A"),
            _make_session("expired-1", LabletSessionStatus.EXPIRED, "def-B"),
            _make_session("active-2", LabletSessionStatus.INSTANTIATING, "def-C"),
        ]

        # Definitions for active sessions
        def_a = _make_definition("def-A", cpu_cores=4, memory_gb=8, storage_gb=50)
        def_c = _make_definition("def-C", cpu_cores=2, memory_gb=4, storage_gb=30)

        async def get_definition(def_id):
            return {"def-A": def_a, "def-C": def_c}.get(def_id)

        mock_definition_repository.get_by_id_async.side_effect = get_definition

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_worker_repository,
            mock_session_repository,
            mock_definition_repository,
        )
        command = RecalculateWorkerCapacityCommand(worker_id="worker-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["active_session_ids"] == ["active-1", "active-2"]
        assert result.data["stale_sessions_removed"] == ["expired-1"]

        # Capacity = def-A + def-C = (4+2, 8+4, 50+30) = (6, 12, 80)
        worker.recalculate_capacity.assert_called_once_with(
            recalculated_cpu_cores=6,
            recalculated_memory_gb=12,
            recalculated_storage_gb=80,
            recalculated_max_nodes=None,
            active_session_ids=["active-1", "active-2"],
            stale_session_ids=["expired-1"],
        )

    @pytest.mark.asyncio
    async def test_session_not_in_db_treated_as_stale(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_worker_repository: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
    ) -> None:
        """Session tracked on worker but not found in DB → treated as stale."""
        worker = _make_worker(session_ids=["ghost-session"])
        mock_worker_repository.get_by_id_async.return_value = worker
        mock_session_repository.get_by_id_async.return_value = None  # Not found

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_worker_repository,
            mock_session_repository,
            mock_definition_repository,
        )
        command = RecalculateWorkerCapacityCommand(worker_id="worker-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["stale_sessions_removed"] == ["ghost-session"]
        assert result.data["stale_reasons"]["ghost-session"] == "session_not_found"

    @pytest.mark.asyncio
    async def test_missing_definition_still_counts_session_active(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_worker_repository: MagicMock,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
    ) -> None:
        """Active session with missing definition: kept in session_ids but contributes 0 capacity."""
        worker = _make_worker(session_ids=["s1"])
        mock_worker_repository.get_by_id_async.return_value = worker

        mock_session_repository.get_by_id_async.return_value = _make_session("s1", LabletSessionStatus.RUNNING, "def-missing")
        mock_definition_repository.get_by_id_async.return_value = None

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_worker_repository,
            mock_session_repository,
            mock_definition_repository,
        )
        command = RecalculateWorkerCapacityCommand(worker_id="worker-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["active_session_ids"] == ["s1"]

        # Capacity is 0 because definition wasn't found
        worker.recalculate_capacity.assert_called_once_with(
            recalculated_cpu_cores=0,
            recalculated_memory_gb=0,
            recalculated_storage_gb=0,
            recalculated_max_nodes=None,
            active_session_ids=["s1"],
            stale_session_ids=[],
        )
