"""Unit tests for Phase 3 scaling commands.

Tests cover:
- RequestScaleUpCommand: template resolution, scaling constraints, worker creation,
  disabled template, template not found, max workers per region, pending workers
- DrainWorkerCommand: RUNNING-only guard, status transitions, drain reason tracking

These commands are the control-plane-api entry points for auto-scaling.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from application.commands.worker import (
    DrainWorkerCommand,
    DrainWorkerCommandHandler,
    RequestScaleUpCommand,
    RequestScaleUpCommandHandler,
)
from application.services.worker_template_service import TemplateNotFoundError, WorkerTemplateService
from application.settings import Settings
from domain.entities.cml_worker import CMLWorker
from domain.enums import CMLWorkerStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.value_objects.worker_capacity import WorkerCapacity
from integration.enums import Ec2InstanceType

# =============================================================================
# Shared Fixtures
# =============================================================================


@pytest.fixture
def mock_worker_repository() -> AsyncMock:
    """Create a mock CMLWorkerRepository."""
    repo = AsyncMock(spec=CMLWorkerRepository)
    repo.get_by_id_async = AsyncMock(return_value=None)
    # add_async should return the worker entity (simulates repo returning saved entity)
    repo.add_async = AsyncMock(side_effect=lambda worker, *a, **kw: worker)
    repo.update_async = AsyncMock(side_effect=lambda worker, *a, **kw: worker)
    repo.get_active_workers_async = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_mediator() -> MagicMock:
    """Create a mock Mediator."""
    mediator = MagicMock()
    mediator.execute_async = AsyncMock()
    return mediator


@pytest.fixture
def mock_mapper() -> MagicMock:
    """Create a mock Mapper."""
    return MagicMock()


@pytest.fixture
def mock_cloud_event_bus() -> MagicMock:
    """Create a mock CloudEventBus."""
    bus = MagicMock()
    bus.output_stream = MagicMock()
    bus.output_stream.on_next = MagicMock()
    return bus


@pytest.fixture
def mock_cloud_event_options() -> MagicMock:
    """Create mock CloudEventPublishingOptions."""
    opts = MagicMock()
    opts.source = "test-source"
    opts.type_prefix = "test.prefix"
    return opts


@pytest.fixture
def mock_template_service() -> AsyncMock:
    """Create a mock WorkerTemplateService."""
    return AsyncMock(spec=WorkerTemplateService)


@pytest.fixture
def mock_settings() -> Settings:
    """Create test settings with scaling constraints."""
    settings = MagicMock(spec=Settings)
    settings.max_workers_per_region = 5
    settings.aws_access_key_id = "test-key"
    settings.cml_worker_ami_names = {"us-east-1": "CML-2.9-Ubuntu"}
    return settings


@pytest.fixture
def sample_template() -> MagicMock:
    """Create a mock WorkerTemplate (enabled, metal)."""
    template = MagicMock()
    template.state = MagicMock()
    template.state.enabled = True
    template.state.instance_type = Ec2InstanceType.METAL
    template.state.ami_name_pattern = "CML-2.9-Ubuntu-*"
    template.state.capacity = WorkerCapacity(cpu_cores=48, memory_gb=192, storage_gb=900)
    return template


@pytest.fixture
def sample_disabled_template() -> MagicMock:
    """Create a mock disabled WorkerTemplate."""
    template = MagicMock()
    template.state = MagicMock()
    template.state.enabled = False
    template.state.instance_type = Ec2InstanceType.METAL
    return template


@pytest.fixture
def sample_running_worker() -> CMLWorker:
    """Create a CMLWorker in RUNNING state."""
    worker = CMLWorker(
        name="test-worker",
        aws_region="us-east-1",
        instance_type="m5zn.metal",
    )
    worker.update_status(CMLWorkerStatus.RUNNING)
    return worker


@pytest.fixture
def sample_pending_worker() -> CMLWorker:
    """Create a CMLWorker in PENDING state."""
    return CMLWorker(
        name="pending-worker",
        aws_region="us-east-1",
        instance_type="m5zn.metal",
    )


@pytest.fixture
def sample_stopped_worker() -> CMLWorker:
    """Create a CMLWorker in STOPPED state."""
    worker = CMLWorker(
        name="stopped-worker",
        aws_region="us-east-1",
        instance_type="m5zn.metal",
    )
    worker.update_status(CMLWorkerStatus.STOPPED)
    return worker


# =============================================================================
# RequestScaleUpCommand Tests
# =============================================================================


class TestRequestScaleUpCommandHandler:
    """Tests for RequestScaleUpCommandHandler."""

    @pytest.fixture
    def handler(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_cloud_event_options,
        mock_worker_repository,
        mock_template_service,
        mock_settings,
    ) -> RequestScaleUpCommandHandler:
        """Create handler with mocked dependencies."""
        return RequestScaleUpCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_options,
            cml_worker_repository=mock_worker_repository,
            template_service=mock_template_service,
            settings=mock_settings,
        )

    @pytest.mark.asyncio
    @pytest.mark.command
    async def test_scale_up_success(self, handler, mock_template_service, mock_worker_repository, sample_template):
        """Test successful scale-up creates a PENDING worker."""
        # Arrange
        mock_template_service.get_template_by_name_async = AsyncMock(return_value=sample_template)

        command = RequestScaleUpCommand(
            template_name="metal",
            reason="insufficient capacity for lablet inst-001",
            requested_by="resource-scheduler",
        )

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert result.is_success
        assert result.status_code == 201
        assert result.data["template_name"] == "metal"
        assert result.data["status"] == "pending"  # CMLWorkerStatus.PENDING.value
        assert result.data["reason"] == "insufficient capacity for lablet inst-001"
        assert result.data["requested_by"] == "resource-scheduler"
        mock_worker_repository.add_async.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.command
    async def test_scale_up_template_not_found(self, handler, mock_template_service):
        """Test scale-up fails when template doesn't exist.

        _resolve_template catches TemplateNotFoundError and returns None,
        which triggers a not_found (404) response.
        """
        # Arrange
        mock_template_service.get_template_by_name_async = AsyncMock(side_effect=TemplateNotFoundError("Template 'nonexistent' not found"))

        command = RequestScaleUpCommand(
            template_name="nonexistent",
            reason="test",
        )

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    @pytest.mark.command
    async def test_scale_up_disabled_template(self, handler, mock_template_service, sample_disabled_template):
        """Test scale-up fails when template is disabled."""
        # Arrange
        mock_template_service.get_template_by_name_async = AsyncMock(return_value=sample_disabled_template)

        command = RequestScaleUpCommand(
            template_name="metal",
            reason="test",
        )

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    @pytest.mark.command
    async def test_scale_up_max_workers_exceeded(self, handler, mock_template_service, mock_worker_repository, sample_template, sample_running_worker):
        """Test scale-up fails when max workers per region is reached."""
        # Arrange
        mock_template_service.get_template_by_name_async = AsyncMock(return_value=sample_template)
        # Return 5 active workers (at limit)
        workers = []
        for i in range(5):
            w = CMLWorker(name=f"worker-{i}", aws_region="us-east-1", instance_type="m5zn.metal")
            w.update_status(CMLWorkerStatus.RUNNING)
            workers.append(w)
        mock_worker_repository.get_active_workers_async = AsyncMock(return_value=workers)

        command = RequestScaleUpCommand(
            template_name="metal",
            reason="test",
        )

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert not result.is_success
        assert result.status_code == 409  # Conflict

    @pytest.mark.asyncio
    @pytest.mark.command
    async def test_scale_up_worker_name_includes_template(self, handler, mock_template_service, mock_worker_repository, sample_template):
        """Test that created worker name includes template name."""
        # Arrange
        mock_template_service.get_template_by_name_async = AsyncMock(return_value=sample_template)

        command = RequestScaleUpCommand(
            template_name="metal",
            reason="test",
        )

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert result.is_success
        assert "metal" in result.data["name"]

    @pytest.mark.asyncio
    @pytest.mark.command
    async def test_scale_up_uses_ami_from_template(self, handler, mock_template_service, mock_worker_repository, sample_template):
        """Test that AMI name comes from template when available."""
        # Arrange
        sample_template.state.ami_name_pattern = "CML-Custom-AMI"
        mock_template_service.get_template_by_name_async = AsyncMock(return_value=sample_template)

        command = RequestScaleUpCommand(
            template_name="metal",
            reason="test",
        )

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert result.is_success
        mock_worker_repository.add_async.assert_called_once()
        # Verify the worker passed to add_async has the correct AMI
        saved_worker = mock_worker_repository.add_async.call_args[0][0]
        assert saved_worker.state.ami_name == "CML-Custom-AMI"

    @pytest.mark.asyncio
    @pytest.mark.command
    async def test_scale_up_falls_back_to_settings_ami(self, handler, mock_template_service, mock_worker_repository, sample_template, mock_settings):
        """Test AMI fallback to settings when template has no AMI pattern."""
        # Arrange
        sample_template.state.ami_name_pattern = ""  # No AMI in template
        mock_template_service.get_template_by_name_async = AsyncMock(return_value=sample_template)

        command = RequestScaleUpCommand(
            template_name="metal",
            reason="test",
        )

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert result.is_success
        saved_worker = mock_worker_repository.add_async.call_args[0][0]
        assert saved_worker.state.ami_name == "CML-2.9-Ubuntu"

    @pytest.mark.asyncio
    @pytest.mark.command
    async def test_scale_up_sets_desired_status_running(self, handler, mock_template_service, mock_worker_repository, sample_template):
        """Test that created worker has desired_status=RUNNING."""
        # Arrange
        mock_template_service.get_template_by_name_async = AsyncMock(return_value=sample_template)

        command = RequestScaleUpCommand(
            template_name="metal",
            reason="test",
        )

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert result.is_success
        assert result.data["desired_status"] == "running"  # CMLWorkerStatus.RUNNING.value


# =============================================================================
# DrainWorkerCommand Tests
# =============================================================================


class TestDrainWorkerCommandHandler:
    """Tests for DrainWorkerCommandHandler."""

    @pytest.fixture
    def handler(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_cloud_event_options,
        mock_worker_repository,
    ) -> DrainWorkerCommandHandler:
        """Create handler with mocked dependencies."""
        return DrainWorkerCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_options,
            cml_worker_repository=mock_worker_repository,
        )

    @pytest.mark.asyncio
    @pytest.mark.command
    async def test_drain_running_worker_success(self, handler, mock_worker_repository, sample_running_worker):
        """Test successful drain of a RUNNING worker."""
        # Arrange
        mock_worker_repository.get_by_id_async = AsyncMock(return_value=sample_running_worker)

        command = DrainWorkerCommand(
            worker_id=sample_running_worker.id(),
            reason="scale_down",
            requested_by="worker-controller",
        )

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert result.is_success
        assert result.data["status"] == "draining"
        assert result.data["desired_status"] == "stopped"
        assert result.data["reason"] == "scale_down"
        mock_worker_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.command
    async def test_drain_nonexistent_worker(self, handler, mock_worker_repository):
        """Test drain fails for non-existent worker."""
        # Arrange
        mock_worker_repository.get_by_id_async = AsyncMock(return_value=None)

        command = DrainWorkerCommand(worker_id="nonexistent-id")

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    @pytest.mark.command
    async def test_drain_pending_worker_rejected(self, handler, mock_worker_repository, sample_pending_worker):
        """Test drain is rejected for PENDING workers."""
        # Arrange
        mock_worker_repository.get_by_id_async = AsyncMock(return_value=sample_pending_worker)

        command = DrainWorkerCommand(worker_id=sample_pending_worker.id())

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert not result.is_success
        assert result.status_code == 409  # Conflict

    @pytest.mark.asyncio
    @pytest.mark.command
    async def test_drain_stopped_worker_rejected(self, handler, mock_worker_repository, sample_stopped_worker):
        """Test drain is rejected for STOPPED workers."""
        # Arrange
        mock_worker_repository.get_by_id_async = AsyncMock(return_value=sample_stopped_worker)

        command = DrainWorkerCommand(worker_id=sample_stopped_worker.id())

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert not result.is_success
        assert result.status_code == 409

    @pytest.mark.asyncio
    @pytest.mark.command
    async def test_drain_sets_worker_to_draining_status(self, handler, mock_worker_repository, sample_running_worker):
        """Test drain sets worker status to DRAINING."""
        # Arrange
        mock_worker_repository.get_by_id_async = AsyncMock(return_value=sample_running_worker)

        command = DrainWorkerCommand(
            worker_id=sample_running_worker.id(),
            reason="maintenance",
            requested_by="admin",
        )

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert result.is_success
        # Verify the worker was saved with DRAINING status
        saved_worker = mock_worker_repository.update_async.call_args[0][0]
        assert saved_worker.state.status == CMLWorkerStatus.DRAINING

    @pytest.mark.asyncio
    @pytest.mark.command
    async def test_drain_preserves_custom_reason(self, handler, mock_worker_repository, sample_running_worker):
        """Test that custom reason is preserved in drain result."""
        # Arrange
        mock_worker_repository.get_by_id_async = AsyncMock(return_value=sample_running_worker)

        command = DrainWorkerCommand(
            worker_id=sample_running_worker.id(),
            reason="maintenance_window",
            requested_by="ops-team",
        )

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert result.is_success
        assert result.data["reason"] == "maintenance_window"
        assert result.data["requested_by"] == "ops-team"
