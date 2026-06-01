"""Worker Template Service for loading, managing, and selecting worker templates.

This service handles:
- Loading template definitions from YAML configuration
- Seeding templates to MongoDB on startup (via HostedService)
- Selecting optimal templates based on capacity requirements
- Template validation and cost-based optimization

Templates are managed as configuration (not user-created) per ADR-007.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.hosting.abstractions import HostedService

from domain.entities.worker_template import WorkerTemplate
from domain.repositories.worker_template_repository import WorkerTemplateRepository
from domain.value_objects.worker_capacity import WorkerCapacity
from integration.enums import Ec2InstanceType

log = logging.getLogger(__name__)


class TemplateLoadError(Exception):
    """Raised when template loading fails."""

    pass


class TemplateValidationError(Exception):
    """Raised when template validation fails."""

    pass


class TemplateNotFoundError(Exception):
    """Raised when a requested template is not found."""

    def __init__(self, template_name: str):
        self.template_name = template_name
        super().__init__(f"Template not found: {template_name}")


class NoMatchingTemplateError(Exception):
    """Raised when no template matches the required capacity."""

    def __init__(self, required_capacity: WorkerCapacity):
        self.required_capacity = required_capacity
        super().__init__(f"No template can satisfy capacity: cpu={required_capacity.cpu_cores}, memory={required_capacity.memory_gb}GB, storage={required_capacity.storage_gb}GB")


@dataclass
class TemplateSelection:
    """Result of template selection with optimization metadata."""

    template: WorkerTemplate
    match_reason: str
    excess_capacity: WorkerCapacity | None = None
    cost_ranking: int = 0  # 0 = cheapest matching option


class WorkerTemplateService:
    """Service for managing and selecting worker templates.

    Responsibilities:
    - Load template definitions from YAML configuration files
    - Seed templates to MongoDB repository on startup
    - Select optimal templates based on capacity requirements
    - Provide cost-optimized template recommendations
    """

    def __init__(
        self,
        template_repository: WorkerTemplateRepository,
        templates_config_path: str | None = None,
    ) -> None:
        """Initialize the WorkerTemplateService.

        Args:
            template_repository: Repository for persisting templates
            templates_config_path: Path to YAML configuration file (optional)
        """
        self._repository = template_repository
        self._config_path = templates_config_path
        self._loaded_templates: dict[str, WorkerTemplate] = {}

    @staticmethod
    def configure(builder: Any) -> None:
        """Configure the service for dependency injection.

        Args:
            builder: Neuroglia WebApplicationBuilder for service registration
        """

        def factory(sp: ServiceProviderBase) -> "WorkerTemplateService":
            repository = sp.get_required_service(WorkerTemplateRepository)
            return WorkerTemplateService(
                template_repository=repository,
            )

        builder.services.add_scoped(WorkerTemplateService, implementation_factory=factory)

    async def load_templates_from_yaml(
        self,
        config_path: str | None = None,
    ) -> list[WorkerTemplate]:
        """Load template definitions from a YAML configuration file.

        Args:
            config_path: Path to YAML file (uses configured path if not provided)

        Returns:
            List of loaded WorkerTemplate entities

        Raises:
            TemplateLoadError: If file cannot be read or parsed
            TemplateValidationError: If template definitions are invalid
        """
        path = config_path or self._config_path
        if not path:
            raise TemplateLoadError("No template configuration path provided")

        config_file = Path(path)
        if not config_file.exists():
            raise TemplateLoadError(f"Template configuration file not found: {path}")

        try:
            with open(config_file) as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise TemplateLoadError(f"Failed to parse YAML configuration: {e}") from e

        if not data:
            raise TemplateLoadError("Empty configuration file")

        templates_data = data.get("templates", data.get("worker_templates", []))
        if not templates_data:
            raise TemplateLoadError("No templates found in configuration")

        templates: list[WorkerTemplate] = []
        for template_def in templates_data:
            try:
                template = self._create_template_from_dict(template_def)
                templates.append(template)
                self._loaded_templates[template.state.name] = template
            except (KeyError, ValueError) as e:
                raise TemplateValidationError(f"Invalid template definition: {template_def.get('name', 'unknown')}: {e}") from e

        log.info(f"Loaded {len(templates)} templates from {path}")
        return templates

    def load_templates_from_dict(
        self,
        templates_data: list[dict[str, Any]],
    ) -> list[WorkerTemplate]:
        """Load template definitions from a list of dictionaries.

        Useful for testing or programmatic template creation.

        Args:
            templates_data: List of template definitions

        Returns:
            List of WorkerTemplate entities

        Raises:
            TemplateValidationError: If template definitions are invalid
        """
        templates: list[WorkerTemplate] = []
        for template_def in templates_data:
            try:
                template = self._create_template_from_dict(template_def)
                templates.append(template)
                self._loaded_templates[template.state.name] = template
            except (KeyError, ValueError) as e:
                raise TemplateValidationError(f"Invalid template definition: {template_def.get('name', 'unknown')}: {e}") from e

        log.info(f"Loaded {len(templates)} templates from dict")
        return templates

    async def seed_templates_async(
        self,
        templates: list[WorkerTemplate] | None = None,
    ) -> int:
        """Seed templates to the repository, upserting by name.

        If templates is None, uses templates loaded from YAML.

        Args:
            templates: Templates to seed (uses loaded templates if None)

        Returns:
            Number of templates seeded

        Raises:
            TemplateLoadError: If no templates available to seed
        """
        templates_to_seed = templates or list(self._loaded_templates.values())
        if not templates_to_seed:
            raise TemplateLoadError("No templates to seed. Load templates first.")

        seeded_count = 0
        for template in templates_to_seed:
            try:
                await self._repository.upsert_by_name_async(template)
                seeded_count += 1
                log.debug(f"Seeded template: {template.state.name}")
            except Exception as e:
                log.error(f"Failed to seed template {template.state.name}: {e}")
                raise

        log.info(f"Seeded {seeded_count} templates to repository")
        return seeded_count

    async def get_template_by_name_async(self, name: str) -> WorkerTemplate:
        """Get a template by name.

        Args:
            name: Template name (e.g., "small", "medium", "large")

        Returns:
            WorkerTemplate entity

        Raises:
            TemplateNotFoundError: If template not found
        """
        template = await self._repository.get_by_name_async(name)
        if not template:
            raise TemplateNotFoundError(name)
        return template

    async def list_enabled_templates_async(self) -> list[WorkerTemplate]:
        """List all enabled templates, ordered by cost.

        Returns:
            List of enabled WorkerTemplates
        """
        return await self._repository.list_enabled_async()

    async def list_all_templates_async(self) -> list[WorkerTemplate]:
        """List all templates including disabled ones.

        Returns:
            List of all WorkerTemplates
        """
        return await self._repository.list_all_async()

    async def select_optimal_template_async(
        self,
        required_capacity: WorkerCapacity,
    ) -> TemplateSelection:
        """Select the optimal (cheapest) template that satisfies capacity requirements.

        Uses a cost-optimized selection strategy:
        1. Find all templates that can satisfy the required capacity
        2. Order by cost (ascending)
        3. Return the cheapest option

        Args:
            required_capacity: Minimum capacity requirements

        Returns:
            TemplateSelection with the optimal template

        Raises:
            NoMatchingTemplateError: If no template can satisfy requirements
        """
        matching_templates = await self._repository.find_matching_templates_async(required_capacity)

        if not matching_templates:
            raise NoMatchingTemplateError(required_capacity)

        # First template is cheapest (repository orders by cost)
        optimal = matching_templates[0]

        # Calculate excess capacity
        excess = WorkerCapacity(
            cpu_cores=optimal.state.capacity.cpu_cores - required_capacity.cpu_cores,
            memory_gb=optimal.state.capacity.memory_gb - required_capacity.memory_gb,
            storage_gb=optimal.state.capacity.storage_gb - required_capacity.storage_gb,
            max_nodes=None,  # Excess max_nodes not meaningful
        )

        return TemplateSelection(
            template=optimal,
            match_reason="Cost-optimized selection",
            excess_capacity=excess,
            cost_ranking=0,
        )

    async def select_template_with_headroom_async(
        self,
        required_capacity: WorkerCapacity,
        headroom_percent: float = 20.0,
    ) -> TemplateSelection:
        """Select a template with additional headroom above requirements.

        Useful for ensuring adequate capacity for workload spikes.

        Args:
            required_capacity: Base capacity requirements
            headroom_percent: Additional capacity as percentage (default 20%)

        Returns:
            TemplateSelection with headroom-adjusted template

        Raises:
            NoMatchingTemplateError: If no template can satisfy requirements
        """
        multiplier = 1 + (headroom_percent / 100)

        adjusted_capacity = WorkerCapacity(
            cpu_cores=int(required_capacity.cpu_cores * multiplier),
            memory_gb=int(required_capacity.memory_gb * multiplier),
            storage_gb=int(required_capacity.storage_gb * multiplier),
            max_nodes=required_capacity.max_nodes,
        )

        selection = await self.select_optimal_template_async(adjusted_capacity)
        selection.match_reason = f"Cost-optimized with {headroom_percent}% headroom"
        return selection

    async def find_all_matching_templates_async(
        self,
        required_capacity: WorkerCapacity,
    ) -> list[TemplateSelection]:
        """Find all templates that can satisfy capacity requirements.

        Returns all matching templates with their cost rankings,
        ordered from cheapest to most expensive.

        Args:
            required_capacity: Minimum capacity requirements

        Returns:
            List of TemplateSelections (empty if none match)
        """
        matching_templates = await self._repository.find_matching_templates_async(required_capacity)

        selections: list[TemplateSelection] = []
        for rank, template in enumerate(matching_templates):
            excess = WorkerCapacity(
                cpu_cores=template.state.capacity.cpu_cores - required_capacity.cpu_cores,
                memory_gb=template.state.capacity.memory_gb - required_capacity.memory_gb,
                storage_gb=template.state.capacity.storage_gb - required_capacity.storage_gb,
                max_nodes=None,
            )
            selections.append(
                TemplateSelection(
                    template=template,
                    match_reason="Capacity match",
                    excess_capacity=excess,
                    cost_ranking=rank,
                )
            )

        return selections

    def _create_template_from_dict(self, data: dict[str, Any]) -> WorkerTemplate:
        """Create a WorkerTemplate from a dictionary definition.

        Expected format:
        ```yaml
        name: medium
        description: Medium worker for moderate workloads
        instance_type: medium  # or m5.xlarge
        ami_name_pattern: cisco-cml2.9*
        capacity:
          cpu_cores: 16
          memory_gb: 64
          storage_gb: 500
          max_nodes: 20
        cost_per_hour_usd: 1.50
        enabled: true
        ```
        """
        # Required fields
        name = data["name"]
        description = data.get("description", f"{name} worker template")

        # Parse instance type (supports friendly names, enum values, or AWS instance types)
        instance_type_value = data.get("instance_type", "small")

        # Mapping from friendly names to enum members
        friendly_name_mapping = {
            "micro": Ec2InstanceType.MICRO,
            "small": Ec2InstanceType.SMALL,
            "medium": Ec2InstanceType.MEDIUM,
            "large": Ec2InstanceType.LARGE,
            "metal": Ec2InstanceType.METAL,
        }

        # Check if it's a friendly name first
        if instance_type_value.lower() in friendly_name_mapping:
            instance_type = friendly_name_mapping[instance_type_value.lower()]
        else:
            try:
                # Try to parse as enum value (e.g., "t3.small")
                instance_type = Ec2InstanceType(instance_type_value)
            except ValueError:
                # Fallback to mapping from common AWS types
                aws_type_mapping = {
                    "m5.xlarge": Ec2InstanceType.SMALL,
                    "m5.2xlarge": Ec2InstanceType.MEDIUM,
                    "m5.4xlarge": Ec2InstanceType.LARGE,
                    "m5zn.metal": Ec2InstanceType.METAL,
                }
                instance_type = aws_type_mapping.get(instance_type_value, Ec2InstanceType.SMALL)

        # Parse capacity
        capacity_data = data.get("capacity", {})
        capacity = WorkerCapacity(
            cpu_cores=capacity_data.get("cpu_cores", 4),
            memory_gb=capacity_data.get("memory_gb", 16),
            storage_gb=capacity_data.get("storage_gb", 100),
            max_nodes=capacity_data.get("max_nodes"),
        )

        # Optional fields
        ami_name_pattern = data.get("ami_name_pattern", "cisco-cml2.9*")
        cost_per_hour_usd = float(data.get("cost_per_hour_usd", 0.0))
        enabled = data.get("enabled", True)
        template_id = data.get("id")  # Optional, for idempotent seeding

        return WorkerTemplate.create(
            name=name,
            description=description,
            instance_type=instance_type,
            capacity=capacity,
            ami_name_pattern=ami_name_pattern,
            cost_per_hour_usd=cost_per_hour_usd,
            enabled=enabled,
            template_id=template_id,
        )


# ============================================================================
# Hosted Service for Template Seeding
# ============================================================================


class WorkerTemplateSeederHostedService(HostedService):
    """Hosted service to seed worker templates on application startup.

    Loads templates from YAML configuration and seeds them to MongoDB.
    This ensures templates are available when the application starts.

    Usage:
        Register via `WorkerTemplateSeederHostedService.configure(builder)`
        in main.py to enable auto-seeding on startup.
    """

    def __init__(
        self,
        template_service: WorkerTemplateService,
        auto_seed: bool = True,
    ) -> None:
        """Initialize the seeder service.

        Args:
            template_service: Service for loading and seeding templates
            auto_seed: Whether to auto-seed on startup (default: True)
        """
        self._template_service = template_service
        self._auto_seed = auto_seed
        self._started = False
        self._seeded_count = 0

    async def start_async(self) -> None:
        """Start the hosted service and seed templates if auto_seed is enabled."""
        if self._started:
            return

        log.info("Starting WorkerTemplateSeederHostedService")

        if not self._auto_seed:
            log.info("Auto-seeding disabled, skipping template seeding")
            self._started = True
            return

        try:
            # Load templates from YAML configuration
            templates = await self._template_service.load_templates_from_yaml()
            log.info(f"Loaded {len(templates)} templates from configuration")

            # Seed to MongoDB (upsert by name)
            self._seeded_count = await self._template_service.seed_templates_async(templates)
            log.info(f"Seeded {self._seeded_count} templates to database")

        except TemplateLoadError as e:
            # Log warning but don't fail startup - templates can be added later
            log.warning(f"Could not load templates: {e}")
        except Exception as e:
            log.error(f"Failed to seed templates: {e}")
            # Don't raise - allow application to start without templates
            # They can be added manually or via API later

        self._started = True

    async def stop_async(self) -> None:
        """Stop the hosted service."""
        if not self._started:
            return

        log.info(f"Stopping WorkerTemplateSeederHostedService (seeded {self._seeded_count} templates during startup)")
        self._started = False

    @property
    def seeded_count(self) -> int:
        """Get the number of templates seeded during startup."""
        return self._seeded_count

    @staticmethod
    def configure(builder: "Any") -> None:
        """Register the seeder service with the DI builder.

        Args:
            builder: Application builder instance
        """
        from application.settings import app_settings

        # Register WorkerTemplateSeederHostedService as singleton
        def factory(sp: ServiceProviderBase) -> "WorkerTemplateSeederHostedService":
            template_service = sp.get_required_service(WorkerTemplateService)
            return WorkerTemplateSeederHostedService(
                template_service=template_service,
                auto_seed=app_settings.worker_templates_auto_seed,
            )

        builder.services.add_singleton(WorkerTemplateSeederHostedService, implementation_factory=factory)
