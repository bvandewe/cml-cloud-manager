"""Unit tests for AllocateLabRecordPortsCommandHandler (ADR-031 / ADR-032).

Tests cover:
- Nominal allocation via PortAllocationService (etcd)
- Idempotency — already-allocated returns existing ports
- No definition → skipped
- Definition not found → skipped
- No port template → skipped
- Empty port template → skipped
- Port allocation failure → conflict (409)
- LabRecord not found → 404
- LabRecord.allocate_ports() called with result mapping

Pattern: pytest fixtures + MagicMock + AsyncMock, matching test_resource_observation_commands.py.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator

from application.commands.lab.allocate_lab_record_ports_command import (
    AllocateLabRecordPortsCommand,
    AllocateLabRecordPortsCommandHandler,
)
from application.services.port_allocation_service import PortAllocationResult, PortAllocationService
from domain.entities.lab_record import LabRecord, LabRecordState
from domain.entities.lablet_definition import LabletDefinition, LabletDefinitionState
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.value_objects.port_template import PortDefinition, PortTemplate

# =============================================================================
# Shared fixtures
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


@pytest.fixture
def mock_port_service() -> MagicMock:
    mock = MagicMock(spec=PortAllocationService)
    mock.allocate_ports = AsyncMock()
    return mock


# =============================================================================
# Helpers
# =============================================================================


def _make_lab_record(
    record_id: str = "lr-001",
    based_on_definition_id: str | None = "def-001",
    allocated_ports: dict[str, int] | None = None,
) -> MagicMock:
    """Create a mock LabRecord with state."""
    lab_record = MagicMock(spec=LabRecord)
    lab_record.id.return_value = record_id

    state = MagicMock(spec=LabRecordState)
    state.based_on_definition_id = based_on_definition_id
    state.allocated_ports = allocated_ports

    lab_record.state = state
    lab_record.allocate_ports = MagicMock()

    return lab_record


def _make_definition(
    definition_id: str = "def-001",
    port_template: PortTemplate | dict | None = None,
    sync_status: str | None = "success",
    form_qualified_name: str | None = "Exam CCNP v1.0 LAB 1.1",
) -> MagicMock:
    """Create a mock LabletDefinition with state."""
    definition = MagicMock(spec=LabletDefinition)
    definition.id.return_value = definition_id

    state = MagicMock(spec=LabletDefinitionState)
    state.port_template = port_template
    state.sync_status = sync_status
    state.form_qualified_name = form_qualified_name

    definition.state = state
    return definition


SAMPLE_PORT_TEMPLATE = PortTemplate(
    ports=(
        PortDefinition(name="serial_1", protocol="tcp"),
        PortDefinition(name="vnc_1", protocol="tcp"),
    )
)

SAMPLE_ALLOCATED = {"serial_1": 5041, "vnc_1": 5044}


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.command
class TestAllocateLabRecordPortsCommandHandler:
    """Tests for port allocation command handler."""

    def _make_handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_record_repository: MagicMock,
        mock_definition_repository: MagicMock,
        mock_port_service: MagicMock,
    ) -> AllocateLabRecordPortsCommandHandler:
        return AllocateLabRecordPortsCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lab_record_repository=mock_lab_record_repository,
            lablet_definition_repository=mock_definition_repository,
            port_allocation_service=mock_port_service,
        )

    @pytest.mark.asyncio
    async def test_nominal_allocation(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_record_repository: MagicMock,
        mock_definition_repository: MagicMock,
        mock_port_service: MagicMock,
    ) -> None:
        """Nominal: allocates ports from etcd and stores on LabRecord."""
        lab_record = _make_lab_record(allocated_ports=None)
        definition = _make_definition(port_template=SAMPLE_PORT_TEMPLATE)

        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_definition_repository.get_by_id_async.return_value = definition
        mock_port_service.allocate_ports.return_value = PortAllocationResult(
            success=True,
            allocated_ports=SAMPLE_ALLOCATED,
        )

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_lab_record_repository,
            mock_definition_repository,
            mock_port_service,
        )
        command = AllocateLabRecordPortsCommand(lab_record_id="lr-001", worker_id="w-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.status_code == 200
        assert result.data["allocated_ports"] == SAMPLE_ALLOCATED

        # Verify etcd allocation was keyed by lab_record_id
        mock_port_service.allocate_ports.assert_awaited_once()
        call_kwargs = mock_port_service.allocate_ports.call_args.kwargs
        assert call_kwargs["session_id"] == "lr-001"  # keyed by lab_record_id per ADR-032
        assert call_kwargs["worker_id"] == "w-001"

        # Verify LabRecord.allocate_ports() called
        lab_record.allocate_ports.assert_called_once_with(SAMPLE_ALLOCATED)
        mock_lab_record_repository.update_async.assert_awaited_once_with(lab_record)

    @pytest.mark.asyncio
    async def test_idempotency_already_allocated(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_record_repository: MagicMock,
        mock_definition_repository: MagicMock,
        mock_port_service: MagicMock,
    ) -> None:
        """Idempotent: returns existing ports without re-allocating."""
        lab_record = _make_lab_record(allocated_ports=SAMPLE_ALLOCATED)
        mock_lab_record_repository.get_by_id_async.return_value = lab_record

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_lab_record_repository,
            mock_definition_repository,
            mock_port_service,
        )
        command = AllocateLabRecordPortsCommand(lab_record_id="lr-001", worker_id="w-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["already_allocated"] is True
        assert result.data["allocated_ports"] == SAMPLE_ALLOCATED

        # No allocation or definition lookup
        mock_port_service.allocate_ports.assert_not_awaited()
        mock_definition_repository.get_by_id_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_lab_record_not_found(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_record_repository: MagicMock,
        mock_definition_repository: MagicMock,
        mock_port_service: MagicMock,
    ) -> None:
        """Returns 404 when LabRecord does not exist."""
        mock_lab_record_repository.get_by_id_async.return_value = None

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_lab_record_repository,
            mock_definition_repository,
            mock_port_service,
        )
        command = AllocateLabRecordPortsCommand(lab_record_id="nonexistent", worker_id="w-001")
        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_no_definition_id_skips(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_record_repository: MagicMock,
        mock_definition_repository: MagicMock,
        mock_port_service: MagicMock,
    ) -> None:
        """Skips allocation when LabRecord has no associated definition."""
        lab_record = _make_lab_record(based_on_definition_id=None, allocated_ports=None)
        mock_lab_record_repository.get_by_id_async.return_value = lab_record

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_lab_record_repository,
            mock_definition_repository,
            mock_port_service,
        )
        command = AllocateLabRecordPortsCommand(lab_record_id="lr-001", worker_id="w-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["skipped"] is True
        assert result.data["reason"] == "no_definition"

    @pytest.mark.asyncio
    async def test_definition_not_found_skips(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_record_repository: MagicMock,
        mock_definition_repository: MagicMock,
        mock_port_service: MagicMock,
    ) -> None:
        """Skips allocation when the definition doesn't exist."""
        lab_record = _make_lab_record(allocated_ports=None)
        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_definition_repository.get_by_id_async.return_value = None

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_lab_record_repository,
            mock_definition_repository,
            mock_port_service,
        )
        command = AllocateLabRecordPortsCommand(lab_record_id="lr-001", worker_id="w-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["skipped"] is True
        assert result.data["reason"] == "definition_not_found"

    @pytest.mark.asyncio
    async def test_no_port_template_skips(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_record_repository: MagicMock,
        mock_definition_repository: MagicMock,
        mock_port_service: MagicMock,
    ) -> None:
        """Skips allocation when definition has no port template."""
        lab_record = _make_lab_record(allocated_ports=None)
        definition = _make_definition(port_template=None)

        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_definition_repository.get_by_id_async.return_value = definition

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_lab_record_repository,
            mock_definition_repository,
            mock_port_service,
        )
        command = AllocateLabRecordPortsCommand(lab_record_id="lr-001", worker_id="w-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["skipped"] is True
        assert result.data["reason"] == "no_port_template"

    @pytest.mark.asyncio
    async def test_empty_port_template_skips(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_record_repository: MagicMock,
        mock_definition_repository: MagicMock,
        mock_port_service: MagicMock,
    ) -> None:
        """Skips allocation when port template has zero ports."""
        lab_record = _make_lab_record(allocated_ports=None)
        empty_template = PortTemplate(ports=())
        definition = _make_definition(port_template=empty_template)

        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_definition_repository.get_by_id_async.return_value = definition

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_lab_record_repository,
            mock_definition_repository,
            mock_port_service,
        )
        command = AllocateLabRecordPortsCommand(lab_record_id="lr-001", worker_id="w-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["skipped"] is True
        assert result.data["reason"] == "empty_port_template"

    @pytest.mark.asyncio
    async def test_port_template_from_dict(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_record_repository: MagicMock,
        mock_definition_repository: MagicMock,
        mock_port_service: MagicMock,
    ) -> None:
        """Handles port_template stored as dict (MongoDB deserialization)."""
        lab_record = _make_lab_record(allocated_ports=None)
        definition = _make_definition(
            port_template={"ports": [{"name": "serial_1", "protocol": "tcp"}]},
        )

        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_definition_repository.get_by_id_async.return_value = definition
        mock_port_service.allocate_ports.return_value = PortAllocationResult(
            success=True,
            allocated_ports={"serial_1": 5041},
        )

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_lab_record_repository,
            mock_definition_repository,
            mock_port_service,
        )
        command = AllocateLabRecordPortsCommand(lab_record_id="lr-001", worker_id="w-001")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["allocated_ports"] == {"serial_1": 5041}

    @pytest.mark.asyncio
    async def test_allocation_failure_returns_conflict(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_record_repository: MagicMock,
        mock_definition_repository: MagicMock,
        mock_port_service: MagicMock,
    ) -> None:
        """Returns 409 Conflict when port allocation fails."""
        lab_record = _make_lab_record(allocated_ports=None)
        definition = _make_definition(port_template=SAMPLE_PORT_TEMPLATE)

        mock_lab_record_repository.get_by_id_async.return_value = lab_record
        mock_definition_repository.get_by_id_async.return_value = definition
        mock_port_service.allocate_ports.return_value = PortAllocationResult(
            success=False,
            error="No ports available in range 2000-9999",
        )

        handler = self._make_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_publishing_options,
            mock_lab_record_repository,
            mock_definition_repository,
            mock_port_service,
        )
        command = AllocateLabRecordPortsCommand(lab_record_id="lr-001", worker_id="w-001")
        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 409

        # LabRecord should NOT be updated
        lab_record.allocate_ports.assert_not_called()
        mock_lab_record_repository.update_async.assert_not_awaited()
