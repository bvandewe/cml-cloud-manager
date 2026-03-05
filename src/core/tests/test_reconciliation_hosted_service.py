"""Tests for ReconciliationHostedService base class.

These tests validate the Kubernetes-style reconciliation loop pattern
implemented in lcm-core infrastructure.
"""

import asyncio
import uuid
from dataclasses import dataclass

import pytest
from lcm_core.infrastructure.hosted_services import (
    ReconciliationConfig,
    ReconciliationHostedService,
    ReconciliationResult,
    ReconciliationStatus,
)


def get_unique_service_name(prefix: str = "test") -> str:
    """Generate a unique service name to avoid Prometheus metric conflicts."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def cleanup_prometheus_registry():
    """Clean up Prometheus registry after each test to avoid metric conflicts."""
    yield
    # The registry is a singleton, so we need to be careful
    # We use unique service names instead of cleaning up


@dataclass
class SampleResource:
    """Simple resource for testing reconciliation."""

    id: str
    name: str
    desired_state: str = "ready"
    current_state: str = "pending"


class TestReconciliationResult:
    """Tests for ReconciliationResult dataclass."""

    def test_success_factory(self):
        """Test ReconciliationResult.success() factory method."""
        result = ReconciliationResult.success("Completed successfully")

        assert result.status == ReconciliationStatus.SUCCESS
        assert result.message == "Completed successfully"
        assert result.requeue_after_seconds is None
        assert result.error is None

    def test_success_factory_default_message(self):
        """Test ReconciliationResult.success() with default message."""
        result = ReconciliationResult.success()

        assert result.status == ReconciliationStatus.SUCCESS
        assert result.message == ""

    def test_requeue_factory(self):
        """Test ReconciliationResult.requeue() factory method."""
        result = ReconciliationResult.requeue("Still processing", after_seconds=10.0)

        assert result.status == ReconciliationStatus.REQUEUE
        assert result.message == "Still processing"
        assert result.requeue_after_seconds == 10.0
        assert result.error is None

    def test_requeue_factory_no_delay(self):
        """Test ReconciliationResult.requeue() without custom delay."""
        result = ReconciliationResult.requeue("Requeue for next cycle")

        assert result.status == ReconciliationStatus.REQUEUE
        assert result.requeue_after_seconds is None

    def test_failed_factory(self):
        """Test ReconciliationResult.failed() factory method."""
        error = ValueError("Invalid state")
        result = ReconciliationResult.failed("Reconciliation error", error=error)

        assert result.status == ReconciliationStatus.FAILED
        assert result.message == "Reconciliation error"
        assert result.error is error
        assert isinstance(result.error, ValueError)

    def test_failed_factory_without_exception(self):
        """Test ReconciliationResult.failed() without exception."""
        result = ReconciliationResult.failed("Something went wrong")

        assert result.status == ReconciliationStatus.FAILED
        assert result.error is None

    def test_skip_factory(self):
        """Test ReconciliationResult.skip() factory method."""
        result = ReconciliationResult.skip("Already being processed")

        assert result.status == ReconciliationStatus.SKIP
        assert result.message == "Already being processed"


class TestReconciliationConfig:
    """Tests for ReconciliationConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = ReconciliationConfig()

        assert config.interval_seconds == 30.0
        assert config.initial_delay_seconds == 5.0
        assert config.max_concurrent_reconciles == 10
        assert config.backoff_initial_seconds == 1.0
        assert config.backoff_max_seconds == 60.0
        assert config.backoff_multiplier == 2.0
        assert config.service_name == "reconciliation"

    def test_custom_values(self):
        """Test configuration with custom values."""
        config = ReconciliationConfig(
            interval_seconds=60.0,
            initial_delay_seconds=10.0,
            max_concurrent_reconciles=5,
            backoff_initial_seconds=2.0,
            backoff_max_seconds=120.0,
            backoff_multiplier=3.0,
            service_name="my-scheduler",
        )

        assert config.interval_seconds == 60.0
        assert config.initial_delay_seconds == 10.0
        assert config.max_concurrent_reconciles == 5
        assert config.backoff_initial_seconds == 2.0
        assert config.backoff_max_seconds == 120.0
        assert config.backoff_multiplier == 3.0
        assert config.service_name == "my-scheduler"


