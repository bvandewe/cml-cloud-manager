"""Unit tests for WorkerTemplateService.

Tests cover:
- Template loading from YAML
- Template loading from dictionaries
- Template seeding to repository
- Optimal template selection by capacity
- Selection with headroom
- Error handling for missing templates and configs
"""

import tempfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from application.services.worker_template_service import (
    NoMatchingTemplateError,
    TemplateLoadError,
    TemplateNotFoundError,
    TemplateValidationError,
    WorkerTemplateService,
)
from domain.entities.worker_template import WorkerTemplate
from domain.repositories.worker_template_repository import WorkerTemplateRepository
from domain.value_objects.worker_capacity import WorkerCapacity
from integration.enums import Ec2InstanceType


@pytest.fixture
def mock_repository() -> AsyncMock:
    """Create a mock WorkerTemplateRepository."""
    repo = AsyncMock(spec=WorkerTemplateRepository)
    repo.get_by_id_async = AsyncMock(return_value=None)
    repo.get_by_name_async = AsyncMock(return_value=None)
    repo.list_enabled_async = AsyncMock(return_value=[])
    repo.list_all_async = AsyncMock(return_value=[])
    repo.find_matching_templates_async = AsyncMock(return_value=[])
    repo.add_async = AsyncMock(side_effect=lambda t: t)
    repo.update_async = AsyncMock(side_effect=lambda t: t)
    repo.upsert_by_name_async = AsyncMock(side_effect=lambda t: t)
    return repo


@pytest.fixture
def sample_templates_yaml() -> str:
    """Create a sample YAML configuration."""
    return """
templates:
  - name: small
    description: Small worker for simple labs
    instance_type: small
    ami_name_pattern: "cisco-cml2.9*"
    capacity:
      cpu_cores: 2
      memory_gb: 4
      storage_gb: 50
      max_nodes: 5
    cost_per_hour_usd: 0.10
    enabled: true

  - name: medium
    description: Medium worker for moderate workloads
    instance_type: medium
    ami_name_pattern: "cisco-cml2.9*"
    capacity:
      cpu_cores: 4
      memory_gb: 16
      storage_gb: 100
      max_nodes: 20
    cost_per_hour_usd: 0.50
    enabled: true

  - name: large
    description: Large worker for complex labs
    instance_type: large
    ami_name_pattern: "cisco-cml2.9*"
    capacity:
      cpu_cores: 8
      memory_gb: 32
      storage_gb: 200
      max_nodes: 50
    cost_per_hour_usd: 1.00
    enabled: true
"""


@pytest.fixture
def sample_templates_dict() -> list[dict[str, Any]]:
    """Sample templates as dictionaries."""
    return [
        {
            "name": "small",
            "description": "Small worker",
            "instance_type": "small",
            "capacity": {"cpu_cores": 2, "memory_gb": 4, "storage_gb": 50, "max_nodes": 5},
            "cost_per_hour_usd": 0.10,
        },
        {
            "name": "medium",
            "description": "Medium worker",
            "instance_type": "medium",
            "capacity": {"cpu_cores": 4, "memory_gb": 16, "storage_gb": 100, "max_nodes": 20},
            "cost_per_hour_usd": 0.50,
        },
    ]


