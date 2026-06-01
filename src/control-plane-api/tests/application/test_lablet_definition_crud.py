"""Unit tests for LabletDefinition CRUD commands and queries.

Tests cover:
- CreateLabletDefinitionCommand with validation
- SyncLabletDefinitionCommand
- GetLabletDefinitionQuery (by id, by name+version)
- ListLabletDefinitionsQuery (with pagination, filters)
- ActivateLabletDefinitionCommand (Phase 3)
- DeactivateLabletDefinitionCommand (Phase 3)
- DeleteLabletDefinitionCommand (Phase 3)
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from application.commands.lablet_definition import (
    CreateLabletDefinitionCommand,
    CreateLabletDefinitionCommandHandler,
    SyncLabletDefinitionCommand,
    SyncLabletDefinitionCommandHandler,
)
from application.commands.lablet_definition.activate_lablet_definition_command import (
    ActivateLabletDefinitionCommand,
    ActivateLabletDefinitionCommandHandler,
)
from application.commands.lablet_definition.deactivate_lablet_definition_command import (
    DeactivateLabletDefinitionCommand,
    DeactivateLabletDefinitionCommandHandler,
)
from application.commands.lablet_definition.delete_lablet_definition_command import (
    DeleteLabletDefinitionCommand,
    DeleteLabletDefinitionCommandHandler,
)
from application.dtos.lablet_definition_dto import (
    LabletDefinitionCreatedDto,
    LabletDefinitionDto,
    LabletDefinitionSyncResultDto,
)
from application.queries import (
    GetLabletDefinitionQuery,
    GetLabletDefinitionQueryHandler,
    ListLabletDefinitionsQuery,
    ListLabletDefinitionsQueryHandler,
)
from domain.entities.lablet_definition import LabletDefinition
from domain.enums import LabletDefinitionStatus, LicenseType
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.value_objects.port_template import PortTemplate
from domain.value_objects.resource_requirements import ResourceRequirements

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_repository() -> AsyncMock:
    """Create a mock LabletDefinitionRepository."""
    repo = AsyncMock(spec=LabletDefinitionRepository)
    repo.get_by_id_async = AsyncMock(return_value=None)
    repo.get_by_name_and_version_async = AsyncMock(return_value=None)
    repo.list_active_async = AsyncMock(return_value=[])
    repo.list_by_status_async = AsyncMock(return_value=[])
    repo.list_by_name_async = AsyncMock(return_value=[])
    repo.add_async = AsyncMock(side_effect=lambda e: e)
    repo.update_async = AsyncMock(side_effect=lambda e: e)
    return repo


@pytest.fixture
def mock_mediator() -> MagicMock:
    """Create a mock Mediator."""
    return MagicMock()


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
def sample_lablet_definition() -> LabletDefinition:
    """Create a sample LabletDefinition for testing."""
    return LabletDefinition.create(
        name="test-lablet",
        version="1.0.0",
        form_qualified_name="Exam Associate CCNA v1.0 LAB 1.1a",
        resource_requirements=ResourceRequirements(cpu_cores=2, memory_gb=4, storage_gb=20),
        license_affinity=[LicenseType.PERSONAL, LicenseType.ENTERPRISE],
        node_count=5,
        port_template=PortTemplate.empty(),
        created_by="test-user",
    )


@pytest.fixture
def sample_lablet_definitions(sample_lablet_definition: LabletDefinition) -> list[LabletDefinition]:
    """Create multiple sample LabletDefinitions for list tests."""
    definitions = [sample_lablet_definition]

    # Create a second definition
    def2 = LabletDefinition.create(
        name="another-lablet",
        version="2.0.0",
        form_qualified_name="Exam Professional ENCOR v2.0 LAB 2.1b",
        resource_requirements=ResourceRequirements(cpu_cores=4, memory_gb=8, storage_gb=40),
        license_affinity=[LicenseType.ENTERPRISE],
        node_count=10,
        port_template=PortTemplate.empty(),
        created_by="test-user",
    )
    definitions.append(def2)

    return definitions


# =============================================================================
# GetLabletDefinitionQuery Tests
# =============================================================================


class TestGetLabletDefinitionQueryHandler:
    """Tests for GetLabletDefinitionQueryHandler."""

    @pytest.mark.asyncio
    async def test_get_by_id_success(
        self,
        mock_repository: AsyncMock,
        sample_lablet_definition: LabletDefinition,
    ):
        """Test successful retrieval by ID."""
        # Arrange
        mock_repository.get_by_id_async.return_value = sample_lablet_definition
        handler = GetLabletDefinitionQueryHandler(mock_repository)

        query = GetLabletDefinitionQuery(id=sample_lablet_definition.id())

        # Act
        result = await handler.handle_async(query)

        # Assert
        assert result.is_success
        assert isinstance(result.data, LabletDefinitionDto)
        assert result.data.name == "test-lablet"
        assert result.data.version == "1.0.0"
        mock_repository.get_by_id_async.assert_called_once_with(sample_lablet_definition.id())

    @pytest.mark.asyncio
    async def test_get_by_name_and_version_success(
        self,
        mock_repository: AsyncMock,
        sample_lablet_definition: LabletDefinition,
    ):
        """Test successful retrieval by name and version."""
        # Arrange
        mock_repository.get_by_name_and_version_async.return_value = sample_lablet_definition
        handler = GetLabletDefinitionQueryHandler(mock_repository)

        query = GetLabletDefinitionQuery(name="test-lablet", version="1.0.0")

        # Act
        result = await handler.handle_async(query)

        # Assert
        assert result.is_success
        assert isinstance(result.data, LabletDefinitionDto)
        assert result.data.name == "test-lablet"
        mock_repository.get_by_name_and_version_async.assert_called_once_with(
            name="test-lablet",
            version="1.0.0",
        )

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, mock_repository: AsyncMock):
        """Test not found error when ID doesn't exist."""
        # Arrange
        mock_repository.get_by_id_async.return_value = None
        handler = GetLabletDefinitionQueryHandler(mock_repository)

        query = GetLabletDefinitionQuery(id="nonexistent-id")

        # Act
        result = await handler.handle_async(query)

        # Assert
        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_by_name_and_version_not_found(self, mock_repository: AsyncMock):
        """Test not found error when name+version doesn't exist."""
        # Arrange
        mock_repository.get_by_name_and_version_async.return_value = None
        handler = GetLabletDefinitionQueryHandler(mock_repository)

        query = GetLabletDefinitionQuery(name="unknown", version="1.0.0")

        # Act
        result = await handler.handle_async(query)

        # Assert
        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_bad_request_no_identifier(self, mock_repository: AsyncMock):
        """Test bad request when neither id nor name+version provided."""
        # Arrange
        handler = GetLabletDefinitionQueryHandler(mock_repository)

        query = GetLabletDefinitionQuery()

        # Act
        result = await handler.handle_async(query)

        # Assert
        assert not result.is_success
        assert result.status_code == 400