class MockReconciler(ReconciliationHostedService[SampleResource]):
    """Mock reconciler for testing."""

    def __init__(
        self,
        config: ReconciliationConfig | None = None,
        resources: list[SampleResource] | None = None,
    ):
        super().__init__(config)
        self.resources_to_return = resources or []
        self.reconcile_calls: list[SampleResource] = []
        self.list_resources_calls = 0
        self.should_fail = False
        self.requeue_resources: set[str] = set()
        self.skip_resources: set[str] = set()
        self.fail_resources: set[str] = set()
        self.custom_results: dict[str, ReconciliationResult] = {}

    async def list_resources(self) -> list[SampleResource]:
        """Return configured resources."""
        self.list_resources_calls += 1
        return self.resources_to_return.copy()

    async def reconcile(self, resource: SampleResource) -> ReconciliationResult:
        """Record reconciliation call and return configured result."""
        self.reconcile_calls.append(resource)

        # Check for custom result
        if resource.id in self.custom_results:
            return self.custom_results[resource.id]

        # Check for configured behaviors
        if resource.id in self.fail_resources:
            return ReconciliationResult.failed(f"Forced failure for {resource.id}")

        if resource.id in self.requeue_resources:
            return ReconciliationResult.requeue(f"Requeued {resource.id}")

        if resource.id in self.skip_resources:
            return ReconciliationResult.skip(f"Skipped {resource.id}")

        if self.should_fail:
            return ReconciliationResult.failed("Forced global failure")

        return ReconciliationResult.success(f"Reconciled {resource.id}")

    def get_resource_id(self, resource: SampleResource) -> str:
        """Extract ID from test resource."""
        return resource.id


