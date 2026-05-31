"""Tests for LabletDefinition Aggregate — Phase 1 Content Sync Domain Model.

Covers:
- Updated create() with form_qualified_name + auto-derived bucket/URI (ADR-028)
- PENDING_SYNC initial status (ADR-028)
- request_sync() aggregate method → SyncRequested event
- record_content_sync() → ContentSynced event with metadata
- PENDING_SYNC → ACTIVE transition on successful content sync
- slugify_fqn integration (via create() auto-derivation)
- Backward-compatible record_artifact_sync() (legacy)
- All existing functionality preserved
"""

from datetime import datetime, timezone

import pytest
from domain.entities.lablet_definition import LabletDefinition, LabletDefinitionState, NotificationConfig
from domain.enums import LabletDefinitionStatus, LicenseType
from domain.events.lablet_definition_events import (
    LabletDefinitionActivatedDomainEvent,
    LabletDefinitionContentSyncedDomainEvent,
    LabletDefinitionCreatedDomainEvent,
    LabletDefinitionDeactivatedDomainEvent,
    LabletDefinitionDeletedDomainEvent,
    LabletDefinitionDeprecatedDomainEvent,
    LabletDefinitionSyncRequestedDomainEvent,
    LabletDefinitionVersionCreatedDomainEvent,
    LabletDefinitionWarmPoolUpdatedDomainEvent,
)
from domain.utils import slugify_fqn
from domain.value_objects.port_template import PortDefinition, PortTemplate
from domain.value_objects.resource_requirements import AmiRequirement, ResourceRequirements

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FQN = "Exam Associate CCNA v1.1 LAB 1.3a"
FQN_SLUG = "exam-associate-ccna-v1.1-lab-1.3a"


class TestResourceRequirements:
    """Test ResourceRequirements value object."""

    def test_valid_creation(self):
        """Test creating valid resource requirements."""
        req = ResourceRequirements(cpu_cores=4, memory_gb=8, storage_gb=50)

        assert req.cpu_cores == 4
        assert req.memory_gb == 8
        assert req.storage_gb == 50
        assert req.nested_virt is True
        assert req.ami_requirements == ()

    def test_with_ami_requirements(self):
        """Test creating resource requirements with AMI constraints."""
        ami_req = AmiRequirement(
            cml_version_min="2.7.0",
            cml_version_max="2.9.0",
            node_definitions_required=("iosv", "csr1000v"),
        )
        req = ResourceRequirements(cpu_cores=8, memory_gb=16, storage_gb=100, nested_virt=True, ami_requirements=(ami_req,))

        assert len(req.ami_requirements) == 1
        assert req.ami_requirements[0].cml_version_min == "2.7.0"

    def test_invalid_cpu_cores(self):
        """Test validation rejects invalid cpu_cores."""
        with pytest.raises(ValueError, match="cpu_cores must be at least 1"):
            ResourceRequirements(cpu_cores=0, memory_gb=8, storage_gb=50)

    def test_invalid_memory_gb(self):
        """Test validation rejects invalid memory_gb."""
        with pytest.raises(ValueError, match="memory_gb must be at least 1"):
            ResourceRequirements(cpu_cores=4, memory_gb=0, storage_gb=50)

    def test_invalid_storage_gb(self):
        """Test validation rejects invalid storage_gb."""
        with pytest.raises(ValueError, match="storage_gb must be at least 1"):
            ResourceRequirements(cpu_cores=4, memory_gb=8, storage_gb=0)

    def test_fits_capacity_success(self):
        """Test fits_capacity returns True when capacity is sufficient."""
        req = ResourceRequirements(cpu_cores=4, memory_gb=8, storage_gb=50)

        assert req.fits_capacity(available_cpu=8, available_memory=16, available_storage=100) is True
        assert req.fits_capacity(available_cpu=4, available_memory=8, available_storage=50) is True

    def test_fits_capacity_failure(self):
        """Test fits_capacity returns False when capacity is insufficient."""
        req = ResourceRequirements(cpu_cores=4, memory_gb=8, storage_gb=50)

        assert req.fits_capacity(available_cpu=2, available_memory=16, available_storage=100) is False
        assert req.fits_capacity(available_cpu=8, available_memory=4, available_storage=100) is False
        assert req.fits_capacity(available_cpu=8, available_memory=16, available_storage=25) is False

    def test_serialization(self):
        """Test to_dict and from_dict round-trip."""
        ami_req = AmiRequirement(cml_version_min="2.7.0", node_definitions_required=("iosv",))
        req = ResourceRequirements(cpu_cores=4, memory_gb=8, storage_gb=50, nested_virt=False, ami_requirements=(ami_req,))

        data = req.to_dict()
        restored = ResourceRequirements.from_dict(data)

        assert restored.cpu_cores == req.cpu_cores
        assert restored.memory_gb == req.memory_gb
        assert restored.storage_gb == req.storage_gb
        assert restored.nested_virt == req.nested_virt
        assert len(restored.ami_requirements) == 1

    def test_with_node_definitions_updates_first_ami(self):
        """Test with_node_definitions() updates first AmiRequirement's node_definitions_required."""
        ami = AmiRequirement(cml_version_min="2.7.0", node_definitions_required=("iosv",))
        req = ResourceRequirements(cpu_cores=4, memory_gb=8, storage_gb=50, ami_requirements=(ami,))

        updated = req.with_node_definitions(("iosv", "mock-server", "ubuntu-desktop-24-04-v2"))

        assert updated.ami_requirements[0].node_definitions_required == ("iosv", "mock-server", "ubuntu-desktop-24-04-v2")
        # Preserves other fields
        assert updated.ami_requirements[0].cml_version_min == "2.7.0"
        assert updated.cpu_cores == 4
        assert updated.memory_gb == 8
        assert updated.storage_gb == 50
        # Original unchanged (frozen)
        assert req.ami_requirements[0].node_definitions_required == ("iosv",)

    def test_with_node_definitions_creates_ami_when_empty(self):
        """Test with_node_definitions() creates AmiRequirement when none exist."""
        req = ResourceRequirements(cpu_cores=2, memory_gb=4, storage_gb=20)
        assert req.ami_requirements == ()

        updated = req.with_node_definitions(("csr1000v",))

        assert len(updated.ami_requirements) == 1
        assert updated.ami_requirements[0].node_definitions_required == ("csr1000v",)
        assert updated.ami_requirements[0].cml_version_min is None

    def test_with_node_definitions_preserves_other_amis(self):
        """Test with_node_definitions() preserves additional AmiRequirements beyond the first."""
        ami1 = AmiRequirement(cml_version_min="2.7.0", node_definitions_required=("iosv",))
        ami2 = AmiRequirement(cml_version_min="2.9.0", node_definitions_required=("cat9kv",))
        req = ResourceRequirements(cpu_cores=4, memory_gb=8, storage_gb=50, ami_requirements=(ami1, ami2))

        updated = req.with_node_definitions(("iosv", "mock-server"))

        assert len(updated.ami_requirements) == 2
        assert updated.ami_requirements[0].node_definitions_required == ("iosv", "mock-server")
        assert updated.ami_requirements[1] == ami2  # Untouched