# =============================================================================
# ListLabletDefinitionsQuery Tests
# =============================================================================


class TestListLabletDefinitionsQueryHandler:
    """Tests for ListLabletDefinitionsQueryHandler."""

    @pytest.mark.asyncio
    async def test_list_active_default(
        self,
        mock_repository: AsyncMock,
        sample_lablet_definitions: list[LabletDefinition],
    ):
        """Test listing active definitions by default."""
        # Arrange
        mock_repository.list_active_async.return_value = sample_lablet_definitions
        handler = ListLabletDefinitionsQueryHandler(mock_repository)

        query = ListLabletDefinitionsQuery()

        # Act
        result = await handler.handle_async(query)

        # Assert
        assert result.is_success
        assert len(result.data) == 2
        mock_repository.list_active_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_by_name(
        self,
        mock_repository: AsyncMock,
        sample_lablet_definition: LabletDefinition,
    ):
        """Test listing by specific name."""
        # Arrange
        mock_repository.list_by_name_async.return_value = [sample_lablet_definition]
        handler = ListLabletDefinitionsQueryHandler(mock_repository)

        query = ListLabletDefinitionsQuery(name="test-lablet")

        # Act
        result = await handler.handle_async(query)

        # Assert
        assert result.is_success
        assert len(result.data) == 1
        mock_repository.list_by_name_async.assert_called_once_with("test-lablet")

    @pytest.mark.asyncio
    async def test_list_by_status(
        self,
        mock_repository: AsyncMock,
        sample_lablet_definitions: list[LabletDefinition],
    ):
        """Test listing by specific status."""
        # Arrange
        mock_repository.list_by_status_async.return_value = sample_lablet_definitions
        handler = ListLabletDefinitionsQueryHandler(mock_repository)

        query = ListLabletDefinitionsQuery(status="active")

        # Act
        result = await handler.handle_async(query)

        # Assert
        assert result.is_success
        assert len(result.data) == 2
        mock_repository.list_by_status_async.assert_called_once_with(LabletDefinitionStatus.ACTIVE)

    @pytest.mark.asyncio
    async def test_list_invalid_status(self, mock_repository: AsyncMock):
        """Test error for invalid status filter."""
        # Arrange
        handler = ListLabletDefinitionsQueryHandler(mock_repository)

        query = ListLabletDefinitionsQuery(status="invalid_status")

        # Act
        result = await handler.handle_async(query)

        # Assert
        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_list_with_pagination(
        self,
        mock_repository: AsyncMock,
        sample_lablet_definitions: list[LabletDefinition],
    ):
        """Test pagination with skip and limit."""
        # Arrange
        mock_repository.list_active_async.return_value = sample_lablet_definitions
        handler = ListLabletDefinitionsQueryHandler(mock_repository)

        query = ListLabletDefinitionsQuery(skip=1, limit=1)

        # Act
        result = await handler.handle_async(query)

        # Assert
        assert result.is_success
        assert len(result.data) == 1  # Only one after skipping first


