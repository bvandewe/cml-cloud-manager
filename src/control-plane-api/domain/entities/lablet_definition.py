"""LabletDefinition aggregate definition using the AggregateState pattern.

A LabletDefinition represents a versioned template for creating lab instances.
It defines the topology artifact, resource requirements, and configuration
for lab instantiation on CML workers.

LabletDefinitions are immutable per version - creating a new version creates
a new aggregate instance while maintaining version history linkage.
"""

from datetime import datetime, timezone
from typing import Any, cast
from uuid import uuid4

from domain.enums import LabletDefinitionStatus, LicenseType
from domain.events.lablet_definition_events import (
    LabletDefinitionActivatedDomainEvent,
    LabletDefinitionArtifactSyncedDomainEvent,
    LabletDefinitionContentSyncedDomainEvent,
    LabletDefinitionCreatedDomainEvent,
    LabletDefinitionDeactivatedDomainEvent,
    LabletDefinitionDeletedDomainEvent,
    LabletDefinitionDeprecatedDomainEvent,
    LabletDefinitionPodDefinitionConfirmedDomainEvent,
    LabletDefinitionSyncRequestedDomainEvent,
    LabletDefinitionUpdatedDomainEvent,
    LabletDefinitionVersionCreatedDomainEvent,
    LabletDefinitionWarmPoolUpdatedDomainEvent,
)
from domain.utils import slugify_fqn
from domain.value_objects.port_template import PortTemplate
from domain.value_objects.resource_requirements import ResourceRequirements
from lcm_core.domain.entities.timed_resource import TimedResourceState
from lcm_core.domain.enums.pod_type import PodType
from lcm_core.domain.value_objects.pod_definition_ref import PodDefinitionRef
from lcm_core.domain.value_objects.state_transition import StateTransition
from multipledispatch import dispatch
from neuroglia.data.abstractions import AggregateRoot


class NotificationConfig:
    """Configuration for owner notifications."""

    def __init__(
        self,
        email: str | None = None,
        webhook_url: str | None = None,
        notify_on_start: bool = True,
        notify_on_complete: bool = True,
        notify_on_error: bool = True,
    ) -> None:
        self.email = email
        self.webhook_url = webhook_url
        self.notify_on_start = notify_on_start
        self.notify_on_complete = notify_on_complete
        self.notify_on_error = notify_on_error

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "email": self.email,
            "webhook_url": self.webhook_url,
            "notify_on_start": self.notify_on_start,
            "notify_on_complete": self.notify_on_complete,
            "notify_on_error": self.notify_on_error,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "NotificationConfig":
        """Create from dictionary."""
        return NotificationConfig(
            email=data.get("email"),
            webhook_url=data.get("webhook_url"),
            notify_on_start=data.get("notify_on_start", True),
            notify_on_complete=data.get("notify_on_complete", True),
            notify_on_error=data.get("notify_on_error", True),
        )


