"""Tests for CMLWorker Aggregate."""

from datetime import datetime, timezone

from lcm_core.domain.entities.resource import ResourceState
from lcm_core.domain.entities.timed_resource import TimedResourceState
from lcm_core.domain.value_objects.managed_lifecycle import ManagedLifecycle
from lcm_core.domain.value_objects.state_transition import StateTransition

from domain.entities.cml_worker import CMLWorker, CMLWorkerState
from domain.enums import CMLWorkerStatus, LicenseStatus, WorkerOrigin
from domain.lifecycles import CML_WORKER_LIFECYCLE
from domain.value_objects.cml_license import CMLLicense
from domain.value_objects.cml_metrics import CMLMetrics, CMLSystemInfo


class TestCMLWorker:
    """Test CMLWorker aggregate."""

    def test_initialization(self):
        """Test worker initialization with default values."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="t3.medium")

        assert worker.state.name == "test-worker"
        assert worker.state.status == CMLWorkerStatus.PENDING
        assert isinstance(worker.state.metrics, CMLMetrics)
        assert isinstance(worker.state.license, CMLLicense)
        assert worker.state.metrics.labs_count == 0
        assert worker.state.license.status == LicenseStatus.UNREGISTERED

    def test_update_cml_metrics(self):
        """Test updating CML metrics."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="t3.medium")

        system_info = {"running_nodes": 5, "total_nodes": 10}
        system_health = {"valid": True}
        license_info = {"registration_status": "COMPLETED"}

        worker.update_cml_metrics(
            cml_version="2.7.0",
            system_info=system_info,
            system_health=system_health,
            license_info=license_info,
            ready=True,
            uptime_seconds=100,
            labs_count=2,
        )

        assert worker.state.metrics.version == "2.7.0"
        assert worker.state.metrics.ready is True
        assert worker.state.metrics.uptime_seconds == 100
        assert worker.state.metrics.labs_count == 2
        # system_info is converted to CMLSystemInfo object, so we compare dict representation
        assert worker.state.metrics.system_info.to_dict() == CMLSystemInfo(**system_info).to_dict()

        # Check license status update side-effect
        assert worker.state.license.status == LicenseStatus.REGISTERED

    def test_update_license(self):
        """Test updating license directly."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="t3.medium")

        worker.update_license(license_status=LicenseStatus.REGISTERED, license_token="token-123")

        assert worker.state.license.status == LicenseStatus.REGISTERED
        assert worker.state.license.token == "token-123"

    def test_is_idle_logic(self):
        """Test idle detection logic using new metrics structure."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="t3.medium")

        # No activity yet
        assert worker.is_idle(idle_threshold_minutes=30) is False

        # Update metrics with labs running
        worker.update_cml_metrics(
            cml_version="2.7.0",
            system_info={},
            system_health={},
            license_info={},
            ready=True,
            uptime_seconds=100,
            labs_count=1,  # Active labs
            synced_at=datetime.now(timezone.utc),
        )

        assert worker.is_idle(idle_threshold_minutes=30) is False

        # Update metrics with 0 labs, but recent sync
        worker.update_cml_metrics(
            cml_version="2.7.0",
            system_info={},
            system_health={},
            license_info={},
            ready=True,
            uptime_seconds=200,
            labs_count=0,  # No labs
            synced_at=datetime.now(timezone.utc),
        )

        assert worker.is_idle(idle_threshold_minutes=30) is False

        # Simulate old sync time (idle)
        # We need to manually set the state because update_cml_metrics uses current time if not provided,
        # or we can pass an old time.
        old_time = datetime.now(timezone.utc).replace(year=2020)

        # We can't easily inject old time via update_cml_metrics because it might filter out if no change?
        # But we can force it.
        worker.update_cml_metrics(
            cml_version="2.7.0",
            system_info={"changed": "yes"},  # Force change
            system_health={},
            license_info={},
            ready=True,
            uptime_seconds=300,
            labs_count=0,
            synced_at=old_time,
        )

        assert worker.is_idle(idle_threshold_minutes=30) is True


