"""Tests for ADR-036 TimedResourceReadModel base class and read model inheritance.

Validates:
    - TimedResourceReadModel field defaults and instantiation
    - LabletSessionReadModel extends TimedResourceReadModel correctly
    - CMLWorkerReadModel extends TimedResourceReadModel correctly
    - from_dict backward compatibility for both children
    - isinstance relationships (child is instance of base)
    - Inherited field access through child instances
"""

from datetime import UTC, datetime, timedelta

from lcm_core.domain.entities.read_models.cml_worker_read_model import CMLLicenseReadModel, CMLWorkerReadModel
from lcm_core.domain.entities.read_models.lablet_session_read_model import LabletSessionReadModel
from lcm_core.domain.entities.read_models.timed_resource_read_model import TimedResourceReadModel

# =============================================================================
# TimedResourceReadModel — Base Class
# =============================================================================


class TestTimedResourceReadModelDefaults:
    """Field initialization and defaults for the base class."""

    def test_all_defaults_produce_valid_instance(self):
        """Base class can be instantiated with zero arguments."""
        rm = TimedResourceReadModel()
        assert rm.id == ""
        assert rm.resource_type == ""
        assert rm.status == ""
        assert rm.desired_status is None
        assert rm.owner_id == ""

    def test_timeslot_fields_default_none(self):
        """Timeslot fields default to None (not Timeslot VO — DTOs use flat fields)."""
        rm = TimedResourceReadModel()
        assert rm.timeslot_start is None
        assert rm.timeslot_end is None

    def test_lifecycle_fields_default_none(self):
        """Runtime lifecycle fields default to None."""
        rm = TimedResourceReadModel()
        assert rm.started_at is None
        assert rm.ended_at is None
        assert rm.duration_seconds is None
        assert rm.terminated_at is None

    def test_pipeline_progress_default_none(self):
        """Pipeline progress defaults to None."""
        rm = TimedResourceReadModel()
        assert rm.pipeline_progress is None

    def test_timestamps_default_none(self):
        """created_at and updated_at default to None (set by API response)."""
        rm = TimedResourceReadModel()
        assert rm.created_at is None
        assert rm.updated_at is None

    def test_keyword_construction(self):
        """All fields can be set via keyword arguments."""
        now = datetime.now(UTC)
        rm = TimedResourceReadModel(
            id="r-001",
            resource_type="cml_worker",
            status="running",
            desired_status="running",
            owner_id="user-1",
            timeslot_start=now,
            timeslot_end=now + timedelta(hours=2),
            started_at=now,
            ended_at=None,
            duration_seconds=3600.0,
            terminated_at=None,
            pipeline_progress={"step": "completed"},
            created_at=now,
            updated_at=now,
        )
        assert rm.id == "r-001"
        assert rm.resource_type == "cml_worker"
        assert rm.status == "running"
        assert rm.desired_status == "running"
        assert rm.owner_id == "user-1"
        assert rm.timeslot_start == now
        assert rm.duration_seconds == 3600.0
        assert rm.pipeline_progress == {"step": "completed"}

    def test_is_dataclass(self):
        """TimedResourceReadModel is a dataclass (mutable DTO, not frozen)."""
        import dataclasses

        assert dataclasses.is_dataclass(TimedResourceReadModel)

    def test_not_frozen(self):
        """Read models are mutable (not frozen) — fields can be updated after creation."""
        rm = TimedResourceReadModel(status="pending")
        rm.status = "running"
        assert rm.status == "running"


class TestTimedResourceReadModelFieldCount:
    """Ensure the base class has exactly the expected number of fields."""

    def test_field_count(self):
        """Base has 14 fields."""
        import dataclasses

        fields = dataclasses.fields(TimedResourceReadModel)
        assert len(fields) == 14, f"Expected 14 fields, got {len(fields)}: {[f.name for f in fields]}"

    def test_field_names(self):
        """Base has the expected field names in order."""
        import dataclasses

        field_names = [f.name for f in dataclasses.fields(TimedResourceReadModel)]
        expected = [
            "id",
            "resource_type",
            "status",
            "desired_status",
            "owner_id",
            "timeslot_start",
            "timeslot_end",
            "started_at",
            "ended_at",
            "duration_seconds",
            "terminated_at",
            "pipeline_progress",
            "created_at",
            "updated_at",
        ]
        assert field_names == expected


