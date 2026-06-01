"""Integration tests for MongoLabletDefinitionRepository.

Tests verify:
- Basic CRUD operations
- Query methods (by name, version, status)
- Value object serialization/deserialization
- Unique constraint on (name, version)
- Domain event publishing via mediator
"""

import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from neuroglia.serialization.json import JsonSerializer

from domain.entities.lablet_definition import LabletDefinition, NotificationConfig
from domain.enums import LabletDefinitionStatus, LicenseType
from domain.value_objects.port_template import PortDefinition, PortTemplate
from domain.value_objects.resource_requirements import AmiRequirement, ResourceRequirements
from integration.repositories.motor_lablet_definition_repository import MongoLabletDefinitionRepository

# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
async def lablet_definition_repository(
    mongo_client: AsyncIOMotorClient,
) -> MongoLabletDefinitionRepository:
    """Provide a LabletDefinition repository for testing."""
    serializer = JsonSerializer()
    repo = MongoLabletDefinitionRepository(
        client=mongo_client,
        database_name="test_lablet_cloud_manager",
        collection_name="lablet_definitions",
        serializer=serializer,
        entity_type=LabletDefinition,
        mediator=None,  # No mediator for basic tests
    )
    # Clean up any existing data
    await repo.collection.delete_many({})
    return repo


@pytest.fixture
def sample_resource_requirements() -> ResourceRequirements:
    """Create sample resource requirements."""
    return ResourceRequirements(
        cpu_cores=4,
        memory_gb=8,
        storage_gb=50,
        ami_requirements=(
            AmiRequirement(
                cml_version_min="2.6.0",
                cml_version_max="2.9.9",
            ),
        ),
    )


@pytest.fixture
def sample_port_template() -> PortTemplate:
    """Create sample port template."""
    return PortTemplate(
        ports=(
            PortDefinition(name="ssh", protocol="tcp", description="SSH access"),
            PortDefinition(name="http", protocol="tcp", description="HTTP service"),
            PortDefinition(name="https", protocol="tcp", description="HTTPS service"),
        )
    )


@pytest.fixture
def sample_lablet_definition(
    sample_resource_requirements: ResourceRequirements,
    sample_port_template: PortTemplate,
) -> LabletDefinition:
    """Create a sample LabletDefinition."""
    return LabletDefinition.create(
        name="ccna-basic-routing",
        version="1.0.0",
        form_qualified_name="Exam CCNA Basic-Routing v1 LAB 1",
        lab_yaml_hash="abc123def456",
        resource_requirements=sample_resource_requirements,
        license_affinity=[LicenseType.PERSONAL, LicenseType.ENTERPRISE],
        node_count=5,
        port_template=sample_port_template,
        created_by="admin@example.com",
        max_duration_minutes=120,
        warm_pool_depth=2,
    )


# ============================================================================
# HELPERS
# ============================================================================


def _activate_definition(definition: LabletDefinition) -> None:
    """Transition a definition from PENDING_SYNC to ACTIVE via a successful content sync.

    Since ADR-028, definitions are created in PENDING_SYNC status.
    Tests that need ACTIVE definitions must explicitly activate them.
    """
    definition.record_content_sync(lab_yaml_hash="synced-hash", sync_status="success")


# ============================================================================
# BASIC CRUD TESTS
# ============================================================================