class TestAmiRequirement:
    """Test AmiRequirement value object."""

    def test_matches_version_within_range(self):
        """Test version matching within range."""
        req = AmiRequirement(cml_version_min="2.7.0", cml_version_max="2.9.0")

        assert req.matches_version("2.7.0") is True
        assert req.matches_version("2.8.0") is True
        assert req.matches_version("2.9.0") is True

    def test_matches_version_below_range(self):
        """Test version matching below range."""
        req = AmiRequirement(cml_version_min="2.7.0", cml_version_max="2.9.0")

        assert req.matches_version("2.6.0") is False

    def test_matches_version_above_range(self):
        """Test version matching above range."""
        req = AmiRequirement(cml_version_min="2.7.0", cml_version_max="2.9.0")

        assert req.matches_version("2.9.1") is False

    def test_matches_version_no_constraints(self):
        """Test version matching with no constraints."""
        req = AmiRequirement()

        assert req.matches_version("2.7.0") is True
        assert req.matches_version("3.0.0") is True


class TestPortTemplate:
    """Test PortTemplate value object."""

    def test_valid_creation(self):
        """Test creating valid port template."""
        template = PortTemplate(
            ports=(
                PortDefinition(name="serial_1", protocol="tcp", description="Serial console"),
                PortDefinition(name="vnc_1", protocol="tcp", description="VNC display"),
            )
        )

        assert template.port_count == 2
        assert template.port_names == ("serial_1", "vnc_1")

    def test_empty_template(self):
        """Test creating empty port template."""
        template = PortTemplate.empty()

        assert template.port_count == 0
        assert template.port_names == ()

    def test_duplicate_port_names_rejected(self):
        """Test validation rejects duplicate port names."""
        with pytest.raises(ValueError, match="Port names must be unique"):
            PortTemplate(
                ports=(
                    PortDefinition(name="serial_1", protocol="tcp"),
                    PortDefinition(name="serial_1", protocol="udp"),
                )
            )

    def test_serialization(self):
        """Test to_dict and from_dict round-trip."""
        template = PortTemplate(
            ports=(
                PortDefinition(name="serial_1", protocol="tcp", description="Serial console"),
                PortDefinition(name="vnc_1", protocol="tcp"),
            )
        )

        data = template.to_dict()
        restored = PortTemplate.from_dict(data)

        assert restored.port_count == 2
        assert restored.port_names == ("serial_1", "vnc_1")

    # --- from_cml_nodes() Tests ---

    def test_from_cml_nodes_basic(self):
        """Test extracting port template from CML topology nodes."""
        nodes = [
            {"label": "PC", "tags": ["serial:4567", "vnc:4568"]},
            {"label": "iosv-0", "tags": ["serial:4566"]},
            {"label": "vManageMockAPI", "tags": ["serial:4569"]},
        ]
        template = PortTemplate.from_cml_nodes(nodes)

        assert template.port_count == 4
        assert "PC_serial" in template.port_names
        assert "PC_vnc" in template.port_names
        assert "iosv-0_serial" in template.port_names
        assert "vManageMockAPI_serial" in template.port_names

        # All protocols should be tcp
        for port in template.ports:
            assert port.protocol == "tcp"

    def test_from_cml_nodes_empty(self):
        """Test from_cml_nodes with no nodes returns empty template."""
        template = PortTemplate.from_cml_nodes([])
        assert template.port_count == 0

    def test_from_cml_nodes_no_tags(self):
        """Test nodes without tags are skipped gracefully."""
        nodes = [
            {"label": "Router", "tags": []},
            {"label": "Switch"},  # missing tags key
        ]
        template = PortTemplate.from_cml_nodes(nodes)
        assert template.port_count == 0

    def test_from_cml_nodes_multiple_protocols(self):
        """Test node with serial, vnc, and ssh tags."""
        nodes = [
            {"label": "router1", "tags": ["ssh:22", "serial:5041", "vnc:5044"]},
        ]
        template = PortTemplate.from_cml_nodes(nodes)

        assert template.port_count == 3
        assert "router1_ssh" in template.port_names
        assert "router1_serial" in template.port_names
        assert "router1_vnc" in template.port_names

    def test_from_cml_nodes_duplicate_tags_deduplicated(self):
        """Test duplicate protocol tags on same node are de-duplicated."""
        nodes = [
            {"label": "router1", "tags": ["serial:5041", "serial:5042"]},
        ]
        template = PortTemplate.from_cml_nodes(nodes)
        assert template.port_count == 1
        assert template.port_names == ("router1_serial",)

    def test_from_cml_nodes_unrecognised_tags_skipped(self):
        """Test unrecognised tag formats are silently skipped."""
        nodes = [
            {"label": "router1", "tags": ["badtag", "vnc:notaport", "serial:5041"]},
        ]
        template = PortTemplate.from_cml_nodes(nodes)
        # Only "serial:5041" matches the pattern (vnc:notaport has non-numeric port)
        assert template.port_count == 1
        assert template.port_names == ("router1_serial",)

    def test_from_cml_nodes_label_with_spaces(self):
        """Test node labels with spaces are sanitised to underscores."""
        nodes = [
            {"label": "My Router", "tags": ["serial:5041"]},
        ]
        template = PortTemplate.from_cml_nodes(nodes)
        assert template.port_names == ("My_Router_serial",)

    def test_from_cml_nodes_missing_label_skipped(self):
        """Test nodes with empty label are skipped."""
        nodes = [
            {"label": "", "tags": ["serial:5041"]},
            {"tags": ["serial:5042"]},  # no label key
        ]
        template = PortTemplate.from_cml_nodes(nodes)
        assert template.port_count == 0

    def test_from_cml_nodes_description_includes_protocol_and_label(self):
        """Test generated port definitions have descriptive descriptions."""
        nodes = [{"label": "PC", "tags": ["serial:4567"]}]
        template = PortTemplate.from_cml_nodes(nodes)

        assert template.ports[0].description == "serial on PC"

    def test_from_cml_nodes_serialization_roundtrip(self):
        """Test from_cml_nodes result survives to_dict/from_dict roundtrip."""
        nodes = [
            {"label": "PC", "tags": ["serial:4567", "vnc:4568"]},
            {"label": "iosv-0", "tags": ["serial:4566"]},
        ]
        template = PortTemplate.from_cml_nodes(nodes)
        restored = PortTemplate.from_dict(template.to_dict())

        assert restored.port_count == template.port_count
        assert restored.port_names == template.port_names

    def test_from_cml_nodes_tag_without_port_number(self):
        """Test tag with protocol but no port number is accepted."""
        nodes = [{"label": "switch", "tags": ["serial:"]}]
        template = PortTemplate.from_cml_nodes(nodes)
        # "serial:" has empty port number — regex requires \d+ or nothing after colon
        # The regex ^([a-zA-Z][a-zA-Z0-9_-]*):(\d+)?$ matches "serial:" with group(2)=None
        assert template.port_count == 1
        assert template.port_names == ("switch_serial",)


