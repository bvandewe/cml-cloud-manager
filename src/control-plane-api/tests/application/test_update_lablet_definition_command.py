"""Unit tests for UpdateLabletDefinitionCommand + handler.

Tests cover:
- Version bump for ACTIVE definitions (deprecate old → create new in PENDING_SYNC)
- In-place update for PENDING_SYNC definitions
- Rejection of deprecated definitions
- Field merging logic (command overrides vs. existing state)
- Validation (empty definition_id, empty changes for in-place)
- _increment_patch_version helper
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from application.commands.lablet_definition import (
    UpdateLabletDefinitionCommand,
    UpdateLabletDefinitionCommandHandler,
)
from application.commands.lablet_definition.update_lablet_definition_command import (
    _increment_patch_version,
)
from application.dtos.lablet_definition_dto import LabletDefinitionDto
from domain.entities.lablet_definition import LabletDefinition
from domain.enums import LabletDefinitionStatus, LicenseType
from domain.value_objects.port_template import PortTemplate
from domain.value_objects.resource_requirements import ResourceRequirements

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_repository() -> AsyncMock:
    """Create a mock LabletDefinitionRepository."""
    repo = AsyncMock()
    repo.get_async = AsyncMock(return_value=None)
    repo.add_async = AsyncMock(side_effect=lambda e: e)
    repo.update_async = AsyncMock(side_effect=lambda e: e)
    return repo


@pytest.fixture
def mock_mediator() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_mapper() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_cloud_event_bus() -> MagicMock:
    bus = MagicMock()
    bus.output_stream = MagicMock()
    bus.output_stream.on_next = MagicMock()
    return bus


@pytest.fixture
def mock_cloud_event_options() -> MagicMock:
    opts = MagicMock()
    opts.source = "test-source"
    opts.type_prefix = "test.prefix"
    return opts


@pytest.fixture
def handler(mock_mediator, mock_mapper, mock_cloud_event_bus, mock_cloud_event_options, mock_repository):
    """Create an UpdateLabletDefinitionCommandHandler."""
    return UpdateLabletDefinitionCommandHandler(
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_cloud_event_options,
        mock_repository,
    )


@pytest.fixture
def pending_definition() -> LabletDefinition:
    """A PENDING_SYNC definition (freshly created)."""
    return LabletDefinition.create(
        name="test-lablet",
        version="1.0.0",
        form_qualified_name="Exam Associate CCNA v1.0 LAB 1.1a",
        resource_requirements=ResourceRequirements(cpu_cores=2, memory_gb=4, storage_gb=20),
        license_affinity=[LicenseType.PERSONAL, LicenseType.ENTERPRISE],
        node_count=5,
        port_template=PortTemplate.empty(),
        created_by="test-user",
        user_session_package_name="SVN.zip",
        grading_ruleset_package_name="SVN.zip",
        user_session_type="LDS",
        user_session_default_region="us-east-1",
    )


@pytest.fixture
def active_definition(pending_definition) -> LabletDefinition:
    """An ACTIVE definition (simulating post-sync)."""
    pending_definition.state.status = LabletDefinitionStatus.ACTIVE
    return pending_definition


@pytest.fixture
def deprecated_definition(pending_definition) -> LabletDefinition:
    """A DEPRECATED definition."""
    pending_definition.state.status = LabletDefinitionStatus.DEPRECATED
    return pending_definition


# =============================================================================
# Validation Tests
# =============================================================================


class TestUpdateLabletDefinitionValidation:
    """Validation tests for UpdateLabletDefinitionCommand."""

    @pytest.mark.asyncio
    async def test_empty_definition_id_returns_bad_request(self, handler):
        """Empty definition_id should return 400."""
        command = UpdateLabletDefinitionCommand(definition_id="", updated_by="user")
        result = await handler.handle_async(command)
        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_whitespace_definition_id_returns_bad_request(self, handler):
        """Whitespace-only definition_id should return 400."""
        command = UpdateLabletDefinitionCommand(definition_id="   ", updated_by="user")
        result = await handler.handle_async(command)
        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_definition_not_found_returns_404(self, handler, mock_repository):
        """Non-existent definition_id should return 404."""
        mock_repository.get_async.return_value = None
        command = UpdateLabletDefinitionCommand(definition_id="nonexistent-id", updated_by="user")
        result = await handler.handle_async(command)
        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_deprecated_definition_returns_bad_request(self, handler, mock_repository, deprecated_definition):
        """Updating a DEPRECATED definition should return 400."""
        mock_repository.get_async.return_value = deprecated_definition
        command = UpdateLabletDefinitionCommand(
            definition_id=deprecated_definition.id(),
            updated_by="user",
            cpu_cores=4,
        )
        result = await handler.handle_async(command)
        assert not result.is_success
        assert result.status_code == 400
        assert "deprecated" in result.detail.lower()

    @pytest.mark.asyncio
    async def test_invalid_license_affinity_returns_bad_request(self, handler, mock_repository, active_definition):
        """Invalid license_affinity value should return 400."""
        mock_repository.get_async.return_value = active_definition
        command = UpdateLabletDefinitionCommand(
            definition_id=active_definition.id(),
            updated_by="user",
            license_affinity=["invalid_type"],
        )
        result = await handler.handle_async(command)
        assert not result.is_success
        assert result.status_code == 400
        assert "Invalid license type" in result.detail


# =============================================================================
# Version Bump Tests (ACTIVE definitions)
# =============================================================================


class TestVersionBumpForActiveDefinitions:
    """Tests for the version-bump flow when editing ACTIVE definitions."""

    @pytest.mark.asyncio
    async def test_version_bump_creates_new_definition(self, handler, mock_repository, active_definition):
        """Editing an ACTIVE definition should create a new version."""
        mock_repository.get_async.return_value = active_definition

        command = UpdateLabletDefinitionCommand(
            definition_id=active_definition.id(),
            updated_by="admin-user",
            cpu_cores=8,
        )
        result = await handler.handle_async(command)

        assert result.is_success
        # Repository should have been called with update (deprecate old) + add (new)
        mock_repository.update_async.assert_called_once()
        mock_repository.add_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_version_bump_deprecates_old_definition(self, handler, mock_repository, active_definition):
        """The old ACTIVE definition should be deprecated after version bump."""
        mock_repository.get_async.return_value = active_definition

        command = UpdateLabletDefinitionCommand(
            definition_id=active_definition.id(),
            updated_by="admin-user",
            cpu_cores=8,
        )
        await handler.handle_async(command)

        # The original definition passed to update_async should now be DEPRECATED
        updated_def = mock_repository.update_async.call_args[0][0]
        assert updated_def.state.status == LabletDefinitionStatus.DEPRECATED

    @pytest.mark.asyncio
    async def test_version_bump_increments_patch_version(self, handler, mock_repository, active_definition):
        """New definition should have incremented patch version."""
        mock_repository.get_async.return_value = active_definition
        old_version = active_definition.state.version  # "1.0.0"

        command = UpdateLabletDefinitionCommand(
            definition_id=active_definition.id(),
            updated_by="admin-user",
            cpu_cores=8,
        )
        result = await handler.handle_async(command)

        assert result.is_success
        dto = result.data
        assert isinstance(dto, LabletDefinitionDto)
        assert dto.version == "1.0.1"
        assert dto.version != old_version

    @pytest.mark.asyncio
    async def test_version_bump_new_definition_is_pending_sync(self, handler, mock_repository, active_definition):
        """New definition from version bump should be in PENDING_SYNC status."""
        mock_repository.get_async.return_value = active_definition

        command = UpdateLabletDefinitionCommand(
            definition_id=active_definition.id(),
            updated_by="admin-user",
            cpu_cores=8,
        )
        result = await handler.handle_async(command)

        assert result.is_success
        dto = result.data
        assert dto.status == LabletDefinitionStatus.PENDING_SYNC.value

    @pytest.mark.asyncio
    async def test_version_bump_preserves_name(self, handler, mock_repository, active_definition):
        """Version bump should preserve the definition name."""
        mock_repository.get_async.return_value = active_definition

        command = UpdateLabletDefinitionCommand(
            definition_id=active_definition.id(),
            updated_by="admin-user",
            cpu_cores=8,
        )
        result = await handler.handle_async(command)

        assert result.is_success
        dto = result.data
        assert dto.name == active_definition.state.name

    @pytest.mark.asyncio
    async def test_version_bump_applies_form_qualified_name(self, handler, mock_repository, active_definition):
        """Version bump should apply the new form_qualified_name and derive bucket_name."""
        mock_repository.get_async.return_value = active_definition
        new_fqn = "Exam Professional ENCOR v2.0 LAB 2.1b"

        command = UpdateLabletDefinitionCommand(
            definition_id=active_definition.id(),
            updated_by="admin-user",
            form_qualified_name=new_fqn,
        )
        result = await handler.handle_async(command)

        assert result.is_success
        dto = result.data
        assert dto.form_qualified_name == new_fqn
        assert dto.bucket_name == "exam-professional-encor-v2.0-lab-2.1b"

    @pytest.mark.asyncio
    async def test_version_bump_merges_resource_requirements(self, handler, mock_repository, active_definition):
        """Only the specified resource fields should change; others should be preserved."""
        mock_repository.get_async.return_value = active_definition

        command = UpdateLabletDefinitionCommand(
            definition_id=active_definition.id(),
            updated_by="admin-user",
            cpu_cores=16,
            # memory_gb, storage_gb, nested_virt NOT provided → should keep existing values
        )
        result = await handler.handle_async(command)

        assert result.is_success
        dto = result.data
        assert dto.resource_requirements.cpu_cores == 16
        assert dto.resource_requirements.memory_gb == 4  # preserved
        assert dto.resource_requirements.storage_gb == 20  # preserved

    @pytest.mark.asyncio
    async def test_version_bump_applies_content_sync_settings(self, handler, mock_repository, active_definition):
        """Version bump should carry over content sync settings with overrides."""
        mock_repository.get_async.return_value = active_definition

        command = UpdateLabletDefinitionCommand(
            definition_id=active_definition.id(),
            updated_by="admin-user",
            user_session_package_name="NewPackage.zip",
            grading_ruleset_package_name="NewRules.zip",
            user_session_type="LDS_V2",
            user_session_default_region="eu-west-1",
        )
        result = await handler.handle_async(command)

        assert result.is_success
        dto = result.data
        assert dto.user_session_package_name == "NewPackage.zip"
        assert dto.grading_ruleset_package_name == "NewRules.zip"
        assert dto.user_session_type == "LDS_V2"
        assert dto.user_session_default_region == "eu-west-1"


# =============================================================================
# In-Place Update Tests (PENDING_SYNC definitions)
# =============================================================================


class TestInPlaceUpdateForPendingSyncDefinitions:
    """Tests for in-place update when editing PENDING_SYNC definitions."""

    @pytest.mark.asyncio
    async def test_in_place_update_does_not_create_new_version(self, handler, mock_repository, pending_definition):
        """In-place update should NOT call add_async (no new version)."""
        mock_repository.get_async.return_value = pending_definition

        command = UpdateLabletDefinitionCommand(
            definition_id=pending_definition.id(),
            updated_by="user",
            cpu_cores=8,
        )
        result = await handler.handle_async(command)

        assert result.is_success
        mock_repository.update_async.assert_called_once()
        mock_repository.add_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_in_place_update_preserves_version(self, handler, mock_repository, pending_definition):
        """In-place update should keep the same version."""
        mock_repository.get_async.return_value = pending_definition
        original_version = pending_definition.state.version

        command = UpdateLabletDefinitionCommand(
            definition_id=pending_definition.id(),
            updated_by="user",
            cpu_cores=8,
        )
        result = await handler.handle_async(command)

        assert result.is_success
        dto = result.data
        assert dto.version == original_version

    @pytest.mark.asyncio
    async def test_in_place_update_applies_form_qualified_name(self, handler, mock_repository, pending_definition):
        """In-place update should apply form_qualified_name and derive bucket_name."""
        mock_repository.get_async.return_value = pending_definition
        new_fqn = "Exam Professional ENCOR v2.0 LAB 2.1b"

        command = UpdateLabletDefinitionCommand(
            definition_id=pending_definition.id(),
            updated_by="user",
            form_qualified_name=new_fqn,
        )
        result = await handler.handle_async(command)

        assert result.is_success
        dto = result.data
        assert dto.form_qualified_name == new_fqn
        assert dto.bucket_name == "exam-professional-encor-v2.0-lab-2.1b"

    @pytest.mark.asyncio
    async def test_in_place_update_applies_resource_requirements(self, handler, mock_repository, pending_definition):
        """In-place update should update resource requirements."""
        mock_repository.get_async.return_value = pending_definition

        command = UpdateLabletDefinitionCommand(
            definition_id=pending_definition.id(),
            updated_by="user",
            cpu_cores=16,
            memory_gb=32,
        )
        result = await handler.handle_async(command)

        assert result.is_success
        dto = result.data
        assert dto.resource_requirements.cpu_cores == 16
        assert dto.resource_requirements.memory_gb == 32

    @pytest.mark.asyncio
    async def test_in_place_update_applies_content_sync_settings(self, handler, mock_repository, pending_definition):
        """In-place update should apply content sync settings."""
        mock_repository.get_async.return_value = pending_definition

        command = UpdateLabletDefinitionCommand(
            definition_id=pending_definition.id(),
            updated_by="user",
            user_session_package_name="Updated.zip",
            user_session_type="LDS_V2",
        )
        result = await handler.handle_async(command)

        assert result.is_success
        dto = result.data
        assert dto.user_session_package_name == "Updated.zip"
        assert dto.user_session_type == "LDS_V2"

    @pytest.mark.asyncio
    async def test_in_place_update_no_changes_returns_bad_request(self, handler, mock_repository, pending_definition):
        """In-place update with no fields should return 400."""
        mock_repository.get_async.return_value = pending_definition

        command = UpdateLabletDefinitionCommand(
            definition_id=pending_definition.id(),
            updated_by="user",
            # No fields provided
        )
        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400
        assert "No fields to update" in result.detail


# =============================================================================
# _increment_patch_version Helper Tests
# =============================================================================


class TestIncrementPatchVersion:
    """Tests for the _increment_patch_version utility."""

    def test_standard_semver(self):
        assert _increment_patch_version("1.0.0") == "1.0.1"

    def test_higher_patch(self):
        assert _increment_patch_version("2.3.7") == "2.3.8"

    def test_two_part_version(self):
        assert _increment_patch_version("1.0") == "1.1"

    def test_single_part_version(self):
        assert _increment_patch_version("1") == "1.1"

    def test_already_high_patch(self):
        assert _increment_patch_version("1.0.99") == "1.0.100"

    def test_zero_version(self):
        assert _increment_patch_version("0.0.0") == "0.0.1"
