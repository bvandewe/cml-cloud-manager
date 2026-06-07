"""Unit tests for Job and PodDefinition aggregates."""

import pytest
from domain.entities.job import Job, JobStatus
from domain.entities.pod_definition import PodDefinition
from lcm_core.domain.enums import PodDefinitionStatus, PodType


class TestJobAggregate:
    """Tests for the Job AggregateRoot."""

    @pytest.mark.unit
    def test_create_job(self):
        """Creating a job sets state via domain event."""
        job = Job.create(
            scenario_name="lab_resolve",
            scenario_version="v1",
            input_data={"worker_id": "w-123"},
            callback_url="http://localhost/events",
            pod_definition_id="pd-456",
        )

        assert job.id() != ""
        assert job.state.scenario_name == "lab_resolve"
        assert job.state.scenario_version == "v1"
        assert job.state.input_data == {"worker_id": "w-123"}
        assert job.state.callback_url == "http://localhost/events"
        assert job.state.pod_definition_id == "pd-456"
        assert job.state.status == JobStatus.SUBMITTED
        assert job.state.created_at is not None

    @pytest.mark.unit
    def test_create_job_requires_scenario_name(self):
        """Creating a job without scenario_name raises ValueError."""
        with pytest.raises(ValueError, match="scenario_name cannot be empty"):
            Job.create(scenario_name="")

    @pytest.mark.unit
    def test_job_lifecycle(self):
        """Job transitions through its full lifecycle."""
        job = Job.create(scenario_name="lab_start", job_id="job-001")
        assert job.state.status == JobStatus.SUBMITTED

        job.start()
        assert job.state.status == JobStatus.RUNNING
        assert job.state.started_at is not None

        job.complete(output_data={"lab_id": "lab-xyz"})
        assert job.state.status == JobStatus.COMPLETED
        assert job.state.output_data == {"lab_id": "lab-xyz"}
        assert job.state.completed_at is not None

    @pytest.mark.unit
    def test_job_failure(self):
        """Job can transition to FAILED."""
        job = Job.create(scenario_name="lab_start", job_id="job-002")
        job.start()
        job.fail("Connection timeout")

        assert job.state.status == JobStatus.FAILED
        assert job.state.error == "Connection timeout"

    @pytest.mark.unit
    def test_job_cancellation(self):
        """Job can be cancelled."""
        job = Job.create(scenario_name="lab_start", job_id="job-003")
        job.cancel()

        assert job.state.status == JobStatus.CANCELLED
        assert job.state.completed_at is not None