class TestCMLWorkerStateHistory:
    """Tests for CMLWorker state_history tracking (ADR-036 §2.1.4).

    Verifies that lifecycle transitions are recorded using the lcm_core
    StateTransition VO, stored as dicts for Neuroglia serialization.
    """

    # --- Creation ---

    def test_creation_records_initial_transition(self):
        """Creating a worker records None → PENDING transition."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="t3.medium")

        assert len(worker.state.state_history) == 1
        t = worker.state.state_history[0]
        assert t["from_state"] is None
        assert t["to_state"] == "pending"
        assert t["triggered_by"] == "system"
        assert t["reason"] == "Worker created"

    def test_creation_metadata_includes_origin_and_ami(self):
        """Creation transition metadata captures AMI identity for licensing audit."""
        worker = CMLWorker(
            name="personal-worker",
            aws_region="us-east-1",
            instance_type="m5zn.metal",
            ami_name="cml-personal-2.9",
            origin=WorkerOrigin.USER_CREATED,
        )

        t = worker.state.state_history[0]
        assert t["metadata"]["origin"] == "user_created"
        assert t["metadata"]["instance_type"] == "m5zn.metal"
        assert t["metadata"]["ami_name"] == "cml-personal-2.9"

    def test_creation_with_created_by(self):
        """created_by is recorded as triggered_by in the transition."""
        worker = CMLWorker(
            name="test",
            aws_region="us-east-1",
            instance_type="t3.medium",
            created_by="admin@example.com",
        )

        t = worker.state.state_history[0]
        assert t["triggered_by"] == "admin@example.com"

    def test_creation_with_no_created_by_defaults_to_system(self):
        """When created_by is None, triggered_by defaults to 'system'."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")

        t = worker.state.state_history[0]
        assert t["triggered_by"] == "system"

    # --- Import ---

    def test_import_records_transition_with_running_status(self):
        """Importing a running instance records None → running."""
        worker = CMLWorker.import_from_existing_instance(
            name="imported-running",
            aws_region="us-east-1",
            aws_instance_id="i-0123456789abcdef0",
            instance_type="m5zn.metal",
            ami_id="ami-enterprise-cml",
            instance_state="running",
        )

        assert len(worker.state.state_history) == 1
        t = worker.state.state_history[0]
        assert t["from_state"] is None
        assert t["to_state"] == "running"
        assert t["reason"] == "Worker imported from existing EC2 instance"

    def test_import_metadata_captures_ami_and_origin(self):
        """Import transition metadata records AMI identity and origin for audit."""
        worker = CMLWorker.import_from_existing_instance(
            name="imported",
            aws_region="us-west-2",
            aws_instance_id="i-abcdef1234567890",
            instance_type="m5zn.metal",
            ami_id="ami-personal-cml-29",
            ami_name="cml-personal-2.9-us-west-2",
            instance_state="stopped",
            origin=WorkerOrigin.EC2_DISCOVERY,
        )

        t = worker.state.state_history[0]
        assert t["to_state"] == "stopped"
        assert t["metadata"]["origin"] == "ec2_discovery"
        assert t["metadata"]["instance_state"] == "stopped"
        assert t["metadata"]["ami_id"] == "ami-personal-cml-29"
        assert t["metadata"]["ami_name"] == "cml-personal-2.9-us-west-2"

    def test_import_with_unknown_instance_state(self):
        """Importing with unrecognised EC2 state maps to 'unknown'."""
        worker = CMLWorker.import_from_existing_instance(
            name="imported-weird",
            aws_region="us-east-1",
            aws_instance_id="i-weird",
            instance_type="t3.medium",
            ami_id="ami-test",
            instance_state="shutting-down",
        )

        t = worker.state.state_history[0]
        assert t["to_state"] == "unknown"
        assert t["metadata"]["instance_state"] == "shutting-down"

    # --- Status updates ---

    def test_status_update_records_transition(self):
        """Updating status records old → new transition."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        worker.update_status(CMLWorkerStatus.RUNNING)

        assert len(worker.state.state_history) == 2
        t = worker.state.state_history[1]
        assert t["from_state"] == "pending"
        assert t["to_state"] == "running"
        assert t["triggered_by"] == "system"

    def test_same_status_does_not_record(self):
        """No-op update_status (same status) does not add to history."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        result = worker.update_status(CMLWorkerStatus.PENDING)  # Already PENDING

        assert result is False
        assert len(worker.state.state_history) == 1  # Only creation

    # --- Termination ---

    def test_terminate_records_transition(self):
        """Terminating records current → terminated with triggered_by."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        worker.update_status(CMLWorkerStatus.RUNNING)
        worker.terminate(terminated_by="admin@example.com")

        t = worker.state.state_history[-1]
        assert t["from_state"] == "running"
        assert t["to_state"] == "terminated"
        assert t["triggered_by"] == "admin@example.com"
        assert t["reason"] == "Worker terminated"

    def test_terminate_without_user_defaults_to_system(self):
        """Terminating without terminated_by defaults to 'system'."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        worker.terminate()

        t = worker.state.state_history[-1]
        assert t["triggered_by"] == "system"

    # --- Full lifecycle ---

    def test_full_lifecycle_tracking(self):
        """Full lifecycle: creation → running → stopping → stopped → terminated."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        worker.update_status(CMLWorkerStatus.RUNNING)
        worker.update_status(CMLWorkerStatus.STOPPING)
        worker.update_status(CMLWorkerStatus.STOPPED)
        worker.terminate(terminated_by="admin")

        assert len(worker.state.state_history) == 5
        transitions = [(t["from_state"], t["to_state"]) for t in worker.state.state_history]
        assert transitions == [
            (None, "pending"),
            ("pending", "running"),
            ("running", "stopping"),
            ("stopping", "stopped"),
            ("stopped", "terminated"),
        ]

    # --- Serialization ---

    def test_transitions_are_dicts(self):
        """All state_history entries are dicts (Neuroglia serialization compatible)."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        worker.update_status(CMLWorkerStatus.RUNNING)

        for entry in worker.state.state_history:
            assert isinstance(entry, dict)

    def test_transitions_roundtrip_via_state_transition_vo(self):
        """Stored dicts can be deserialized back to StateTransition VOs."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")

        t_dict = worker.state.state_history[0]
        t_vo = StateTransition.from_dict(t_dict)

        assert t_vo.from_state is None
        assert t_vo.to_state == "pending"
        assert t_vo.triggered_by == "system"
        assert isinstance(t_vo.transitioned_at, datetime)

    def test_transition_has_iso_timestamp(self):
        """Each transition has a transitioned_at ISO timestamp."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")

        t = worker.state.state_history[0]
        assert "transitioned_at" in t
        # Should be parseable as ISO-format datetime
        parsed = datetime.fromisoformat(t["transitioned_at"])
        assert parsed.tzinfo is not None  # Must be timezone-aware


