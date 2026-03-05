"""Tests for WatchTriggeredHostedService.

Validates the etcd watch + debounce mechanism for reactive reconciliation,
including the drain-loop fix for the race condition where self-induced
watch events are dropped during _debounced_reconcile() execution.
"""

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from lcm_core.infrastructure.hosted_services import (
    LeaderElectionConfig,
    ReconciliationConfig,
    ReconciliationResult,
    WatchConfig,
    WatchTriggeredHostedService,
)
from lcm_core.integration.clients.etcd_client import EtcdEvent


def get_unique_service_name(prefix: str = "test") -> str:
    """Generate a unique service name to avoid Prometheus metric conflicts."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@dataclass
class MockResource:
    """Simple test resource."""

    id: str
    status: str = "pending"


class MockWatchEtcdClient:
    """Mock etcd client that supports watch_prefix for testing."""

    def __init__(self):
        self.keys: dict[str, tuple[str, int | None]] = {}
        self._watch_queues: list[asyncio.Queue[EtcdEvent]] = []

        # Leader election mocks
        self.grant_lease_calls = 0
        self.put_if_not_exists_calls = 0
        self.refresh_lease_calls = 0
        self.revoke_lease_calls = 0
        self.put_should_succeed = True
        self.leases: dict[int, Any] = {}
        self.next_lease_id = 1

    async def grant_lease(self, ttl: int) -> int:
        self.grant_lease_calls += 1
        lease_id = self.next_lease_id
        self.next_lease_id += 1
        self.leases[lease_id] = {"ttl": ttl, "revoked": False}
        return lease_id

    async def put_if_not_exists(self, key: str, value: str, lease: int) -> bool:
        self.put_if_not_exists_calls += 1
        if key in self.keys:
            return False
        if self.put_should_succeed:
            self.keys[key] = (value, lease)
            return True
        return False

    async def get(self, key: str) -> str | None:
        if key in self.keys:
            return self.keys[key][0]
        return None

    async def refresh_lease(self, lease: int) -> None:
        self.refresh_lease_calls += 1
        if lease not in self.leases:
            raise Exception("Lease not found")

    async def revoke_lease(self, lease: int) -> None:
        self.revoke_lease_calls += 1
        if lease in self.leases:
            self.leases[lease]["revoked"] = True
            keys_to_remove = [k for k, v in self.keys.items() if v[1] == lease]
            for key in keys_to_remove:
                del self.keys[key]

    async def watch_prefix(self, prefix: str):
        """Yield events from a queue (test-controlled)."""
        queue: asyncio.Queue[EtcdEvent] = asyncio.Queue()
        self._watch_queues.append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        except asyncio.CancelledError:
            pass

    def inject_event(self, event: EtcdEvent) -> None:
        """Inject a watch event from test code."""
        for queue in self._watch_queues:
            queue.put_nowait(event)


class MockWatchReconciler(WatchTriggeredHostedService[MockResource]):
    """Mock reconciler with configurable behavior for testing debounce patterns."""

    def __init__(
        self,
        reconciliation_config: ReconciliationConfig | None = None,
        election_config: LeaderElectionConfig | None = None,
        watch_config: WatchConfig | None = None,
        etcd_client: MockWatchEtcdClient | None = None,
    ):
        super().__init__(reconciliation_config, election_config, watch_config, etcd_client)
        self.resources: dict[str, MockResource] = {}
        self.reconcile_calls: list[str] = []  # resource IDs in reconciliation order
        self._reconcile_side_effects: dict[str, Any] = {}  # resource_id -> callback or result
        self.on_elected_called = 0
        self.on_demoted_called = 0

        self.on_elected(self._track_elected)
        self.on_demoted(self._track_demoted)

    def _track_elected(self):
        self.on_elected_called += 1

    def _track_demoted(self):
        self.on_demoted_called += 1

    @property
    def watch_prefix(self) -> str:
        return "/resources/"

    async def on_watch_event(self, event: EtcdEvent) -> str | None:
        """Extract resource ID from /resources/{id}/state."""
        parts = event.key.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "resources":
            return parts[1]
        return None

    async def fetch_resource_by_id(self, resource_id: str) -> MockResource | None:
        return self.resources.get(resource_id)

    async def list_resources(self) -> list[MockResource]:
        return list(self.resources.values())

    async def reconcile(self, resource: MockResource) -> ReconciliationResult:
        self.reconcile_calls.append(resource.id)

        # Execute side effect if registered
        side_effect = self._reconcile_side_effects.get(resource.id)
        if side_effect:
            if callable(side_effect):
                return await side_effect(resource)
            return side_effect

        return ReconciliationResult.success(f"Reconciled {resource.id}")

    def get_resource_id(self, resource: MockResource) -> str:
        return resource.id

    def set_reconcile_side_effect(self, resource_id: str, side_effect):
        """Set a side effect for when a resource is reconciled."""
        self._reconcile_side_effects[resource_id] = side_effect


def _make_reconciler(
    etcd_client: MockWatchEtcdClient | None = None,
    polling_enabled: bool = False,
    debounce_seconds: float = 0.05,
    interval_seconds: float = 0.1,
) -> MockWatchReconciler:
    """Create a test reconciler with sensible defaults."""
    service_name = get_unique_service_name("watch_test")
    return MockWatchReconciler(
        reconciliation_config=ReconciliationConfig(
            interval_seconds=interval_seconds,
            initial_delay_seconds=0.0,
            polling_enabled=polling_enabled,
            max_concurrent_reconciles=5,
            service_name=service_name,
        ),
        election_config=LeaderElectionConfig(
            lease_ttl_seconds=5,
            renewal_interval_seconds=1.0,
            instance_id=f"test-{service_name}",
            service_name=service_name,
        ),
        watch_config=WatchConfig(
            enabled=True,
            prefix="/resources/",
            debounce_seconds=debounce_seconds,
            startup_reconcile_enabled=False,  # Disable to isolate watch tests
        ),
        etcd_client=etcd_client,
    )


class TestDebouncedReconcile:
    """Tests for the _debounced_reconcile drain-loop fix."""

    async def test_basic_watch_event_triggers_reconcile(self):
        """A single watch event triggers reconciliation after debounce."""
        etcd = MockWatchEtcdClient()
        r = _make_reconciler(etcd_client=etcd)
        r.resources["res-1"] = MockResource(id="res-1", status="pending")

        await r.start_async()
        try:
            await asyncio.sleep(0.2)  # Let leader election happen
            assert r.is_leader

            # Inject a watch event
            etcd.inject_event(EtcdEvent(type="PUT", key="/resources/res-1/state", value="SCHEDULED"))
            await asyncio.sleep(0.3)  # Wait for debounce + processing

            assert "res-1" in r.reconcile_calls
        finally:
            await r.stop_async()

    async def test_events_during_processing_are_not_lost(self):
        """Events added to _pending_reconciles during _debounced_reconcile execution
        are processed by the drain-loop (not silently dropped).

        This is the race condition fix: when _handle_scheduled() calls
        start_instantiation() which triggers a watch event for INSTANTIATING,
        that event arrives during _debounced_reconcile() execution. Before the
        fix, _schedule_debounced_reconcile() returned early because the debounce
        task was still running, and the pending item was never processed.
        """
        etcd = MockWatchEtcdClient()
        r = _make_reconciler(etcd_client=etcd, polling_enabled=False)

        # Resources: res-1 starts as SCHEDULED, then transitions to INSTANTIATING
        r.resources["res-1"] = MockResource(id="res-1", status="scheduled")

        # When res-1 is reconciled in SCHEDULED state, inject a new watch event
        # (simulating what happens when _handle_scheduled calls start_instantiation)
        async def simulate_self_induced_event(resource: MockResource):
            # The handler calls an API that triggers a state change → watch event
            resource.status = "instantiating"
            # Inject the self-induced watch event (happens during the await in real code)
            etcd.inject_event(EtcdEvent(type="PUT", key="/resources/res-1/state", value="INSTANTIATING"))
            # Small yield to let the watch stream process the event
            await asyncio.sleep(0.01)
            return ReconciliationResult.requeue("Transitioning to instantiation")

        r.set_reconcile_side_effect("res-1", simulate_self_induced_event)

        await r.start_async()
        try:
            await asyncio.sleep(0.2)  # Let leader election happen
            assert r.is_leader

            # Trigger the initial SCHEDULED event
            etcd.inject_event(EtcdEvent(type="PUT", key="/resources/res-1/state", value="SCHEDULED"))

            # Wait for debounce + processing + drain-loop
            await asyncio.sleep(0.8)

            # res-1 should have been reconciled TWICE:
            # 1. First for the SCHEDULED event
            # 2. Then again for the INSTANTIATING event (via drain-loop)
            assert r.reconcile_calls.count("res-1") >= 2, (
                f"Expected res-1 to be reconciled at least twice (SCHEDULED + INSTANTIATING), " f"but got {r.reconcile_calls.count('res-1')} calls: {r.reconcile_calls}"
            )
        finally:
            await r.stop_async()

    async def test_multiple_resources_in_pending_set(self):
        """Multiple resources in the pending set are all processed."""
        etcd = MockWatchEtcdClient()
        r = _make_reconciler(etcd_client=etcd)
        r.resources["res-1"] = MockResource(id="res-1")
        r.resources["res-2"] = MockResource(id="res-2")
        r.resources["res-3"] = MockResource(id="res-3")

        await r.start_async()
        try:
            await asyncio.sleep(0.2)  # Leader election

            # Inject multiple events rapidly (within debounce window)
            etcd.inject_event(EtcdEvent(type="PUT", key="/resources/res-1/state", value="A"))
            etcd.inject_event(EtcdEvent(type="PUT", key="/resources/res-2/state", value="A"))
            etcd.inject_event(EtcdEvent(type="PUT", key="/resources/res-3/state", value="A"))

            await asyncio.sleep(0.3)

            assert "res-1" in r.reconcile_calls
            assert "res-2" in r.reconcile_calls
            assert "res-3" in r.reconcile_calls
        finally:
            await r.stop_async()

    async def test_chained_self_induced_events(self):
        """Chain of self-induced events: SCHEDULED → INSTANTIATING → READY
        are all processed without relying on polling.

        This tests that the drain-loop handles multi-step state machines
        where each reconciliation triggers the next state transition.
        """
        etcd = MockWatchEtcdClient()
        r = _make_reconciler(etcd_client=etcd, polling_enabled=False)
        r.resources["session-1"] = MockResource(id="session-1", status="scheduled")

        call_count = 0

        async def multi_step_handler(resource: MockResource):
            nonlocal call_count
            call_count += 1

            if resource.status == "scheduled":
                resource.status = "instantiating"
                etcd.inject_event(EtcdEvent(type="PUT", key="/resources/session-1/state", value="INSTANTIATING"))
                await asyncio.sleep(0.01)
                return ReconciliationResult.requeue("→ INSTANTIATING")

            elif resource.status == "instantiating":
                resource.status = "ready"
                etcd.inject_event(EtcdEvent(type="PUT", key="/resources/session-1/state", value="READY"))
                await asyncio.sleep(0.01)
                return ReconciliationResult.requeue("→ READY")

            elif resource.status == "ready":
                return ReconciliationResult.success("Session is READY")

            return ReconciliationResult.success()

        r.set_reconcile_side_effect("session-1", multi_step_handler)

        await r.start_async()
        try:
            await asyncio.sleep(0.2)  # Leader election

            # Trigger the chain
            etcd.inject_event(EtcdEvent(type="PUT", key="/resources/session-1/state", value="SCHEDULED"))

            await asyncio.sleep(1.0)  # Allow the full chain to process

            # All three states should have been processed
            assert call_count >= 3, f"Expected at least 3 reconciliation calls (SCHEDULED → INSTANTIATING → READY), got {call_count}"
        finally:
            await r.stop_async()

    async def test_empty_pending_set_exits_immediately(self):
        """When _pending_reconciles is empty, the drain-loop exits without processing."""
        etcd = MockWatchEtcdClient()
        r = _make_reconciler(etcd_client=etcd)

        await r.start_async()
        try:
            await asyncio.sleep(0.2)  # Leader election

            # Manually trigger _debounced_reconcile with empty pending set
            assert len(r._pending_reconciles) == 0
            await r._debounced_reconcile()

            # No reconcile calls should have been made
            assert len(r.reconcile_calls) == 0
        finally:
            await r.stop_async()

    async def test_resource_not_found_skipped_gracefully(self):
        """Resources in pending set but not returned by fetch_resource_by_id are skipped."""
        etcd = MockWatchEtcdClient()
        r = _make_reconciler(etcd_client=etcd)
        # Don't add res-ghost to r.resources — fetch_resource_by_id returns None

        await r.start_async()
        try:
            await asyncio.sleep(0.2)

            etcd.inject_event(EtcdEvent(type="PUT", key="/resources/res-ghost/state", value="A"))
            await asyncio.sleep(0.3)

            # Should NOT crash, and no reconcile calls
            assert "res-ghost" not in r.reconcile_calls
        finally:
            await r.stop_async()

    async def test_debounce_deduplicates_rapid_events(self):
        """Multiple events for the same resource within the debounce window
        result in a single reconciliation (set deduplication).
        """
        etcd = MockWatchEtcdClient()
        r = _make_reconciler(etcd_client=etcd, debounce_seconds=0.1)
        r.resources["res-1"] = MockResource(id="res-1")

        await r.start_async()
        try:
            await asyncio.sleep(0.2)

            # Inject 5 events for the same resource within the debounce window
            for i in range(5):
                etcd.inject_event(EtcdEvent(type="PUT", key="/resources/res-1/state", value=f"STATE_{i}"))
                await asyncio.sleep(0.01)  # Within 0.1s debounce

            await asyncio.sleep(0.4)

            # Should be reconciled only once (set deduplication)
            assert r.reconcile_calls.count("res-1") == 1
        finally:
            await r.stop_async()

    async def test_watch_stats_updated(self):
        """Watch statistics are updated correctly."""
        etcd = MockWatchEtcdClient()
        r = _make_reconciler(etcd_client=etcd)
        r.resources["res-1"] = MockResource(id="res-1")

        await r.start_async()
        try:
            await asyncio.sleep(0.2)

            etcd.inject_event(EtcdEvent(type="PUT", key="/resources/res-1/state", value="A"))
            await asyncio.sleep(0.3)

            stats = r.stats
            assert stats["watch_enabled"] is True
            assert stats["watch_events_received"] >= 1
            assert stats["watch_triggered_reconciles"] >= 1
        finally:
            await r.stop_async()


class TestScheduleDebounce:
    """Tests for _schedule_debounced_reconcile guard logic."""

    async def test_second_schedule_during_running_debounce_is_noop(self):
        """Calling _schedule_debounced_reconcile while debounce task is running is a no-op.

        This is expected behavior — the drain-loop in _debounced_reconcile
        handles items added during execution. The guard in
        _schedule_debounced_reconcile just prevents duplicate tasks.
        """
        etcd = MockWatchEtcdClient()
        r = _make_reconciler(etcd_client=etcd)

        await r.start_async()
        try:
            await asyncio.sleep(0.2)  # Leader election

            # Manually set up a pending item and start debounce
            r._pending_reconciles.add("test-resource")
            r._schedule_debounced_reconcile()
            task1 = r._debounce_task

            # Schedule again — should be same task (no-op)
            r._pending_reconciles.add("test-resource-2")
            r._schedule_debounced_reconcile()
            task2 = r._debounce_task

            assert task1 is task2, "Should reuse existing debounce task"

            # Wait for processing
            await asyncio.sleep(0.3)
        finally:
            await r.stop_async()

    async def test_new_debounce_after_previous_completes(self):
        """A new debounce task is created after the previous one completes."""
        etcd = MockWatchEtcdClient()
        r = _make_reconciler(etcd_client=etcd, debounce_seconds=0.05)
        r.resources["res-1"] = MockResource(id="res-1")
        r.resources["res-2"] = MockResource(id="res-2")

        await r.start_async()
        try:
            await asyncio.sleep(0.2)

            # First event
            etcd.inject_event(EtcdEvent(type="PUT", key="/resources/res-1/state", value="A"))
            await asyncio.sleep(0.2)  # Let debounce complete

            task1 = r._debounce_task
            assert task1 is not None and task1.done()

            # Second event (new debounce task)
            etcd.inject_event(EtcdEvent(type="PUT", key="/resources/res-2/state", value="A"))
            await asyncio.sleep(0.2)

            assert "res-1" in r.reconcile_calls
            assert "res-2" in r.reconcile_calls
        finally:
            await r.stop_async()