class TestPodDefinitionAggregate:
    """Tests for the PodDefinition AggregateRoot."""

    @pytest.mark.unit
    def test_create_pod_definition(self):
        """Creating a PodDefinition sets state via domain event."""
        pod_def = PodDefinition.create(
            name="exam-ccnp-v1-lab-1.1",
            version="1.0.0",
            pod_type=PodType.CML_ON_AWS,
            source_uri="s3://lcm-content/exam-ccnp-v1-lab-1.1.zip",
        )

        assert pod_def.id() != ""
        assert pod_def.state.name == "exam-ccnp-v1-lab-1.1"
        assert pod_def.state.version == "1.0.0"
        assert pod_def.state.pod_type == PodType.CML_ON_AWS
        assert pod_def.state.source_uri == "s3://lcm-content/exam-ccnp-v1-lab-1.1.zip"
        assert pod_def.state.status == PodDefinitionStatus.DEFINED

    @pytest.mark.unit
    def test_create_requires_name(self):
        """Creating without name raises ValueError."""
        with pytest.raises(ValueError, match="name cannot be empty"):
            PodDefinition.create(name="", version="1.0", pod_type=PodType.CML_ON_AWS, source_uri="s3://x")

    @pytest.mark.unit
    def test_create_requires_source_uri(self):
        """Creating without source_uri raises ValueError."""
        with pytest.raises(ValueError, match="source_uri cannot be empty"):
            PodDefinition.create(name="test", version="1.0", pod_type=PodType.CML_ON_AWS, source_uri="")

    @pytest.mark.unit
    def test_pod_definition_sync_lifecycle(self):
        """PodDefinition transitions through sync lifecycle."""
        pod_def = PodDefinition.create(
            name="test-lab",
            version="2.0",
            pod_type=PodType.CML_ON_AWS,
            source_uri="s3://bucket/test.zip",
            definition_id="pd-001",
        )
        assert pod_def.state.status == PodDefinitionStatus.DEFINED

        pod_def.start_sync()
        assert pod_def.state.status == PodDefinitionStatus.SYNCHRONIZING

        pod_def.mark_ready(local_path="/tmp/pd-001", manifest={"pod_type": "CML_ON_AWS"})
        assert pod_def.state.status == PodDefinitionStatus.READY
        assert pod_def.state.local_path == "/tmp/pd-001"
        assert pod_def.state.manifest == {"pod_type": "CML_ON_AWS"}
        assert pod_def.state.synced_at is not None

    @pytest.mark.unit
    def test_pod_definition_expire(self):
        """PodDefinition can transition to EXPIRED."""
        pod_def = PodDefinition.create(name="test-lab", version="1.0", pod_type=PodType.CML_ON_AWS, source_uri="s3://x/y.zip")
        pod_def.start_sync()
        pod_def.mark_ready(local_path="/tmp/x", manifest={})
        pod_def.expire()

        assert pod_def.state.status == PodDefinitionStatus.EXPIRED

    @pytest.mark.unit
    def test_pod_definition_supersede(self):
        """PodDefinition can be superseded by a newer version."""
        pod_def = PodDefinition.create(name="test-lab", version="1.0", pod_type=PodType.CML_ON_AWS, source_uri="s3://x/y.zip")
        pod_def.supersede(superseded_by="pd-new-version")

        assert pod_def.state.status == PodDefinitionStatus.SUPERSEDED

    @pytest.mark.unit
    def test_pod_definition_state_has_pav1_field_defaults(self):
        """AD-CSI-004 / G-03: new PAv1 fields default to None on a fresh aggregate."""
        pod_def = PodDefinition.create(name="test-lab", version="1.0", pod_type=PodType.CML_ON_AWS, source_uri="s3://x/y.zip")
        for field in (
            "content_hash",
            "topology",
            "devices",
            "lifecycle_phases",
            "scenarios",
            "grading_rules",
            "reports",
            "restore_rules",
        ):
            assert getattr(pod_def.state, field) is None

    @pytest.mark.unit
    def test_mark_ready_with_empty_pav1_payload_keeps_defaults(self):
        """G-03: mark_ready() with no PAv1 payload leaves new fields as None."""
        pod_def = PodDefinition.create(name="test-lab", version="1.0", pod_type=PodType.CML_ON_AWS, source_uri="s3://x/y.zip")
        pod_def.start_sync()
        pod_def.mark_ready(local_path="/tmp/x", manifest={})

        assert pod_def.state.status == PodDefinitionStatus.READY
        for field in (
            "content_hash",
            "topology",
            "devices",
            "lifecycle_phases",
            "scenarios",
            "grading_rules",
            "reports",
            "restore_rules",
        ):
            assert getattr(pod_def.state, field) is None

    @pytest.mark.unit
    def test_mark_ready_with_full_pav1_payload_populates_state(self):
        """G-03: mark_ready() with full PAv1 payload writes all extracted fields."""
        pod_def = PodDefinition.create(name="test-lab", version="1.0", pod_type=PodType.CML_ON_AWS, source_uri="s3://x/y.zip")
        pod_def.start_sync()
        pod_def.mark_ready(
            local_path="/tmp/x",
            manifest={"format_version": "PAv1"},
            content_hash="sha256:abc",
            topology={"nodes": []},
            devices=[{"hostname": "r1"}],
            lifecycle_phases={"instantiate": {"steps": []}},
            scenarios={"lab_resolve@v1": {"name": "lab_resolve"}},
            grading_rules={"items": []},
            reports={"summary": {}},
            restore_rules={"snapshots": []},
        )

        assert pod_def.state.content_hash == "sha256:abc"
        assert pod_def.state.topology == {"nodes": []}
        assert pod_def.state.devices == [{"hostname": "r1"}]
        assert pod_def.state.lifecycle_phases == {"instantiate": {"steps": []}}
        assert pod_def.state.scenarios == {"lab_resolve@v1": {"name": "lab_resolve"}}
        assert pod_def.state.grading_rules == {"items": []}
        assert pod_def.state.reports == {"summary": {}}
        assert pod_def.state.restore_rules == {"snapshots": []}
