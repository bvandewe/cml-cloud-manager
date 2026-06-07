"""Unit tests for CQRS command handlers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from application.commands.cancel_job_command import CancelJobCommand, CancelJobCommandHandler
from application.commands.submit_job_command import SubmitJobCommand, SubmitJobCommandHandler
from application.commands.sync_content_command import SyncContentCommand, SyncContentCommandHandler
from application.services.job_execution_service import JobExecutionService
from domain.entities.job import Job, JobStatus
from domain.entities.pod_definition import PodDefinition
from lcm_core.domain.enums import PodDefinitionStatus, PodType

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_job_repository():
    repo = AsyncMock()
    repo.get_by_id_async = AsyncMock(return_value=None)
    repo.add_async = AsyncMock()
    repo.update_async = AsyncMock()
    return repo


@pytest.fixture
def mock_execution_service():
    service = MagicMock(spec=JobExecutionService)
    service.enqueue_job = MagicMock()
    service.request_cancel = MagicMock()
    return service


@pytest.fixture
def mock_pod_definition_repository():
    repo = AsyncMock()
    repo.get_by_id_async = AsyncMock(return_value=None)
    repo.add_async = AsyncMock()
    repo.update_async = AsyncMock()
    return repo


@pytest.fixture
def fake_registry():
    """A registry dict with one scenario registered."""
    return {
        "hello-world@v1": {
            "name": "hello-world",
            "version": "v1",
            "description": "Hello World scenario",
            "input_schema": {},
            "output_schema": {},
        }
    }


# =============================================================================
# SubmitJobCommandHandler
# =============================================================================


class TestSubmitJobCommandHandler:
    """Tests for SubmitJobCommandHandler."""

    @pytest.mark.unit
    async def test_submit_job_happy_path(self, mock_job_repository, mock_execution_service, fake_registry):
        handler = SubmitJobCommandHandler(job_repository=mock_job_repository, job_execution_service=mock_execution_service)
        command = SubmitJobCommand(scenario_name="hello-world", scenario_version="v1")

        with patch("application.commands.submit_job_command.get_all_scenarios", return_value=fake_registry):
            result = await handler.handle_async(command)

        assert result.is_success
        assert result.status_code == 202
        assert result.data.status == "submitted"
        assert result.data.id != ""
        mock_job_repository.add_async.assert_called_once()
        mock_execution_service.enqueue_job.assert_called_once()

    @pytest.mark.unit
    async def test_submit_job_with_input_data(self, mock_job_repository, mock_execution_service, fake_registry):
        handler = SubmitJobCommandHandler(job_repository=mock_job_repository, job_execution_service=mock_execution_service)
        command = SubmitJobCommand(
            scenario_name="hello-world",
            scenario_version="v1",
            input_data={"worker_id": "w-123"},
            callback_url="http://localhost/events",
            pod_definition_id="pd-456",
        )

        with patch("application.commands.submit_job_command.get_all_scenarios", return_value=fake_registry):
            result = await handler.handle_async(command)

        assert result.is_success
        assert result.status_code == 202
        mock_job_repository.add_async.assert_called_once()
        mock_execution_service.enqueue_job.assert_called_once()

    @pytest.mark.unit
    async def test_submit_job_missing_scenario_name(self, mock_job_repository, mock_execution_service):
        handler = SubmitJobCommandHandler(job_repository=mock_job_repository, job_execution_service=mock_execution_service)
        command = SubmitJobCommand(scenario_name="")

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400
        mock_job_repository.add_async.assert_not_called()

    @pytest.mark.unit
    async def test_submit_job_scenario_not_found(self, mock_job_repository, mock_execution_service, fake_registry):
        handler = SubmitJobCommandHandler(job_repository=mock_job_repository, job_execution_service=mock_execution_service)
        command = SubmitJobCommand(scenario_name="nonexistent", scenario_version="v1")

        with patch("application.commands.submit_job_command.get_all_scenarios", return_value=fake_registry):
            result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400
        mock_job_repository.add_async.assert_not_called()


# =============================================================================
# CancelJobCommandHandler
# =============================================================================


class TestCancelJobCommandHandler:
    """Tests for CancelJobCommandHandler."""

    @pytest.mark.unit
    async def test_cancel_job_happy_path(self, mock_job_repository, mock_execution_service):
        # Create a SUBMITTED job
        job = Job.create(scenario_name="hello-world", scenario_version="v1")
        mock_job_repository.get_by_id_async = AsyncMock(return_value=job)

        handler = CancelJobCommandHandler(job_repository=mock_job_repository, job_execution_service=mock_execution_service)
        command = CancelJobCommand(job_id=job.id())

        result = await handler.handle_async(command)

        assert result.is_success
        assert result.status_code == 204
        mock_job_repository.update_async.assert_called_once()
        mock_execution_service.request_cancel.assert_called_once_with(job.id())

    @pytest.mark.unit
    async def test_cancel_running_job(self, mock_job_repository, mock_execution_service):
        # Create a RUNNING job
        job = Job.create(scenario_name="hello-world", scenario_version="v1")
        job.start()
        assert job.state.status == JobStatus.RUNNING
        mock_job_repository.get_by_id_async = AsyncMock(return_value=job)

        handler = CancelJobCommandHandler(job_repository=mock_job_repository, job_execution_service=mock_execution_service)
        command = CancelJobCommand(job_id=job.id())

        result = await handler.handle_async(command)

        assert result.is_success
        assert result.status_code == 204
        mock_job_repository.update_async.assert_called_once()
        mock_execution_service.request_cancel.assert_called_once_with(job.id())

    @pytest.mark.unit
    async def test_cancel_job_missing_job_id(self, mock_job_repository, mock_execution_service):
        handler = CancelJobCommandHandler(job_repository=mock_job_repository, job_execution_service=mock_execution_service)
        command = CancelJobCommand(job_id="")

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.unit
    async def test_cancel_job_not_found(self, mock_job_repository, mock_execution_service):
        mock_job_repository.get_by_id_async = AsyncMock(return_value=None)

        handler = CancelJobCommandHandler(job_repository=mock_job_repository, job_execution_service=mock_execution_service)
        command = CancelJobCommand(job_id="job-nonexistent")

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.unit
    async def test_cancel_completed_job_conflict(self, mock_job_repository, mock_execution_service):
        # Create a COMPLETED job (non-cancellable)
        job = Job.create(scenario_name="hello-world", scenario_version="v1")
        job.start()
        job.complete(output_data={"result": "done"})
        assert job.state.status == JobStatus.COMPLETED
        mock_job_repository.get_by_id_async = AsyncMock(return_value=job)

        handler = CancelJobCommandHandler(job_repository=mock_job_repository, job_execution_service=mock_execution_service)
        command = CancelJobCommand(job_id=job.id())

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 409
        mock_job_repository.update_async.assert_not_called()

    @pytest.mark.unit
    async def test_cancel_failed_job_conflict(self, mock_job_repository, mock_execution_service):
        # Create a FAILED job (non-cancellable)
        job = Job.create(scenario_name="hello-world", scenario_version="v1")
        job.start()
        job.fail(error="Something went wrong")
        assert job.state.status == JobStatus.FAILED
        mock_job_repository.get_by_id_async = AsyncMock(return_value=job)

        handler = CancelJobCommandHandler(job_repository=mock_job_repository, job_execution_service=mock_execution_service)
        command = CancelJobCommand(job_id=job.id())

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 409
        mock_job_repository.update_async.assert_not_called()


# =============================================================================
# SyncContentCommandHandler
# =============================================================================


class TestSyncContentCommandHandler:
    """Tests for SyncContentCommandHandler."""

    @pytest.mark.unit
    async def test_sync_new_pod_definition(self, mock_pod_definition_repository):
        handler = SyncContentCommandHandler(pod_definition_repository=mock_pod_definition_repository)
        command = SyncContentCommand(
            name="my-content",
            version="v1",
            source_uri="s3://bucket/content.zip",
        )

        result = await handler.handle_async(command)

        assert result.is_success
        assert result.status_code == 202
        assert result.data["status"] == "synchronizing"
        assert result.data["definition_id"] != ""
        mock_pod_definition_repository.add_async.assert_called_once()
        mock_pod_definition_repository.update_async.assert_called_once()

    @pytest.mark.unit
    async def test_sync_existing_pod_definition(self, mock_pod_definition_repository):
        # Create an existing PodDefinition in DEFINED state
        pod_def = PodDefinition.create(
            name="existing-content",
            version="v1",
            pod_type=PodType.CML_ON_AWS,
            source_uri="s3://bucket/old.zip",
            definition_id="pd-existing",
        )
        mock_pod_definition_repository.get_by_id_async = AsyncMock(return_value=pod_def)

        handler = SyncContentCommandHandler(pod_definition_repository=mock_pod_definition_repository)
        command = SyncContentCommand(
            definition_id="pd-existing",
            source_uri="s3://bucket/new.zip",
        )

        result = await handler.handle_async(command)

        assert result.is_success
        assert result.status_code == 202
        assert result.data["definition_id"] == "pd-existing"
        mock_pod_definition_repository.add_async.assert_not_called()
        mock_pod_definition_repository.update_async.assert_called_once()

    @pytest.mark.unit
    async def test_sync_ready_without_force_conflict(self, mock_pod_definition_repository):
        # Create a READY PodDefinition
        pod_def = PodDefinition.create(
            name="ready-content",
            version="v1",
            pod_type=PodType.CML_ON_AWS,
            source_uri="s3://bucket/ready.zip",
            definition_id="pd-ready",
        )
        pod_def.start_sync()
        pod_def.mark_ready(local_path="/data/ready", manifest={"files": ["a.yaml"]})
        assert pod_def.state.status == PodDefinitionStatus.READY
        mock_pod_definition_repository.get_by_id_async = AsyncMock(return_value=pod_def)

        handler = SyncContentCommandHandler(pod_definition_repository=mock_pod_definition_repository)
        command = SyncContentCommand(
            definition_id="pd-ready",
            source_uri="s3://bucket/ready.zip",
            force=False,
        )

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 409
        mock_pod_definition_repository.update_async.assert_not_called()

    @pytest.mark.unit
    async def test_sync_ready_with_force(self, mock_pod_definition_repository):
        # Create a READY PodDefinition
        pod_def = PodDefinition.create(
            name="ready-content",
            version="v1",
            pod_type=PodType.CML_ON_AWS,
            source_uri="s3://bucket/ready.zip",
            definition_id="pd-ready",
        )
        pod_def.start_sync()
        pod_def.mark_ready(local_path="/data/ready", manifest={"files": ["a.yaml"]})
        assert pod_def.state.status == PodDefinitionStatus.READY
        mock_pod_definition_repository.get_by_id_async = AsyncMock(return_value=pod_def)

        handler = SyncContentCommandHandler(pod_definition_repository=mock_pod_definition_repository)
        command = SyncContentCommand(
            definition_id="pd-ready",
            source_uri="s3://bucket/ready.zip",
            force=True,
        )

        result = await handler.handle_async(command)

        assert result.is_success
        assert result.status_code == 202
        mock_pod_definition_repository.update_async.assert_called_once()

    @pytest.mark.unit
    async def test_sync_missing_source_uri(self, mock_pod_definition_repository):
        handler = SyncContentCommandHandler(pod_definition_repository=mock_pod_definition_repository)
        command = SyncContentCommand(source_uri="")

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.unit
    async def test_sync_new_missing_name(self, mock_pod_definition_repository):
        handler = SyncContentCommandHandler(pod_definition_repository=mock_pod_definition_repository)
        command = SyncContentCommand(
            name="",
            source_uri="s3://bucket/content.zip",
        )

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400