# =============================================================================
# CreateLabletDefinitionCommand Tests
# =============================================================================


class TestCreateLabletDefinitionCommandHandler:
    """Tests for CreateLabletDefinitionCommandHandler."""

    @pytest.mark.asyncio
    async def test_create_success(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
    ):
        """Test successful creation of a LabletDefinition."""
        # Arrange
        handler = CreateLabletDefinitionCommandHandler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_options,
            mock_repository,
        )

        command = CreateLabletDefinitionCommand(
            name="new-lablet",
            version="1.0.0",
            form_qualified_name="Exam Associate CCNA v1.0 LAB 1.1a",
            created_by="test-user",
            cpu_cores=2,
            memory_gb=4,
            storage_gb=20,
            node_count=5,
        )

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert result.is_success
        assert result.status_code == 201
        assert isinstance(result.data, LabletDefinitionCreatedDto)
        assert result.data.name == "new-lablet"
        assert result.data.version == "1.0.0"
        mock_repository.add_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_duplicate_conflict(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
        sample_lablet_definition: LabletDefinition,
    ):
        """Test conflict error when name+version already exists."""
        # Arrange
        mock_repository.get_by_name_and_version_async.return_value = sample_lablet_definition
        handler = CreateLabletDefinitionCommandHandler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_options,
            mock_repository,
        )

        command = CreateLabletDefinitionCommand(
            name="test-lablet",
            version="1.0.0",
            form_qualified_name="Exam Associate CCNA v1.0 LAB 1.1a",
            created_by="test-user",
        )

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert not result.is_success
        assert result.status_code == 409
        mock_repository.add_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_missing_name(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
    ):
        """Test validation error when name is missing."""
        # Arrange
        handler = CreateLabletDefinitionCommandHandler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_options,
            mock_repository,
        )

        command = CreateLabletDefinitionCommand(
            name="",  # Empty name
            version="1.0.0",
            form_qualified_name="Exam Associate CCNA v1.0 LAB 1.1a",
            created_by="test-user",
        )

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_create_invalid_license_type(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
    ):
        """Test validation error for invalid license type."""
        # Arrange
        handler = CreateLabletDefinitionCommandHandler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_options,
            mock_repository,
        )

        command = CreateLabletDefinitionCommand(
            name="new-lablet",
            version="1.0.0",
            form_qualified_name="Exam Associate CCNA v1.0 LAB 1.1a",
            created_by="test-user",
            license_affinity=["invalid_license_type"],
        )

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert not result.is_success
        assert result.status_code == 400


# =============================================================================
# SyncLabletDefinitionCommand Tests
# =============================================================================


