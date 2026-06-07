"""Unit tests for JobExecutionService."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from application.services.job_execution_service import JobExecutionService
from application.services.scenario_context import ScenarioContext
from application.services.scenario_registry import ScenarioResult, clear_registry, scenario
from application.settings import Settings
from domain.entities.job import Job, JobStatus
from domain.repositories.job_repository import JobRepository
from integration.services.cloud_event_client import CloudEventCallbackService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_service_provider(mock_repository):
    """Create a mock service provider that returns mock_repository from scopes."""
    scope = MagicMock()
    scope.get_required_service = MagicMock(side_effect=lambda t: mock_repository if t is JobRepository else None)

    sp = MagicMock()
    sp.create_scope = MagicMock(return_value=scope)
    return sp


@pytest.fixture
def settings():
    """Test settings with fast timeouts."""
    s = Settings()
    s.max_concurrent_jobs = 2
    s.job_default_timeout = 5
    s.job_progress_interval = 0  # No throttling in tests
    s.cloud_event_sink = ""
    return s


@pytest.fixture
def mock_repository():
    """Mock JobRepository."""
    repo = AsyncMock()
    repo.find_by_status_async = AsyncMock(return_value=[])
    repo.get_by_id_async = AsyncMock(return_value=None)
    repo.add_async = AsyncMock()
    repo.update_async = AsyncMock()
    return repo


@pytest.fixture
def mock_callback_service(settings):
    """Mock CloudEventCallbackService."""
    service = MagicMock(spec=CloudEventCallbackService)
    service.emit_started = AsyncMock()
    service.emit_progress = AsyncMock()
    service.emit_completed = AsyncMock()
    service.emit_failed = AsyncMock()
    service.emit_cancelled = AsyncMock()
    service.close = AsyncMock()
    return service


@pytest.fixture
def execution_service(mock_repository, mock_callback_service, settings):
    """Create a JobExecutionService with mocked dependencies."""
    return JobExecutionService(
        service_provider=_make_mock_service_provider(mock_repository),
        callback_service=mock_callback_service,
        settings=settings,
    )


@pytest.fixture(autouse=True)
def clean_scenario_registry():
    """Clear scenario registry between tests."""
    clear_registry()
    yield
    clear_registry()


def _make_job(scenario_name="echo", scenario_version="v1", status=JobStatus.SUBMITTED, job_id="test-job-1") -> Job:
    """Helper to create a Job in a specific state."""
    job = Job.create(
        scenario_name=scenario_name,
        scenario_version=scenario_version,
        input_data={"key": "value"},
        job_id=job_id,
    )
    if status == JobStatus.RUNNING:
        job.start()
    elif status == JobStatus.COMPLETED:
        job.start()
        job.complete({"result": "done"})
    elif status == JobStatus.FAILED:
        job.start()
        job.fail("some error")
    elif status == JobStatus.CANCELLED:
        job.cancel()
    return job


# ---------------------------------------------------------------------------
# Startup Sweep Tests
# ---------------------------------------------------------------------------


class TestStartupSweep:
    """Tests for _startup_sweep() — recovering orphaned jobs."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_submitted_jobs_re_enqueued(self, execution_service, mock_repository):
        """SUBMITTED jobs found on startup are re-enqueued."""
        submitted_job = _make_job(status=JobStatus.SUBMITTED, job_id="orphan-1")
        mock_repository.find_by_status_async.side_effect = lambda status: ([submitted_job] if status == JobStatus.SUBMITTED else [])

        await execution_service._startup_sweep()

        assert execution_service._queue.qsize() == 1
        assert await execution_service._queue.get() == "orphan-1"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_running_jobs_marked_failed(self, execution_service, mock_repository):
        """RUNNING jobs found on startup are marked as FAILED."""
        running_job = _make_job(status=JobStatus.RUNNING, job_id="orphan-2")
        mock_repository.find_by_status_async.side_effect = lambda status: ([running_job] if status == JobStatus.RUNNING else [])

        await execution_service._startup_sweep()

        mock_repository.update_async.assert_called_once()
        updated_job = mock_repository.update_async.call_args[0][0]
        assert updated_job.state.status == JobStatus.FAILED
        assert "Service restarted" in updated_job.state.error


# ---------------------------------------------------------------------------
# Dispatch + Execution Tests
# ---------------------------------------------------------------------------