# =============================================================================
# LabletSessionReadModel — Inheritance
# =============================================================================


class TestLabletSessionInheritance:
    """LabletSessionReadModel extends TimedResourceReadModel correctly."""

    def test_is_subclass(self):
        """LabletSessionReadModel is a subclass of TimedResourceReadModel."""
        assert issubclass(LabletSessionReadModel, TimedResourceReadModel)

    def test_instance_of_base(self):
        """A LabletSessionReadModel instance is also a TimedResourceReadModel instance."""
        session = LabletSessionReadModel(id="s-001", name="lab1", status="pending")
        assert isinstance(session, TimedResourceReadModel)

    def test_inherited_field_access(self):
        """Inherited fields from base are accessible on the child."""
        now = datetime.now(UTC)
        session = LabletSessionReadModel(
            id="s-001",
            status="running",
            desired_status="running",
            timeslot_start=now,
            timeslot_end=now + timedelta(hours=2),
            pipeline_progress={"step": "lab_create", "status": "completed"},
            started_at=now,
            ended_at=None,
            name="lab1",
        )
        assert session.id == "s-001"
        assert session.status == "running"
        assert session.desired_status == "running"
        assert session.timeslot_start == now
        assert session.pipeline_progress["step"] == "lab_create"
        assert session.started_at == now
        assert session.ended_at is None

    def test_new_base_fields_accessible(self):
        """New fields from base (not in original LabletSession) are accessible."""
        session = LabletSessionReadModel(
            id="s-001",
            resource_type="lablet_session",
            owner_id="user-1",
            duration_seconds=7200.0,
            terminated_at=None,
        )
        assert session.resource_type == "lablet_session"
        assert session.owner_id == "user-1"
        assert session.duration_seconds == 7200.0
        assert session.terminated_at is None

    def test_child_specific_fields(self):
        """Child-specific fields (name, definition_id, worker_*) work correctly."""
        session = LabletSessionReadModel(
            id="s-001",
            name="test-lab",
            definition_id="def-001",
            worker_id="w-001",
            worker_ip="10.0.0.1",
            cml_lab_id="lab-abc",
        )
        assert session.name == "test-lab"
        assert session.definition_id == "def-001"
        assert session.worker_id == "w-001"
        assert session.worker_ip == "10.0.0.1"
        assert session.cml_lab_id == "lab-abc"

    def test_name_and_definition_id_have_defaults(self):
        """name and definition_id default to empty string (MRO compatibility)."""
        session = LabletSessionReadModel(id="s-001", status="pending")
        assert session.name == ""
        assert session.definition_id == ""