class TestSyncLabletDefinitionCommandHandler:
    """Tests for SyncLabletDefinitionCommandHandler (trigger-only, 202 Accepted)."""

    @pytest.mark.asyncio
    async def test_sync_trigger_success(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
        sample_lablet_definition: LabletDefinition,
    ):
        """Test successful sync trigger returns 202 Accepted."""
        # Arrange
        mock_repository.get_by_id_async.return_value = sample_lablet_definition
        handler = SyncLabletDefinitionCommandHandler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_options,
            mock_repository,
        )

        command = SyncLabletDefinitionCommand(
            id=sample_lablet_definition.id(),
            synced_by="test-user",
        )

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert result.is_success
        assert result.status_code == 202  # Accepted
        assert isinstance(result.data, LabletDefinitionSyncResultDto)
        mock_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_not_found(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
    ):
        """Test sync fails when definition not found."""
        # Arrange
        mock_repository.get_by_id_async.return_value = None
        mock_repository.get_by_name_and_version_async.return_value = None
        handler = SyncLabletDefinitionCommandHandler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_options,
            mock_repository,
        )

        command = SyncLabletDefinitionCommand(
            id="nonexistent-id",
            synced_by="test-user",
        )

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_sync_bad_request_no_identifier(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
    ):
        """Test sync fails when no identifier provided."""
        # Arrange
        handler = SyncLabletDefinitionCommandHandler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_options,
            mock_repository,
        )

        command = SyncLabletDefinitionCommand(
            synced_by="test-user",
        )

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_sync_trigger_missing_fqn(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
    ):
        """Test sync fails when definition has no form_qualified_name."""
        # Arrange - create a definition without FQN (should not happen normally)
        definition = LabletDefinition.create(
            name="no-fqn-lablet",
            version="1.0.0",
            form_qualified_name="Exam Associate CCNA v1.0 LAB 1.1a",
            resource_requirements=ResourceRequirements(cpu_cores=2, memory_gb=4, storage_gb=20),
            license_affinity=[LicenseType.PERSONAL],
            node_count=1,
            port_template=PortTemplate.empty(),
            created_by="test-user",
        )
        # Manually clear the FQN to simulate legacy data
        definition.state.form_qualified_name = ""
        mock_repository.get_by_id_async.return_value = definition

        handler = SyncLabletDefinitionCommandHandler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_cloud_event_options,
            mock_repository,
        )

        command = SyncLabletDefinitionCommand(
            id=definition.id(),
            synced_by="test-user",
        )

        # Act
        result = await handler.handle_async(command)

        # Assert
        assert not result.is_success
        assert result.status_code == 400


# =============================================================================
# Shared fixtures for lifecycle command handler tests (Phase 3)
# =============================================================================


@pytest.fixture
def active_lablet_definition() -> LabletDefinition:
    """Create a sample LabletDefinition in ACTIVE state (synced)."""
    defn = LabletDefinition.create(
        name="active-lablet",
        version="1.0.0",
        form_qualified_name="Exam Associate CCNA v1.0 LAB 1.1a",
        resource_requirements=ResourceRequirements(cpu_cores=2, memory_gb=4, storage_gb=20),
        license_affinity=[LicenseType.PERSONAL, LicenseType.ENTERPRISE],
        node_count=5,
        port_template=PortTemplate.empty(),
        created_by="test-user",
    )
    defn.record_content_sync(lab_yaml_hash="sha256:test", sync_status="success")
    return defn


@pytest.fixture
def inactive_lablet_definition(active_lablet_definition: LabletDefinition) -> LabletDefinition:
    """Create a sample LabletDefinition in INACTIVE state."""
    active_lablet_definition.deactivate(deactivated_by="test-user")
    return active_lablet_definition


# =============================================================================
# ActivateLabletDefinitionCommand Tests (Phase 3)
# =============================================================================


class TestActivateLabletDefinitionCommandHandler:
    """Tests for ActivateLabletDefinitionCommandHandler."""

    @pytest.mark.asyncio
    async def test_activate_success(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
        inactive_lablet_definition: LabletDefinition,
    ):
        """Test successful activation from INACTIVE → ACTIVE."""
        mock_repository.get_by_id_async.return_value = inactive_lablet_definition

        handler = ActivateLabletDefinitionCommandHandler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_options, mock_repository)

        command = ActivateLabletDefinitionCommand(
            definition_id=inactive_lablet_definition.id(),
            activated_by="admin-user",
        )

        result = await handler.handle_async(command)

        assert result.is_success
        assert result.status_code == 200
        assert result.data["status"] == "active"
        mock_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_activate_not_found(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
    ):
        """Test activate returns 404 for unknown definition."""
        mock_repository.get_by_id_async.return_value = None

        handler = ActivateLabletDefinitionCommandHandler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_options, mock_repository)

        command = ActivateLabletDefinitionCommand(definition_id="nonexistent", activated_by="admin")

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_activate_rejects_pending_sync(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
        sample_lablet_definition: LabletDefinition,
    ):
        """Test activate returns 400 for PENDING_SYNC definition."""
        mock_repository.get_by_id_async.return_value = sample_lablet_definition

        handler = ActivateLabletDefinitionCommandHandler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_options, mock_repository)

        command = ActivateLabletDefinitionCommand(
            definition_id=sample_lablet_definition.id(),
            activated_by="admin",
        )

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_activate_missing_definition_id(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
    ):
        """Test activate returns 400 when definition_id is empty."""
        handler = ActivateLabletDefinitionCommandHandler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_options, mock_repository)

        command = ActivateLabletDefinitionCommand(definition_id="", activated_by="admin")

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400