class TestDispatchAndExecution:
    """Tests for the dispatch loop and job execution."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_job_executes_to_completion(self, execution_service, mock_repository, mock_callback_service):
        """A submitted job transitions SUBMITTED → RUNNING → COMPLETED."""

        @scenario(name="test_complete", version="v1")
        class CompleteScenario:
            async def execute(self, input_data: dict, context: ScenarioContext) -> ScenarioResult:
                return ScenarioResult.completed(output_data={"echoed": input_data})

        job = _make_job(scenario_name="test_complete", job_id="exec-1")
        mock_repository.get_by_id_async.return_value = job

        # Start service and enqueue
        await execution_service.start_async()
        try:
            execution_service.enqueue_job("exec-1")
            # Give time for execution
            await asyncio.sleep(0.3)
        finally:
            await execution_service.stop_async()

        # Verify job was started then completed
        assert mock_repository.update_async.call_count >= 2
        mock_callback_service.emit_started.assert_called_once()
        mock_callback_service.emit_completed.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_job_scenario_failure(self, execution_service, mock_repository, mock_callback_service):
        """A scenario returning failed result transitions job to FAILED."""

        @scenario(name="test_fail", version="v1")
        class FailScenario:
            async def execute(self, input_data: dict, context: ScenarioContext) -> ScenarioResult:
                return ScenarioResult.failed(error="Something went wrong")

        job = _make_job(scenario_name="test_fail", job_id="fail-1")
        mock_repository.get_by_id_async.return_value = job

        await execution_service.start_async()
        try:
            execution_service.enqueue_job("fail-1")
            await asyncio.sleep(0.3)
        finally:
            await execution_service.stop_async()

        mock_callback_service.emit_failed.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_scenario_not_found(self, execution_service, mock_repository, mock_callback_service):
        """Job with non-existent scenario is marked FAILED."""
        job = _make_job(scenario_name="nonexistent", job_id="nf-1")
        mock_repository.get_by_id_async.return_value = job

        await execution_service.start_async()
        try:
            execution_service.enqueue_job("nf-1")
            await asyncio.sleep(0.3)
        finally:
            await execution_service.stop_async()

        mock_callback_service.emit_failed.assert_called_once()


# ---------------------------------------------------------------------------
# Timeout Tests
# ---------------------------------------------------------------------------


class TestTimeout:
    """Tests for job timeout handling."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_job_exceeding_timeout_fails(self, mock_repository, mock_callback_service):
        """Job exceeding timeout transitions to FAILED."""
        settings = Settings()
        settings.max_concurrent_jobs = 2
        settings.job_default_timeout = 1  # 1 second timeout
        settings.job_progress_interval = 0
        settings.cloud_event_sink = ""

        service = JobExecutionService(
            service_provider=_make_mock_service_provider(mock_repository),
            callback_service=mock_callback_service,
            settings=settings,
        )

        @scenario(name="test_slow", version="v1")
        class SlowScenario:
            async def execute(self, input_data: dict, context: ScenarioContext) -> ScenarioResult:
                await asyncio.sleep(10)  # Way past timeout
                return ScenarioResult.completed()

        job = _make_job(scenario_name="test_slow", job_id="slow-1")
        mock_repository.get_by_id_async.return_value = job

        await service.start_async()
        try:
            service.enqueue_job("slow-1")
            await asyncio.sleep(2.0)  # Wait for timeout to fire
        finally:
            await service.stop_async()

        mock_callback_service.emit_failed.assert_called_once()
        # Check that error mentions timeout
        call_kwargs = mock_callback_service.emit_failed.call_args[1]
        assert "timeout" in call_kwargs["error"].lower()


# ---------------------------------------------------------------------------
# Cancellation Tests
# ---------------------------------------------------------------------------


class TestCancellation:
    """Tests for job cancellation."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cooperative_cancellation(self, execution_service, mock_repository, mock_callback_service):
        """Setting cancellation_event causes scenario to detect cancel."""

        @scenario(name="test_cancellable", version="v1")
        class CancellableScenario:
            async def execute(self, input_data: dict, context: ScenarioContext) -> ScenarioResult:
                # Check cancellation between steps
                for _ in range(50):
                    if context.cancellation_event.is_set():
                        return ScenarioResult.cancelled()
                    await asyncio.sleep(0.05)
                return ScenarioResult.completed()

        job = _make_job(scenario_name="test_cancellable", job_id="cancel-1")
        mock_repository.get_by_id_async.return_value = job

        await execution_service.start_async()
        try:
            execution_service.enqueue_job("cancel-1")
            await asyncio.sleep(0.2)  # Let it start
            execution_service.request_cancel("cancel-1")
            await asyncio.sleep(0.5)  # Let cancellation propagate
        finally:
            await execution_service.stop_async()

        mock_callback_service.emit_cancelled.assert_called_once()


# ---------------------------------------------------------------------------
# Concurrency Tests
# ---------------------------------------------------------------------------


class TestConcurrency:
    """Tests for semaphore-based concurrency limiting."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_semaphore_limits_parallel_execution(self, mock_repository, mock_callback_service):
        """Semaphore limits parallel jobs to max_concurrent_jobs."""
        settings = Settings()
        settings.max_concurrent_jobs = 2
        settings.job_default_timeout = 10
        settings.job_progress_interval = 0
        settings.cloud_event_sink = ""

        service = JobExecutionService(
            service_provider=_make_mock_service_provider(mock_repository),
            callback_service=mock_callback_service,
            settings=settings,
        )

        execution_count = {"concurrent": 0, "max_concurrent": 0}

        @scenario(name="test_concurrent", version="v1")
        class ConcurrentScenario:
            async def execute(self, input_data: dict, context: ScenarioContext) -> ScenarioResult:
                execution_count["concurrent"] += 1
                execution_count["max_concurrent"] = max(execution_count["max_concurrent"], execution_count["concurrent"])
                await asyncio.sleep(0.3)
                execution_count["concurrent"] -= 1
                return ScenarioResult.completed()

        # Create 4 jobs, max concurrency is 2
        jobs = {f"conc-{i}": _make_job(scenario_name="test_concurrent", job_id=f"conc-{i}") for i in range(4)}
        mock_repository.get_by_id_async.side_effect = lambda jid: jobs.get(jid)

        await service.start_async()
        try:
            for job_id in jobs:
                service.enqueue_job(job_id)
            await asyncio.sleep(1.5)  # Wait for all to complete
        finally:
            await service.stop_async()

        # Max concurrent should never exceed 2
        assert execution_count["max_concurrent"] <= 2
