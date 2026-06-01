"""LabletDefinition Data Transfer Objects for API responses."""

from dataclasses import dataclass


@dataclass
class ResourceRequirementsDto:
    """DTO for resource requirements."""

    cpu_cores: int
    memory_gb: int
    storage_gb: int
    nested_virt: bool


@dataclass
class PortDefinitionDto:
    """DTO for a single port definition."""

    name: str
    protocol: str
    description: str | None


@dataclass
class PortTemplateDto:
    """DTO for port template configuration."""

    ports: list[PortDefinitionDto]
    port_count: int


@dataclass
class LabletDefinitionCreatedDto:
    """DTO returned after creating a LabletDefinition."""

    id: str
    name: str
    version: str
    lab_artifact_uri: str
    status: str
    created_by: str
    created_at: str


@dataclass
class LabletDefinitionSummaryDto:
    """Summary DTO for list queries - lightweight representation."""

    id: str
    name: str
    version: str
    form_qualified_name: str | None
    status: str
    sync_status: str | None
    node_count: int
    max_duration_minutes: int
    warm_pool_depth: int
    is_deprecated: bool
    created_at: str
    updated_at: str


@dataclass
class LabletDefinitionDto:
    """Full DTO for single LabletDefinition retrieval."""

    # Identity
    id: str
    name: str
    version: str
    form_qualified_name: str | None
    bucket_name: str

    # Artifact
    lab_artifact_uri: str
    lab_yaml_hash: str
    lab_yaml_cached: str | None

    # Resources
    resource_requirements: ResourceRequirementsDto
    license_affinity: list[str]
    node_count: int

    # Port configuration
    port_template: PortTemplateDto

    # Assessment
    grading_rules_uri: str | None
    max_duration_minutes: int

    # LDS / Content config
    user_session_package_name: str
    grading_ruleset_package_name: str
    user_session_type: str
    user_session_default_region: str | None

    # Warm pool
    warm_pool_depth: int

    # Status
    status: str
    previous_version_id: str | None

    # Content metadata (from sync — ADR-025)
    content_package_hash: str | None
    upstream_version: str | None
    upstream_date_published: str | None
    upstream_instance_name: str | None
    upstream_form_id: str | None
    grade_xml_path: str | None
    cml_yaml_path: str | None
    cml_yaml_content: str | None  # Cached CML YAML content (for content viewer)
    devices_json: str | None  # Cached devices.json content (for content viewer)
    content_xml_content: str | None  # Raw content.xml from session package (for content viewer)
    user_visible_devices: list[dict[str, str]] | None  # From content.xml (AD-LDS-001)
    upstream_sync_status: dict | None
    port_conflicts: list[dict] | None  # Multi-port device conflicts (AD-LDS-002)
    lds_port_preferences: dict[str, str] | None  # User per-device port override (AD-LDS-002 Phase 3)

    # Deprecation
    deprecated_by: str | None
    deprecated_at: str | None
    deprecation_reason: str | None
    replacement_version: str | None

    # Sync status
    last_synced_at: str | None
    sync_status: str | None

    # Lab binding options
    lab_reuse_enabled: bool
    multi_lab_enabled: bool

    # Instantiation timing (AD-P10-01)
    boot_lead_time_minutes: int | None  # Per-definition override, None = use global setting

    # Pipeline definitions (ADR-034)
    pipelines: dict | None  # Optional pipeline DAGs from definition YAML

    # Ownership
    created_by: str
    created_at: str
    updated_at: str


@dataclass
class LabletDefinitionSyncResultDto:
    """DTO returned after syncing a LabletDefinition artifact."""

    id: str
    name: str
    version: str
    sync_status: str
    synced_at: str | None
    lab_yaml_hash: str
    content_changed: bool