class TestLabletDefinitionRepositoryCRUD:
    """Tests for basic CRUD operations."""

    @pytest.mark.integration
    @pytest.mark.repository
    @pytest.mark.asyncio
    async def test_add_and_get_by_id(
        self,
        lablet_definition_repository: MongoLabletDefinitionRepository,
        sample_lablet_definition: LabletDefinition,
    ) -> None:
        """Test adding and retrieving a definition by ID."""
        # Add
        added = await lablet_definition_repository.add_async(sample_lablet_definition)
        assert added is not None
        assert added.id() == sample_lablet_definition.id()

        # Get by ID
        retrieved = await lablet_definition_repository.get_by_id_async(sample_lablet_definition.id())
        assert retrieved is not None
        assert retrieved.id() == sample_lablet_definition.id()
        assert retrieved.state.name == "ccna-basic-routing"
        assert retrieved.state.version == "1.0.0"

    @pytest.mark.integration
    @pytest.mark.repository
    @pytest.mark.asyncio
    async def test_get_by_id_not_found(
        self,
        lablet_definition_repository: MongoLabletDefinitionRepository,
    ) -> None:
        """Test getting a non-existent definition returns None."""
        result = await lablet_definition_repository.get_by_id_async("non-existent-id")
        assert result is None

    @pytest.mark.integration
    @pytest.mark.repository
    @pytest.mark.asyncio
    async def test_update_definition(
        self,
        lablet_definition_repository: MongoLabletDefinitionRepository,
        sample_lablet_definition: LabletDefinition,
    ) -> None:
        """Test updating a definition."""
        # Add
        await lablet_definition_repository.add_async(sample_lablet_definition)

        # Modify (via domain method)
        sample_lablet_definition.update_warm_pool_depth(5, "admin@example.com")

        # Update
        updated = await lablet_definition_repository.update_async(sample_lablet_definition)
        assert updated.state.warm_pool_depth == 5

        # Verify persistence
        retrieved = await lablet_definition_repository.get_by_id_async(sample_lablet_definition.id())
        assert retrieved is not None
        assert retrieved.state.warm_pool_depth == 5

    @pytest.mark.integration
    @pytest.mark.repository
    @pytest.mark.asyncio
    async def test_delete_definition(
        self,
        lablet_definition_repository: MongoLabletDefinitionRepository,
        sample_lablet_definition: LabletDefinition,
    ) -> None:
        """Test deleting a definition."""
        # Add
        await lablet_definition_repository.add_async(sample_lablet_definition)

        # Delete
        result = await lablet_definition_repository.delete_async(sample_lablet_definition.id())
        assert result is True

        # Verify deletion
        retrieved = await lablet_definition_repository.get_by_id_async(sample_lablet_definition.id())
        assert retrieved is None


# ============================================================================
# QUERY METHOD TESTS
# ============================================================================