@pytest.fixture
def temp_yaml_file(sample_templates_yaml: str) -> str:
    """Create a temporary YAML file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(sample_templates_yaml)
        return f.name


class TestLoadTemplatesFromYaml:
    """Tests for loading templates from YAML configuration."""

    @pytest.mark.asyncio
    async def test_load_templates_from_yaml_success(
        self,
        mock_repository: AsyncMock,
        temp_yaml_file: str,
    ) -> None:
        """Test successful template loading from YAML."""
        service = WorkerTemplateService(
            template_repository=mock_repository,
            templates_config_path=temp_yaml_file,
        )

        templates = await service.load_templates_from_yaml()

        assert len(templates) == 3
        assert templates[0].state.name == "small"
        assert templates[1].state.name == "medium"
        assert templates[2].state.name == "large"

    @pytest.mark.asyncio
    async def test_load_templates_with_explicit_path(
        self,
        mock_repository: AsyncMock,
        temp_yaml_file: str,
    ) -> None:
        """Test loading with explicit path parameter."""
        service = WorkerTemplateService(template_repository=mock_repository)

        templates = await service.load_templates_from_yaml(config_path=temp_yaml_file)

        assert len(templates) == 3

    @pytest.mark.asyncio
    async def test_load_templates_no_path_raises_error(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test that missing path raises TemplateLoadError."""
        service = WorkerTemplateService(template_repository=mock_repository)

        with pytest.raises(TemplateLoadError, match="No template configuration path"):
            await service.load_templates_from_yaml()

    @pytest.mark.asyncio
    async def test_load_templates_file_not_found_raises_error(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test that missing file raises TemplateLoadError."""
        service = WorkerTemplateService(
            template_repository=mock_repository,
            templates_config_path="/nonexistent/path.yaml",
        )

        with pytest.raises(TemplateLoadError, match="not found"):
            await service.load_templates_from_yaml()

    @pytest.mark.asyncio
    async def test_load_templates_invalid_yaml_raises_error(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test that invalid YAML raises TemplateLoadError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("invalid: yaml: content: [")
            temp_path = f.name

        service = WorkerTemplateService(
            template_repository=mock_repository,
            templates_config_path=temp_path,
        )

        with pytest.raises(TemplateLoadError, match="Failed to parse YAML"):
            await service.load_templates_from_yaml()

    @pytest.mark.asyncio
    async def test_load_templates_empty_file_raises_error(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test that empty file raises TemplateLoadError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            temp_path = f.name

        service = WorkerTemplateService(
            template_repository=mock_repository,
            templates_config_path=temp_path,
        )

        with pytest.raises(TemplateLoadError, match="Empty configuration"):
            await service.load_templates_from_yaml()

    @pytest.mark.asyncio
    async def test_load_templates_no_templates_key_raises_error(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test that missing templates key raises TemplateLoadError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("other_key: value")
            temp_path = f.name

        service = WorkerTemplateService(
            template_repository=mock_repository,
            templates_config_path=temp_path,
        )

        with pytest.raises(TemplateLoadError, match="No templates found"):
            await service.load_templates_from_yaml()

    @pytest.mark.asyncio
    async def test_load_templates_parses_instance_types(
        self,
        mock_repository: AsyncMock,
        temp_yaml_file: str,
    ) -> None:
        """Test that instance types are correctly parsed."""
        service = WorkerTemplateService(
            template_repository=mock_repository,
            templates_config_path=temp_yaml_file,
        )

        templates = await service.load_templates_from_yaml()

        assert templates[0].state.instance_type == Ec2InstanceType.SMALL
        assert templates[1].state.instance_type == Ec2InstanceType.MEDIUM
        assert templates[2].state.instance_type == Ec2InstanceType.LARGE

    @pytest.mark.asyncio
    async def test_load_templates_parses_capacity(
        self,
        mock_repository: AsyncMock,
        temp_yaml_file: str,
    ) -> None:
        """Test that capacity is correctly parsed."""
        service = WorkerTemplateService(
            template_repository=mock_repository,
            templates_config_path=temp_yaml_file,
        )

        templates = await service.load_templates_from_yaml()
        small = templates[0]

        assert small.state.capacity.cpu_cores == 2
        assert small.state.capacity.memory_gb == 4
        assert small.state.capacity.storage_gb == 50
        assert small.state.capacity.max_nodes == 5


class TestLoadTemplatesFromDict:
    """Tests for loading templates from dictionaries."""

    def test_load_templates_from_dict_success(
        self,
        mock_repository: AsyncMock,
        sample_templates_dict: list[dict[str, Any]],
    ) -> None:
        """Test successful template loading from dict."""
        service = WorkerTemplateService(template_repository=mock_repository)

        templates = service.load_templates_from_dict(sample_templates_dict)

        assert len(templates) == 2
        assert templates[0].state.name == "small"
        assert templates[1].state.name == "medium"

    def test_load_templates_from_dict_validates_required_fields(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test that missing required fields raise TemplateValidationError."""
        service = WorkerTemplateService(template_repository=mock_repository)
        invalid_templates = [{"description": "Missing name"}]

        with pytest.raises(TemplateValidationError, match="Invalid template definition"):
            service.load_templates_from_dict(invalid_templates)

    def test_load_templates_from_dict_uses_defaults(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test that missing optional fields use defaults."""
        service = WorkerTemplateService(template_repository=mock_repository)
        minimal_template = [{"name": "minimal", "capacity": {"cpu_cores": 1, "memory_gb": 1, "storage_gb": 10}}]

        templates = service.load_templates_from_dict(minimal_template)

        assert templates[0].state.ami_name_pattern == "cisco-cml2.9*"
        assert templates[0].state.cost_per_hour_usd == 0.0
        assert templates[0].state.enabled is True


class TestSeedTemplates:
    """Tests for seeding templates to repository."""

    @pytest.mark.asyncio
    async def test_seed_templates_success(
        self,
        mock_repository: AsyncMock,
        temp_yaml_file: str,
    ) -> None:
        """Test successful template seeding."""
        service = WorkerTemplateService(
            template_repository=mock_repository,
            templates_config_path=temp_yaml_file,
        )
        await service.load_templates_from_yaml()

        count = await service.seed_templates_async()

        assert count == 3
        assert mock_repository.upsert_by_name_async.call_count == 3

    @pytest.mark.asyncio
    async def test_seed_templates_with_provided_templates(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test seeding with explicitly provided templates."""
        service = WorkerTemplateService(template_repository=mock_repository)
        templates = [
            WorkerTemplate.create(
                name="test",
                description="Test template",
                instance_type=Ec2InstanceType.SMALL,
                capacity=WorkerCapacity(cpu_cores=2, memory_gb=4, storage_gb=50),
            )
        ]

        count = await service.seed_templates_async(templates=templates)

        assert count == 1
        mock_repository.upsert_by_name_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_seed_templates_no_templates_raises_error(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test that seeding without templates raises error."""
        service = WorkerTemplateService(template_repository=mock_repository)

        with pytest.raises(TemplateLoadError, match="No templates to seed"):
            await service.seed_templates_async()


class TestGetTemplateByName:
    """Tests for retrieving templates by name."""

    @pytest.mark.asyncio
    async def test_get_template_by_name_success(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test successful template retrieval."""
        template = WorkerTemplate.create(
            name="small",
            description="Small worker",
            instance_type=Ec2InstanceType.SMALL,
            capacity=WorkerCapacity(cpu_cores=2, memory_gb=4, storage_gb=50),
        )
        mock_repository.get_by_name_async.return_value = template

        service = WorkerTemplateService(template_repository=mock_repository)
        result = await service.get_template_by_name_async("small")

        assert result.state.name == "small"
        mock_repository.get_by_name_async.assert_called_once_with("small")

    @pytest.mark.asyncio
    async def test_get_template_by_name_not_found_raises_error(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test that missing template raises TemplateNotFoundError."""
        mock_repository.get_by_name_async.return_value = None

        service = WorkerTemplateService(template_repository=mock_repository)

        with pytest.raises(TemplateNotFoundError, match="nonexistent"):
            await service.get_template_by_name_async("nonexistent")


class TestSelectOptimalTemplate:
    """Tests for optimal template selection."""

    @pytest.mark.asyncio
    async def test_select_optimal_template_returns_cheapest(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test that optimal selection returns cheapest matching template."""
        small = WorkerTemplate.create(
            name="small",
            description="Small",
            instance_type=Ec2InstanceType.SMALL,
            capacity=WorkerCapacity(cpu_cores=4, memory_gb=8, storage_gb=100),
            cost_per_hour_usd=0.10,
        )
        medium = WorkerTemplate.create(
            name="medium",
            description="Medium",
            instance_type=Ec2InstanceType.MEDIUM,
            capacity=WorkerCapacity(cpu_cores=8, memory_gb=16, storage_gb=200),
            cost_per_hour_usd=0.50,
        )
        # Repository returns templates ordered by cost (ascending)
        mock_repository.find_matching_templates_async.return_value = [small, medium]

        service = WorkerTemplateService(template_repository=mock_repository)
        required = WorkerCapacity(cpu_cores=2, memory_gb=4, storage_gb=50)
        result = await service.select_optimal_template_async(required)

        assert result.template.state.name == "small"
        assert result.cost_ranking == 0
        assert result.match_reason == "Cost-optimized selection"

    @pytest.mark.asyncio
    async def test_select_optimal_template_calculates_excess_capacity(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test that excess capacity is correctly calculated."""
        template = WorkerTemplate.create(
            name="medium",
            description="Medium",
            instance_type=Ec2InstanceType.MEDIUM,
            capacity=WorkerCapacity(cpu_cores=8, memory_gb=16, storage_gb=200),
        )
        mock_repository.find_matching_templates_async.return_value = [template]

        service = WorkerTemplateService(template_repository=mock_repository)
        required = WorkerCapacity(cpu_cores=4, memory_gb=8, storage_gb=100)
        result = await service.select_optimal_template_async(required)

        assert result.excess_capacity is not None
        assert result.excess_capacity.cpu_cores == 4  # 8 - 4
        assert result.excess_capacity.memory_gb == 8  # 16 - 8
        assert result.excess_capacity.storage_gb == 100  # 200 - 100

    @pytest.mark.asyncio
    async def test_select_optimal_template_no_match_raises_error(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test that no matching template raises NoMatchingTemplateError."""
        mock_repository.find_matching_templates_async.return_value = []

        service = WorkerTemplateService(template_repository=mock_repository)
        required = WorkerCapacity(cpu_cores=100, memory_gb=500, storage_gb=10000)

        with pytest.raises(NoMatchingTemplateError):
            await service.select_optimal_template_async(required)


class TestSelectTemplateWithHeadroom:
    """Tests for template selection with headroom."""

    @pytest.mark.asyncio
    async def test_select_with_headroom_adjusts_requirements(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test that headroom adjusts capacity requirements."""
        template = WorkerTemplate.create(
            name="medium",
            description="Medium",
            instance_type=Ec2InstanceType.MEDIUM,
            capacity=WorkerCapacity(cpu_cores=12, memory_gb=24, storage_gb=150),
        )
        mock_repository.find_matching_templates_async.return_value = [template]

        service = WorkerTemplateService(template_repository=mock_repository)
        required = WorkerCapacity(cpu_cores=8, memory_gb=16, storage_gb=100)

        result = await service.select_template_with_headroom_async(
            required_capacity=required,
            headroom_percent=50.0,  # 50% headroom
        )

        # Verify adjusted capacity was passed (8*1.5=12, 16*1.5=24, 100*1.5=150)
        call_args = mock_repository.find_matching_templates_async.call_args[0][0]
        assert call_args.cpu_cores == 12
        assert call_args.memory_gb == 24
        assert call_args.storage_gb == 150
        assert "50.0% headroom" in result.match_reason


class TestFindAllMatchingTemplates:
    """Tests for finding all matching templates."""

    @pytest.mark.asyncio
    async def test_find_all_matching_returns_ranked_list(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test that all matching templates are returned with rankings."""
        templates = [
            WorkerTemplate.create(
                name=f"size-{i}",
                description=f"Size {i}",
                instance_type=Ec2InstanceType.SMALL,
                capacity=WorkerCapacity(
                    cpu_cores=(i + 1) * 2,
                    memory_gb=(i + 1) * 4,
                    storage_gb=(i + 1) * 50,
                ),
                cost_per_hour_usd=i * 0.10 + 0.10,
            )
            for i in range(3)
        ]
        mock_repository.find_matching_templates_async.return_value = templates

        service = WorkerTemplateService(template_repository=mock_repository)
        required = WorkerCapacity(cpu_cores=1, memory_gb=2, storage_gb=25)

        results = await service.find_all_matching_templates_async(required)

        assert len(results) == 3
        assert results[0].cost_ranking == 0
        assert results[1].cost_ranking == 1
        assert results[2].cost_ranking == 2

    @pytest.mark.asyncio
    async def test_find_all_matching_returns_empty_list_if_no_match(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test that empty list is returned when no templates match."""
        mock_repository.find_matching_templates_async.return_value = []

        service = WorkerTemplateService(template_repository=mock_repository)
        required = WorkerCapacity(cpu_cores=100, memory_gb=500, storage_gb=10000)

        results = await service.find_all_matching_templates_async(required)

        assert results == []


class TestTemplateCreationFromDict:
    """Tests for the internal _create_template_from_dict method."""

    def test_creates_template_with_all_fields(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test template creation with all fields specified."""
        service = WorkerTemplateService(template_repository=mock_repository)
        data = {
            "id": "custom-id",
            "name": "test-template",
            "description": "Test description",
            "instance_type": "medium",
            "ami_name_pattern": "CML-2.7.*",
            "capacity": {"cpu_cores": 4, "memory_gb": 16, "storage_gb": 100, "max_nodes": 20},
            "cost_per_hour_usd": 0.50,
            "enabled": False,
        }

        template = service._create_template_from_dict(data)

        assert template.state.id == "custom-id"
        assert template.state.name == "test-template"
        assert template.state.description == "Test description"
        assert template.state.instance_type == Ec2InstanceType.MEDIUM
        assert template.state.ami_name_pattern == "CML-2.7.*"
        assert template.state.capacity.cpu_cores == 4
        assert template.state.capacity.max_nodes == 20
        assert template.state.cost_per_hour_usd == 0.50
        assert template.state.enabled is False

    def test_maps_aws_instance_types(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test that AWS instance type strings are mapped correctly."""
        service = WorkerTemplateService(template_repository=mock_repository)

        # Test m5zn.metal mapping
        data = {
            "name": "metal",
            "instance_type": "m5zn.metal",
            "capacity": {"cpu_cores": 48, "memory_gb": 192, "storage_gb": 1000},
        }

        template = service._create_template_from_dict(data)

        assert template.state.instance_type == Ec2InstanceType.METAL

    def test_defaults_to_small_for_unknown_instance_type(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test that unknown instance types default to SMALL."""
        service = WorkerTemplateService(template_repository=mock_repository)
        data = {
            "name": "unknown",
            "instance_type": "c5.4xlarge",  # Not in our mapping
            "capacity": {"cpu_cores": 4, "memory_gb": 8, "storage_gb": 50},
        }

        template = service._create_template_from_dict(data)

        assert template.state.instance_type == Ec2InstanceType.SMALL


class TestListTemplates:
    """Tests for listing templates."""

    @pytest.mark.asyncio
    async def test_list_enabled_templates(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test listing enabled templates."""
        templates = [
            WorkerTemplate.create(
                name="small",
                description="Small",
                instance_type=Ec2InstanceType.SMALL,
                capacity=WorkerCapacity(cpu_cores=2, memory_gb=4, storage_gb=50),
            )
        ]
        mock_repository.list_enabled_async.return_value = templates

        service = WorkerTemplateService(template_repository=mock_repository)
        result = await service.list_enabled_templates_async()

        assert len(result) == 1
        mock_repository.list_enabled_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_all_templates(
        self,
        mock_repository: AsyncMock,
    ) -> None:
        """Test listing all templates including disabled."""
        templates = [
            WorkerTemplate.create(
                name="small",
                description="Small",
                instance_type=Ec2InstanceType.SMALL,
                capacity=WorkerCapacity(cpu_cores=2, memory_gb=4, storage_gb=50),
                enabled=True,
            ),
            WorkerTemplate.create(
                name="disabled",
                description="Disabled",
                instance_type=Ec2InstanceType.MEDIUM,
                capacity=WorkerCapacity(cpu_cores=4, memory_gb=8, storage_gb=100),
                enabled=False,
            ),
        ]
        mock_repository.list_all_async.return_value = templates

        service = WorkerTemplateService(template_repository=mock_repository)
        result = await service.list_all_templates_async()

        assert len(result) == 2
        mock_repository.list_all_async.assert_called_once()


class TestServiceConfigure:
    """Tests for DI configuration."""

    def test_configure_registers_factory(self) -> None:
        """Test that configure registers the service factory."""
        mock_builder = MagicMock()
        mock_builder.services = MagicMock()
        mock_builder.services.add_scoped = MagicMock()

        WorkerTemplateService.configure(mock_builder)

        mock_builder.services.add_scoped.assert_called_once()
        args = mock_builder.services.add_scoped.call_args[0]
        assert args[0] == WorkerTemplateService