def map_lablet_definition_to_dto(entity) -> LabletDefinitionDto:
    """Map a LabletDefinition entity to its full DTO representation.

    Args:
        entity: The LabletDefinition aggregate

    Returns:
        LabletDefinitionDto with all fields populated
    """
    state = entity.state

    # Map resource requirements
    resource_requirements = ResourceRequirementsDto(
        cpu_cores=state.resource_requirements.cpu_cores,
        memory_gb=state.resource_requirements.memory_gb,
        storage_gb=state.resource_requirements.storage_gb,
        nested_virt=state.resource_requirements.nested_virt,
    )

    # Map port template
    port_definitions = [
        PortDefinitionDto(
            name=p.name,
            protocol=p.protocol,
            description=p.description,
        )
        for p in state.port_template.ports
    ]
    port_template = PortTemplateDto(
        ports=port_definitions,
        port_count=state.port_template.port_count,
    )

    return LabletDefinitionDto(
        id=entity.id(),
        name=state.name,
        version=state.version,
        form_qualified_name=state.form_qualified_name,
        bucket_name=state.bucket_name,
        lab_artifact_uri=state.lab_artifact_uri,
        lab_yaml_hash=state.lab_yaml_hash,
        lab_yaml_cached=state.lab_yaml_cached,
        resource_requirements=resource_requirements,
        license_affinity=[lt.value for lt in state.license_affinity],
        node_count=state.node_count,
        port_template=port_template,
        grading_rules_uri=state.grading_rules_uri,
        max_duration_minutes=state.max_duration_minutes,
        user_session_package_name=state.user_session_package_name,
        grading_ruleset_package_name=state.grading_ruleset_package_name,
        user_session_type=state.user_session_type,
        user_session_default_region=state.user_session_default_region,
        warm_pool_depth=state.warm_pool_depth,
        status=state.status.value,
        previous_version_id=state.previous_version_id,
        content_package_hash=state.content_package_hash,
        upstream_version=state.upstream_version,
        upstream_date_published=state.upstream_date_published,
        upstream_instance_name=state.upstream_instance_name,
        upstream_form_id=state.upstream_form_id,
        grade_xml_path=state.grade_xml_path,
        cml_yaml_path=state.cml_yaml_path,
        cml_yaml_content=state.cml_yaml_content,
        devices_json=state.devices_json,
        content_xml_content=getattr(state, "content_xml_content", None),
        user_visible_devices=getattr(state, "user_visible_devices", None),
        upstream_sync_status=state.upstream_sync_status,
        port_conflicts=getattr(state, "port_conflicts", None),
        lds_port_preferences=getattr(state, "lds_port_preferences", None),
        deprecated_by=state.deprecated_by,
        deprecated_at=state.deprecated_at.isoformat() if state.deprecated_at else None,
        deprecation_reason=state.deprecation_reason,
        replacement_version=state.replacement_version,
        last_synced_at=state.last_synced_at.isoformat() if state.last_synced_at else None,
        sync_status=state.sync_status,
        lab_reuse_enabled=getattr(state, "lab_reuse_enabled", False),
        multi_lab_enabled=getattr(state, "multi_lab_enabled", False),
        boot_lead_time_minutes=getattr(state, "boot_lead_time_minutes", None),
        pipelines=getattr(state, "pipelines", None),
        created_by=state.created_by,
        created_at=state.created_at.isoformat(),
        updated_at=state.updated_at.isoformat(),
    )


def map_lablet_definition_to_summary_dto(entity) -> LabletDefinitionSummaryDto:
    """Map a LabletDefinition entity to a summary DTO for lists.

    Args:
        entity: The LabletDefinition aggregate

    Returns:
        LabletDefinitionSummaryDto with essential fields
    """
    from domain.enums import LabletDefinitionStatus

    state = entity.state
    return LabletDefinitionSummaryDto(
        id=entity.id(),
        name=state.name,
        version=state.version,
        form_qualified_name=state.form_qualified_name,
        status=state.status.value,
        sync_status=state.sync_status,
        node_count=state.node_count,
        max_duration_minutes=state.max_duration_minutes,
        warm_pool_depth=state.warm_pool_depth,
        is_deprecated=state.status == LabletDefinitionStatus.DEPRECATED,
        created_at=state.created_at.isoformat(),
        updated_at=state.updated_at.isoformat(),
    )