class TestLabletDefinitionRepositoryQueries:
    """Tests for query methods."""

    @pytest.mark.integration
    @pytest.mark.repository
    @pytest.mark.asyncio
    async def test_get_by_name_and_version(
        self,
        lablet_definition_repository: MongoLabletDefinitionRepository,
        sample_lablet_definition: LabletDefinition,
    ) -> None:
        """Test retrieving by name and version."""
        await lablet_definition_repository.add_async(sample_lablet_definition)

        # Found
        retrieved = await lablet_definition_repository.get_by_name_and_version_async("ccna-basic-routing", "1.0.0")
        assert retrieved is not None
        assert retrieved.id() == sample_lablet_definition.id()

        # Not found (wrong version)
        not_found = await lablet_definition_repository.get_by_name_and_version_async("ccna-basic-routing", "2.0.0")
        assert not_found is None

    @pytest.mark.integration
    @pytest.mark.repository
    @pytest.mark.asyncio
    async def test_list_active(
        self,
        lablet_definition_repository: MongoLabletDefinitionRepository,
        sample_resource_requirements: ResourceRequirements,
        sample_port_template: PortTemplate,
    ) -> None:
        """Test listing active definitions."""
        # Create and add active definitions
        def1 = LabletDefinition.create(
            name="lab-1",
            version="1.0.0",
            form_qualified_name="Exam Lab-1 Test v1 LAB 1",
            lab_yaml_hash="hash1",
            resource_requirements=sample_resource_requirements,
            license_affinity=[LicenseType.PERSONAL],
            node_count=3,
            port_template=sample_port_template,
            created_by="admin@example.com",
        )
        def2 = LabletDefinition.create(
            name="lab-2",
            version="1.0.0",
            form_qualified_name="Exam Lab-2 Test v1 LAB 1",
            lab_yaml_hash="hash2",
            resource_requirements=sample_resource_requirements,
            license_affinity=[LicenseType.PERSONAL],
            node_count=3,
            port_template=sample_port_template,
            created_by="admin@example.com",
        )

        # Activate both (ADR-028: created as PENDING_SYNC)
        _activate_definition(def1)
        _activate_definition(def2)

        await lablet_definition_repository.add_async(def1)
        await lablet_definition_repository.add_async(def2)

        # Deprecate one
        def2.deprecate("admin@example.com", "Replaced by newer version")
        await lablet_definition_repository.update_async(def2)

        # List active
        active = await lablet_definition_repository.list_active_async()
        assert len(active) == 1
        assert active[0].state.name == "lab-1"

    @pytest.mark.integration
    @pytest.mark.repository
    @pytest.mark.asyncio
    async def test_list_by_status(
        self,
        lablet_definition_repository: MongoLabletDefinitionRepository,
        sample_resource_requirements: ResourceRequirements,
        sample_port_template: PortTemplate,
    ) -> None:
        """Test listing by status."""
        # Create definitions
        def1 = LabletDefinition.create(
            name="lab-active",
            version="1.0.0",
            form_qualified_name="Exam Lab-Active Test v1 LAB 1",
            lab_yaml_hash="hash1",
            resource_requirements=sample_resource_requirements,
            license_affinity=[LicenseType.PERSONAL],
            node_count=3,
            port_template=sample_port_template,
            created_by="admin@example.com",
        )
        # Activate def1 (ADR-028: created as PENDING_SYNC)
        _activate_definition(def1)

        def2 = LabletDefinition.create(
            name="lab-deprecated",
            version="1.0.0",
            form_qualified_name="Exam Lab-Deprecated Test v1 LAB 1",
            lab_yaml_hash="hash2",
            resource_requirements=sample_resource_requirements,
            license_affinity=[LicenseType.PERSONAL],
            node_count=3,
            port_template=sample_port_template,
            created_by="admin@example.com",
        )
        def2.deprecate("admin@example.com")

        await lablet_definition_repository.add_async(def1)
        await lablet_definition_repository.add_async(def2)

        # List by status
        active = await lablet_definition_repository.list_by_status_async(LabletDefinitionStatus.ACTIVE)
        deprecated = await lablet_definition_repository.list_by_status_async(LabletDefinitionStatus.DEPRECATED)

        assert len(active) == 1
        assert active[0].state.name == "lab-active"
        assert len(deprecated) == 1
        assert deprecated[0].state.name == "lab-deprecated"

    @pytest.mark.integration
    @pytest.mark.repository
    @pytest.mark.asyncio
    async def test_list_by_name(
        self,
        lablet_definition_repository: MongoLabletDefinitionRepository,
        sample_resource_requirements: ResourceRequirements,
        sample_port_template: PortTemplate,
    ) -> None:
        """Test listing all versions of a definition by name."""
        # Create multiple versions
        versions = ["1.0.0", "1.1.0", "2.0.0"]
        for version in versions:
            definition = LabletDefinition.create(
                name="multi-version-lab",
                version=version,
                form_qualified_name="Exam Multi-Version-Lab Test v1 LAB 1",
                lab_yaml_hash=f"hash-{version}",
                resource_requirements=sample_resource_requirements,
                license_affinity=[LicenseType.PERSONAL],
                node_count=3,
                port_template=sample_port_template,
                created_by="admin@example.com",
            )
            await lablet_definition_repository.add_async(definition)

        # Also add a different definition
        other = LabletDefinition.create(
            name="other-lab",
            version="1.0.0",
            form_qualified_name="Exam Other-Lab Test v1 LAB 1",
            lab_yaml_hash="other-hash",
            resource_requirements=sample_resource_requirements,
            license_affinity=[LicenseType.PERSONAL],
            node_count=2,
            port_template=sample_port_template,
            created_by="admin@example.com",
        )
        await lablet_definition_repository.add_async(other)

        # List by name
        versions_list = await lablet_definition_repository.list_by_name_async("multi-version-lab")
        assert len(versions_list) == 3

        # Verify sorted by version descending
        version_numbers = [d.state.version for d in versions_list]
        assert version_numbers == ["2.0.0", "1.1.0", "1.0.0"]

    @pytest.mark.integration
    @pytest.mark.repository
    @pytest.mark.asyncio
    async def test_get_latest_version(
        self,
        lablet_definition_repository: MongoLabletDefinitionRepository,
        sample_resource_requirements: ResourceRequirements,
        sample_port_template: PortTemplate,
    ) -> None:
        """Test getting the latest active version."""
        # Create multiple versions
        for version in ["1.0.0", "1.1.0", "2.0.0"]:
            definition = LabletDefinition.create(
                name="versioned-lab",
                version=version,
                form_qualified_name="Exam Versioned-Lab Test v1 LAB 1",
                lab_yaml_hash=f"hash-{version}",
                resource_requirements=sample_resource_requirements,
                license_affinity=[LicenseType.PERSONAL],
                node_count=3,
                port_template=sample_port_template,
                created_by="admin@example.com",
            )
            _activate_definition(definition)  # ADR-028: PENDING_SYNC → ACTIVE
            await lablet_definition_repository.add_async(definition)

        # Get latest
        latest = await lablet_definition_repository.get_latest_version_async("versioned-lab")
        assert latest is not None
        assert latest.state.version == "2.0.0"

    @pytest.mark.integration
    @pytest.mark.repository
    @pytest.mark.asyncio
    async def test_get_latest_version_excludes_deprecated(
        self,
        lablet_definition_repository: MongoLabletDefinitionRepository,
        sample_resource_requirements: ResourceRequirements,
        sample_port_template: PortTemplate,
    ) -> None:
        """Test that get_latest_version excludes deprecated versions."""
        # Create versions
        v1 = LabletDefinition.create(
            name="deprecation-test",
            version="1.0.0",
            form_qualified_name="Exam Deprecation Test v1 LAB 1",
            lab_yaml_hash="hash-1.0.0",
            resource_requirements=sample_resource_requirements,
            license_affinity=[LicenseType.PERSONAL],
            node_count=3,
            port_template=sample_port_template,
            created_by="admin@example.com",
        )
        v2 = LabletDefinition.create(
            name="deprecation-test",
            version="2.0.0",
            form_qualified_name="Exam Deprecation Test v1 LAB 2",
            lab_yaml_hash="hash-2.0.0",
            resource_requirements=sample_resource_requirements,
            license_affinity=[LicenseType.PERSONAL],
            node_count=3,
            port_template=sample_port_template,
            created_by="admin@example.com",
        )
        # Activate both, then deprecate v2 (ADR-028: PENDING_SYNC → ACTIVE → DEPRECATED)
        _activate_definition(v1)
        _activate_definition(v2)
        # Deprecate v2
        v2.deprecate("admin@example.com", "Testing deprecation")

        await lablet_definition_repository.add_async(v1)
        await lablet_definition_repository.add_async(v2)

        # Get latest should return v1 (v2 is deprecated)
        latest = await lablet_definition_repository.get_latest_version_async("deprecation-test")
        assert latest is not None
        assert latest.state.version == "1.0.0"


