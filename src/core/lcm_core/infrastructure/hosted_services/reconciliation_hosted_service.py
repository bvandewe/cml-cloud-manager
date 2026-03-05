"""ReconciliationHostedService base class.

Provides a Kubernetes-style reconciliation loop pattern for resource-oriented
services. Subclasses implement list_resources() and reconcile() to process
resources in a standardized way.

This is designed as an interim solution in lcm-core that will eventually
migrate to the Neuroglia framework.
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, TypeVar

from neuroglia.hosting import HostedService
from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger(__name__)

# Type variable for the resource type being reconciled
T = TypeVar("T")


class ReconciliationStatus(Enum):
    """Result status of a reconciliation attempt."""

    SUCCESS = "success"  # Reconciliation completed, resource is in desired state
    REQUEUE = "requeue"  # Reconciliation in progress, requeue for another attempt
    FAILED = "failed"  # Reconciliation failed, may retry with backoff
    SKIP = "skip"  # Skip this resource (e.g., already being processed)


@dataclass
class ReconciliationResult:
    """Result of a single reconciliation attempt."""

    status: ReconciliationStatus
    message: str = ""
    requeue_after_seconds: float | None = None  # Custom requeue delay
    error: Exception | None = None

    @classmethod
    def success(cls, message: str = "") -> "ReconciliationResult":
        """Create a successful result."""
        return cls(status=ReconciliationStatus.SUCCESS, message=message)

    @classmethod
    def requeue(cls, message: str = "", after_seconds: float | None = None) -> "ReconciliationResult":
        """Create a requeue result."""
        return cls(status=ReconciliationStatus.REQUEUE, message=message, requeue_after_seconds=after_seconds)

    @classmethod
    def failed(cls, message: str = "", error: Exception | None = None) -> "ReconciliationResult":
        """Create a failed result."""
        return cls(status=ReconciliationStatus.FAILED, message=message, error=error)

    @classmethod
    def skip(cls, message: str = "") -> "ReconciliationResult":
        """Create a skip result."""
        return cls(status=ReconciliationStatus.SKIP, message=message)


@dataclass
class ReconciliationConfig:
    """Configuration for the reconciliation loop."""

    # Main loop timing
    interval_seconds: float = 30.0  # Time between reconciliation cycles
    initial_delay_seconds: float = 5.0  # Delay before first reconciliation

    # Polling mode (can be disabled for pure reactive/watch-based reconciliation)
    polling_enabled: bool = True  # Set to False for watch-only mode (ADR-015)

    # Concurrency
    max_concurrent_reconciles: int = 10  # Max parallel reconciliations

    # Backoff for failed reconciliations
    backoff_initial_seconds: float = 1.0
    backoff_max_seconds: float = 60.0
    backoff_multiplier: float = 2.0

    # Metrics
    service_name: str = "reconciliation"  # Used in metric labels


@dataclass
class ResourceState:
    """Tracks state for a resource being reconciled."""

    resource_id: str
    in_progress: bool = False
    last_attempt: float = 0.0
    failure_count: int = 0
    next_retry: float = 0.0


class ReconciliationHostedService(HostedService, ABC, Generic[T]):
    """
    Base class for Kubernetes-style reconciliation loops.

    Implements the controller pattern:
    1. List all resources to reconcile (list_resources)
    2. For each resource, determine if it needs work (reconcile)
    3. Handle results (success/requeue/fail)
    4. Repeat on interval

    Subclasses must implement:
    - list_resources(): Fetch resources to reconcile
    - reconcile(resource): Process a single resource
    - get_resource_id(resource): Extract unique ID from resource

    Example:
        class MyReconciler(ReconciliationHostedService[MyResource]):
            async def list_resources(self) -> List[MyResource]:
                return await self.api.get_pending_resources()

            async def reconcile(self, resource: MyResource) -> ReconciliationResult:
                try:
                    await self.process(resource)
                    return ReconciliationResult.success()
                except Exception as e:
                    return ReconciliationResult.failed(str(e), e)

            def get_resource_id(self, resource: MyResource) -> str:
                return resource.id
    """

    def __init__(self, config: ReconciliationConfig | None = None):
        """Initialize the reconciliation service.

        Args:
            config: Configuration for the reconciliation loop.
                   Defaults to ReconciliationConfig() if not provided.
        """
        self._config = config or ReconciliationConfig()
        self._stopping = False
        self._started = False
        self._reconcile_task: asyncio.Task[None] | None = None
        self._resource_states: dict[str, ResourceState] = {}
        self._semaphore: asyncio.Semaphore | None = None

        # Metrics (lazy initialization with service name)
        self._metrics_initialized = False
        self._reconcile_total: Counter | None = None
        self._reconcile_duration: Histogram | None = None
        self._active_reconciles: Gauge | None = None
        self._resources_pending: Gauge | None = None

        # Stats
        self._last_reconcile_time: float | None = None
        self._total_reconciled: int = 0
        self._total_failed: int = 0

    def _init_metrics(self) -> None:
        """Initialize Prometheus metrics with service-specific labels."""
        if self._metrics_initialized:
            return

        prefix = self._config.service_name.replace("-", "_")

        self._reconcile_total = Counter(
            f"{prefix}_reconcile_total",
            "Total number of reconciliation attempts",
            ["status"],
        )
        self._reconcile_duration = Histogram(
            f"{prefix}_reconcile_duration_seconds",
            "Duration of reconciliation attempts",
        )
        self._active_reconciles = Gauge(
            f"{prefix}_active_reconciles",
            "Number of reconciliations currently in progress",
        )
        self._resources_pending = Gauge(
            f"{prefix}_resources_pending",
            "Number of resources pending reconciliation",
        )

        self._metrics_initialized = True

    @abstractmethod
    async def list_resources(self) -> list[T]:
        """List all resources that may need reconciliation.

        Returns:
            List of resources to potentially reconcile.

        Raises:
            Exception: If resource listing fails (will be logged and retried).
        """
        pass

    @abstractmethod
    async def reconcile(self, resource: T) -> ReconciliationResult:
        """Reconcile a single resource.

        This method should:
        1. Check current state vs desired state
        2. Take actions to move towards desired state
        3. Return appropriate result

        Args:
            resource: The resource to reconcile.

        Returns:
            ReconciliationResult indicating success/requeue/fail.
        """
        pass

    @abstractmethod
    def get_resource_id(self, resource: T) -> str:
        """Extract unique identifier from a resource.

        Args:
            resource: The resource.

        Returns:
            Unique string identifier for tracking state.
        """
        pass

    async def start_async(self) -> None:
        """Start the reconciliation loop."""
        if self._started:
            logger.warning(f"{self._config.service_name}: Already started")
            return

        logger.info(f"{self._config.service_name}: Starting reconciliation service")

        self._init_metrics()
        self._stopping = False
        self._started = True
        self._semaphore = asyncio.Semaphore(self._config.max_concurrent_reconciles)

        # Start the reconciliation loop in background
        self._reconcile_task = asyncio.create_task(self._run_reconciliation_loop(), name=f"{self._config.service_name}_reconcile_loop")

        logger.info(f"{self._config.service_name}: Started with interval={self._config.interval_seconds}s, " f"max_concurrent={self._config.max_concurrent_reconciles}")

    async def stop_async(self) -> None:
        """Stop the reconciliation loop gracefully."""
        if not self._started:
            return

        logger.info(f"{self._config.service_name}: Stopping reconciliation service")
        self._stopping = True

        # Cancel the reconciliation task
        if self._reconcile_task:
            self._reconcile_task.cancel()
            try:
                await self._reconcile_task
            except asyncio.CancelledError:
                pass
            self._reconcile_task = None

        self._started = False
        logger.info(f"{self._config.service_name}: Stopped. " f"Total reconciled: {self._total_reconciled}, failed: {self._total_failed}")

    async def _run_reconciliation_loop(self) -> None:
        """Main reconciliation loop."""
        # Initial delay
        if self._config.initial_delay_seconds > 0:
            logger.debug(f"{self._config.service_name}: Waiting {self._config.initial_delay_seconds}s before first reconcile")
            await asyncio.sleep(self._config.initial_delay_seconds)

        while not self._stopping:
            try:
                await self._reconcile_all()
            except asyncio.CancelledError:
                logger.debug(f"{self._config.service_name}: Reconciliation loop cancelled")
                break
            except Exception as e:
                logger.exception(f"{self._config.service_name}: Error in reconciliation loop: {e}")

            # Wait for next cycle
            if not self._stopping:
                await asyncio.sleep(self._config.interval_seconds)

    async def _reconcile_all(self) -> None:
        """Run one complete reconciliation cycle."""
        start_time = time.time()
        self._last_reconcile_time = start_time

        logger.debug(f"{self._config.service_name}: Starting reconciliation cycle")

        try:
            # Fetch resources
            resources = await self.list_resources()
            if self._resources_pending:
                self._resources_pending.set(len(resources))

            if not resources:
                logger.debug(f"{self._config.service_name}: No resources to reconcile")
                return

            logger.info(f"{self._config.service_name}: Found {len(resources)} resources to reconcile")

            # Process resources concurrently with semaphore limit
            tasks = []
            for resource in resources:
                resource_id = self.get_resource_id(resource)

                # Skip if already in progress
                state = self._resource_states.get(resource_id)
                if state and state.in_progress:
                    logger.debug(f"{self._config.service_name}: Skipping {resource_id} (in progress)")
                    continue

                # Check retry backoff
                if state and state.next_retry > time.time():
                    logger.debug(f"{self._config.service_name}: Skipping {resource_id} (backoff until {state.next_retry})")
                    continue

                task = asyncio.create_task(
                    self._reconcile_with_semaphore(resource, resource_id),
                    name=f"reconcile_{resource_id}",
                )
                tasks.append(task)

            # Wait for all reconciliations to complete
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.exception(f"{self._config.service_name}: Failed to list resources: {e}")

        duration = time.time() - start_time
        logger.debug(f"{self._config.service_name}: Reconciliation cycle completed in {duration:.2f}s")

    async def _reconcile_with_semaphore(self, resource: T, resource_id: str) -> None:
        """Reconcile a single resource with concurrency limiting."""
        if self._semaphore is None:
            # Should not happen, but handle defensively
            await self._reconcile_single(resource, resource_id)
            return
        async with self._semaphore:
            await self._reconcile_single(resource, resource_id)

    async def _reconcile_single(self, resource: T, resource_id: str) -> None:
        """Reconcile a single resource and track state."""
        # Get or create state
        state = self._resource_states.setdefault(resource_id, ResourceState(resource_id=resource_id))
        state.in_progress = True
        state.last_attempt = time.time()

        if self._active_reconciles:
            self._active_reconciles.inc()

        start_time = time.time()

        try:
            result = await self.reconcile(resource)
            duration = time.time() - start_time

            if self._reconcile_duration:
                self._reconcile_duration.observe(duration)

            if result.status == ReconciliationStatus.SUCCESS:
                logger.debug(f"{self._config.service_name}: {resource_id} reconciled successfully: {result.message}")
                if self._reconcile_total:
                    self._reconcile_total.labels(status="success").inc()
                self._total_reconciled += 1
                state.failure_count = 0
                state.next_retry = 0

            elif result.status == ReconciliationStatus.REQUEUE:
                requeue_delay = result.requeue_after_seconds or self._config.interval_seconds
                logger.debug(f"{self._config.service_name}: {resource_id} requeued: {result.message}")
                if self._reconcile_total:
                    self._reconcile_total.labels(status="requeue").inc()
                state.next_retry = time.time() + requeue_delay

            elif result.status == ReconciliationStatus.FAILED:
                state.failure_count += 1
                backoff = self._calculate_backoff(state.failure_count)
                state.next_retry = time.time() + backoff

                logger.warning(f"{self._config.service_name}: {resource_id} failed (attempt {state.failure_count}): " f"{result.message}. Retry in {backoff:.1f}s")
                if self._reconcile_total:
                    self._reconcile_total.labels(status="failed").inc()
                self._total_failed += 1

            elif result.status == ReconciliationStatus.SKIP:
                logger.debug(f"{self._config.service_name}: {resource_id} skipped: {result.message}")
                if self._reconcile_total:
                    self._reconcile_total.labels(status="skip").inc()

        except Exception as e:
            logger.exception(f"{self._config.service_name}: Exception reconciling {resource_id}: {e}")
            state.failure_count += 1
            state.next_retry = time.time() + self._calculate_backoff(state.failure_count)
            if self._reconcile_total:
                self._reconcile_total.labels(status="error").inc()
            self._total_failed += 1

        finally:
            state.in_progress = False
            if self._active_reconciles:
                self._active_reconciles.dec()

    def _calculate_backoff(self, failure_count: int) -> float:
        """Calculate exponential backoff based on failure count."""
        backoff = self._config.backoff_initial_seconds * (self._config.backoff_multiplier ** (failure_count - 1))
        return min(backoff, self._config.backoff_max_seconds)

    async def reconcile_now(self) -> None:
        """Trigger immediate reconciliation cycle (for admin endpoints)."""
        logger.info(f"{self._config.service_name}: Manual reconciliation triggered")
        await self._reconcile_all()

    @property
    def is_running(self) -> bool:
        """Check if the reconciliation service is running."""
        return self._started and not self._stopping

    @property
    def last_reconcile_time(self) -> float | None:
        """Get timestamp of last reconciliation cycle."""
        return self._last_reconcile_time

    @property
    def stats(self) -> dict[str, Any]:
        """Get current reconciliation statistics."""
        return {
            "running": self.is_running,
            "total_reconciled": self._total_reconciled,
            "total_failed": self._total_failed,
            "last_reconcile_time": self._last_reconcile_time,
            "pending_retries": len([s for s in self._resource_states.values() if s.next_retry > time.time()]),
            "in_progress": len([s for s in self._resource_states.values() if s.in_progress]),
        }