class TestPortDefinition:
    """Test PortDefinition value object."""

    def test_valid_creation(self):
        """Test creating valid port definition."""
        port = PortDefinition(name="serial_1", protocol="tcp", description="Serial console")

        assert port.name == "serial_1"
        assert port.protocol == "tcp"
        assert port.description == "Serial console"

    def test_default_protocol(self):
        """Test default protocol is tcp."""
        port = PortDefinition(name="serial_1")

        assert port.protocol == "tcp"

    def test_empty_name_rejected(self):
        """Test validation rejects empty name."""
        with pytest.raises(ValueError, match="Port name cannot be empty"):
            PortDefinition(name="")

    def test_invalid_protocol_rejected(self):
        """Test validation rejects invalid protocol."""
        with pytest.raises(ValueError, match="Invalid protocol"):
            PortDefinition(name="serial_1", protocol="http")


class TestNotificationConfig:
    """Test NotificationConfig helper class."""

    def test_creation_with_defaults(self):
        """Test creating notification config with defaults."""
        config = NotificationConfig(email="user@example.com")

        assert config.email == "user@example.com"
        assert config.webhook_url is None
        assert config.notify_on_start is True
        assert config.notify_on_complete is True
        assert config.notify_on_error is True

    def test_serialization(self):
        """Test to_dict and from_dict round-trip."""
        config = NotificationConfig(
            email="user@example.com",
            webhook_url="https://hook.example.com/notify",
            notify_on_start=False,
        )

        data = config.to_dict()
        restored = NotificationConfig.from_dict(data)

        assert restored.email == config.email
        assert restored.webhook_url == config.webhook_url
        assert restored.notify_on_start is False


class TestLabletDefinitionState:
    """Test LabletDefinitionState."""

    def test_initialization(self):
        """Test state initialization with default values."""
        state = LabletDefinitionState()

        assert state.id == ""
        assert state.name == ""
        assert state.version == ""
        assert state.status == LabletDefinitionStatus.ACTIVE
        assert state.node_count == 0
        assert state.warm_pool_depth == 0
        assert state.max_duration_minutes == 60
        assert state.license_affinity == []
        assert state.deprecated_by is None

    def test_content_sync_field_defaults(self):
        """Test content sync fields have correct defaults."""
        state = LabletDefinitionState()

        assert state.form_qualified_name is None
        assert state.bucket_name == ""
        assert state.user_session_package_name == "SVN.zip"
        assert state.grading_ruleset_package_name == "SVN.zip"
        assert state.user_session_type == "LDS"
        assert state.user_session_default_region is None
        assert state.content_package_hash is None
        assert state.upstream_version is None
        assert state.upstream_date_published is None
        assert state.upstream_instance_name is None
        assert state.upstream_form_id is None
        assert state.grade_xml_path is None
        assert state.cml_yaml_path is None
        assert state.cml_yaml_content is None
        assert state.devices_json is None
        assert state.upstream_sync_status is None