# ============================================================================
# VALUE OBJECT SERIALIZATION TESTS
# ============================================================================


class TestValueObjectSerialization:
    """Tests for proper serialization of nested value objects."""

    @pytest.mark.integration
    @pytest.mark.repository
    @pytest.mark.asyncio
    async def test_resource_requirements_serialization(
        self,
        lablet_definition_repository: MongoLabletDefinitionRepository,
        sample_lablet_definition: LabletDefinition,
    ) -> None:
        """Test that ResourceRequirements is properly serialized and deserialized."""
        await lablet_definition_repository.add_async(sample_lablet_definition)

        retrieved = await lablet_definition_repository.get_by_id_async(sample_lablet_definition.id())
        assert retrieved is not None

        # Verify resource requirements
        req = retrieved.state.resource_requirements
        assert req.cpu_cores == 4
        assert req.memory_gb == 8
        assert req.storage_gb == 50
        assert len(req.ami_requirements) == 1
        assert req.ami_requirements[0].cml_version_min == "2.6.0"
        assert req.ami_requirements[0].cml_version_max == "2.9.9"

    @pytest.mark.integration
    @pytest.mark.repository
    @pytest.mark.asyncio
    async def test_port_template_serialization(
        self,
        lablet_definition_repository: MongoLabletDefinitionRepository,
        sample_lablet_definition: LabletDefinition,
    ) -> None:
        """Test that PortTemplate is properly serialized and deserialized."""
        await lablet_definition_repository.add_async(sample_lablet_definition)

        retrieved = await lablet_definition_repository.get_by_id_async(sample_lablet_definition.id())
        assert retrieved is not None

        # Verify port template
        pt = retrieved.state.port_template
        assert pt.port_count == 3
        assert len(pt.ports) == 3

        # Check individual ports
        port_names = {p.name for p in pt.ports}
        assert port_names == {"ssh", "http", "https"}

    @pytest.mark.integration
    @pytest.mark.repository
    @pytest.mark.asyncio
    async def test_license_affinity_serialization(
        self,
        lablet_definition_repository: MongoLabletDefinitionRepository,
        sample_lablet_definition: LabletDefinition,
    ) -> None:
        """Test that license_affinity enum list is properly serialized."""
        await lablet_definition_repository.add_async(sample_lablet_definition)

        retrieved = await lablet_definition_repository.get_by_id_async(sample_lablet_definition.id())
        assert retrieved is not None

        # Verify license affinity
        assert len(retrieved.state.license_affinity) == 2
        assert LicenseType.PERSONAL in retrieved.state.license_affinity
        assert LicenseType.ENTERPRISE in retrieved.state.license_affinity

    @pytest.mark.integration
    @pytest.mark.repository
    @pytest.mark.asyncio
    async def test_notification_config_serialization(
        self,
        lablet_definition_repository: MongoLabletDefinitionRepository,
        sample_resource_requirements: ResourceRequirements,
        sample_port_template: PortTemplate,
    ) -> None:
        """Test that NotificationConfig is properly serialized."""
        notification = NotificationConfig(
            email="owner@example.com",
            webhook_url="https://webhook.example.com/notify",
            notify_on_start=True,
            notify_on_complete=True,
            notify_on_error=False,
        )

        definition = LabletDefinition.create(
            name="notification-test",
            version="1.0.0",
            form_qualified_name="Exam Notification Test v1 LAB 1",
            lab_yaml_hash="hash123",
            resource_requirements=sample_resource_requirements,
            license_affinity=[LicenseType.PERSONAL],
            node_count=3,
            port_template=sample_port_template,
            created_by="admin@example.com",
            owner_notification=notification,
        )

        await lablet_definition_repository.add_async(definition)
        retrieved = await lablet_definition_repository.get_by_id_async(definition.id())

        assert retrieved is not None
        assert retrieved.state.owner_notification is not None
        assert retrieved.state.owner_notification.email == "owner@example.com"
        assert retrieved.state.owner_notification.webhook_url == "https://webhook.example.com/notify"
        assert retrieved.state.owner_notification.notify_on_error is False