class TestLabletSessionFromDict:
    """LabletSessionReadModel.from_dict backward compatibility."""

    def test_minimal_dict(self):
        """from_dict with minimal data produces valid instance."""
        data = {"id": "s-001", "name": "lab1", "status": "pending"}
        session = LabletSessionReadModel.from_dict(data)
        assert session.id == "s-001"
        assert session.name == "lab1"
        assert session.status == "pending"
        assert session.desired_status is None

    def test_full_dict(self):
        """from_dict with all fields preserves every value."""
        now = datetime.now(UTC)
        data = {
            "id": "s-001",
            "name": "lab1",
            "definition_id": "def-001",
            "status": "running",
            "desired_status": "running",
            "worker_id": "w-001",
            "worker": {
                "ip_address": "10.0.0.1",
                "aws_region": "us-east-1",
                "cml_username": "admin",
                "cml_password": "secret",  # pragma: allowlist secret
            },
            "lab_record_id": "lr-001",
            "cml_lab_id": "lab-abc",
            "timeslot_start": now,
            "timeslot_end": now + timedelta(hours=2),
            "allocated_ports": {"ssh": 22, "http": 80},
            "pipeline_progress": {"phase": "running"},
            "started_at": now,
            "ended_at": None,
            "topology_yaml": "nodes:\n  - name: router1",
            "metadata": {"lab_type": "networking"},
            "user_session_id": "us-001",
            "grading_session_id": "gs-001",
            "score_report_id": "sr-001",
            "user_login_url": "https://lab.example.com",
        }
        session = LabletSessionReadModel.from_dict(data)
        assert session.id == "s-001"
        assert session.name == "lab1"
        assert session.definition_id == "def-001"
        assert session.status == "running"
        assert session.desired_status == "running"
        assert session.worker_id == "w-001"
        assert session.worker_ip == "10.0.0.1"
        assert session.worker_aws_region == "us-east-1"
        assert session.worker_cml_username == "admin"
        assert session.worker_cml_password == "secret"  # pragma: allowlist secret
        assert session.lab_record_id == "lr-001"
        assert session.cml_lab_id == "lab-abc"
        assert session.timeslot_start == now
        assert session.timeslot_end == now + timedelta(hours=2)
        assert session.allocated_ports == {"ssh": 22, "http": 80}
        assert session.pipeline_progress == {"phase": "running"}
        assert session.started_at == now
        assert session.ended_at is None
        assert session.topology_yaml.startswith("nodes:")
        assert session.metadata == {"lab_type": "networking"}
        assert session.user_session_id == "us-001"
        assert session.grading_session_id == "gs-001"
        assert session.score_report_id == "sr-001"
        assert session.user_login_url == "https://lab.example.com"

    def test_deprecated_lds_aliases_in_dict(self):
        """from_dict accepts deprecated lds_session_id/lds_login_url field names."""
        data = {
            "id": "s-001",
            "lds_session_id": "us-legacy",
            "lds_login_url": "https://legacy.example.com",
        }
        session = LabletSessionReadModel.from_dict(data)
        assert session.user_session_id == "us-legacy"
        assert session.user_login_url == "https://legacy.example.com"

    def test_from_dict_returns_correct_type(self):
        """from_dict returns LabletSessionReadModel, not base class."""
        data = {"id": "s-001", "status": "pending"}
        session = LabletSessionReadModel.from_dict(data)
        assert type(session) is LabletSessionReadModel
        assert isinstance(session, TimedResourceReadModel)

    def test_from_dict_instance_of_base(self):
        """Instance created via from_dict passes isinstance check for base."""
        session = LabletSessionReadModel.from_dict({"id": "s-001"})
        assert isinstance(session, TimedResourceReadModel)


class TestLabletSessionPostInit:
    """Deprecated alias mapping in __post_init__ still works after refactoring."""

    def test_lds_session_id_maps_to_user_session_id(self):
        """lds_session_id → user_session_id when user_session_id not set."""
        session = LabletSessionReadModel(lds_session_id="legacy-1")
        assert session.user_session_id == "legacy-1"

    def test_user_session_id_maps_to_lds_session_id(self):
        """user_session_id → lds_session_id for backward compat reads."""
        session = LabletSessionReadModel(user_session_id="new-1")
        assert session.lds_session_id == "new-1"

    def test_lds_login_url_maps_to_user_login_url(self):
        """lds_login_url → user_login_url when user_login_url not set."""
        session = LabletSessionReadModel(lds_login_url="https://legacy.com")
        assert session.user_login_url == "https://legacy.com"


# =============================================================================
# CMLWorkerReadModel — Inheritance
# =============================================================================


