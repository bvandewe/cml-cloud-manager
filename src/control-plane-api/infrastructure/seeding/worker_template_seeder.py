"""WorkerTemplate EntitySeeder implementation.

Seeds WorkerTemplate aggregates from YAML files in data/seeds/worker_templates/.
"""

import logging
from typing import Any

from domain.entities.worker_template import WorkerTemplate
from domain.value_objects.worker_capacity import WorkerCapacity
from integration.enums import Ec2InstanceType
from lcm_core.infrastructure.seeding import EntitySeeder
from neuroglia.data.infrastructure.abstractions import Repository

logger = logging.getLogger(__name__)


class WorkerTemplateSeeder(EntitySeeder[WorkerTemplate]):
    """Seeds WorkerTemplate aggregates from YAML configuration.

    YAML Schema:
        id: worker-template-small
        name: small
        description: Small worker for simple labs
        instance_type: t3.small
        ami_name_pattern: 'cisco-cml2.9*'
        capacity:
          cpu_cores: 2
          memory_gb: 2
          storage_gb: 50
          max_nodes: 5
        cost_per_hour_usd: 0.0208
        enabled: true
        created_by: seeder
    """

    @property
    def entity_type(self) -> str:
        return "worker_templates"

    @property
    def folder_name(self) -> str:
        return "worker_templates"

    @property
    def seeding_order(self) -> int:
        # Templates should be seeded early (before workers)
        return 10

    def get_repository(self, scoped_provider: Any) -> Repository[WorkerTemplate, str]:
        """Get the WorkerTemplate repository."""
        return scoped_provider.get_required_service(Repository[WorkerTemplate, str])

    def get_entity_id(self, data: dict[str, Any]) -> str | None:
        """Extract template ID from YAML data.

        Uses 'id' field, or generates from 'name' if not present.
        """
        template_id = data.get("id")
        if template_id:
            return str(template_id)

        # Fallback: generate ID from name
        name = data.get("name")
        if name:
            return f"worker-template-{name}"

        return None

    def validate_data(self, data: dict[str, Any]) -> list[str]:
        """Validate WorkerTemplate YAML data."""
        errors = []

        if not data.get("name"):
            errors.append("Missing required field: name")

        if not data.get("instance_type"):
            errors.append("Missing required field: instance_type")

        capacity = data.get("capacity", {})
        if not capacity:
            errors.append("Missing required field: capacity")
        else:
            required_capacity_fields = ["cpu_cores", "memory_gb", "storage_gb", "max_nodes"]
            for field in required_capacity_fields:
                if field not in capacity:
                    errors.append(f"Missing required capacity field: {field}")

        return errors

    def create_entity(self, data: dict[str, Any]) -> WorkerTemplate:
        """Create a WorkerTemplate aggregate from YAML data."""
        # Parse capacity
        capacity_data = data.get("capacity", {})
        capacity = WorkerCapacity(
            cpu_cores=capacity_data.get("cpu_cores", 2),
            memory_gb=capacity_data.get("memory_gb", 4),
            storage_gb=capacity_data.get("storage_gb", 100),
            max_nodes=capacity_data.get("max_nodes", 10),
        )

        # Parse instance type
        instance_type_str = data.get("instance_type", "small")
        try:
            # Handle both enum value (t3.small) and name (SMALL)
            if instance_type_str.startswith("t3.") or instance_type_str.startswith("m5"):
                instance_type = Ec2InstanceType(instance_type_str)
            else:
                instance_type = Ec2InstanceType[instance_type_str.upper()]
        except (ValueError, KeyError):
            logger.warning(f"Unknown instance type '{instance_type_str}', using SMALL")
            instance_type = Ec2InstanceType.SMALL

        # Create template using factory method
        template = WorkerTemplate.create(
            name=data.get("name", ""),
            description=data.get("description", ""),
            instance_type=instance_type,
            capacity=capacity,
            ami_name_pattern=data.get("ami_name_pattern", "cisco-cml2.9*"),
            cost_per_hour_usd=float(data.get("cost_per_hour_usd", 0.0)),
            enabled=data.get("enabled", True),
            template_id=self.get_entity_id(data),
        )

        return template
