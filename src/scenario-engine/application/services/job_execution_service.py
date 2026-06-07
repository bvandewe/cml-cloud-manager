"""JobExecutionService — HostedService that dispatches and executes scenario jobs.

Picks up submitted jobs from an asyncio.Queue, resolves the scenario from the
registry, executes it with a ScenarioContext, and emits CloudEvents callbacks
on completion/failure.

Lifecycle: start_async() → _startup_sweep() → _dispatch_loop() → stop_async()
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from domain.entities.job import JobStatus
from domain.repositories.job_repository import JobRepository
from integration.services.cloud_event_client import CloudEventCallbackService
from neuroglia.dependency_injection.service_provider import ServiceProviderBase
from neuroglia.hosting import HostedService

from application.services.scenario_context import AdapterRegistry, ScenarioContext
from application.services.scenario_registry import ScenarioResult, get_scenario
from application.settings import Settings

if TYPE_CHECKING:
    from neuroglia.dependency_injection.service_provider import ServiceCollection

logger = logging.getLogger(__name__)


class JobExecutionService(HostedService):
    """Manages job dispatch, execution, concurrency, and graceful shutdown.

    Hybrid dispatch: in-process asyncio.Queue for immediate dispatch +
    MongoDB sweep on startup to recover orphaned jobs.
    """

    def __init__(
        self,
        service_provider: ServiceProviderBase,
        callback_service: CloudEventCallbackService,
        settings: Settings,
    ) -> None:
        self._service_provider = service_provider
        self._callback_service = callback_service
        self._settings = settings

        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)
        self._running_tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
        self._cancellation_events: dict[str, asyncio.Event] = {}
        self._dispatch_task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._stopping = False

    def _get_repository(self) -> JobRepository:
        """Resolve JobRepository from a new DI scope.

        JobRepository is registered as scoped (per-request), so we must create
        a scope from the root service provider each time we need it.
        """
        scope = self._service_provider.create_scope()
        return scope.get_required_service(JobRepository)

    # =========================================================================
    # DI Registration
    # =========================================================================

    @classmethod
    def configure(cls, services: ServiceCollection, settings: Settings) -> None:
        """Register JobExecutionService as singleton + HostedService.

        Args:
            services: Neuroglia service collection.
            settings: Application settings.
        """

        def factory(sp) -> JobExecutionService:  # type: ignore[type-arg]
            return cls(
                service_provider=sp,
                callback_service=sp.get_required_service(CloudEventCallbackService),
                settings=settings,
            )

        def hosted_service_factory(sp) -> JobExecutionService:  # type: ignore[type-arg]
            return sp.get_required_service(cls)

        services.add_singleton(cls, implementation_type=cls, implementation_factory=factory)
        services.add_singleton(HostedService, implementation_type=cls, implementation_factory=hosted_service_factory)

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start_async(self) -> None:
        """Start the execution service: sweep orphans, then dispatch loop."""
        logger.info("JobExecutionService starting (max_concurrent=%d, timeout=%ds)", self._settings.max_concurrent_jobs, self._settings.job_default_timeout)
        self._stopping = False
        await self._startup_sweep()
        self._dispatch_task = asyncio.create_task(self._dispatch_loop(), name="job-dispatch-loop")
        logger.info("JobExecutionService started")

    async def stop_async(self) -> None:
        """Gracefully stop: cancel dispatch loop, cancel running tasks, await drain."""
        logger.info("JobExecutionService stopping...")
        self._stopping = True

        # Cancel dispatch loop
        if self._dispatch_task and not self._dispatch_task.done():
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass

        # Cancel all running job tasks
        for job_id, task in list(self._running_tasks.items()):
            if not task.done():
                logger.info("Cancelling running job %s on shutdown", job_id)
                task.cancel()

        # Wait for all tasks to finish (with a grace period)
        if self._running_tasks:
            pending = [t for t in self._running_tasks.values() if not t.done()]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        # Close callback service
        await self._callback_service.close()

        self._running_tasks.clear()
        self._cancellation_events.clear()
        logger.info("JobExecutionService stopped")

    # =========================================================================
    # Public API
    # =========================================================================

    def enqueue_job(self, job_id: str) -> None:
        """Enqueue a job for execution. Called by SubmitJobCommandHandler."""
        if self._stopping:
            logger.warning("JobExecutionService is stopping — ignoring enqueue for %s", job_id)
            return
        self._queue.put_nowait(job_id)
        logger.info("Job %s enqueued for execution", job_id)

    def request_cancel(self, job_id: str) -> None:
        """Request cancellation of a running job. Called by CancelJobCommandHandler."""
        # Set cooperative cancellation event
        cancel_event = self._cancellation_events.get(job_id)
        if cancel_event:
            cancel_event.set()
            logger.info("Cancellation event set for job %s", job_id)

        # Schedule hard cancel after grace period
        task = self._running_tasks.get(job_id)
        if task and not task.done():
            asyncio.get_event_loop().call_later(10.0, self._hard_cancel, job_id)

    def _hard_cancel(self, job_id: str) -> None:
        """Hard-cancel a job task after grace period."""
        task = self._running_tasks.get(job_id)
        if task and not task.done():
            logger.warning("Hard-cancelling job %s after grace period", job_id)
            task.cancel()

    # =========================================================================
    # Internal
    # =========================================================================

    async def _startup_sweep(self) -> None:
        """Recover orphaned jobs after service restart.

        - SUBMITTED → re-enqueue for execution
        - RUNNING → mark FAILED (execution context lost)
        """
        try:
            repository = self._get_repository()

            # Re-enqueue orphaned SUBMITTED jobs
            submitted_jobs = await repository.find_by_status_async(JobStatus.SUBMITTED)
            for job in submitted_jobs:
                self._queue.put_nowait(job.id())
                logger.info("Startup sweep: re-enqueued SUBMITTED job %s", job.id())

            # Fail orphaned RUNNING jobs
            running_jobs = await repository.find_by_status_async(JobStatus.RUNNING)
            for job in running_jobs:
                job.fail("Service restarted; execution context lost")
                await repository.update_async(job)
                logger.warning("Startup sweep: marked RUNNING job %s as FAILED", job.id())

            if submitted_jobs or running_jobs:
                logger.info("Startup sweep complete: %d re-enqueued, %d failed", len(submitted_jobs), len(running_jobs))
        except Exception as exc:
            logger.error("Startup sweep failed: %s", exc)

    async def _dispatch_loop(self) -> None:
        """Main dispatch loop: consume from queue, acquire semaphore, execute."""
        logger.debug("Dispatch loop started")
        try:
            while not self._stopping:
                job_id = await self._queue.get()
                if self._stopping:
                    break

                # Acquire semaphore (blocks if at max concurrency)
                await self._semaphore.acquire()

                # Create execution task
                task = asyncio.create_task(self._execute_job(job_id), name=f"job-{job_id}")
                self._running_tasks[job_id] = task
                task.add_done_callback(lambda t, jid=job_id: self._on_task_done(jid))
        except asyncio.CancelledError:
            logger.debug("Dispatch loop cancelled")

    def _on_task_done(self, job_id: str) -> None:
        """Callback when a job task finishes — release semaphore, cleanup."""
        self._running_tasks.pop(job_id, None)
        self._cancellation_events.pop(job_id, None)
        self._semaphore.release()

    async def _execute_job(self, job_id: str) -> None:
        """Load, execute, and finalize a single job."""
        job_logger = logger.getChild(f"job:{job_id}")
        start_time = time.monotonic()
        repository = self._get_repository()

        try:
            # Load job from repository
            job = await repository.get_by_id_async(job_id)
            if job is None:
                job_logger.error("Job not found in repository — skipping")
                return

            # Verify job is still in SUBMITTED state (deduplication)
            if job.state.status != JobStatus.SUBMITTED:
                job_logger.warning("Job is in %s state, expected SUBMITTED — skipping", job.state.status)
                return

            # Resolve scenario from registry
            scenario_meta = get_scenario(job.state.scenario_name, job.state.scenario_version)
            if scenario_meta is None:
                job.fail(f"Scenario '{job.state.scenario_name}@{job.state.scenario_version}' not found in registry")
                await repository.update_async(job)
                await self._callback_service.emit_failed(
                    job_id=job_id,
                    error=job.state.error or "Scenario not found",
                    duration=time.monotonic() - start_time,
                    callback_url=job.state.callback_url,
                )
                return

            # Transition to RUNNING
            job.start()
            await repository.update_async(job)
            await self._callback_service.emit_started(
                job_id=job_id,
                scenario_name=job.state.scenario_name,
                started_at=datetime.now(timezone.utc).isoformat(),
                callback_url=job.state.callback_url,
            )

            # Build ScenarioContext
            cancellation_event = asyncio.Event()
            self._cancellation_events[job_id] = cancellation_event

            async def report_progress(percentage: int, message: str, details: dict | None = None) -> None:
                """Progress callback — persists and emits throttled CloudEvent."""
                job_logger.debug("Progress: %d%% — %s", percentage, message)
                await self._callback_service.emit_progress(
                    job_id=job_id,
                    percentage=percentage,
                    message=message,
                    details=details,
                    callback_url=job.state.callback_url,
                )

            context = ScenarioContext(
                job_id=job_id,
                scenario_name=job.state.scenario_name,
                scenario_version=job.state.scenario_version,
                input_data=job.state.input_data,
                pod_definition_id=job.state.pod_definition_id,
                callback_url=job.state.callback_url,
                adapters=AdapterRegistry(),
                report_progress=report_progress,
                cancellation_event=cancellation_event,
                logger=job_logger,
            )

            # Execute scenario with timeout
            scenario_instance = scenario_meta.implementation()
            try:
                result: ScenarioResult = await asyncio.wait_for(
                    scenario_instance.execute(job.state.input_data, context),
                    timeout=self._settings.job_default_timeout,
                )
            except asyncio.TimeoutError:
                duration = time.monotonic() - start_time
                job.fail(f"Job exceeded timeout ({self._settings.job_default_timeout}s)")
                await repository.update_async(job)
                await self._callback_service.emit_failed(
                    job_id=job_id,
                    error=job.state.error or "Timeout",
                    duration=duration,
                    callback_url=job.state.callback_url,
                )
                job_logger.warning("Job timed out after %.1fs", duration)
                return
            except asyncio.CancelledError:
                duration = time.monotonic() - start_time
                # Check if this was a user-requested cancel or shutdown
                if cancellation_event.is_set():
                    job_logger.info("Job cancelled (cooperative)")
                    await self._callback_service.emit_cancelled(
                        job_id=job_id,
                        cancelled_at=datetime.now(timezone.utc).isoformat(),
                        callback_url=job.state.callback_url,
                    )
                else:
                    # Shutdown cancel — mark as failed
                    job.fail("Service shutting down")
                    await repository.update_async(job)
                    await self._callback_service.emit_failed(
                        job_id=job_id,
                        error="Service shutting down",
                        duration=duration,
                        callback_url=job.state.callback_url,
                    )
                return

            # Process scenario result
            duration = time.monotonic() - start_time
            if result.status == "completed":
                job.complete(output_data=result.output_data)
                await repository.update_async(job)
                await self._callback_service.emit_completed(
                    job_id=job_id,
                    output_data=result.output_data,
                    artifacts=result.artifacts,
                    duration=duration,
                    callback_url=job.state.callback_url,
                )
                job_logger.info("Job completed in %.1fs", duration)
            elif result.status == "failed":
                job.fail(result.error or "Scenario returned failed status")
                await repository.update_async(job)
                await self._callback_service.emit_failed(
                    job_id=job_id,
                    error=result.error or "Unknown error",
                    duration=duration,
                    callback_url=job.state.callback_url,
                )
                job_logger.warning("Job failed: %s", result.error)
            elif result.status == "cancelled":
                job.cancel()
                await repository.update_async(job)
                await self._callback_service.emit_cancelled(
                    job_id=job_id,
                    cancelled_at=datetime.now(timezone.utc).isoformat(),
                    callback_url=job.state.callback_url,
                )
                job_logger.info("Job cancelled by scenario")

        except Exception as exc:
            duration = time.monotonic() - start_time
            job_logger.exception("Unhandled exception executing job")
            try:
                job = await repository.get_by_id_async(job_id)
                if job and job.state.status == JobStatus.RUNNING:
                    job.fail(str(exc))
                    await repository.update_async(job)
                    await self._callback_service.emit_failed(
                        job_id=job_id,
                        error=str(exc),
                        duration=duration,
                        callback_url=job.state.callback_url,
                    )
            except Exception as persist_exc:
                job_logger.error("Failed to persist error state: %s", persist_exc)