class TestLabletDefinition:
    """Test LabletDefinition aggregate."""

    @pytest.fixture
    def resource_requirements(self):
        """Create test resource requirements."""
        return ResourceRequirements(cpu_cores=4, memory_gb=8, storage_gb=50)

    @pytest.fixture
    def port_template(self):
        """Create test port template."""
        return PortTemplate(
            ports=(
                PortDefinition(name="serial_1", protocol="tcp"),
                PortDefinition(name="vnc_1", protocol="tcp"),
            )
        )

    def _create_definition(self, resource_requirements, port_template, **overrides):
        """Helper to create a definition with standard defaults."""
        kwargs = dict(
            name="ccna-basic-routing",
            version="1.0.0",
            form_qualified_name=FQN,
            resource_requirements=resource_requirements,
            license_affinity=[LicenseType.PERSONAL, LicenseType.ENTERPRISE],
            node_count=5,
            port_template=port_template,
            created_by="admin@example.com",
        )
        kwargs.update(overrides)
        return LabletDefinition.create(**kwargs)

    # --- Creation Tests (ADR-028: PENDING_SYNC) ---

    def test_create_lablet_definition(self, resource_requirements, port_template):
        """Test creating a new LabletDefinition with content sync fields."""
        definition = self._create_definition(
            resource_requirements,
            port_template,
            max_duration_minutes=120,
            warm_pool_depth=2,
        )

        # Verify core state
        assert definition.state.name == "ccna-basic-routing"
        assert definition.state.version == "1.0.0"
        assert definition.state.node_count == 5
        assert definition.state.max_duration_minutes == 120
        assert definition.state.warm_pool_depth == 2
        assert definition.state.created_by == "admin@example.com"
        assert LicenseType.PERSONAL in definition.state.license_affinity
        assert LicenseType.ENTERPRISE in definition.state.license_affinity

        # ADR-028: Initial status is PENDING_SYNC
        assert definition.state.status == LabletDefinitionStatus.PENDING_SYNC

        # Content sync fields derived from FQN
        assert definition.state.form_qualified_name == FQN
        assert definition.state.bucket_name == FQN_SLUG
        assert definition.state.lab_artifact_uri == f"s3://{FQN_SLUG}/SVN.zip"
        assert definition.state.lab_yaml_hash == ""  # Empty until sync

        # Package config defaults
        assert definition.state.user_session_package_name == "SVN.zip"
        assert definition.state.grading_ruleset_package_name == "SVN.zip"
        assert definition.state.user_session_type == "LDS"
        assert definition.state.user_session_default_region is None

        # Verify event was recorded
        events = definition.domain_events
        assert len(events) == 1
        assert isinstance(events[0], LabletDefinitionCreatedDomainEvent)

    def test_create_with_custom_package_config(self, resource_requirements, port_template):
        """Test creating with custom package configuration."""
        definition = self._create_definition(
            resource_requirements,
            port_template,
            user_session_package_name="custom-pkg.zip",
            grading_ruleset_package_name="grading-rules.zip",
            user_session_type="LDS",
            user_session_default_region="us-west-2",
        )

        assert definition.state.user_session_package_name == "custom-pkg.zip"
        assert definition.state.grading_ruleset_package_name == "grading-rules.zip"
        assert definition.state.user_session_type == "LDS"
        assert definition.state.user_session_default_region == "us-west-2"
        # lab_artifact_uri uses custom package name
        assert definition.state.lab_artifact_uri == f"s3://{FQN_SLUG}/custom-pkg.zip"

    def test_create_lablet_definition_minimal(self, resource_requirements, port_template):
        """Test creating with minimal required fields."""
        definition = LabletDefinition.create(
            name="test-lab",
            version="0.1.0",
            form_qualified_name="Practice Level1 TEST v1.0 LAB basics",
            resource_requirements=resource_requirements,
            license_affinity=[],
            node_count=2,
            port_template=port_template,
            created_by="user@example.com",
        )

        assert definition.state.name == "test-lab"
        assert definition.state.version == "0.1.0"
        assert definition.state.max_duration_minutes == 60  # Default
        assert definition.state.warm_pool_depth == 0  # Default
        assert definition.state.status == LabletDefinitionStatus.PENDING_SYNC
        assert definition.state.bucket_name == "practice-level1-test-v1.0-lab-basics"

    def test_aggregate_id_assigned(self, resource_requirements, port_template):
        """Test that aggregate ID is properly assigned."""
        definition = self._create_definition(resource_requirements, port_template)

        assert definition.id() is not None
        assert len(definition.id()) == 36  # UUID format

    def test_created_event_carries_content_sync_fields(self, resource_requirements, port_template):
        """Test the CreatedDomainEvent contains content sync fields."""
        definition = self._create_definition(
            resource_requirements,
            port_template,
            user_session_package_name="custom.zip",
            user_session_default_region="eu-west-1",
        )

        event = definition.domain_events[0]
        assert isinstance(event, LabletDefinitionCreatedDomainEvent)
        assert event.form_qualified_name == FQN
        assert event.bucket_name == FQN_SLUG
        assert event.user_session_package_name == "custom.zip"
        assert event.grading_ruleset_package_name == "SVN.zip"
        assert event.user_session_type == "LDS"
        assert event.user_session_default_region == "eu-west-1"

    # --- Version Creation ---

    def test_create_version(self, resource_requirements, port_template):
        """Test creating a new version of a definition."""
        new_requirements = ResourceRequirements(cpu_cores=8, memory_gb=16, storage_gb=100)

        definition = LabletDefinition.create_version(
            name="ccna-basic-routing",
            version="2.0.0",
            previous_version="1.0.0",
            lab_artifact_uri="s3://labs/ccna-basic-routing/2.0.0/topology.yaml",
            lab_yaml_hash="sha256:xyz789",
            resource_requirements=new_requirements,
            node_count=10,
            port_template=port_template,
            created_by="admin@example.com",
        )

        assert definition.state.name == "ccna-basic-routing"
        assert definition.state.version == "2.0.0"
        assert definition.state.resource_requirements.cpu_cores == 8
        assert definition.state.node_count == 10

        events = definition.domain_events
        assert len(events) == 1
        assert isinstance(events[0], LabletDefinitionVersionCreatedDomainEvent)
        assert events[0].previous_version == "1.0.0"

    # --- Deprecation ---

    def test_deprecate_definition(self, resource_requirements, port_template):
        """Test deprecating a definition."""
        definition = self._create_definition(resource_requirements, port_template)

        definition.deprecate(
            deprecated_by="admin@example.com",
            deprecation_reason="Replaced by version 2.0.0",
            replacement_version="2.0.0",
        )

        assert definition.state.status == LabletDefinitionStatus.DEPRECATED
        assert definition.state.deprecated_by == "admin@example.com"
        assert definition.state.deprecation_reason == "Replaced by version 2.0.0"
        assert definition.state.replacement_version == "2.0.0"
        assert definition.state.deprecated_at is not None

        events = definition.domain_events
        assert len(events) == 2
        assert isinstance(events[1], LabletDefinitionDeprecatedDomainEvent)

    def test_deprecate_idempotent(self, resource_requirements, port_template):
        """Test that deprecating twice is a no-op."""
        definition = self._create_definition(resource_requirements, port_template)

        definition.deprecate(deprecated_by="admin@example.com")
        definition.deprecate(deprecated_by="another-admin@example.com")

        assert len(definition.domain_events) == 2

    # --- Legacy Artifact Sync (backward compat) ---

    def test_record_artifact_sync_success(self, resource_requirements, port_template):
        """Test recording successful artifact sync (legacy method)."""
        definition = self._create_definition(resource_requirements, port_template)

        definition.record_artifact_sync(lab_yaml_hash="sha256:updated", sync_status="success")

        assert definition.state.sync_status == "success"
        assert definition.state.lab_yaml_hash == "sha256:updated"
        assert definition.state.last_synced_at is not None

    def test_record_artifact_sync_failure(self, resource_requirements, port_template):
        """Test recording failed artifact sync (legacy method)."""
        definition = self._create_definition(resource_requirements, port_template)

        definition.record_artifact_sync(
            lab_yaml_hash="sha256:abc123",
            sync_status="failed",
            error_message="S3 bucket not accessible",
        )

        assert definition.state.sync_status == "failed"

    # --- request_sync() (ADR-028, AD-CS-001) ---

    def test_request_sync(self, resource_requirements, port_template):
        """Test request_sync() emits SyncRequestedDomainEvent."""
        definition = self._create_definition(resource_requirements, port_template)

        definition.request_sync(requested_by="user@example.com")

        assert definition.state.sync_status == "sync_requested"

        events = definition.domain_events
        assert len(events) == 2  # Created + SyncRequested
        sync_event = events[1]
        assert isinstance(sync_event, LabletDefinitionSyncRequestedDomainEvent)
        assert sync_event.aggregate_id == definition.id()
        assert sync_event.form_qualified_name == FQN
        assert sync_event.bucket_name == FQN_SLUG
        assert sync_event.user_session_package_name == "SVN.zip"
        assert sync_event.requested_by == "user@example.com"
        assert sync_event.requested_at != ""

    def test_request_sync_default_requested_by(self, resource_requirements, port_template):
        """Test request_sync() works without specifying requested_by."""
        definition = self._create_definition(resource_requirements, port_template)

        definition.request_sync()

        assert definition.state.sync_status == "sync_requested"
        event = definition.domain_events[1]
        assert isinstance(event, LabletDefinitionSyncRequestedDomainEvent)
        assert event.requested_by == ""

    # --- record_content_sync() (ADR-025) ---

    def test_record_content_sync_success(self, resource_requirements, port_template):
        """Test record_content_sync() with full metadata on success."""
        definition = self._create_definition(resource_requirements, port_template)

        definition.record_content_sync(
            lab_yaml_hash="sha256:newpackagehash",
            sync_status="success",
            content_package_hash="sha256:fullziphash",
            upstream_version="3.2.1",
            upstream_date_published="2026-02-20T10:00:00Z",
            upstream_instance_name="mosaic-prod",
            upstream_form_id="FORM-12345",
            grade_xml_path="content/grade.xml",
            cml_yaml_path="content/cml.yaml",
            cml_yaml_content="lab:\n  title: test",
            devices_json='[{"name": "router1"}]',
            upstream_sync_status={
                "lds": {"status": "success", "synced_at": "2026-02-20T10:05:00Z"},
                "grading_engine": {"status": "success", "synced_at": "2026-02-20T10:06:00Z"},
            },
        )

        state = definition.state

        # Status transitions: PENDING_SYNC → ACTIVE on success
        assert state.status == LabletDefinitionStatus.ACTIVE
        assert state.sync_status == "success"
        assert state.lab_yaml_hash == "sha256:newpackagehash"
        assert state.last_synced_at is not None

        # Content metadata populated
        assert state.content_package_hash == "sha256:fullziphash"
        assert state.upstream_version == "3.2.1"
        assert state.upstream_date_published == "2026-02-20T10:00:00Z"
        assert state.upstream_instance_name == "mosaic-prod"
        assert state.upstream_form_id == "FORM-12345"
        assert state.grade_xml_path == "content/grade.xml"
        assert state.cml_yaml_path == "content/cml.yaml"
        assert state.cml_yaml_content == "lab:\n  title: test"
        assert state.devices_json == '[{"name": "router1"}]'
        assert state.upstream_sync_status["lds"]["status"] == "success"

        # Verify event
        events = definition.domain_events
        assert len(events) == 2  # Created + ContentSynced
        assert isinstance(events[1], LabletDefinitionContentSyncedDomainEvent)

    def test_record_content_sync_failure(self, resource_requirements, port_template):
        """Test record_content_sync() on failure does NOT transition status."""
        definition = self._create_definition(resource_requirements, port_template)

        definition.record_content_sync(
            lab_yaml_hash="",
            sync_status="failed",
            error_message="Mosaic download failed: 404 Not Found",
        )

        # Status remains PENDING_SYNC on failure
        assert definition.state.status == LabletDefinitionStatus.PENDING_SYNC
        assert definition.state.sync_status == "failed"
        # Content metadata stays None
        assert definition.state.content_package_hash is None

    def test_record_content_sync_preserves_existing_metadata_on_none(self, resource_requirements, port_template):
        """Test that None values in content sync don't overwrite existing metadata."""
        definition = self._create_definition(resource_requirements, port_template)

        # First sync: populate metadata
        definition.record_content_sync(
            lab_yaml_hash="sha256:first",
            sync_status="success",
            content_package_hash="sha256:pkg1",
            upstream_version="1.0.0",
        )

        assert definition.state.status == LabletDefinitionStatus.ACTIVE
        assert definition.state.upstream_version == "1.0.0"

        # Second sync: partial update (only hash changed, version not provided)
        definition.record_content_sync(
            lab_yaml_hash="sha256:second",
            sync_status="success",
            content_package_hash="sha256:pkg2",
            # upstream_version not provided → None → existing value preserved
        )

        assert definition.state.content_package_hash == "sha256:pkg2"  # Updated
        assert definition.state.upstream_version == "1.0.0"  # Preserved

    def test_content_sync_event_fields(self, resource_requirements, port_template):
        """Test ContentSyncedDomainEvent carries all metadata."""
        definition = self._create_definition(resource_requirements, port_template)

        definition.record_content_sync(
            lab_yaml_hash="sha256:hash",
            sync_status="success",
            content_package_hash="sha256:pkg",
            upstream_version="2.0.0",
            grade_xml_path="grade.xml",
            cml_yaml_path="cml.yaml",
        )

        event = definition.domain_events[1]
        assert isinstance(event, LabletDefinitionContentSyncedDomainEvent)
        assert event.aggregate_id == definition.id()
        assert event.lab_yaml_hash == "sha256:hash"
        assert event.sync_status == "success"
        assert event.content_package_hash == "sha256:pkg"
        assert event.upstream_version == "2.0.0"
        assert event.grade_xml_path == "grade.xml"
        assert event.cml_yaml_path == "cml.yaml"
        assert event.lab_artifact_uri == definition.state.lab_artifact_uri

    def test_record_content_sync_with_port_template(self, resource_requirements, port_template):
        """Test record_content_sync() updates port_template from CML YAML extraction."""
        definition = self._create_definition(resource_requirements, port_template)

        # Original port template has 2 ports from creation
        assert definition.port_count == 2

        # Simulate content sync extracting ports from CML YAML nodes
        extracted_template = PortTemplate.from_cml_nodes(
            [
                {"label": "PC", "tags": ["serial:4567", "vnc:4568"]},
                {"label": "iosv-0", "tags": ["serial:4566"]},
                {"label": "vManageMockAPI", "tags": ["serial:4569"]},
            ]
        )

        definition.record_content_sync(
            lab_yaml_hash="sha256:xyz",
            sync_status="success",
            port_template=extracted_template,
        )

        # Port template should be updated to the extracted one
        assert definition.port_count == 4
        assert "PC_serial" in definition.state.port_template.port_names
        assert "PC_vnc" in definition.state.port_template.port_names
        assert "iosv-0_serial" in definition.state.port_template.port_names
        assert "vManageMockAPI_serial" in definition.state.port_template.port_names

    def test_record_content_sync_without_port_template_preserves_existing(self, resource_requirements, port_template):
        """Test record_content_sync() without port_template doesn't overwrite."""
        definition = self._create_definition(resource_requirements, port_template)
        original_names = definition.state.port_template.port_names

        definition.record_content_sync(
            lab_yaml_hash="sha256:abc",
            sync_status="success",
            # port_template not provided
        )

        # Original port template preserved
        assert definition.state.port_template.port_names == original_names

    def test_record_content_sync_with_node_count(self, resource_requirements, port_template):
        """Test record_content_sync() updates node_count from CML topology (AD-SEED-001)."""
        definition = self._create_definition(resource_requirements, port_template, node_count=5)
        assert definition.state.node_count == 5

        definition.record_content_sync(
            lab_yaml_hash="sha256:topo",
            sync_status="success",
            node_count=3,
        )

        assert definition.state.node_count == 3

    def test_record_content_sync_without_node_count_preserves_existing(self, resource_requirements, port_template):
        """Test record_content_sync() without node_count doesn't overwrite."""
        definition = self._create_definition(resource_requirements, port_template, node_count=5)

        definition.record_content_sync(
            lab_yaml_hash="sha256:abc",
            sync_status="success",
            # node_count not provided
        )

        assert definition.state.node_count == 5

    def test_record_content_sync_with_node_definitions_required(self, resource_requirements, port_template):
        """Test record_content_sync() updates ami_requirements.node_definitions_required (AD-SEED-001)."""
        rr = ResourceRequirements(
            cpu_cores=4,
            memory_gb=8,
            storage_gb=50,
            ami_requirements=(AmiRequirement(cml_version_min="2.7.0", node_definitions_required=("iosv",)),),
        )
        definition = self._create_definition(rr, port_template)
        assert definition.state.resource_requirements.ami_requirements[0].node_definitions_required == ("iosv",)

        definition.record_content_sync(
            lab_yaml_hash="sha256:defs",
            sync_status="success",
            node_definitions_required=["iosv", "mock-server", "ubuntu-desktop-24-04-v2"],
        )

        # ami_requirements updated with new node definitions
        ami = definition.state.resource_requirements.ami_requirements[0]
        assert ami.node_definitions_required == ("iosv", "mock-server", "ubuntu-desktop-24-04-v2")
        # Other ami_requirement fields preserved
        assert ami.cml_version_min == "2.7.0"
        # Resource limits preserved
        assert definition.state.resource_requirements.cpu_cores == 4
        assert definition.state.resource_requirements.memory_gb == 8

    def test_record_content_sync_with_node_definitions_no_existing_ami(self, resource_requirements, port_template):
        """Test record_content_sync() creates ami_requirement when none exist."""
        rr = ResourceRequirements(cpu_cores=2, memory_gb=4, storage_gb=20)
        assert rr.ami_requirements == ()

        definition = self._create_definition(rr, port_template)

        definition.record_content_sync(
            lab_yaml_hash="sha256:newdefs",
            sync_status="success",
            node_definitions_required=["iosv"],
        )

        assert len(definition.state.resource_requirements.ami_requirements) == 1
        assert definition.state.resource_requirements.ami_requirements[0].node_definitions_required == ("iosv",)

    def test_record_content_sync_event_carries_topology_fields(self, resource_requirements, port_template):
        """Test ContentSyncedDomainEvent carries node_count and node_definitions_required."""
        definition = self._create_definition(resource_requirements, port_template)

        definition.record_content_sync(
            lab_yaml_hash="sha256:topo2",
            sync_status="success",
            node_count=2,
            node_definitions_required=["mock-server", "ubuntu-desktop-24-04-v2"],
        )

        event = definition.domain_events[1]
        assert isinstance(event, LabletDefinitionContentSyncedDomainEvent)
        assert event.node_count == 2
        assert event.node_definitions_required == ["mock-server", "ubuntu-desktop-24-04-v2"]

    # --- Warm Pool ---

    def test_update_warm_pool_depth(self, resource_requirements, port_template):
        """Test updating warm pool depth."""
        definition = self._create_definition(resource_requirements, port_template, warm_pool_depth=0)

        definition.update_warm_pool_depth(new_depth=5, updated_by="admin@example.com")

        assert definition.state.warm_pool_depth == 5

        events = definition.domain_events
        warm_pool_event = next(e for e in events if isinstance(e, LabletDefinitionWarmPoolUpdatedDomainEvent))
        assert warm_pool_event.old_warm_pool_depth == 0
        assert warm_pool_event.new_warm_pool_depth == 5

    def test_update_warm_pool_depth_idempotent(self, resource_requirements, port_template):
        """Test that updating to same value is a no-op."""
        definition = self._create_definition(resource_requirements, port_template, warm_pool_depth=5)

        definition.update_warm_pool_depth(new_depth=5, updated_by="admin@example.com")

        assert len(definition.domain_events) == 1

    def test_update_warm_pool_depth_negative_rejected(self, resource_requirements, port_template):
        """Test that negative warm pool depth is rejected."""
        definition = self._create_definition(resource_requirements, port_template)

        with pytest.raises(ValueError, match="cannot be negative"):
            definition.update_warm_pool_depth(new_depth=-1, updated_by="admin@example.com")

    # --- Computed Properties ---

    def test_is_active_property(self, resource_requirements, port_template):
        """Test is_active computed property."""
        definition = self._create_definition(resource_requirements, port_template)

        # New definitions are PENDING_SYNC, not ACTIVE
        assert definition.is_active is False
        assert definition.is_pending_sync is True
        assert definition.is_deprecated is False

        # Sync to activate
        definition.record_content_sync(lab_yaml_hash="sha256:x", sync_status="success")
        assert definition.is_active is True
        assert definition.is_pending_sync is False

        # Deprecate
        definition.deprecate(deprecated_by="admin@example.com")
        assert definition.is_active is False
        assert definition.is_deprecated is True

    def test_is_pending_sync_property(self, resource_requirements, port_template):
        """Test is_pending_sync computed property."""
        definition = self._create_definition(resource_requirements, port_template)

        assert definition.is_pending_sync is True
        assert definition.state.status == LabletDefinitionStatus.PENDING_SYNC

    def test_port_count_property(self, resource_requirements, port_template):
        """Test port_count computed property."""
        definition = self._create_definition(resource_requirements, port_template)

        assert definition.port_count == 2

    def test_unique_key_property(self, resource_requirements, port_template):
        """Test unique_key computed property."""
        definition = self._create_definition(resource_requirements, port_template)

        assert definition.unique_key == "ccna-basic-routing:1.0.0"

    # --- Notification Config ---

    def test_with_notification_config(self, resource_requirements, port_template):
        """Test creating definition with notification config."""
        notification = NotificationConfig(
            email="admin@example.com",
            notify_on_start=True,
            notify_on_complete=True,
            notify_on_error=True,
        )

        definition = self._create_definition(
            resource_requirements,
            port_template,
            owner_notification=notification,
        )

        assert definition.state.owner_notification is not None
        assert definition.state.owner_notification.email == "admin@example.com"

    def test_with_grading_rules(self, resource_requirements, port_template):
        """Test creating definition with grading rules."""
        definition = self._create_definition(
            resource_requirements,
            port_template,
            grading_rules_uri="s3://labs/test-lab/grading.json",
        )

        assert definition.state.grading_rules_uri == "s3://labs/test-lab/grading.json"

    # --- Lifecycle Transitions: activate / deactivate / soft_delete (Phase 3) ---

    def _create_active_definition(self, resource_requirements, port_template, **overrides):
        """Helper: create a definition and sync it to ACTIVE."""
        defn = self._create_definition(resource_requirements, port_template, **overrides)
        defn.record_content_sync(lab_yaml_hash="sha256:test", sync_status="success")
        assert defn.state.status == LabletDefinitionStatus.ACTIVE
        return defn

    def test_activate_from_inactive(self, resource_requirements, port_template):
        """Test INACTIVE → ACTIVE transition via activate()."""
        defn = self._create_active_definition(resource_requirements, port_template)
        defn.deactivate(deactivated_by="admin")
        assert defn.state.status == LabletDefinitionStatus.INACTIVE

        defn.activate(activated_by="admin")

        assert defn.state.status == LabletDefinitionStatus.ACTIVE
        events = defn.domain_events
        assert isinstance(events[-1], LabletDefinitionActivatedDomainEvent)
        assert events[-1].activated_by == "admin"
        assert events[-1].activated_at is not None

    def test_activate_idempotent_when_already_active(self, resource_requirements, port_template):
        """Test activate() is a no-op when already ACTIVE."""
        defn = self._create_active_definition(resource_requirements, port_template)
        event_count = len(defn.domain_events)

        defn.activate(activated_by="admin")

        assert defn.state.status == LabletDefinitionStatus.ACTIVE
        assert len(defn.domain_events) == event_count  # No new event

    def test_activate_rejects_deprecated(self, resource_requirements, port_template):
        """Test activate() raises ValueError for DEPRECATED definitions."""
        defn = self._create_active_definition(resource_requirements, port_template)
        defn.deprecate(deprecated_by="admin")

        with pytest.raises(ValueError, match="Cannot activate a deprecated definition"):
            defn.activate(activated_by="admin")

    def test_activate_rejects_deleted(self, resource_requirements, port_template):
        """Test activate() raises ValueError for DELETED definitions."""
        defn = self._create_active_definition(resource_requirements, port_template)
        defn.soft_delete(deleted_by="admin")

        with pytest.raises(ValueError, match="Cannot activate a deleted definition"):
            defn.activate(activated_by="admin")

    def test_activate_rejects_pending_sync(self, resource_requirements, port_template):
        """Test activate() raises ValueError for PENDING_SYNC definitions."""
        defn = self._create_definition(resource_requirements, port_template)
        assert defn.state.status == LabletDefinitionStatus.PENDING_SYNC

        with pytest.raises(ValueError, match="Cannot activate a definition that is pending sync"):
            defn.activate(activated_by="admin")

    def test_activate_records_state_transition(self, resource_requirements, port_template):
        """Test activate() records audit trail via state_history."""
        defn = self._create_active_definition(resource_requirements, port_template)
        defn.deactivate(deactivated_by="admin")
        defn.activate(activated_by="admin")

        history = defn.state.state_history
        last_transition = history[-1]
        assert last_transition["to_state"] == "active"
        assert last_transition["from_state"] == "inactive"
        assert last_transition["triggered_by"] == "admin"

    def test_deactivate_from_active(self, resource_requirements, port_template):
        """Test ACTIVE → INACTIVE transition via deactivate()."""
        defn = self._create_active_definition(resource_requirements, port_template)

        defn.deactivate(deactivated_by="admin", reason="Maintenance window")

        assert defn.state.status == LabletDefinitionStatus.INACTIVE
        events = defn.domain_events
        assert isinstance(events[-1], LabletDefinitionDeactivatedDomainEvent)
        assert events[-1].deactivated_by == "admin"
        assert events[-1].reason == "Maintenance window"
        assert events[-1].deactivated_at is not None

    def test_deactivate_idempotent_when_already_inactive(self, resource_requirements, port_template):
        """Test deactivate() is a no-op when already INACTIVE."""
        defn = self._create_active_definition(resource_requirements, port_template)
        defn.deactivate(deactivated_by="admin")
        event_count = len(defn.domain_events)

        defn.deactivate(deactivated_by="admin")

        assert defn.state.status == LabletDefinitionStatus.INACTIVE
        assert len(defn.domain_events) == event_count  # No new event

    def test_deactivate_rejects_non_active(self, resource_requirements, port_template):
        """Test deactivate() raises ValueError for non-ACTIVE definitions."""
        defn = self._create_definition(resource_requirements, port_template)
        assert defn.state.status == LabletDefinitionStatus.PENDING_SYNC

        with pytest.raises(ValueError, match="Cannot deactivate a pending_sync definition"):
            defn.deactivate(deactivated_by="admin")

    def test_deactivate_rejects_deprecated(self, resource_requirements, port_template):
        """Test deactivate() raises ValueError for DEPRECATED definitions."""
        defn = self._create_active_definition(resource_requirements, port_template)
        defn.deprecate(deprecated_by="admin")

        with pytest.raises(ValueError, match="Cannot deactivate a deprecated definition"):
            defn.deactivate(deactivated_by="admin")

    def test_deactivate_records_state_transition(self, resource_requirements, port_template):
        """Test deactivate() records audit trail via state_history."""
        defn = self._create_active_definition(resource_requirements, port_template)
        defn.deactivate(deactivated_by="admin", reason="Quarterly maintenance")

        history = defn.state.state_history
        last_transition = history[-1]
        assert last_transition["to_state"] == "inactive"
        assert last_transition["from_state"] == "active"
        assert last_transition["triggered_by"] == "admin"
        assert last_transition["reason"] == "Quarterly maintenance"

    def test_soft_delete_from_active(self, resource_requirements, port_template):
        """Test soft_delete() from ACTIVE status."""
        defn = self._create_active_definition(resource_requirements, port_template)

        defn.soft_delete(deleted_by="admin")

        assert defn.state.status == LabletDefinitionStatus.DELETED
        events = defn.domain_events
        assert isinstance(events[-1], LabletDefinitionDeletedDomainEvent)
        assert events[-1].deleted_by == "admin"
        assert events[-1].deleted_at is not None

    def test_soft_delete_from_inactive(self, resource_requirements, port_template):
        """Test soft_delete() from INACTIVE status."""
        defn = self._create_active_definition(resource_requirements, port_template)
        defn.deactivate(deactivated_by="admin")

        defn.soft_delete(deleted_by="admin")

        assert defn.state.status == LabletDefinitionStatus.DELETED

    def test_soft_delete_from_pending_sync(self, resource_requirements, port_template):
        """Test soft_delete() from PENDING_SYNC status."""
        defn = self._create_definition(resource_requirements, port_template)

        defn.soft_delete(deleted_by="admin")

        assert defn.state.status == LabletDefinitionStatus.DELETED

    def test_soft_delete_from_deprecated(self, resource_requirements, port_template):
        """Test soft_delete() from DEPRECATED status."""
        defn = self._create_active_definition(resource_requirements, port_template)
        defn.deprecate(deprecated_by="admin")

        defn.soft_delete(deleted_by="admin")

        assert defn.state.status == LabletDefinitionStatus.DELETED

    def test_soft_delete_idempotent_when_already_deleted(self, resource_requirements, port_template):
        """Test soft_delete() is a no-op when already DELETED."""
        defn = self._create_active_definition(resource_requirements, port_template)
        defn.soft_delete(deleted_by="admin")
        event_count = len(defn.domain_events)

        defn.soft_delete(deleted_by="admin")

        assert defn.state.status == LabletDefinitionStatus.DELETED
        assert len(defn.domain_events) == event_count  # No new event

    def test_soft_delete_records_state_transition(self, resource_requirements, port_template):
        """Test soft_delete() records audit trail via state_history."""
        defn = self._create_active_definition(resource_requirements, port_template)
        defn.soft_delete(deleted_by="admin")

        history = defn.state.state_history
        last_transition = history[-1]
        assert last_transition["to_state"] == "deleted"
        assert last_transition["from_state"] == "active"
        assert last_transition["triggered_by"] == "admin"

    def test_full_lifecycle_activate_deactivate_activate_delete(self, resource_requirements, port_template):
        """Integration test: create → sync → activate → deactivate → activate → soft_delete."""
        defn = self._create_definition(resource_requirements, port_template)
        assert defn.state.status == LabletDefinitionStatus.PENDING_SYNC

        # Sync → ACTIVE
        defn.record_content_sync(lab_yaml_hash="sha256:test", sync_status="success")
        assert defn.state.status == LabletDefinitionStatus.ACTIVE

        # Deactivate
        defn.deactivate(deactivated_by="admin", reason="Planned maintenance")
        assert defn.state.status == LabletDefinitionStatus.INACTIVE

        # Re-activate
        defn.activate(activated_by="admin")
        assert defn.state.status == LabletDefinitionStatus.ACTIVE

        # Soft-delete
        defn.soft_delete(deleted_by="admin")
        assert defn.state.status == LabletDefinitionStatus.DELETED

        # Verify full event chain
        event_types = [type(e).__name__ for e in defn.domain_events]
        assert "LabletDefinitionCreatedDomainEvent" in event_types
        assert "LabletDefinitionContentSyncedDomainEvent" in event_types
        assert "LabletDefinitionDeactivatedDomainEvent" in event_types
        assert "LabletDefinitionActivatedDomainEvent" in event_types
        assert "LabletDefinitionDeletedDomainEvent" in event_types

        # Verify state history has all transitions
        assert len(defn.state.state_history) >= 4  # sync→active, active→inactive, inactive→active, active→deleted