class TestCMLWorkerInheritance:
    """CMLWorkerReadModel extends TimedResourceReadModel correctly."""

    def test_is_subclass(self):
        """CMLWorkerReadModel is a subclass of TimedResourceReadModel."""
        assert issubclass(CMLWorkerReadModel, TimedResourceReadModel)

    def test_instance_of_base(self):
        """A CMLWorkerReadModel instance is also a TimedResourceReadModel instance."""
        worker = CMLWorkerReadModel(id="w-001", name="worker-1", status="running")
        assert isinstance(worker, TimedResourceReadModel)

    def test_inherited_field_access(self):
        """Inherited fields from base are accessible on the worker read model."""
        now = datetime.now(UTC)
        worker = CMLWorkerReadModel(
            id="w-001",
            status="running",
            desired_status="running",
            timeslot_start=now,
            timeslot_end=now + timedelta(hours=4),
            started_at=now,
            name="worker-1",
        )
        assert worker.id == "w-001"
        assert worker.status == "running"
        assert worker.desired_status == "running"
        assert worker.timeslot_start == now
        assert worker.started_at == now

    def test_new_base_fields_accessible(self):
        """New fields from base (resource_type, owner_id, etc.) are accessible."""
        worker = CMLWorkerReadModel(
            id="w-001",
            resource_type="cml_worker",
            owner_id="admin",
            duration_seconds=14400.0,
        )
        assert worker.resource_type == "cml_worker"
        assert worker.owner_id == "admin"
        assert worker.duration_seconds == 14400.0

    def test_child_specific_fields(self):
        """Worker-specific fields (ec2_instance_id, ip_address, license) work correctly."""
        worker = CMLWorkerReadModel(
            id="w-001",
            name="worker-1",
            status="running",
            ec2_instance_id="i-abc123",
            ip_address="10.0.0.5",
            aws_region="us-east-1",
            instance_type="m5zn.metal",
        )
        assert worker.ec2_instance_id == "i-abc123"
        assert worker.ip_address == "10.0.0.5"
        assert worker.aws_region == "us-east-1"
        assert worker.instance_type == "m5zn.metal"

    def test_name_has_default(self):
        """name defaults to empty string (MRO compatibility)."""
        worker = CMLWorkerReadModel(id="w-001", status="running")
        assert worker.name == ""

    def test_desired_status_inherited_as_optional(self):
        """desired_status is inherited from base as str | None with default None."""
        worker = CMLWorkerReadModel(id="w-001")
        assert worker.desired_status is None

    def test_license_default_factory(self):
        """license field has a default CMLLicenseReadModel instance."""
        worker = CMLWorkerReadModel(id="w-001")
        assert isinstance(worker.license, CMLLicenseReadModel)
        assert worker.license.status == "unregistered"


class TestCMLWorkerFromDict:
    """CMLWorkerReadModel.from_dict backward compatibility."""

    def test_minimal_dict(self):
        """from_dict with minimal data produces valid instance."""
        data = {"id": "w-001", "name": "worker-1", "status": "running"}
        worker = CMLWorkerReadModel.from_dict(data)
        assert worker.id == "w-001"
        assert worker.name == "worker-1"
        assert worker.status == "running"
        # from_dict defaults desired_status to "running"
        assert worker.desired_status == "running"

    def test_full_dict(self):
        """from_dict with all fields preserves every value."""
        data = {
            "id": "w-001",
            "name": "worker-1",
            "status": "running",
            "desired_status": "stopped",
            "ec2_instance_id": "i-abc123",
            "ip_address": "10.0.0.5",
            "template_id": "t-001",
            "template_name": "Default Worker",
            "instance_type": "m5zn.metal",
            "ami_name": "cml-ami-2024",
            "aws_region": "us-east-1",
            "cml_username": "admin",
            "cml_password": "secret",  # pragma: allowlist secret
            "metadata": {"env": "test"},
            "is_idle_detection_enabled": False,
            "refresh_requested_at": "2024-01-01T00:00:00Z",
            "allocated_port_count": 5,
            "available_port_count": 95,
            "port_utilization_pct": 5.0,
            "license": {"status": "registered", "token": "lic-123"},  # pragma: allowlist secret
        }
        worker = CMLWorkerReadModel.from_dict(data)
        assert worker.id == "w-001"
        assert worker.name == "worker-1"
        assert worker.status == "running"
        assert worker.desired_status == "stopped"
        assert worker.ec2_instance_id == "i-abc123"
        assert worker.ip_address == "10.0.0.5"
        assert worker.template_id == "t-001"
        assert worker.template_name == "Default Worker"
        assert worker.instance_type == "m5zn.metal"
        assert worker.ami_name == "cml-ami-2024"
        assert worker.aws_region == "us-east-1"
        assert worker.cml_username == "admin"
        assert worker.cml_password == "secret"  # pragma: allowlist secret
        assert worker.metadata == {"env": "test"}
        assert worker.is_idle_detection_enabled is False
        assert worker.refresh_requested_at == "2024-01-01T00:00:00Z"
        assert worker.allocated_port_count == 5
        assert worker.available_port_count == 95
        assert worker.port_utilization_pct == 5.0
        assert worker.license.status == "registered"
        assert worker.license.token == "lic-123"

    def test_ec2_instance_id_alias(self):
        """from_dict accepts aws_instance_id as alias for ec2_instance_id."""
        data = {"id": "w-001", "aws_instance_id": "i-legacy-123"}
        worker = CMLWorkerReadModel.from_dict(data)
        assert worker.ec2_instance_id == "i-legacy-123"

    def test_ip_address_aliases(self):
        """from_dict accepts public_ip and private_ip as fallbacks."""
        worker1 = CMLWorkerReadModel.from_dict({"id": "w-001", "public_ip": "1.2.3.4"})
        assert worker1.ip_address == "1.2.3.4"

        worker2 = CMLWorkerReadModel.from_dict({"id": "w-002", "private_ip": "10.0.0.1"})
        assert worker2.ip_address == "10.0.0.1"

    def test_from_dict_returns_correct_type(self):
        """from_dict returns CMLWorkerReadModel, not base class."""
        data = {"id": "w-001", "name": "w1", "status": "running"}
        worker = CMLWorkerReadModel.from_dict(data)
        assert type(worker) is CMLWorkerReadModel
        assert isinstance(worker, TimedResourceReadModel)

    def test_license_missing_creates_default(self):
        """from_dict with no license data creates default CMLLicenseReadModel."""
        worker = CMLWorkerReadModel.from_dict({"id": "w-001"})
        assert worker.license.status == "unregistered"
        assert worker.license.token is None