class TestReconciliationHostedService:
    """Tests for ReconciliationHostedService base class."""

    @pytest.fixture
    def config(self) -> ReconciliationConfig:
        """Create test configuration with short intervals."""
        return ReconciliationConfig(
            interval_seconds=0.1,
            initial_delay_seconds=0.0,
            max_concurrent_reconciles=5,
            backoff_initial_seconds=0.1,
            backoff_max_seconds=1.0,
            service_name=get_unique_service_name("reconciler"),
        )

    @pytest.fixture
    def resources(self) -> list[SampleResource]:
        """Create test resources."""
        return [
            SampleResource(id="res-1", name="Resource 1"),
            SampleResource(id="res-2", name="Resource 2"),
            SampleResource(id="res-3", name="Resource 3"),
        ]

    @pytest.fixture
    def reconciler(self, config: ReconciliationConfig, resources: list[SampleResource]) -> MockReconciler:
        """Create mock reconciler with default setup."""
        return MockReconciler(config=config, resources=resources)

    async def test_start_async_initializes_service(self, reconciler: MockReconciler):
        """Test that start_async properly initializes the service."""
        assert not reconciler.is_running

        await reconciler.start_async()

        try:
            assert reconciler.is_running
            assert reconciler._started is True
            assert reconciler._stopping is False
            assert reconciler._semaphore is not None
        finally:
            await reconciler.stop_async()

    async def test_start_async_prevents_double_start(self, reconciler: MockReconciler):
        """Test that calling start_async twice doesn't cause issues."""
        await reconciler.start_async()

        try:
            # Second start should be no-op
            await reconciler.start_async()
            assert reconciler.is_running
        finally:
            await reconciler.stop_async()

    async def test_stop_async_stops_service(self, reconciler: MockReconciler):
        """Test that stop_async properly stops the service."""
        await reconciler.start_async()
        assert reconciler.is_running

        await reconciler.stop_async()

        assert not reconciler.is_running
        assert reconciler._started is False

    async def test_stop_async_when_not_started(self, reconciler: MockReconciler):
        """Test that stop_async handles not-started state gracefully."""
        # Should not raise
        await reconciler.stop_async()
        assert not reconciler.is_running

    async def test_reconcile_loop_calls_list_resources(self, reconciler: MockReconciler):
        """Test that the reconciliation loop calls list_resources."""
        await reconciler.start_async()

        try:
            # Wait for at least one reconcile cycle
            await asyncio.sleep(0.2)
            assert reconciler.list_resources_calls >= 1
        finally:
            await reconciler.stop_async()

    async def test_reconcile_loop_processes_all_resources(self, reconciler: MockReconciler, resources: list[SampleResource]):
        """Test that all resources are reconciled."""
        await reconciler.start_async()

        try:
            # Wait for reconciliation
            await asyncio.sleep(0.3)

            # All resources should have been processed
            reconciled_ids = {r.id for r in reconciler.reconcile_calls}
            expected_ids = {r.id for r in resources}
            assert reconciled_ids == expected_ids
        finally:
            await reconciler.stop_async()

    async def test_reconcile_now_triggers_immediate_reconciliation(self, reconciler: MockReconciler, resources: list[SampleResource]):
        """Test that reconcile_now triggers immediate processing."""
        reconciler._config.initial_delay_seconds = 1000  # Long delay
        await reconciler.start_async()

        try:
            # Shouldn't have reconciled yet due to delay
            assert len(reconciler.reconcile_calls) == 0

            # Trigger immediate reconciliation
            await reconciler.reconcile_now()

            # Now resources should be processed
            assert len(reconciler.reconcile_calls) == len(resources)
        finally:
            await reconciler.stop_async()

    async def test_successful_reconciliation_updates_stats(self, reconciler: MockReconciler):
        """Test that successful reconciliations update statistics."""
        await reconciler.start_async()

        try:
            await asyncio.sleep(0.3)

            stats = reconciler.stats
            assert stats["running"] is True
            assert stats["total_reconciled"] >= 3  # At least one cycle
            assert stats["total_failed"] == 0
        finally:
            await reconciler.stop_async()

    async def test_failed_reconciliation_updates_stats(self, config: ReconciliationConfig):
        """Test that failed reconciliations update statistics."""
        resources = [SampleResource(id="fail-1", name="Failing Resource")]
        reconciler = MockReconciler(config=config, resources=resources)
        reconciler.fail_resources.add("fail-1")

        await reconciler.start_async()

        try:
            await asyncio.sleep(0.3)

            stats = reconciler.stats
            assert stats["total_failed"] >= 1
        finally:
            await reconciler.stop_async()

    async def test_backoff_calculation(self, reconciler: MockReconciler):
        """Test exponential backoff calculation."""
        # With default config: initial=0.1, multiplier=2, max=1.0
        assert reconciler._calculate_backoff(1) == 0.1
        assert reconciler._calculate_backoff(2) == 0.2
        assert reconciler._calculate_backoff(3) == 0.4
        assert reconciler._calculate_backoff(4) == 0.8
        # Should cap at max
        assert reconciler._calculate_backoff(10) == 1.0

    async def test_concurrent_reconciliation_limited_by_semaphore(self, config: ReconciliationConfig):
        """Test that concurrent reconciliations are limited."""
        # Create many resources
        resources = [SampleResource(id=f"res-{i}", name=f"Resource {i}") for i in range(20)]
        reconciler = MockReconciler(config=config, resources=resources)

        # Track concurrent execution
        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        original_reconcile = reconciler.reconcile

        async def tracking_reconcile(resource: SampleResource) -> ReconciliationResult:
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent

            try:
                await asyncio.sleep(0.05)  # Simulate some work
                return await original_reconcile(resource)
            finally:
                async with lock:
                    current_concurrent -= 1

        reconciler.reconcile = tracking_reconcile

        await reconciler.start_async()

        try:
            await asyncio.sleep(0.5)
            # Should not exceed configured max
            assert max_concurrent <= config.max_concurrent_reconciles
        finally:
            await reconciler.stop_async()

    async def test_requeue_result_delays_next_attempt(self, config: ReconciliationConfig):
        """Test that requeue results delay subsequent attempts."""
        resources = [SampleResource(id="requeue-1", name="Requeue Resource")]
        reconciler = MockReconciler(config=config, resources=resources)
        reconciler.custom_results["requeue-1"] = ReconciliationResult.requeue("Wait", after_seconds=10.0)

        await reconciler.start_async()

        try:
            # First reconciliation
            await asyncio.sleep(0.15)
            first_call_count = len(reconciler.reconcile_calls)
            assert first_call_count == 1

            # Should be skipped due to requeue delay
            await asyncio.sleep(0.15)
            assert len(reconciler.reconcile_calls) == 1  # Still 1, didn't retry
        finally:
            await reconciler.stop_async()

    async def test_skip_result_does_not_count_as_failure(self, config: ReconciliationConfig):
        """Test that skip results don't count as failures."""
        resources = [SampleResource(id="skip-1", name="Skip Resource")]
        reconciler = MockReconciler(config=config, resources=resources)
        reconciler.skip_resources.add("skip-1")

        await reconciler.start_async()

        try:
            await asyncio.sleep(0.3)

            stats = reconciler.stats
            assert stats["total_failed"] == 0
        finally:
            await reconciler.stop_async()

    async def test_empty_resource_list_handles_gracefully(self, config: ReconciliationConfig):
        """Test that empty resource list is handled gracefully."""
        reconciler = MockReconciler(config=config, resources=[])

        await reconciler.start_async()

        try:
            await asyncio.sleep(0.3)

            assert reconciler.list_resources_calls >= 1
            assert len(reconciler.reconcile_calls) == 0
        finally:
            await reconciler.stop_async()

    async def test_last_reconcile_time_updated(self, reconciler: MockReconciler):
        """Test that last_reconcile_time is updated after each cycle."""
        assert reconciler.last_reconcile_time is None

        await reconciler.start_async()

        try:
            await asyncio.sleep(0.2)
            assert reconciler.last_reconcile_time is not None
            assert reconciler.last_reconcile_time > 0
        finally:
            await reconciler.stop_async()

    async def test_stats_property(self, reconciler: MockReconciler):
        """Test the stats property returns expected structure."""
        await reconciler.start_async()

        try:
            await asyncio.sleep(0.2)

            stats = reconciler.stats

            assert "running" in stats
            assert "total_reconciled" in stats
            assert "total_failed" in stats
            assert "last_reconcile_time" in stats
            assert "pending_retries" in stats
            assert "in_progress" in stats
        finally:
            await reconciler.stop_async()

    async def test_exception_in_reconcile_is_caught(self, config: ReconciliationConfig):
        """Test that exceptions in reconcile() are caught and logged."""
        resources = [SampleResource(id="exception-1", name="Exception Resource")]
        reconciler = MockReconciler(config=config, resources=resources)

        # Make reconcile raise an exception
        async def raising_reconcile(resource: SampleResource) -> ReconciliationResult:
            raise RuntimeError("Simulated error")

        reconciler.reconcile = raising_reconcile

        await reconciler.start_async()

        try:
            # Should not crash
            await asyncio.sleep(0.3)

            stats = reconciler.stats
            assert stats["running"] is True
            assert stats["total_failed"] >= 1
        finally:
            await reconciler.stop_async()

    async def test_exception_in_list_resources_is_caught(self, config: ReconciliationConfig):
        """Test that exceptions in list_resources() are caught."""
        reconciler = MockReconciler(config=config, resources=[])

        # Make list_resources raise an exception
        async def raising_list_resources() -> list[SampleResource]:
            raise RuntimeError("Simulated listing error")

        reconciler.list_resources = raising_list_resources

        await reconciler.start_async()

        try:
            # Should not crash, should keep running
            await asyncio.sleep(0.3)
            assert reconciler.is_running
        finally:
            await reconciler.stop_async()


class TestReconciliationStatus:
    """Tests for ReconciliationStatus enum."""

    def test_all_status_values(self):
        """Test all status enum values exist."""
        assert ReconciliationStatus.SUCCESS.value == "success"
        assert ReconciliationStatus.REQUEUE.value == "requeue"
        assert ReconciliationStatus.FAILED.value == "failed"
        assert ReconciliationStatus.SKIP.value == "skip"

    def test_status_equality(self):
        """Test status comparison."""
        assert ReconciliationStatus.SUCCESS == ReconciliationStatus.SUCCESS
        assert ReconciliationStatus.SUCCESS != ReconciliationStatus.FAILED
