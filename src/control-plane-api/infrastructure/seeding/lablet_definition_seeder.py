"""LabletDefinition EntitySeeder implementation.

Seeds LabletDefinition aggregates from YAML files in data/seeds/lablet_definitions/.

Each YAML file represents a versioned lab template that can be instantiated
on CML workers. The seeder handles proper construction of value objects
(ResourceRequirements, PortTemplate) and domain entity creation.
"""

import logging
from typing import Any

from domain.entities.lablet_definition import LabletDefinition, NotificationConfig
from domain.enums import LicenseType
from domain.value_objects.port_template import PortDefinition, PortTemplate
from domain.value_objects.resource_requirements import AmiRequirement, ResourceRequirements
from lcm_core.infrastructure.seeding import EntitySeeder
from neuroglia.data.infrastructure.abstractions import Repository

logger = logging.getLogger(__name__)


class LabletDefinitionSeeder(EntitySeeder[LabletDefinition]):
    """Seeds LabletDefinition aggregates from YAML configuration.

    YAML Schema:
        id: lablet-def-test-lab-1.1-v1.0.0  # Optional, auto-generated if not provided
        name: test-lab-1.1
        version: '1.0.0'
        description: A test lab with PC, router, and mock API

        # Content identification (required)
        form_qualified_name: Exam Associate CCNA v1.1 LAB 1.1  # FQN for LDS content

        # Artifact references (optional — populated by content sync)
        lab_yaml_hash: abc123...  # SHA-256 of the lab YAML content (optional, default empty)
        grading_rules_uri: s3://lablet-artifacts/TEST-LAB-1.1/grade.xml  # Optional

        # Content packaging (optional)
        user_session_package_name: SVN.zip  # Default: SVN.zip
        grading_ruleset_package_name: SVN.zip  # Default: SVN.zip
        user_session_type: LDS  # Default: LDS
        user_session_default_region: us-east-1  # Optional, None = use global default

        # Resource requirements
        resource_requirements:
          cpu_cores: 4
          memory_gb: 8
          storage_gb: 50
          nested_virt: true  # Default: true
          ami_requirements:
            - cml_version_min: '2.7.0'
              node_definitions_required:
                - ubuntu-desktop-24-04-v2
                - iosv
                - vmanagemock

        # Lab metadata
        node_count: 3
        license_affinity:
          - personal
          - enterprise

        # Port template (ports to be allocated per instance)
        port_template:
          ports:
            - name: pc_serial
              protocol: tcp
              description: Serial console for PC node
            - name: pc_vnc
              protocol: tcp
              description: VNC display for PC node
            - name: router_serial
              protocol: tcp
              description: Serial console for router

        # Session configuration
        max_duration_minutes: 120
        warm_pool_depth: 0

        # Ownership and notifications (optional)
        owner_notification:
          email: lab-admin@example.com
          notify_on_start: true
          notify_on_complete: true
          notify_on_error: true

        created_by: seeder
    """

    @property
    def entity_type(self) -> str:
        return "lablet_definitions"

    @property
    def folder_name(self) -> str:
        return "lablet_definitions"

    @property
    def seeding_order(self) -> int:
        # Lablet definitions depend on nothing, but seed after templates
        return 20

    def get_repository(self, scoped_provider: Any) -> Repository[LabletDefinition, str]:
        """Get the LabletDefinition repository."""
        return scoped_provider.get_required_service(Repository[LabletDefinition, str])

    async def entity_exists_async(
        self,
        entity_id: str,
        data: dict[str, Any],
        repository: Repository[LabletDefinition, str],
    ) -> bool:
        """Check if LabletDefinition exists by name+version (not by ID).

        LabletDefinitions use generated UUIDs, so we check by name+version
        which is the actual uniqueness constraint.
        """
        name = data.get("name")
        version = str(data.get("version", "1.0.0"))
        if not name:
            return False

        # Cast to specific repository type for get_by_name_and_version_async
        if hasattr(repository, "get_by_name_and_version_async"):
            existing = await repository.get_by_name_and_version_async(name, version)  # type: ignore
            return existing is not None

        # Fallback to base implementation
        return await super().entity_exists_async(entity_id, data, repository)

    def get_entity_id(self, data: dict[str, Any]) -> str | None:
        """Extract definition ID from YAML data.

        Uses 'id' field, or generates from name and version if not present.
        """
        definition_id = data.get("id")
        if definition_id:
            return str(definition_id)

        # Fallback: generate ID from name and version
        name = data.get("name")
        version = data.get("version", "1.0.0")
        if name:
            return f"lablet-def-{name}-v{version}"

        return None

    def validate_data(self, data: dict[str, Any]) -> list[str]:
        """Validate LabletDefinition YAML data."""
        errors = []

        # Required fields
        if not data.get("name"):
            errors.append("Missing required field: name")

        if not data.get("version"):
            errors.append("Missing required field: version")

        if not data.get("form_qualified_name"):
            errors.append("Missing required field: form_qualified_name")

        # Resource requirements validation
        resource_req = data.get("resource_requirements", {})
        if not resource_req:
            errors.append("Missing required field: resource_requirements")
        else:
            required_fields = ["cpu_cores", "memory_gb", "storage_gb"]
            for field in required_fields:
                if field not in resource_req:
                    errors.append(f"Missing required resource_requirements field: {field}")

        # Port template validation
        port_template = data.get("port_template", {})
        ports = port_template.get("ports", [])
        for i, port in enumerate(ports):
            if not port.get("name"):
                errors.append(f"Port definition {i} missing required field: name")

        # License affinity validation
        license_affinity = data.get("license_affinity", [])
        valid_licenses = {lt.value for lt in LicenseType}
        for lic in license_affinity:
            if lic not in valid_licenses:
                errors.append(f"Invalid license type: {lic}. Must be one of: {valid_licenses}")

        return errors

    def create_entity(self, data: dict[str, Any]) -> LabletDefinition:
        """Create a LabletDefinition aggregate from YAML data."""
        # Parse resource requirements
        resource_req_data = data.get("resource_requirements", {})
        ami_reqs = [
            AmiRequirement(
                cml_version_min=req.get("cml_version_min"),
                cml_version_max=req.get("cml_version_max"),
                node_definitions_required=tuple(req.get("node_definitions_required", [])),
            )
            for req in resource_req_data.get("ami_requirements", [])
        ]
        resource_requirements = ResourceRequirements(
            cpu_cores=resource_req_data.get("cpu_cores", 2),
            memory_gb=resource_req_data.get("memory_gb", 4),
            storage_gb=resource_req_data.get("storage_gb", 50),
            nested_virt=resource_req_data.get("nested_virt", True),
            ami_requirements=tuple(ami_reqs),
        )

        # Parse port template
        port_template_data = data.get("port_template", {})
        ports = [
            PortDefinition(
                name=port.get("name"),
                protocol=port.get("protocol", "tcp"),
                description=port.get("description"),
            )
            for port in port_template_data.get("ports", [])
        ]
        port_template = PortTemplate(ports=tuple(ports))

        # Parse license affinity
        license_affinity = [LicenseType(lic) for lic in data.get("license_affinity", [])]

        # Parse owner notification config (optional)
        notification_data = data.get("owner_notification")
        owner_notification = None
        if notification_data:
            owner_notification = NotificationConfig(
                email=notification_data.get("email"),
                webhook_url=notification_data.get("webhook_url"),
                notify_on_start=notification_data.get("notify_on_start", True),
                notify_on_complete=notification_data.get("notify_on_complete", True),
                notify_on_error=notification_data.get("notify_on_error", True),
            )

        # Create the LabletDefinition aggregate
        # Note: lab_artifact_uri is auto-derived from form_qualified_name + package name
        definition = LabletDefinition.create(
            name=data.get("name"),
            version=str(data.get("version", "1.0.0")),
            form_qualified_name=data.get("form_qualified_name"),
            resource_requirements=resource_requirements,
            license_affinity=license_affinity,
            node_count=data.get("node_count", 0),
            port_template=port_template,
            created_by=data.get("created_by", "seeder"),
            user_session_package_name=data.get("user_session_package_name", "SVN.zip"),
            grading_ruleset_package_name=data.get("grading_ruleset_package_name", "SVN.zip"),
            user_session_type=data.get("user_session_type", "LDS"),
            user_session_default_region=data.get("user_session_default_region"),
            lab_yaml_hash=data.get("lab_yaml_hash", ""),
            lab_yaml_cached=data.get("lab_yaml_cached"),
            grading_rules_uri=data.get("grading_rules_uri"),
            max_duration_minutes=data.get("max_duration_minutes", 60),
            warm_pool_depth=data.get("warm_pool_depth", 0),
            owner_notification=owner_notification,
            pipelines=data.get("pipelines"),
            lab_reuse_enabled=data.get("lab_reuse_enabled", False),
        )

        # Note: LabletDefinition.create() generates its own ID via uuid4.
        # If we need to use the YAML-specified ID, we'd need to override it.
        # For now, we let the domain generate the ID and use name+version for lookup.

        logger.debug(f"Created LabletDefinition: name={data.get('name')}, version={data.get('version')}, id={definition.id()}")

        return definition
