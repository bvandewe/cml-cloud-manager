"""Domain events for LabletDefinition aggregate operations."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from neuroglia.data.abstractions import DomainEvent
from neuroglia.eventing.cloud_events.decorators import cloudevent


@cloudevent("lablet_definition.created.v1")
@dataclass
class LabletDefinitionCreatedDomainEvent(DomainEvent):
    """Event raised when a new LabletDefinition is created."""

    aggregate_id: str
    name: str
    version: str
    lab_artifact_uri: str
    lab_yaml_hash: str
    lab_yaml_cached: str | None
    resource_requirements: dict[str, Any]  # Serialized ResourceRequirements
    license_affinity: list[str]  # LicenseType values
    node_count: int
    port_template: dict[str, Any]  # Serialized PortTemplate
    grading_rules_uri: str | None
    max_duration_minutes: int
    warm_pool_depth: int
    owner_notification: dict[str, Any] | None
    created_by: str
    created_at: datetime

    # Content synchronization fields (ADR-025, ADR-028)
    form_qualified_name: str | None
    bucket_name: str
    user_session_package_name: str
    grading_ruleset_package_name: str
    user_session_type: str
    user_session_default_region: str | None

    # Instantiation timing (AD-P10-01)
    boot_lead_time_minutes: int | None

    # Pipeline definitions (ADR-034)
    pipelines: dict | None

    def __init__(
        self,
        aggregate_id: str,
        name: str,
        version: str,
        lab_artifact_uri: str,
        lab_yaml_hash: str,
        lab_yaml_cached: str | None,
        resource_requirements: dict[str, Any],
        license_affinity: list[str],
        node_count: int,
        port_template: dict[str, Any],
        grading_rules_uri: str | None,
        max_duration_minutes: int,
        warm_pool_depth: int,
        owner_notification: dict[str, Any] | None,
        created_by: str,
        created_at: datetime,
        # Content synchronization fields (ADR-025, ADR-028)
        form_qualified_name: str | None = None,
        bucket_name: str = "",
        user_session_package_name: str = "SVN.zip",
        grading_ruleset_package_name: str = "SVN.zip",
        user_session_type: str = "LDS",
        user_session_default_region: str | None = None,
        boot_lead_time_minutes: int | None = None,
        pipelines: dict | None = None,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.name = name
        self.version = version
        self.lab_artifact_uri = lab_artifact_uri
        self.lab_yaml_hash = lab_yaml_hash
        self.lab_yaml_cached = lab_yaml_cached
        self.resource_requirements = resource_requirements
        self.license_affinity = license_affinity
        self.node_count = node_count
        self.port_template = port_template
        self.grading_rules_uri = grading_rules_uri
        self.max_duration_minutes = max_duration_minutes
        self.warm_pool_depth = warm_pool_depth
        self.owner_notification = owner_notification
        self.created_by = created_by
        self.created_at = created_at
        self.form_qualified_name = form_qualified_name
        self.bucket_name = bucket_name
        self.user_session_package_name = user_session_package_name
        self.grading_ruleset_package_name = grading_ruleset_package_name
        self.user_session_type = user_session_type
        self.user_session_default_region = user_session_default_region
        self.boot_lead_time_minutes = boot_lead_time_minutes
        self.pipelines = pipelines


@cloudevent("lablet_definition.version_created.v1")
@dataclass
class LabletDefinitionVersionCreatedDomainEvent(DomainEvent):
    """Event raised when a new version of a LabletDefinition is created.

    This event is raised when an existing definition gets a new version,
    linking it to the previous version for version history tracking.
    """

    aggregate_id: str
    name: str
    version: str
    previous_version: str
    lab_artifact_uri: str
    lab_yaml_hash: str
    resource_requirements: dict[str, Any]
    node_count: int
    port_template: dict[str, Any]
    created_by: str
    created_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        name: str,
        version: str,
        previous_version: str,
        lab_artifact_uri: str,
        lab_yaml_hash: str,
        resource_requirements: dict[str, Any],
        node_count: int,
        port_template: dict[str, Any],
        created_by: str,
        created_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.name = name
        self.version = version
        self.previous_version = previous_version
        self.lab_artifact_uri = lab_artifact_uri
        self.lab_yaml_hash = lab_yaml_hash
        self.resource_requirements = resource_requirements
        self.node_count = node_count
        self.port_template = port_template
        self.created_by = created_by
        self.created_at = created_at


@cloudevent("lablet_definition.deprecated.v1")
@dataclass
class LabletDefinitionDeprecatedDomainEvent(DomainEvent):
    """Event raised when a LabletDefinition is deprecated.

    A deprecated definition can no longer be used for new instances,
    but existing instances using this definition continue to work.
    """

    aggregate_id: str
    name: str
    version: str
    deprecated_by: str
    deprecated_at: datetime
    deprecation_reason: str | None
    replacement_version: str | None  # Suggested replacement version

    def __init__(
        self,
        aggregate_id: str,
        name: str,
        version: str,
        deprecated_by: str,
        deprecated_at: datetime,
        deprecation_reason: str | None = None,
        replacement_version: str | None = None,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.name = name
        self.version = version
        self.deprecated_by = deprecated_by
        self.deprecated_at = deprecated_at
        self.deprecation_reason = deprecation_reason
        self.replacement_version = replacement_version


@cloudevent("lablet_definition.artifact_synced.v1")
@dataclass
class LabletDefinitionArtifactSyncedDomainEvent(DomainEvent):
    """Event raised when artifact sync completes for a LabletDefinition."""

    aggregate_id: str
    lab_artifact_uri: str
    lab_yaml_hash: str
    synced_at: datetime
    sync_status: str  # "success" | "failed"
    error_message: str | None

    def __init__(
        self,
        aggregate_id: str,
        lab_artifact_uri: str,
        lab_yaml_hash: str,
        synced_at: datetime,
        sync_status: str,
        error_message: str | None = None,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_artifact_uri = lab_artifact_uri
        self.lab_yaml_hash = lab_yaml_hash
        self.synced_at = synced_at
        self.sync_status = sync_status
        self.error_message = error_message


@cloudevent("lablet_definition.warm_pool_updated.v1")
@dataclass
class LabletDefinitionWarmPoolUpdatedDomainEvent(DomainEvent):
    """Event raised when warm pool depth is updated."""

    aggregate_id: str
    old_warm_pool_depth: int
    new_warm_pool_depth: int
    updated_by: str
    updated_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        old_warm_pool_depth: int,
        new_warm_pool_depth: int,
        updated_by: str,
        updated_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.old_warm_pool_depth = old_warm_pool_depth
        self.new_warm_pool_depth = new_warm_pool_depth
        self.updated_by = updated_by
        self.updated_at = updated_at


@cloudevent("lablet_definition.updated.v1")
@dataclass
class LabletDefinitionUpdatedDomainEvent(DomainEvent):
    """Event raised when a LabletDefinition is updated.

    Records which fields were changed and by whom.
    """

    aggregate_id: str
    changes: dict[str, Any]  # Field name -> new value
    updated_by: str
    updated_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        changes: dict[str, Any],
        updated_by: str,
        updated_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.changes = changes
        self.updated_by = updated_by
        self.updated_at = updated_at


@cloudevent("lablet_definition.activated.v1")
@dataclass
class LabletDefinitionActivatedDomainEvent(DomainEvent):
    """Event raised when a LabletDefinition is activated (made available for scheduling)."""

    aggregate_id: str
    activated_by: str
    activated_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        activated_by: str,
        activated_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.activated_by = activated_by
        self.activated_at = activated_at


@cloudevent("lablet_definition.deactivated.v1")
@dataclass
class LabletDefinitionDeactivatedDomainEvent(DomainEvent):
    """Event raised when a LabletDefinition is deactivated (temporarily unavailable for scheduling)."""

    aggregate_id: str
    deactivated_by: str
    deactivated_at: datetime
    reason: str | None

    def __init__(
        self,
        aggregate_id: str,
        deactivated_by: str,
        deactivated_at: datetime,
        reason: str | None = None,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.deactivated_by = deactivated_by
        self.deactivated_at = deactivated_at
        self.reason = reason


@cloudevent("lablet_definition.deleted.v1")
@dataclass
class LabletDefinitionDeletedDomainEvent(DomainEvent):
    """Event raised when a LabletDefinition is soft-deleted."""

    aggregate_id: str
    deleted_by: str
    deleted_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        deleted_by: str,
        deleted_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.deleted_by = deleted_by
        self.deleted_at = deleted_at


@cloudevent("lablet_definition.sync_requested.v1")
@dataclass
class LabletDefinitionSyncRequestedDomainEvent(DomainEvent):
    """Emitted when a user requests content synchronization for a definition.

    This event triggers the ContentSyncRequestedEtcdProjector, which writes
    an etcd key to notify the lablet-controller's ContentSyncService (AD-CS-001).
    """

    aggregate_id: str
    aggregate_type: str
    form_qualified_name: str
    bucket_name: str
    user_session_package_name: str
    requested_by: str
    requested_at: str

    def __init__(
        self,
        aggregate_id: str,
        form_qualified_name: str,
        bucket_name: str,
        requested_by: str,
        requested_at: str,
        aggregate_type: str = "LabletDefinition",
        user_session_package_name: str = "SVN.zip",
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.aggregate_type = aggregate_type
        self.form_qualified_name = form_qualified_name
        self.bucket_name = bucket_name
        self.user_session_package_name = user_session_package_name
        self.requested_by = requested_by
        self.requested_at = requested_at


@cloudevent("lablet_definition.content_synced.v1")
@dataclass
class LabletDefinitionContentSyncedDomainEvent(DomainEvent):
    """Event raised when content synchronization completes for a LabletDefinition.

    Carries full sync result including content metadata from the downloaded package.
    On success, transitions the definition from PENDING_SYNC to ACTIVE (ADR-028).
    Also triggers the ContentSyncCompletedEtcdProjector for etcd key cleanup.
    """

    aggregate_id: str
    lab_artifact_uri: str
    lab_yaml_hash: str
    synced_at: datetime
    sync_status: str  # "success" | "failed"
    error_message: str | None

    # Content metadata from sync (ADR-025)
    content_package_hash: str | None
    upstream_version: str | None
    upstream_date_published: str | None
    upstream_instance_name: str | None
    upstream_form_id: str | None
    grade_xml_path: str | None
    cml_yaml_path: str | None
    cml_yaml_content: str | None
    devices_json: str | None
    upstream_sync_status: dict | None  # Per-service sync results
    port_template: dict[str, Any] | None  # Serialized PortTemplate extracted from CML YAML

    def __init__(
        self,
        aggregate_id: str,
        lab_artifact_uri: str,
        lab_yaml_hash: str,
        synced_at: datetime,
        sync_status: str,
        error_message: str | None = None,
        content_package_hash: str | None = None,
        upstream_version: str | None = None,
        upstream_date_published: str | None = None,
        upstream_instance_name: str | None = None,
        upstream_form_id: str | None = None,
        grade_xml_path: str | None = None,
        cml_yaml_path: str | None = None,
        cml_yaml_content: str | None = None,
        devices_json: str | None = None,
        upstream_sync_status: dict | None = None,
        port_template: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.lab_artifact_uri = lab_artifact_uri
        self.lab_yaml_hash = lab_yaml_hash
        self.synced_at = synced_at
        self.sync_status = sync_status
        self.error_message = error_message
        self.content_package_hash = content_package_hash
        self.upstream_version = upstream_version
        self.upstream_date_published = upstream_date_published
        self.upstream_instance_name = upstream_instance_name
        self.upstream_form_id = upstream_form_id
        self.grade_xml_path = grade_xml_path
        self.cml_yaml_path = cml_yaml_path
        self.cml_yaml_content = cml_yaml_content
        self.devices_json = devices_json
        self.upstream_sync_status = upstream_sync_status
        self.port_template = port_template