# =============================================================================
# Cross-Cutting: isinstance & Polymorphism
# =============================================================================


class TestPolymorphism:
    """Both children can be handled polymorphically as TimedResourceReadModel."""

    def test_heterogeneous_collection(self):
        """Sessions and workers can coexist in a list typed as TimedResourceReadModel."""
        resources: list[TimedResourceReadModel] = [
            LabletSessionReadModel(id="s-001", name="lab1", status="pending"),
            CMLWorkerReadModel(id="w-001", name="worker-1", status="running"),
            TimedResourceReadModel(id="r-001", status="generic"),
        ]
        assert len(resources) == 3
        assert all(isinstance(r, TimedResourceReadModel) for r in resources)

    def test_common_field_access_polymorphic(self):
        """Common base fields are accessible without downcasting."""
        resources: list[TimedResourceReadModel] = [
            LabletSessionReadModel(id="s-001", status="running"),
            CMLWorkerReadModel(id="w-001", status="stopped"),
        ]
        statuses = [r.status for r in resources]
        assert statuses == ["running", "stopped"]

        ids = [r.id for r in resources]
        assert ids == ["s-001", "w-001"]

    def test_timeslot_access_on_session(self):
        """Timeslot fields inherited from base work on session."""
        now = datetime.now(UTC)
        session = LabletSessionReadModel(
            id="s-001",
            timeslot_start=now,
            timeslot_end=now + timedelta(hours=2),
        )
        # Access as base type
        rm: TimedResourceReadModel = session
        assert rm.timeslot_start == now
        assert rm.timeslot_end == now + timedelta(hours=2)

    def test_timeslot_access_on_worker(self):
        """Timeslot fields inherited from base work on worker (even if not typically used)."""
        now = datetime.now(UTC)
        worker = CMLWorkerReadModel(
            id="w-001",
            timeslot_start=now,
            timeslot_end=now + timedelta(hours=8),
        )
        rm: TimedResourceReadModel = worker
        assert rm.timeslot_start == now
        assert rm.timeslot_end == now + timedelta(hours=8)


# =============================================================================
# Import Path Verification
# =============================================================================


class TestImportPaths:
    """Verify all import paths work correctly after refactoring."""

    def test_import_from_read_models_package(self):
        """TimedResourceReadModel is importable from the read_models package."""
        from lcm_core.domain.entities.read_models import TimedResourceReadModel as TRM

        assert TRM is TimedResourceReadModel

    def test_import_from_entities_package(self):
        """TimedResourceReadModel is importable from the entities package."""
        from lcm_core.domain.entities import TimedResourceReadModel as TRM

        assert TRM is TimedResourceReadModel

    def test_lablet_session_still_importable_from_entities(self):
        """LabletSessionReadModel import path unchanged after refactoring."""
        from lcm_core.domain.entities import LabletSessionReadModel as LS

        assert LS is LabletSessionReadModel

    def test_cml_worker_still_importable_from_entities(self):
        """CMLWorkerReadModel import path unchanged after refactoring."""
        from lcm_core.domain.entities import CMLWorkerReadModel as CW

        assert CW is CMLWorkerReadModel