# =============================================================================
# DeactivateLabletDefinitionCommand Tests (Phase 3)
# =============================================================================


class TestDeactivateLabletDefinitionCommandHandler:
    """Tests for DeactivateLabletDefinitionCommandHandler."""

    @pytest.mark.asyncio
    async def test_deactivate_success(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
        active_lablet_definition: LabletDefinition,
    ):
        """Test successful deactivation from ACTIVE → INACTIVE."""
        mock_repository.get_by_id_async.return_value = active_lablet_definition

        handler = DeactivateLabletDefinitionCommandHandler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_options, mock_repository)

        command = DeactivateLabletDefinitionCommand(
            definition_id=active_lablet_definition.id(),
            deactivated_by="admin-user",
            reason="Planned maintenance",
        )

        result = await handler.handle_async(command)

        assert result.is_success
        assert result.status_code == 200
        assert result.data["status"] == "inactive"
        mock_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_deactivate_not_found(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
    ):
        """Test deactivate returns 404 for unknown definition."""
        mock_repository.get_by_id_async.return_value = None

        handler = DeactivateLabletDefinitionCommandHandler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_options, mock_repository)

        command = DeactivateLabletDefinitionCommand(definition_id="nonexistent", deactivated_by="admin")

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_deactivate_rejects_pending_sync(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
        sample_lablet_definition: LabletDefinition,
    ):
        """Test deactivate returns 400 for PENDING_SYNC definition."""
        mock_repository.get_by_id_async.return_value = sample_lablet_definition

        handler = DeactivateLabletDefinitionCommandHandler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_options, mock_repository)

        command = DeactivateLabletDefinitionCommand(
            definition_id=sample_lablet_definition.id(),
            deactivated_by="admin",
        )

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_deactivate_missing_definition_id(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
    ):
        """Test deactivate returns 400 when definition_id is empty."""
        handler = DeactivateLabletDefinitionCommandHandler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_options, mock_repository)

        command = DeactivateLabletDefinitionCommand(definition_id="", deactivated_by="admin")

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400


# =============================================================================
# DeleteLabletDefinitionCommand Tests (Phase 3)
# =============================================================================


class TestDeleteLabletDefinitionCommandHandler:
    """Tests for DeleteLabletDefinitionCommandHandler."""

    @pytest.mark.asyncio
    async def test_delete_success(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
        active_lablet_definition: LabletDefinition,
    ):
        """Test successful soft-deletion returns 204."""
        mock_repository.get_by_id_async.return_value = active_lablet_definition

        handler = DeleteLabletDefinitionCommandHandler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_options, mock_repository)

        command = DeleteLabletDefinitionCommand(
            definition_id=active_lablet_definition.id(),
            deleted_by="admin-user",
        )

        result = await handler.handle_async(command)

        assert result.is_success
        assert result.status_code == 204
        mock_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_not_found(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
    ):
        """Test delete returns 404 for unknown definition."""
        mock_repository.get_by_id_async.return_value = None

        handler = DeleteLabletDefinitionCommandHandler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_options, mock_repository)

        command = DeleteLabletDefinitionCommand(definition_id="nonexistent", deleted_by="admin")

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_idempotent_when_already_deleted(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
        active_lablet_definition: LabletDefinition,
    ):
        """Test delete is idempotent (no-op) for already-deleted definition."""
        active_lablet_definition.soft_delete(deleted_by="admin")
        mock_repository.get_by_id_async.return_value = active_lablet_definition

        handler = DeleteLabletDefinitionCommandHandler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_options, mock_repository)

        command = DeleteLabletDefinitionCommand(
            definition_id=active_lablet_definition.id(),
            deleted_by="admin",
        )

        result = await handler.handle_async(command)

        # Soft_delete is idempotent → no error, still updates
        assert result.is_success
        assert result.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_missing_definition_id(
        self,
        mock_repository: AsyncMock,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_options: MagicMock,
    ):
        """Test delete returns 400 when definition_id is empty."""
        handler = DeleteLabletDefinitionCommandHandler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_options, mock_repository)

        command = DeleteLabletDefinitionCommand(definition_id="", deleted_by="admin")

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400