class TestLabletDefinitionEvents:
    """Test LabletDefinition domain events."""

    def test_created_event_cloudevent_type(self):
        """Test LabletDefinitionCreatedDomainEvent has correct fields."""
        event = LabletDefinitionCreatedDomainEvent(
            aggregate_id="test-id",
            name="test-lab",
            version="1.0.0",
            lab_artifact_uri="s3://labs/test.yaml",
            lab_yaml_hash="sha256:abc",
            lab_yaml_cached=None,
            resource_requirements={"cpu_cores": 4, "memory_gb": 8, "storage_gb": 50},
            license_affinity=["personal"],
            node_count=5,
            port_template={"ports": []},
            grading_rules_uri=None,
            max_duration_minutes=60,
            warm_pool_depth=0,
            owner_notification=None,
            created_by="user@example.com",
            created_at=datetime.now(timezone.utc),
            form_qualified_name=FQN,
            bucket_name=FQN_SLUG,
            user_session_package_name="SVN.zip",
            grading_ruleset_package_name="SVN.zip",
            user_session_type="LDS",
            user_session_default_region=None,
        )

        assert event.aggregate_id == "test-id"
        assert event.name == "test-lab"
        assert event.form_qualified_name == FQN
        assert event.bucket_name == FQN_SLUG

    def test_created_event_backward_compat_defaults(self):
        """Test CreatedDomainEvent works without new fields (backward compat)."""
        event = LabletDefinitionCreatedDomainEvent(
            aggregate_id="test-id",
            name="test-lab",
            version="1.0.0",
            lab_artifact_uri="s3://labs/test.yaml",
            lab_yaml_hash="sha256:abc",
            lab_yaml_cached=None,
            resource_requirements={"cpu_cores": 4, "memory_gb": 8, "storage_gb": 50},
            license_affinity=["personal"],
            node_count=5,
            port_template={"ports": []},
            grading_rules_uri=None,
            max_duration_minutes=60,
            warm_pool_depth=0,
            owner_notification=None,
            created_by="user@example.com",
            created_at=datetime.now(timezone.utc),
            # No content sync fields → defaults
        )

        assert event.form_qualified_name is None
        assert event.bucket_name == ""
        assert event.user_session_package_name == "SVN.zip"

    def test_deprecated_event_optional_fields(self):
        """Test LabletDefinitionDeprecatedDomainEvent with optional fields."""
        event = LabletDefinitionDeprecatedDomainEvent(
            aggregate_id="test-id",
            name="test-lab",
            version="1.0.0",
            deprecated_by="admin@example.com",
            deprecated_at=datetime.now(timezone.utc),
        )

        assert event.deprecation_reason is None
        assert event.replacement_version is None

    def test_sync_requested_event(self):
        """Test LabletDefinitionSyncRequestedDomainEvent construction."""
        event = LabletDefinitionSyncRequestedDomainEvent(
            aggregate_id="def-123",
            form_qualified_name=FQN,
            bucket_name=FQN_SLUG,
            requested_by="user@example.com",
            requested_at="2026-02-25T10:00:00+00:00",
        )

        assert event.aggregate_id == "def-123"
        assert event.aggregate_type == "LabletDefinition"
        assert event.form_qualified_name == FQN
        assert event.bucket_name == FQN_SLUG
        assert event.user_session_package_name == "SVN.zip"
        assert event.requested_by == "user@example.com"

    def test_content_synced_event(self):
        """Test LabletDefinitionContentSyncedDomainEvent construction."""
        now = datetime.now(timezone.utc)
        event = LabletDefinitionContentSyncedDomainEvent(
            aggregate_id="def-123",
            lab_artifact_uri="s3://bucket/SVN.zip",
            lab_yaml_hash="sha256:abc",
            synced_at=now,
            sync_status="success",
            content_package_hash="sha256:fullpkg",
            upstream_version="2.0.0",
            grade_xml_path="content/grade.xml",
        )

        assert event.aggregate_id == "def-123"
        assert event.sync_status == "success"
        assert event.content_package_hash == "sha256:fullpkg"
        assert event.upstream_version == "2.0.0"
        assert event.grade_xml_path == "content/grade.xml"
        # Optional fields default to None
        assert event.error_message is None
        assert event.devices_json is None
        assert event.upstream_sync_status is None
        assert event.port_template is None


class TestSlugifyFqnIntegration:
    """Test slugify_fqn integration via CPA domain.utils re-export."""

    def test_basic_slugification(self):
        """Test that slugify_fqn works via CPA domain.utils."""
        result = slugify_fqn(FQN)
        assert result == FQN_SLUG

    def test_empty_raises(self):
        """Test empty FQN raises ValueError."""
        with pytest.raises(ValueError):
            slugify_fqn("")