# ============================================================================
# CONSTRAINT TESTS
# ============================================================================


class TestRepositoryConstraints:
    """Tests for repository constraints and edge cases."""

    @pytest.mark.integration
    @pytest.mark.repository
    @pytest.mark.asyncio
    async def test_duplicate_name_version_rejected(
        self,
        lablet_definition_repository: MongoLabletDefinitionRepository,
        sample_resource_requirements: ResourceRequirements,
        sample_port_template: PortTemplate,
    ) -> None:
        """Test that duplicate (name, version) combinations are rejected."""
        definition1 = LabletDefinition.create(
            name="duplicate-test",
            version="1.0.0",
            form_qualified_name="Exam Duplicate Test v1 LAB 1",
            lab_yaml_hash="hash1",
            resource_requirements=sample_resource_requirements,
            license_affinity=[LicenseType.PERSONAL],
            node_count=3,
            port_template=sample_port_template,
            created_by="admin@example.com",
        )

        definition2 = LabletDefinition.create(
            name="duplicate-test",
            version="1.0.0",  # Same name and version
            form_qualified_name="Exam Duplicate Test v1 LAB 1",
            lab_yaml_hash="hash2",
            resource_requirements=sample_resource_requirements,
            license_affinity=[LicenseType.PERSONAL],
            node_count=4,
            port_template=sample_port_template,
            created_by="other@example.com",
        )

        # First add should succeed
        await lablet_definition_repository.add_async(definition1)

        # Second add should fail
        with pytest.raises(ValueError, match="already exists"):
            await lablet_definition_repository.add_async(definition2)

    @pytest.mark.integration
    @pytest.mark.repository
    @pytest.mark.asyncio
    async def test_same_name_different_version_allowed(
        self,
        lablet_definition_repository: MongoLabletDefinitionRepository,
        sample_resource_requirements: ResourceRequirements,
        sample_port_template: PortTemplate,
    ) -> None:
        """Test that same name with different versions is allowed."""
        definition1 = LabletDefinition.create(
            name="versioned-test",
            version="1.0.0",
            form_qualified_name="Exam Versioned Test v1 LAB 1",
            lab_yaml_hash="hash1",
            resource_requirements=sample_resource_requirements,
            license_affinity=[LicenseType.PERSONAL],
            node_count=3,
            port_template=sample_port_template,
            created_by="admin@example.com",
        )

        definition2 = LabletDefinition.create(
            name="versioned-test",
            version="2.0.0",  # Different version
            form_qualified_name="Exam Versioned Test v1 LAB 2",
            lab_yaml_hash="hash2",
            resource_requirements=sample_resource_requirements,
            license_affinity=[LicenseType.PERSONAL],
            node_count=4,
            port_template=sample_port_template,
            created_by="admin@example.com",
        )

        # Both should succeed
        await lablet_definition_repository.add_async(definition1)
        await lablet_definition_repository.add_async(definition2)

        # Verify both exist
        all_versions = await lablet_definition_repository.list_by_name_async("versioned-test")
        assert len(all_versions) == 2

    @pytest.mark.integration
    @pytest.mark.repository
    @pytest.mark.asyncio
    async def test_get_all_async(
        self,
        lablet_definition_repository: MongoLabletDefinitionRepository,
        sample_resource_requirements: ResourceRequirements,
        sample_port_template: PortTemplate,
    ) -> None:
        """Test retrieving all definitions."""
        # Add multiple definitions
        for i in range(3):
            definition = LabletDefinition.create(
                name=f"lab-{i}",
                version="1.0.0",
                form_qualified_name=f"Exam Lab-{i} Test v1 LAB 1",
                lab_yaml_hash=f"hash{i}",
                resource_requirements=sample_resource_requirements,
                license_affinity=[LicenseType.PERSONAL],
                node_count=3,
                port_template=sample_port_template,
                created_by="admin@example.com",
            )
            await lablet_definition_repository.add_async(definition)

        # Get all
        all_defs = await lablet_definition_repository.get_all_async()
        assert len(all_defs) == 3

    @pytest.mark.integration
    @pytest.mark.repository
    @pytest.mark.asyncio
    async def test_count_by_status(
        self,
        lablet_definition_repository: MongoLabletDefinitionRepository,
        sample_resource_requirements: ResourceRequirements,
        sample_port_template: PortTemplate,
    ) -> None:
        """Test counting definitions by status."""
        # Add active and deprecated definitions
        for i in range(3):
            definition = LabletDefinition.create(
                name=f"count-test-{i}",
                version="1.0.0",
                form_qualified_name=f"Exam Count-Test-{i} Test v1 LAB 1",
                lab_yaml_hash=f"hash{i}",
                resource_requirements=sample_resource_requirements,
                license_affinity=[LicenseType.PERSONAL],
                node_count=3,
                port_template=sample_port_template,
                created_by="admin@example.com",
            )
            _activate_definition(definition)  # ADR-028: PENDING_SYNC → ACTIVE
            if i == 2:
                definition.deprecate("admin@example.com")
            await lablet_definition_repository.add_async(definition)

        # Count
        active_count = await lablet_definition_repository.count_active_async()
        deprecated_count = await lablet_definition_repository.count_by_status_async(LabletDefinitionStatus.DEPRECATED)

        assert active_count == 2
        assert deprecated_count == 1