class LabletDefinitionState(TimedResourceState):
    """Encapsulates the persisted state for the LabletDefinition aggregate.

    Inheritance hierarchy (ADR-036 §2.1.4, Batch I):
        AggregateState[str]  (Neuroglia)
            └── ResourceState  (Layer 1 — status, desired_status, state_history)
                    └── TimedResourceState  (Layer 2 — timeslot, lifecycle)
                            └── LabletDefinitionState  ← YOU ARE HERE

    Inherits from TimedResourceState (Layer 2):
        - id, resource_type, owner_id
        - status (str), desired_status (str | None)
        - state_history (list), pipeline_progress (dict | None)
        - created_at, updated_at
        - timeslot (dict | None), lifecycle (dict | None)
        - started_at, ended_at, duration_seconds, terminated_at

    Shadows parent fields with typed versions:
        - status: LabletDefinitionStatus (parent: str)

    A LabletDefinition is immutable once created - modifications require
    creating a new version which gets a new aggregate ID.
    """

    id: str
    name: str
    version: str  # Semantic version (e.g., "1.0.0", "2.1.3")

    # Artifact reference
    lab_artifact_uri: str  # S3/MinIO path to lab topology YAML
    lab_yaml_hash: str  # SHA-256 hash for change detection
    lab_yaml_cached: str | None  # Cached YAML content (optional)

    # Resource requirements
    resource_requirements: ResourceRequirements
    license_affinity: list[LicenseType]  # Preferred/required license types
    node_count: int  # Number of nodes in the lab topology

    # Port configuration
    port_template: PortTemplate  # Template with port placeholders

    # Assessment integration
    grading_rules_uri: str | None  # S3/MinIO path to grading rules
    max_duration_minutes: int  # Maximum duration for lab session

    # LDS integration
    form_qualified_name: str | None  # FQN: "{trackType} {trackLevel} {trackAcronym} {examVersion} {moduleAcronym} {formName}"

    # Content identification (derived from form_qualified_name)
    bucket_name: str  # Slugified FQN, used as S3 bucket name

    # Package configuration (user-configurable, with defaults)
    user_session_package_name: str  # Filename in bucket for LDS (default: "SVN.zip")
    grading_ruleset_package_name: str  # Filename for grading rules (default: "SVN.zip")

    # User session type
    user_session_type: str  # "LDS" (default), extensible for future types
    user_session_default_region: str | None  # Default LDS region (e.g., "us-east-1"), None = use global default

    # Warm pool
    warm_pool_depth: int  # Number of pre-instantiated instances to maintain

    # State history — audit trail (ADR-036 Batch I)
    # Stored as list[dict] (StateTransition.to_dict()) for Neuroglia serialization.
    state_history: list

    # Status and versioning
    status: LabletDefinitionStatus  # Shadows ResourceState.status (str)
    previous_version_id: str | None  # Reference to previous version's aggregate ID

    # Ownership and notification
    owner_notification: NotificationConfig | None
    created_by: str

    # Deprecation tracking
    deprecated_by: str | None
    deprecated_at: datetime | None
    deprecation_reason: str | None
    replacement_version: str | None

    # Lifecycle timestamps
    created_at: datetime
    updated_at: datetime

    # Artifact sync status
    last_synced_at: datetime | None
    sync_status: str | None  # "success" | "failed" | "sync_requested" | None

    # Content metadata (populated by content sync job — ADR-025)
    content_package_hash: str | None  # SHA-256 hash of the entire downloaded zip
    upstream_version: str | None  # "Version" field from mosaic_meta.json
    upstream_date_published: str | None  # "DatePublished" from mosaic_meta.json
    upstream_instance_name: str | None  # "InstanceName" from mosaic_meta.json
    upstream_form_id: str | None  # "FormId" from mosaic_meta.json
    grade_xml_path: str | None  # Relative path to grade.xml in the package
    cml_yaml_path: str | None  # Relative path to cml.yml/cml.yaml in the package
    cml_yaml_content: str | None  # Cached CML YAML content (for lab import)
    devices_json: str | None  # Cached devices.json content (serialized JSON string)
    upstream_sync_status: dict | None  # Per-service sync status

    # Pipeline definitions (ADR-034)
    pipelines: dict | None  # Optional pipeline DAGs keyed by name (e.g., "instantiate", "teardown")

    # Pod definition reference (ADR-044 §2.6) — links to ScenarioEngine's PodDefinition
    pod_definition_ref: PodDefinitionRef | None  # Set at creation from pod_type, confirmed after content sync

    def __init__(self) -> None:
        super().__init__()

        # Resource hierarchy fields (ADR-036 Batch I)
        self.resource_type = "lablet_definition"
        self.desired_status = None

        self.id = ""
        self.name = ""
        self.version = ""

        self.lab_artifact_uri = ""
        self.lab_yaml_hash = ""
        self.lab_yaml_cached = None

        self.resource_requirements = ResourceRequirements(cpu_cores=1, memory_gb=1, storage_gb=1)
        self.license_affinity = []
        self.node_count = 0

        self.port_template = PortTemplate.empty()

        self.grading_rules_uri = None
        self.max_duration_minutes = 60  # Default 1 hour

        self.form_qualified_name = None  # FQN content ref

        # Content identification
        self.bucket_name = ""

        # Package configuration
        self.user_session_package_name = "SVN.zip"
        self.grading_ruleset_package_name = "SVN.zip"

        # User session type
        self.user_session_type = "LDS"
        self.user_session_default_region: str | None = None

        self.warm_pool_depth = 0

        self.status = LabletDefinitionStatus.ACTIVE
        self.previous_version_id = None

        self.owner_notification = None
        self.created_by = ""

        self.deprecated_by = None
        self.deprecated_at = None
        self.deprecation_reason = None
        self.replacement_version = None

        now = datetime.now(timezone.utc)
        self.created_at = now
        self.updated_at = now

        self.last_synced_at = None
        self.sync_status = None

        # Content metadata (populated by sync)
        self.content_package_hash: str | None = None
        self.upstream_version: str | None = None
        self.upstream_date_published: str | None = None
        self.upstream_instance_name: str | None = None
        self.upstream_form_id: str | None = None
        self.grade_xml_path: str | None = None
        self.cml_yaml_path: str | None = None
        self.cml_yaml_content: str | None = None
        self.devices_json: str | None = None
        self.content_xml_content: str | None = None  # Raw content.xml from session package
        self.user_visible_devices: list[dict[str, str]] | None = None  # From content.xml (AD-LDS-001)
        self.upstream_sync_status: dict | None = None
        self.port_conflicts: list[dict[str, Any]] | None = None  # Multi-port device conflicts (AD-LDS-002)
        self.lds_port_preferences: dict[str, str] | None = None  # User-configurable per-device port override (AD-LDS-002 Phase 3)

        # Pipeline definitions (ADR-034)
        self.pipelines: dict | None = None  # Optional pipeline DAGs from definition YAML

        # Pod definition reference (ADR-044 §2.6)
        self.pod_definition_ref: PodDefinitionRef | None = None

        # State history — audit trail (ADR-036 Batch I)
        # Explicit init required: Neuroglia bypasses __init__ on deserialization,
        # so existing MongoDB docs without this field need the defensive check
        # in _record_transition() below. New aggregates get it here.
        self.state_history: list = []

        # Lab binding options (Phase 7)
        self.lab_reuse_enabled: bool = False  # Allow labs to be reused across timeslots
        self.multi_lab_enabled: bool = False  # Allow multiple labs per lablet instance

        # Instantiation timing (AD-P10-01)
        self.boot_lead_time_minutes: int | None = None  # Per-definition override, None = use global setting

    def _record_transition(
        self,
        from_state: str | None,
        to_state: str,
        triggered_by: str = "system",
        reason: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Record a state transition in the history.

        Overrides ResourceState._record_transition() to store transitions
        as dicts (via StateTransition.to_dict()) for Neuroglia serialization
        compatibility.

        ADR-036 Batch I: Follows LabRecordState/CMLWorkerState pattern.
        """
        transition = StateTransition(
            from_state=from_state,
            to_state=to_state,
            transitioned_at=datetime.now(timezone.utc),
            triggered_by=triggered_by,
            reason=reason,
            metadata=metadata,
        )
        # Defensive: Neuroglia bypasses __init__ on deserialization, so
        # documents created before state_history was added may lack it.
        if not hasattr(self, "state_history") or self.state_history is None:
            self.state_history = []
        self.state_history.append(transition.to_dict())
        self.updated_at = datetime.now(timezone.utc)

    @dispatch(LabletDefinitionCreatedDomainEvent)
    def on(self, event: LabletDefinitionCreatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the creation event to the state."""
        self.id = event.aggregate_id
        self.name = event.name
        self.version = event.version
        self.lab_artifact_uri = event.lab_artifact_uri
        self.lab_yaml_hash = event.lab_yaml_hash
        self.lab_yaml_cached = event.lab_yaml_cached
        self.resource_requirements = ResourceRequirements.from_dict(event.resource_requirements)
        self.license_affinity = [LicenseType(lt) for lt in event.license_affinity]
        self.node_count = event.node_count
        self.port_template = PortTemplate.from_dict(event.port_template)
        self.grading_rules_uri = event.grading_rules_uri
        self.max_duration_minutes = event.max_duration_minutes
        self.warm_pool_depth = event.warm_pool_depth
        self.owner_notification = NotificationConfig.from_dict(event.owner_notification) if event.owner_notification else None
        self.created_by = event.created_by
        self.created_at = event.created_at
        self.updated_at = event.created_at
        self.form_qualified_name = event.form_qualified_name
        self.status = LabletDefinitionStatus.PENDING_SYNC  # ADR-028

        # Content sync fields (ADR-025)
        self.bucket_name = event.bucket_name
        self.user_session_package_name = event.user_session_package_name
        self.grading_ruleset_package_name = event.grading_ruleset_package_name
        self.user_session_type = event.user_session_type
        self.user_session_default_region = event.user_session_default_region

        # Instantiation timing (AD-P10-01)
        self.boot_lead_time_minutes = event.boot_lead_time_minutes

        # Pipeline definitions (ADR-034)
        self.pipelines = getattr(event, "pipelines", None)

        # Pod definition reference (ADR-044 §2.6)
        pod_ref_data = getattr(event, "pod_definition_ref", None)
        self.pod_definition_ref = PodDefinitionRef.from_dict(pod_ref_data) if pod_ref_data else None

        # Lab binding options (Phase 7)
        self.lab_reuse_enabled = getattr(event, "lab_reuse_enabled", False)

        # Resource hierarchy fields (ADR-036 Batch I)
        self.owner_id = event.created_by
        self._record_transition(
            from_state=None,
            to_state=self.status.value,
            triggered_by=event.created_by,
            reason="Definition created",
        )

    @dispatch(LabletDefinitionVersionCreatedDomainEvent)
    def on(self, event: LabletDefinitionVersionCreatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the version creation event to the state.

        Note: This creates a NEW aggregate with a new ID, linking to the previous version.
        """
        self.id = event.aggregate_id
        self.name = event.name
        self.version = event.version
        self.lab_artifact_uri = event.lab_artifact_uri
        self.lab_yaml_hash = event.lab_yaml_hash
        self.resource_requirements = ResourceRequirements.from_dict(event.resource_requirements)
        self.node_count = event.node_count
        self.port_template = PortTemplate.from_dict(event.port_template)
        self.created_by = event.created_by
        self.created_at = event.created_at
        self.updated_at = event.created_at
        self.status = LabletDefinitionStatus.PENDING_SYNC  # ADR-028: must sync before ACTIVE
        # Note: previous_version_id would be set via separate tracking

        # Resource hierarchy fields (ADR-036 Batch I)
        self.owner_id = event.created_by
        self._record_transition(
            from_state=None,
            to_state=self.status.value,
            triggered_by=event.created_by,
            reason="New version created",
        )

    @dispatch(LabletDefinitionDeprecatedDomainEvent)
    def on(self, event: LabletDefinitionDeprecatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the deprecation event to the state."""
        old_status = self.status
        self.status = LabletDefinitionStatus.DEPRECATED
        self.deprecated_by = event.deprecated_by
        self.deprecated_at = event.deprecated_at
        self.deprecation_reason = event.deprecation_reason
        self.replacement_version = event.replacement_version
        self.updated_at = event.deprecated_at
        self._record_transition(
            from_state=old_status.value,
            to_state=self.status.value,
            triggered_by=event.deprecated_by,
            reason=event.deprecation_reason or "Definition deprecated",
        )

    @dispatch(LabletDefinitionArtifactSyncedDomainEvent)
    def on(self, event: LabletDefinitionArtifactSyncedDomainEvent) -> None:  # type: ignore[override]
        """Apply the artifact sync event to the state (legacy)."""
        self.last_synced_at = event.synced_at
        self.sync_status = event.sync_status
        self.lab_yaml_hash = event.lab_yaml_hash
        self.updated_at = event.synced_at

    @dispatch(LabletDefinitionSyncRequestedDomainEvent)
    def on(self, event: LabletDefinitionSyncRequestedDomainEvent) -> None:  # type: ignore[override]
        """Apply the sync requested event to the state."""
        old_status = self.status
        self.sync_status = "sync_requested"
        self.status = LabletDefinitionStatus.PENDING_SYNC
        self.updated_at = datetime.fromisoformat(event.requested_at)
        if self.status != old_status:
            self._record_transition(
                from_state=old_status.value,
                to_state=self.status.value,
                triggered_by="system",
                reason="Sync requested",
            )

    @dispatch(LabletDefinitionContentSyncedDomainEvent)
    def on(self, event: LabletDefinitionContentSyncedDomainEvent) -> None:  # type: ignore[override]
        """Apply the content sync event to the state (ADR-025)."""
        old_status = self.status
        self.last_synced_at = event.synced_at
        self.sync_status = event.sync_status
        self.lab_yaml_hash = event.lab_yaml_hash
        self.updated_at = event.synced_at

        # Content metadata
        if event.content_package_hash is not None:
            self.content_package_hash = event.content_package_hash
        if event.upstream_version is not None:
            self.upstream_version = event.upstream_version
        if event.upstream_date_published is not None:
            self.upstream_date_published = event.upstream_date_published
        if event.upstream_instance_name is not None:
            self.upstream_instance_name = event.upstream_instance_name
        if event.upstream_form_id is not None:
            self.upstream_form_id = event.upstream_form_id
        if event.grade_xml_path is not None:
            self.grade_xml_path = event.grade_xml_path
        if event.cml_yaml_path is not None:
            self.cml_yaml_path = event.cml_yaml_path
        if event.cml_yaml_content is not None:
            self.cml_yaml_content = event.cml_yaml_content
        if event.devices_json is not None:
            self.devices_json = event.devices_json
        if event.content_xml_content is not None:
            self.content_xml_content = event.content_xml_content
        if event.user_visible_devices is not None:
            self.user_visible_devices = event.user_visible_devices
        if event.upstream_sync_status is not None:
            self.upstream_sync_status = event.upstream_sync_status
        if event.port_template is not None:
            self.port_template = PortTemplate.from_dict(event.port_template)

        # Topology metadata from CML YAML (AD-SEED-001)
        if event.node_count is not None:
            self.node_count = event.node_count
        if event.node_definitions_required is not None:
            self.resource_requirements = self.resource_requirements.with_node_definitions(tuple(event.node_definitions_required))

        # Multi-port device conflicts (AD-LDS-002 Phase 2)
        if event.port_conflicts is not None:
            self.port_conflicts = event.port_conflicts

        # Transition from PENDING_SYNC to ACTIVE on successful sync (ADR-028)
        if event.sync_status == "success" and self.status == LabletDefinitionStatus.PENDING_SYNC:
            self.status = LabletDefinitionStatus.ACTIVE
            self._record_transition(
                from_state=old_status.value,
                to_state=self.status.value,
                triggered_by="system",
                reason="Content sync completed successfully",
            )

        # Update pod_definition_ref content_hash on successful sync (ADR-044 §2.6)
        if event.sync_status == "success" and self.pod_definition_ref is not None and event.content_package_hash:
            self.pod_definition_ref = self.pod_definition_ref.with_sync_confirmation(event.content_package_hash)

    @dispatch(LabletDefinitionPodDefinitionConfirmedDomainEvent)
    def on(self, event: LabletDefinitionPodDefinitionConfirmedDomainEvent) -> None:  # type: ignore[override]
        """Apply the PodDefinition confirmation event (AD-CSI-001 / G-07).

        Establishes or refreshes ``pod_definition_ref`` after SE confirms which
        PodDefinition owns the synced content. Conflict detection (mismatched
        ``pod_type``) is enforced in the aggregate method, not the handler.
        """
        new_ref = PodDefinitionRef(
            definition_id=event.pod_definition_id,
            version=self.version,
            pod_type=PodType(event.pod_type),
            content_hash=event.content_hash,
        )
        self.pod_definition_ref = new_ref
        self.updated_at = event.confirmed_at

    @dispatch(LabletDefinitionWarmPoolUpdatedDomainEvent)
    def on(self, event: LabletDefinitionWarmPoolUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the warm pool update event to the state."""
        self.warm_pool_depth = event.new_warm_pool_depth
        self.updated_at = event.updated_at

    @dispatch(LabletDefinitionUpdatedDomainEvent)
    def on(self, event: LabletDefinitionUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the update event to the state.

        Supports updating mutable fields: resource_requirements, license_affinity,
        node_count, max_duration_minutes, warm_pool_depth, grading_rules_uri,
        lab_artifact_uri, lab_yaml_hash.
        """
        changes = event.changes
        if "resource_requirements" in changes:
            self.resource_requirements = ResourceRequirements.from_dict(changes["resource_requirements"])
        if "license_affinity" in changes:
            self.license_affinity = [LicenseType(lt) for lt in changes["license_affinity"]]
        if "node_count" in changes:
            self.node_count = changes["node_count"]
        if "max_duration_minutes" in changes:
            self.max_duration_minutes = changes["max_duration_minutes"]
        if "warm_pool_depth" in changes:
            self.warm_pool_depth = changes["warm_pool_depth"]
        if "grading_rules_uri" in changes:
            self.grading_rules_uri = changes["grading_rules_uri"]
        if "lab_artifact_uri" in changes:
            self.lab_artifact_uri = changes["lab_artifact_uri"]
        if "lab_yaml_hash" in changes:
            self.lab_yaml_hash = changes["lab_yaml_hash"]
        # Content identification and sync settings
        if "form_qualified_name" in changes:
            self.form_qualified_name = changes["form_qualified_name"]
        if "bucket_name" in changes:
            self.bucket_name = changes["bucket_name"]
        if "user_session_package_name" in changes:
            self.user_session_package_name = changes["user_session_package_name"]
        if "grading_ruleset_package_name" in changes:
            self.grading_ruleset_package_name = changes["grading_ruleset_package_name"]
        if "user_session_type" in changes:
            self.user_session_type = changes["user_session_type"]
        if "user_session_default_region" in changes:
            self.user_session_default_region = changes["user_session_default_region"]
        if "boot_lead_time_minutes" in changes:
            self.boot_lead_time_minutes = changes["boot_lead_time_minutes"]
        if "lab_reuse_enabled" in changes:
            self.lab_reuse_enabled = changes["lab_reuse_enabled"]
        if "lds_port_preferences" in changes:
            self.lds_port_preferences = changes["lds_port_preferences"]
        if "pod_definition_ref" in changes:
            ref_data = changes["pod_definition_ref"]
            self.pod_definition_ref = PodDefinitionRef.from_dict(ref_data) if ref_data else None
        self.updated_at = event.updated_at

    @dispatch(LabletDefinitionActivatedDomainEvent)
    def on(self, event: LabletDefinitionActivatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the activated event to the state."""
        previous_status = self.status.value if self.status else None
        self.status = LabletDefinitionStatus.ACTIVE
        self.updated_at = event.activated_at
        self._record_transition(
            from_state=previous_status,
            to_state=LabletDefinitionStatus.ACTIVE.value,
            triggered_by=event.activated_by,
            reason="Definition activated",
        )

    @dispatch(LabletDefinitionDeactivatedDomainEvent)
    def on(self, event: LabletDefinitionDeactivatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the deactivated event to the state."""
        previous_status = self.status.value if self.status else None
        self.status = LabletDefinitionStatus.INACTIVE
        self.updated_at = event.deactivated_at
        self._record_transition(
            from_state=previous_status,
            to_state=LabletDefinitionStatus.INACTIVE.value,
            triggered_by=event.deactivated_by,
            reason=event.reason,
        )

    @dispatch(LabletDefinitionDeletedDomainEvent)
    def on(self, event: LabletDefinitionDeletedDomainEvent) -> None:  # type: ignore[override]
        """Apply the deleted event to the state (soft-delete)."""
        previous_status = self.status.value if self.status else None
        self.status = LabletDefinitionStatus.DELETED
        self.updated_at = event.deleted_at
        self._record_transition(
            from_state=previous_status,
            to_state=LabletDefinitionStatus.DELETED.value,
            triggered_by=event.deleted_by,
            reason="Definition soft-deleted",
        )


class LabletDefinition(AggregateRoot[LabletDefinitionState, str]):
    """LabletDefinition aggregate - immutable per version.

    Represents a versioned template for lab instantiation. Each version
    is a separate aggregate instance to maintain immutability.
    """

    def __init__(self) -> None:
        super().__init__()

    def id(self) -> str:
        """Return the aggregate identifier with a precise type."""
        aggregate_id = super().id()
        if aggregate_id is None:
            raise ValueError("LabletDefinition aggregate identifier has not been initialized")
        return cast(str, aggregate_id)

    @staticmethod
    def create(
        name: str,
        version: str,
        form_qualified_name: str,
        resource_requirements: ResourceRequirements,
        license_affinity: list[LicenseType],
        node_count: int,
        port_template: PortTemplate,
        created_by: str,
        # Optional content config
        user_session_package_name: str = "SVN.zip",
        grading_ruleset_package_name: str = "SVN.zip",
        user_session_type: str = "LDS",
        user_session_default_region: str | None = None,
        # Optional lab config (may be populated later by sync)
        lab_yaml_hash: str = "",
        lab_yaml_cached: str | None = None,
        grading_rules_uri: str | None = None,
        max_duration_minutes: int = 60,
        warm_pool_depth: int = 0,
        owner_notification: NotificationConfig | None = None,
        boot_lead_time_minutes: int | None = None,
        pipelines: dict | None = None,
        lab_reuse_enabled: bool = False,
        pod_type: PodType | None = None,
    ) -> "LabletDefinition":
        """Create a new LabletDefinition in PENDING_SYNC status (ADR-028).

        The bucket_name is auto-derived by slugifying the form_qualified_name.
        The lab_artifact_uri is auto-derived from bucket_name + package name.

        Args:
            name: Unique name for the definition (e.g., "ccna-basic-routing")
            version: Semantic version string (e.g., "1.0.0")
            form_qualified_name: FQN string (6 space-separated components)
            resource_requirements: Compute resource requirements
            license_affinity: List of acceptable license types
            node_count: Number of nodes in the topology
            port_template: Template defining required ports
            created_by: User ID or system identifier
            user_session_package_name: Filename in bucket for LDS (default: "SVN.zip")
            grading_ruleset_package_name: Filename for grading rules (default: "SVN.zip")
            user_session_type: Session type (default: "LDS")
            user_session_default_region: Default LDS region (None = use global default)
            lab_yaml_hash: SHA-256 hash (empty until sync populates it)
            lab_yaml_cached: Optional cached YAML content
            grading_rules_uri: Optional path to grading rules
            max_duration_minutes: Maximum session duration (default 60)
            warm_pool_depth: Number of pre-instantiated instances (default 0)
            owner_notification: Optional notification configuration
            boot_lead_time_minutes: Minutes before session to start boot (None = global default)

        Returns:
            A new LabletDefinition aggregate in PENDING_SYNC status
        """
        bucket_name = slugify_fqn(form_qualified_name)
        lab_artifact_uri = f"s3://{bucket_name}/{user_session_package_name}"

        # Build pod_definition_ref if pod_type is provided (ADR-044 §2.6)
        # definition_id is derived from slugified FQN, content_hash populated after SE sync
        pod_ref_dict: dict | None = None
        if pod_type is not None:
            pod_ref = PodDefinitionRef(
                definition_id=bucket_name,
                version=version,
                pod_type=pod_type,
            )
            pod_ref_dict = pod_ref.to_dict()

        definition = LabletDefinition()
        definition.state.on(
            definition.register_event(  # type: ignore
                LabletDefinitionCreatedDomainEvent(
                    aggregate_id=str(uuid4()),
                    name=name,
                    version=version,
                    lab_artifact_uri=lab_artifact_uri,
                    lab_yaml_hash=lab_yaml_hash,
                    lab_yaml_cached=lab_yaml_cached,
                    resource_requirements=resource_requirements.to_dict(),
                    license_affinity=[lt.value for lt in license_affinity],
                    node_count=node_count,
                    port_template=port_template.to_dict(),
                    grading_rules_uri=grading_rules_uri,
                    max_duration_minutes=max_duration_minutes,
                    warm_pool_depth=warm_pool_depth,
                    owner_notification=owner_notification.to_dict() if owner_notification else None,
                    created_by=created_by,
                    created_at=datetime.now(timezone.utc),
                    form_qualified_name=form_qualified_name,
                    bucket_name=bucket_name,
                    user_session_package_name=user_session_package_name,
                    grading_ruleset_package_name=grading_ruleset_package_name,
                    user_session_type=user_session_type,
                    user_session_default_region=user_session_default_region,
                    boot_lead_time_minutes=boot_lead_time_minutes,
                    pipelines=pipelines,
                    lab_reuse_enabled=lab_reuse_enabled,
                    pod_definition_ref=pod_ref_dict,
                )
            )
        )
        return definition

    @staticmethod
    def create_version(
        name: str,
        version: str,
        previous_version: str,
        lab_artifact_uri: str,
        lab_yaml_hash: str,
        resource_requirements: ResourceRequirements,
        node_count: int,
        port_template: PortTemplate,
        created_by: str,
    ) -> "LabletDefinition":
        """Create a new version of an existing LabletDefinition.

        Args:
            name: Name of the definition (must match existing)
            version: New version string (must be greater than previous)
            previous_version: Previous version string for linking
            lab_artifact_uri: S3/MinIO path to updated topology YAML
            lab_yaml_hash: SHA-256 hash of the new YAML content
            resource_requirements: Updated resource requirements
            node_count: Number of nodes in the updated topology
            port_template: Updated port template
            created_by: User ID or system identifier

        Returns:
            A new LabletDefinition aggregate with version creation event
        """
        definition = LabletDefinition()
        definition.state.on(
            definition.register_event(  # type: ignore
                LabletDefinitionVersionCreatedDomainEvent(
                    aggregate_id=str(uuid4()),
                    name=name,
                    version=version,
                    previous_version=previous_version,
                    lab_artifact_uri=lab_artifact_uri,
                    lab_yaml_hash=lab_yaml_hash,
                    resource_requirements=resource_requirements.to_dict(),
                    node_count=node_count,
                    port_template=port_template.to_dict(),
                    created_by=created_by,
                    created_at=datetime.now(timezone.utc),
                )
            )
        )
        return definition

    def deprecate(
        self,
        deprecated_by: str,
        deprecation_reason: str | None = None,
        replacement_version: str | None = None,
    ) -> None:
        """Mark this definition as deprecated.

        Deprecated definitions cannot be used for new instances,
        but existing instances continue to work.

        Args:
            deprecated_by: User ID or system identifier
            deprecation_reason: Optional reason for deprecation
            replacement_version: Optional suggested replacement version
        """
        if self.state.status == LabletDefinitionStatus.DEPRECATED:
            return  # Already deprecated, no-op

        self.state.on(
            self.register_event(  # type: ignore
                LabletDefinitionDeprecatedDomainEvent(
                    aggregate_id=self.id(),
                    name=self.state.name,
                    version=self.state.version,
                    deprecated_by=deprecated_by,
                    deprecated_at=datetime.now(timezone.utc),
                    deprecation_reason=deprecation_reason,
                    replacement_version=replacement_version,
                )
            )
        )

    def record_artifact_sync(
        self,
        lab_yaml_hash: str,
        sync_status: str,
        error_message: str | None = None,
    ) -> None:
        """Record the result of an artifact sync operation (legacy).

        .. deprecated:: Use record_content_sync() for content sync pipeline.

        Args:
            lab_yaml_hash: Current hash of the artifact
            sync_status: "success" or "failed"
            error_message: Error details if sync failed
        """
        self.state.on(
            self.register_event(  # type: ignore
                LabletDefinitionArtifactSyncedDomainEvent(
                    aggregate_id=self.id(),
                    lab_artifact_uri=self.state.lab_artifact_uri,
                    lab_yaml_hash=lab_yaml_hash,
                    synced_at=datetime.now(timezone.utc),
                    sync_status=sync_status,
                    error_message=error_message,
                )
            )
        )

    def request_sync(self, requested_by: str = "") -> None:
        """Request content synchronization.

        Emits LabletDefinitionSyncRequestedDomainEvent, which triggers the
        ContentSyncRequestedEtcdProjector to write an etcd key (AD-CS-001).
        The lablet-controller's ContentSyncService watches for this key.

        Args:
            requested_by: User ID or system identifier requesting the sync.
        """
        self.state.on(
            self.register_event(  # type: ignore
                LabletDefinitionSyncRequestedDomainEvent(
                    aggregate_id=self.id(),
                    form_qualified_name=self.state.form_qualified_name or "",
                    bucket_name=self.state.bucket_name,
                    user_session_package_name=self.state.user_session_package_name or "SVN.zip",
                    requested_by=requested_by,
                    requested_at=datetime.now(timezone.utc).isoformat(),
                )
            )
        )

    def record_content_sync(
        self,
        lab_yaml_hash: str,
        sync_status: str,
        content_package_hash: str | None = None,
        upstream_version: str | None = None,
        upstream_date_published: str | None = None,
        upstream_instance_name: str | None = None,
        upstream_form_id: str | None = None,
        grade_xml_path: str | None = None,
        cml_yaml_path: str | None = None,
        cml_yaml_content: str | None = None,
        devices_json: str | None = None,
        content_xml_content: str | None = None,
        user_visible_devices: list[dict[str, str]] | None = None,
        upstream_sync_status: dict | None = None,
        error_message: str | None = None,
        port_template: PortTemplate | None = None,
        node_count: int | None = None,
        node_definitions_required: list[str] | None = None,
        port_conflicts: list[dict[str, Any]] | None = None,
    ) -> None:
        """Record the result of a content synchronization operation.

        On success, transitions the definition from PENDING_SYNC to ACTIVE.

        Args:
            lab_yaml_hash: SHA-256 hash of the lab topology YAML.
            sync_status: "success" or "failed".
            content_package_hash: SHA-256 hash of the entire downloaded zip.
            upstream_version: Version from mosaic_meta.json.
            upstream_date_published: DatePublished from mosaic_meta.json.
            upstream_instance_name: InstanceName from mosaic_meta.json.
            upstream_form_id: FormId from mosaic_meta.json.
            grade_xml_path: Relative path to grade.xml in the package.
            cml_yaml_path: Relative path to cml.yml/cml.yaml in the package.
            cml_yaml_content: Cached CML YAML content for lab import.
            devices_json: Cached devices.json content (serialized JSON string).
            content_xml_content: Raw content.xml from session package.
            upstream_sync_status: Per-service sync status dict.
            error_message: Error details if sync failed.
            port_template: PortTemplate extracted from CML YAML node tags.
            node_count: Number of nodes in the CML topology (AD-SEED-001).
            node_definitions_required: Unique node definitions from CML YAML.
            port_conflicts: Multi-port device conflicts detected at sync time (AD-LDS-002).
        """
        self.state.on(
            self.register_event(  # type: ignore
                LabletDefinitionContentSyncedDomainEvent(
                    aggregate_id=self.id(),
                    lab_artifact_uri=self.state.lab_artifact_uri,
                    lab_yaml_hash=lab_yaml_hash,
                    synced_at=datetime.now(timezone.utc),
                    sync_status=sync_status,
                    error_message=error_message,
                    content_package_hash=content_package_hash,
                    upstream_version=upstream_version,
                    upstream_date_published=upstream_date_published,
                    upstream_instance_name=upstream_instance_name,
                    upstream_form_id=upstream_form_id,
                    grade_xml_path=grade_xml_path,
                    cml_yaml_path=cml_yaml_path,
                    cml_yaml_content=cml_yaml_content,
                    devices_json=devices_json,
                    content_xml_content=content_xml_content,
                    user_visible_devices=user_visible_devices,
                    upstream_sync_status=upstream_sync_status,
                    port_template=port_template.to_dict() if port_template else None,
                    node_count=node_count,
                    node_definitions_required=node_definitions_required,
                    port_conflicts=port_conflicts,
                )
            )
        )

    def confirm_pod_definition(
        self,
        pod_definition_id: str,
        pod_type: str | PodType,
        content_hash: str | None = None,
    ) -> None:
        """Confirm the PodDefinition that owns the synced content (AD-CSI-001 / G-07).

        Called by ``RecordContentSyncResultCommand`` once the SE has accepted
        and validated the content package. Idempotent: invoking with the same
        ``(pod_definition_id, pod_type)`` simply refreshes ``content_hash``.

        Args:
            pod_definition_id: Identifier of the SE PodDefinition.
            pod_type: Infrastructure type required to run this content. Accepts
                either a ``PodType`` enum value or its string value.
            content_hash: Optional SHA256 of the synced package; carries the
                AD-CSI-004 sync confirmation when supplied.

        Raises:
            ValueError: If ``pod_definition_id`` is empty, ``pod_type`` is not
                a valid ``PodType``, or a confirmed ref already exists for a
                different ``pod_type``.
        """
        if not pod_definition_id:
            raise ValueError("pod_definition_id must not be empty")

        # Normalise pod_type input (accept enum or string).
        try:
            resolved_pod_type = pod_type if isinstance(pod_type, PodType) else PodType(pod_type)
        except ValueError as exc:
            raise ValueError(f"Unknown pod_type: {pod_type}") from exc

        existing_ref = self.state.pod_definition_ref
        if existing_ref is not None and existing_ref.pod_type != resolved_pod_type:
            raise ValueError(f"PodDefinition pod_type conflict: existing ref has " f"{existing_ref.pod_type.value}, but SE confirmed {resolved_pod_type.value}")

        self.state.on(
            self.register_event(  # type: ignore
                LabletDefinitionPodDefinitionConfirmedDomainEvent(
                    aggregate_id=self.id(),
                    pod_definition_id=pod_definition_id,
                    pod_type=resolved_pod_type.value,
                    content_hash=content_hash,
                    confirmed_at=datetime.now(timezone.utc),
                )
            )
        )

    def update_warm_pool_depth(self, new_depth: int, updated_by: str) -> None:
        """Update the warm pool depth for this definition.

        This is one of the few mutable properties on a LabletDefinition.

        Args:
            new_depth: New warm pool depth (0 for no warm pool)
            updated_by: User ID or system identifier
        """
        if new_depth < 0:
            raise ValueError("Warm pool depth cannot be negative")

        if new_depth == self.state.warm_pool_depth:
            return  # No change, no-op

        self.state.on(
            self.register_event(  # type: ignore
                LabletDefinitionWarmPoolUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    old_warm_pool_depth=self.state.warm_pool_depth,
                    new_warm_pool_depth=new_depth,
                    updated_by=updated_by,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        )

    def update(self, changes: dict[str, Any], updated_by: str) -> None:
        """Update mutable fields on this definition.

        Supports updating resource requirements, license affinity, node count,
        max duration, warm pool depth, grading rules URI, artifact URI, and hash.

        Args:
            changes: Dictionary of field name → new value
            updated_by: User ID or system identifier

        Raises:
            ValueError: If definition is deprecated
        """
        if self.state.status == LabletDefinitionStatus.DEPRECATED:
            raise ValueError("Cannot update a deprecated definition")

        if not changes:
            return  # No changes, no-op

        self.state.on(
            self.register_event(  # type: ignore
                LabletDefinitionUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    changes=changes,
                    updated_by=updated_by,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        )

    def activate(self, activated_by: str) -> None:
        """Activate this definition, making it available for scheduling.

        Can transition from INACTIVE or ARCHIVED status to ACTIVE.

        Args:
            activated_by: User ID or system identifier

        Raises:
            ValueError: If definition is already active, deprecated, or deleted
        """
        if self.state.status == LabletDefinitionStatus.ACTIVE:
            return  # Already active, no-op

        if self.state.status in (LabletDefinitionStatus.DEPRECATED, LabletDefinitionStatus.DELETED):
            raise ValueError(f"Cannot activate a {self.state.status.value} definition")

        if self.state.status == LabletDefinitionStatus.PENDING_SYNC:
            raise ValueError("Cannot activate a definition that is pending sync")

        self.state.on(
            self.register_event(  # type: ignore
                LabletDefinitionActivatedDomainEvent(
                    aggregate_id=self.id(),
                    activated_by=activated_by,
                    activated_at=datetime.now(timezone.utc),
                )
            )
        )

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> None:
        """Deactivate this definition, temporarily removing it from scheduling.

        Active definitions can be deactivated without losing their configuration.
        They can be reactivated later via activate().

        Args:
            deactivated_by: User ID or system identifier
            reason: Optional reason for deactivation

        Raises:
            ValueError: If definition is not active
        """
        if self.state.status == LabletDefinitionStatus.INACTIVE:
            return  # Already inactive, no-op

        if self.state.status != LabletDefinitionStatus.ACTIVE:
            raise ValueError(f"Cannot deactivate a {self.state.status.value} definition")

        self.state.on(
            self.register_event(  # type: ignore
                LabletDefinitionDeactivatedDomainEvent(
                    aggregate_id=self.id(),
                    deactivated_by=deactivated_by,
                    deactivated_at=datetime.now(timezone.utc),
                    reason=reason,
                )
            )
        )

    def soft_delete(self, deleted_by: str) -> None:
        """Soft-delete this definition.

        Marks the definition as deleted. It will be excluded from all listings
        but remains in the database for audit purposes.

        Args:
            deleted_by: User ID or system identifier

        Raises:
            ValueError: If definition is already deleted
        """
        if self.state.status == LabletDefinitionStatus.DELETED:
            return  # Already deleted, no-op

        self.state.on(
            self.register_event(  # type: ignore
                LabletDefinitionDeletedDomainEvent(
                    aggregate_id=self.id(),
                    deleted_by=deleted_by,
                    deleted_at=datetime.now(timezone.utc),
                )
            )
        )

    # --- Computed Properties ---

    @property
    def is_active(self) -> bool:
        """Check if this definition is active and can be used for new instances."""
        return self.state.status == LabletDefinitionStatus.ACTIVE

    @property
    def is_pending_sync(self) -> bool:
        """Check if this definition is pending content synchronization."""
        return self.state.status == LabletDefinitionStatus.PENDING_SYNC

    @property
    def is_deprecated(self) -> bool:
        """Check if this definition is deprecated."""
        return self.state.status == LabletDefinitionStatus.DEPRECATED

    @property
    def port_count(self) -> int:
        """Return the number of ports required by this definition."""
        return self.state.port_template.port_count

    @property
    def unique_key(self) -> str:
        """Return a unique key combining name and version."""
        return f"{self.state.name}:{self.state.version}"