class TestCMLWorkerTimedResource:
    """Tests for CMLWorker TimedResource integration (ADR-036 §2.1.4 Batch E).

    Verifies that CMLWorkerState extends TimedResourceState, inherits
    ResourceState fields, and correctly wires lifecycle/timestamps.
    """

    # --- Inheritance hierarchy ---

    def test_state_inherits_from_timed_resource_state(self):
        """CMLWorkerState is a proper subclass of TimedResourceState."""
        assert issubclass(CMLWorkerState, TimedResourceState)

    def test_state_inherits_from_resource_state(self):
        """CMLWorkerState is a proper subclass of ResourceState (transitive)."""
        assert issubclass(CMLWorkerState, ResourceState)

    def test_resource_type_is_cml_worker(self):
        """resource_type field from ResourceState is set to 'cml_worker'."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        assert worker.state.resource_type == "cml_worker"

    # --- TimedResourceState fields ---

    def test_has_timeslot_field(self):
        """CMLWorkerState has timeslot field from TimedResourceState."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        assert hasattr(worker.state, "timeslot")
        # Not set on creation (timeslot is optional, set by scheduler)
        assert worker.state.timeslot is None

    def test_has_lifecycle_field(self):
        """CMLWorkerState has lifecycle field from TimedResourceState."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        assert hasattr(worker.state, "lifecycle")
        # Set on creation via the event handler
        assert worker.state.lifecycle is not None

    def test_has_started_at_field(self):
        """CMLWorkerState has started_at field from TimedResourceState."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        assert hasattr(worker.state, "started_at")
        assert worker.state.started_at is not None

    def test_has_ended_at_field(self):
        """CMLWorkerState has ended_at field from TimedResourceState."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        assert hasattr(worker.state, "ended_at")
        assert worker.state.ended_at is None  # Not terminated yet

    def test_has_terminated_at_field(self):
        """CMLWorkerState has terminated_at field from TimedResourceState."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        assert hasattr(worker.state, "terminated_at")
        assert worker.state.terminated_at is None  # Not terminated yet

    def test_has_duration_seconds_field(self):
        """CMLWorkerState has duration_seconds field from TimedResourceState."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        assert hasattr(worker.state, "duration_seconds")
        assert worker.state.duration_seconds is None

    # --- ResourceState fields ---

    def test_has_status_from_resource_state(self):
        """CMLWorkerState has status field (shadows ResourceState str with enum)."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        assert hasattr(worker.state, "status")
        assert worker.state.status == CMLWorkerStatus.PENDING

    def test_has_desired_status_from_resource_state(self):
        """CMLWorkerState has desired_status field (shadows ResourceState)."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        assert hasattr(worker.state, "desired_status")
        assert worker.state.desired_status == CMLWorkerStatus.RUNNING

    def test_has_state_history_from_resource_state(self):
        """CMLWorkerState has state_history field (shadows ResourceState)."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        assert hasattr(worker.state, "state_history")
        assert isinstance(worker.state.state_history, list)
        assert len(worker.state.state_history) >= 1

    def test_has_pipeline_progress_from_resource_state(self):
        """CMLWorkerState has pipeline_progress field from ResourceState."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        assert hasattr(worker.state, "pipeline_progress")
        assert worker.state.pipeline_progress is None

    # --- Lifecycle assignment on creation ---

    def test_lifecycle_set_on_creation(self):
        """Lifecycle is assigned when worker is created."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")

        lifecycle = ManagedLifecycle.from_dict(worker.state.lifecycle)
        assert lifecycle is not None
        assert lifecycle.current_phase == "provision"

    def test_lifecycle_has_correct_phases(self):
        """Created worker lifecycle has all 8 expected phases in order."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")

        lifecycle = ManagedLifecycle.from_dict(worker.state.lifecycle)
        expected_phases = [
            "provision",
            "startup",
            "initial_metrics",
            "license_register",
            "monitor_resources",
            "drain",
            "teardown",
            "terminate",
        ]
        assert lifecycle.phase_names() == expected_phases

    def test_license_register_phase_is_optional(self):
        """license_register phase is marked as not required (optional)."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")

        lifecycle = ManagedLifecycle.from_dict(worker.state.lifecycle)
        phase = lifecycle.get_phase("license_register")
        assert phase is not None
        assert phase.is_required is False

    def test_all_other_phases_are_required(self):
        """All phases except license_register are required."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")

        lifecycle = ManagedLifecycle.from_dict(worker.state.lifecycle)
        for phase in lifecycle.phases:
            if phase.name == "license_register":
                continue
            assert phase.is_required is True, f"Phase {phase.name} should be required"

    # --- started_at set on creation ---

    def test_started_at_set_on_creation(self):
        """started_at is set to created_at when worker is created."""
        before = datetime.now(timezone.utc)
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        after = datetime.now(timezone.utc)

        assert worker.state.started_at is not None
        assert before <= worker.state.started_at <= after

    def test_started_at_matches_created_at(self):
        """started_at equals created_at for freshly created workers."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")

        assert worker.state.started_at == worker.state.created_at

    # --- Termination timestamps ---

    def test_terminated_at_set_on_termination(self):
        """terminated_at is set when worker is terminated."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        worker.terminate(terminated_by="admin@example.com")

        assert worker.state.terminated_at is not None

    def test_ended_at_set_on_termination(self):
        """ended_at (TimedResourceState) is set when worker is terminated."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        worker.terminate()

        assert worker.state.ended_at is not None
        assert worker.state.ended_at == worker.state.terminated_at

    def test_duration_computed_on_termination(self):
        """duration_seconds is computed from started_at to ended_at on termination."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        worker.terminate()

        assert worker.state.duration_seconds is not None
        assert worker.state.duration_seconds >= 0

    # --- Import lifecycle ---

    def test_imported_running_worker_lifecycle_at_monitor_resources(self):
        """Imported running worker sets lifecycle current_phase to monitor_resources."""
        worker = CMLWorker.import_from_existing_instance(
            name="imported",
            aws_region="us-east-1",
            aws_instance_id="i-abc123",
            instance_type="m5zn.metal",
            ami_id="ami-test",
            instance_state="running",
        )

        lifecycle = ManagedLifecycle.from_dict(worker.state.lifecycle)
        assert lifecycle.current_phase == "monitor_resources"

    def test_imported_stopped_worker_lifecycle_paused(self):
        """Imported stopped worker sets lifecycle current_phase to None (paused)."""
        worker = CMLWorker.import_from_existing_instance(
            name="imported",
            aws_region="us-east-1",
            aws_instance_id="i-abc123",
            instance_type="m5zn.metal",
            ami_id="ami-test",
            instance_state="stopped",
        )

        lifecycle = ManagedLifecycle.from_dict(worker.state.lifecycle)
        assert lifecycle.current_phase is None

    def test_imported_pending_worker_lifecycle_at_provision(self):
        """Imported pending worker sets lifecycle current_phase to provision."""
        worker = CMLWorker.import_from_existing_instance(
            name="imported",
            aws_region="us-east-1",
            aws_instance_id="i-abc123",
            instance_type="m5zn.metal",
            ami_id="ami-test",
            instance_state="pending",
        )

        lifecycle = ManagedLifecycle.from_dict(worker.state.lifecycle)
        assert lifecycle.current_phase == "provision"

    def test_imported_worker_has_started_at(self):
        """Imported workers also get started_at set."""
        worker = CMLWorker.import_from_existing_instance(
            name="imported",
            aws_region="us-east-1",
            aws_instance_id="i-abc123",
            instance_type="m5zn.metal",
            ami_id="ami-test",
            instance_state="running",
        )

        assert worker.state.started_at is not None

    def test_imported_worker_has_all_lifecycle_phases(self):
        """Imported workers have the same 8 lifecycle phases as created workers."""
        worker = CMLWorker.import_from_existing_instance(
            name="imported",
            aws_region="us-east-1",
            aws_instance_id="i-abc123",
            instance_type="m5zn.metal",
            ami_id="ami-test",
            instance_state="running",
        )

        lifecycle = ManagedLifecycle.from_dict(worker.state.lifecycle)
        assert len(lifecycle.phases) == 8

    # --- _record_transition updated_at behavior ---

    def test_record_transition_updates_updated_at(self):
        """_record_transition() now updates updated_at (ResourceState consistency)."""
        worker = CMLWorker(name="test", aws_region="us-east-1", instance_type="t3.medium")
        old_updated_at = worker.state.updated_at

        worker.update_status(CMLWorkerStatus.RUNNING)

        # updated_at should be at least as recent as the old value
        assert worker.state.updated_at >= old_updated_at


class TestCMLWorkerLifecycleConstant:
    """Tests for CML_WORKER_LIFECYCLE domain constant.

    Verifies the lifecycle definition matches the domain specification.
    """

    def test_lifecycle_is_managed_lifecycle(self):
        """CML_WORKER_LIFECYCLE is a ManagedLifecycle instance."""
        assert isinstance(CML_WORKER_LIFECYCLE, ManagedLifecycle)

    def test_lifecycle_has_8_phases(self):
        """CML_WORKER_LIFECYCLE has exactly 8 phases."""
        assert len(CML_WORKER_LIFECYCLE.phases) == 8

    def test_lifecycle_phase_order(self):
        """Phases are in the correct lifecycle order."""
        expected = [
            "provision",
            "startup",
            "initial_metrics",
            "license_register",
            "monitor_resources",
            "drain",
            "teardown",
            "terminate",
        ]
        assert CML_WORKER_LIFECYCLE.phase_names() == expected

    def test_all_phases_use_pipeline_engine(self):
        """All phases use the pipeline engine."""
        for phase in CML_WORKER_LIFECYCLE.phases:
            assert phase.engine == "pipeline", f"Phase {phase.name} should use pipeline engine"

    def test_trigger_on_status_values(self):
        """Each phase has the correct trigger_on_status."""
        expected_triggers = {
            "provision": "pending",
            "startup": "provisioning",
            "initial_metrics": "starting",
            "license_register": "starting",
            "monitor_resources": "running",
            "drain": "draining",
            "teardown": "stopping",
            "terminate": "terminating",
        }
        for phase in CML_WORKER_LIFECYCLE.phases:
            assert phase.trigger_on_status == expected_triggers[phase.name], f"Phase {phase.name}: expected trigger_on_status={expected_triggers[phase.name]}, got {phase.trigger_on_status}"

    def test_only_license_register_is_optional(self):
        """Only license_register phase is optional; all others are required."""
        for phase in CML_WORKER_LIFECYCLE.phases:
            if phase.name == "license_register":
                assert phase.is_required is False
            else:
                assert phase.is_required is True, f"Phase {phase.name} should be required"

    def test_lifecycle_roundtrip_serialization(self):
        """Lifecycle survives to_dict() → from_dict() roundtrip."""
        d = CML_WORKER_LIFECYCLE.to_dict()
        restored = ManagedLifecycle.from_dict(d)

        assert restored.phase_names() == CML_WORKER_LIFECYCLE.phase_names()
        assert restored.current_phase == CML_WORKER_LIFECYCLE.current_phase

        for orig, rest in zip(CML_WORKER_LIFECYCLE.phases, restored.phases):
            assert orig.name == rest.name
            assert orig.engine == rest.engine
            assert orig.trigger_on_status == rest.trigger_on_status
            assert orig.is_required == rest.is_required

    def test_lifecycle_no_current_phase_initially(self):
        """CML_WORKER_LIFECYCLE constant has no current_phase (it's a template)."""
        assert CML_WORKER_LIFECYCLE.current_phase is None
