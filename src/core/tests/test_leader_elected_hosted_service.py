"""Tests for LeaderElectedHostedService base class.

These tests validate the leader election pattern with etcd lease mechanism
implemented in lcm-core infrastructure.
"""

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import pytest

from lcm_core.infrastructure.hosted_services import (
    LeaderElectedHostedService,
    LeaderElectionConfig,
    ReconciliationConfig,
    ReconciliationResult,
)


def get_unique_service_name(prefix: str = "test") -> str:
    """Generate a unique service name to avoid Prometheus metric conflicts."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@dataclass
class SampleResource:
    """Simple resource for testing reconciliation."""

    id: str
    name: str


class MockEtcdClient:
    """Mock etcd client for testing leader election."""

    def __init__(self):
        self.leases: dict[int, Any] = {}
        self.keys: dict[str, tuple[str, int | None]] = {}  # key -> (value, lease_id)
        self.next_lease_id = 1
        self.grant_lease_calls = 0
        self.put_if_not_exists_calls = 0
        self.refresh_lease_calls = 0
        self.revoke_lease_calls = 0
        self.get_calls = 0

        # Control flags for testing
        self.should_fail_grant = False
        self.should_fail_put = False
        self.should_fail_refresh = False
        self.put_should_succeed = True

    async def grant_lease(self, ttl: int) -> int:
        """Grant a lease with the given TTL."""
        self.grant_lease_calls += 1
        if self.should_fail_grant:
            raise Exception("Failed to grant lease")

        lease_id = self.next_lease_id
        self.next_lease_id += 1
        self.leases[lease_id] = {"ttl": ttl, "revoked": False}
        return lease_id

    async def put_if_not_exists(self, key: str, value: str, lease: int) -> bool:
        """Try to put a key if it doesn't exist."""
        self.put_if_not_exists_calls += 1
        if self.should_fail_put:
            raise Exception("Failed to put key")

        if key in self.keys:
            return False  # Key already exists

        if self.put_should_succeed:
            self.keys[key] = (value, lease)
            return True
        return False

    async def get(self, key: str) -> str | None:
        """Get a key's value."""
        self.get_calls += 1
        if key in self.keys:
            return self.keys[key][0]
        return None

    async def refresh_lease(self, lease: int) -> None:
        """Refresh/keep-alive a lease."""
        self.refresh_lease_calls += 1
        if self.should_fail_refresh:
            raise Exception("Failed to refresh lease")

        if lease not in self.leases:
            raise Exception("Lease not found")
        if self.leases[lease]["revoked"]:
            raise Exception("Lease revoked")

    async def revoke_lease(self, lease: int) -> None:
        """Revoke a lease."""
        self.revoke_lease_calls += 1
        if lease in self.leases:
            self.leases[lease]["revoked"] = True
            # Remove keys associated with this lease
            keys_to_remove = [k for k, v in self.keys.items() if v[1] == lease]
            for key in keys_to_remove:
                del self.keys[key]


class MockLeaderReconciler(LeaderElectedHostedService[SampleResource]):
    """Mock leader-elected reconciler for testing."""

    def __init__(
        self,
        reconciliation_config: ReconciliationConfig | None = None,
        election_config: LeaderElectionConfig | None = None,
        etcd_client: Any | None = None,
        resources: list[SampleResource] | None = None,
    ):
        super().__init__(reconciliation_config, election_config, etcd_client)
        self.resources_to_return = resources or []
        self.reconcile_calls: list[SampleResource] = []
        self.list_resources_calls = 0
        self.on_elected_called = 0
        self.on_demoted_called = 0

        # Register callbacks
        self.on_elected(self._track_elected)
        self.on_demoted(self._track_demoted)

    def _track_elected(self):
        self.on_elected_called += 1

    def _track_demoted(self):
        self.on_demoted_called += 1

    async def list_resources(self) -> list[SampleResource]:
        """Return configured resources."""
        self.list_resources_calls += 1
        return self.resources_to_return.copy()

    async def reconcile(self, resource: SampleResource) -> ReconciliationResult:
        """Record reconciliation call."""
        self.reconcile_calls.append(resource)
        return ReconciliationResult.success(f"Reconciled {resource.id}")

    def get_resource_id(self, resource: SampleResource) -> str:
        """Extract ID from test resource."""
        return resource.id


class TestLeaderElectionConfig:
    """Tests for LeaderElectionConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = LeaderElectionConfig()

        assert config.etcd_endpoints == ["localhost:2379"]
        assert config.election_key_prefix == "/elections"
        assert config.lease_ttl_seconds == 15
        assert config.renewal_interval_seconds == 5.0
        assert config.service_name == "service"
        # instance_id has a dynamic default

    def test_custom_values(self):
        """Test configuration with custom values."""
        config = LeaderElectionConfig(
            etcd_endpoints=["etcd1:2379", "etcd2:2379"],
            election_key_prefix="/my-elections",
            lease_ttl_seconds=30,
            renewal_interval_seconds=10.0,
            instance_id="my-instance-1",
            service_name="my-service",
        )

        assert config.etcd_endpoints == ["etcd1:2379", "etcd2:2379"]
        assert config.election_key_prefix == "/my-elections"
        assert config.lease_ttl_seconds == 30
        assert config.renewal_interval_seconds == 10.0
        assert config.instance_id == "my-instance-1"
        assert config.service_name == "my-service"

    def test_election_key_property(self):
        """Test the election_key property."""
        config = LeaderElectionConfig(
            election_key_prefix="/elections",
            service_name="scheduler",
        )

        assert config.election_key == "/elections/scheduler/leader"

    def test_from_env(self):
        """Test configuration from environment variables."""
        with patch.dict(
            "os.environ",
            {
                "ETCD_ENDPOINTS": "etcd1:2379,etcd2:2379",
                "LEADER_TTL": "25",
                "INSTANCE_ID": "test-instance",
            },
        ):
            config = LeaderElectionConfig.from_env("my-service")

            assert config.etcd_endpoints == ["etcd1:2379", "etcd2:2379"]
            assert config.lease_ttl_seconds == 25
            assert config.instance_id == "test-instance"
            assert config.service_name == "my-service"

    def test_from_env_defaults(self):
        """Test configuration from environment with default values."""
        with patch.dict("os.environ", {}, clear=False):
            # Clear relevant env vars
            import os

            for key in ["ETCD_ENDPOINTS", "LEADER_TTL", "INSTANCE_ID"]:
                os.environ.pop(key, None)

            config = LeaderElectionConfig.from_env("test-service")

            assert config.etcd_endpoints == ["localhost:2379"]
            assert config.lease_ttl_seconds == 15
            assert "test-service" == config.service_name


class TestLeaderElectedHostedService:
    """Tests for LeaderElectedHostedService base class."""

    @pytest.fixture
    def reconciliation_config(self) -> ReconciliationConfig:
        """Create test reconciliation configuration."""
        return ReconciliationConfig(
            interval_seconds=0.1,
            initial_delay_seconds=0.0,
            max_concurrent_reconciles=5,
            service_name=get_unique_service_name("leader_svc"),
        )

    @pytest.fixture
    def election_config(self) -> LeaderElectionConfig:
        """Create test election configuration."""
        return LeaderElectionConfig(
            lease_ttl_seconds=5,
            renewal_interval_seconds=1.0,
            instance_id="test-instance-1",
            service_name=get_unique_service_name("leader_svc"),
        )

    @pytest.fixture
    def etcd_client(self) -> MockEtcdClient:
        """Create mock etcd client."""
        return MockEtcdClient()

    @pytest.fixture
    def resources(self) -> list[SampleResource]:
        """Create test resources."""
        return [
            SampleResource(id="res-1", name="Resource 1"),
            SampleResource(id="res-2", name="Resource 2"),
        ]

    @pytest.fixture
    def reconciler(
        self,
        reconciliation_config: ReconciliationConfig,
        election_config: LeaderElectionConfig,
        etcd_client: MockEtcdClient,
        resources: list[SampleResource],
    ) -> MockLeaderReconciler:
        """Create mock leader-elected reconciler."""
        return MockLeaderReconciler(
            reconciliation_config=reconciliation_config,
            election_config=election_config,
            etcd_client=etcd_client,
            resources=resources,
        )

    async def test_initial_state(self, reconciler: MockLeaderReconciler):
        """Test initial state before starting."""
        assert reconciler.is_leader is False
        assert reconciler.current_leader_id is None
        assert reconciler.instance_id == "test-instance-1"
        assert reconciler.is_running is False

    async def test_start_async_acquires_leadership(
        self,
        reconciler: MockLeaderReconciler,
        etcd_client: MockEtcdClient,
    ):
        """Test that start_async attempts to acquire leadership."""
        await reconciler.start_async()

        try:
            # Wait for leader election
            await asyncio.sleep(0.2)

            assert etcd_client.grant_lease_calls >= 1
            assert etcd_client.put_if_not_exists_calls >= 1
            assert reconciler.is_leader is True
            assert reconciler.on_elected_called >= 1
        finally:
            await reconciler.stop_async()

    async def test_leader_starts_reconciliation(
        self,
        reconciler: MockLeaderReconciler,
        resources: list[SampleResource],
    ):
        """Test that leader starts reconciliation loop."""
        await reconciler.start_async()

        try:
            # Wait for leader election and reconciliation
            await asyncio.sleep(0.3)

            assert reconciler.is_leader is True
            assert reconciler.list_resources_calls >= 1
            assert len(reconciler.reconcile_calls) >= len(resources)
        finally:
            await reconciler.stop_async()

    async def test_stop_async_releases_leadership(
        self,
        reconciler: MockLeaderReconciler,
        etcd_client: MockEtcdClient,
    ):
        """Test that stop_async releases leadership."""
        await reconciler.start_async()

        try:
            await asyncio.sleep(0.2)
            assert reconciler.is_leader is True
        finally:
            await reconciler.stop_async()

        assert reconciler.is_leader is False
        assert reconciler.is_running is False
        assert etcd_client.revoke_lease_calls >= 1
        assert reconciler.on_demoted_called >= 1

    async def test_non_leader_does_not_reconcile(
        self,
        resources: list[SampleResource],
    ):
        """Test that non-leader instances don't reconcile."""
        service_name = get_unique_service_name("non_leader")
        reconciliation_config = ReconciliationConfig(
            interval_seconds=0.1,
            initial_delay_seconds=0.0,
            max_concurrent_reconciles=5,
            service_name=service_name,
        )
        election_config = LeaderElectionConfig(
            lease_ttl_seconds=5,
            renewal_interval_seconds=1.0,
            instance_id="test-instance-1",
            service_name=service_name,
        )

        etcd_client = MockEtcdClient()
        # Simulate existing leader
        etcd_client.keys[election_config.election_key] = ("other-instance", None)
        etcd_client.put_should_succeed = False

        reconciler = MockLeaderReconciler(
            reconciliation_config=reconciliation_config,
            election_config=election_config,
            etcd_client=etcd_client,
            resources=resources,
        )

        await reconciler.start_async()

        try:
            await asyncio.sleep(0.3)

            assert reconciler.is_leader is False
            assert reconciler.current_leader_id == "other-instance"
            assert reconciler.list_resources_calls == 0
            assert len(reconciler.reconcile_calls) == 0
        finally:
            await reconciler.stop_async()

    async def test_mock_mode_becomes_leader_immediately(
        self,
        resources: list[SampleResource],
    ):
        """Test that mock mode (no etcd client) becomes leader immediately."""
        service_name = get_unique_service_name("mock_leader")
        reconciliation_config = ReconciliationConfig(
            interval_seconds=0.1,
            initial_delay_seconds=0.0,
            max_concurrent_reconciles=5,
            service_name=service_name,
        )
        election_config = LeaderElectionConfig(
            lease_ttl_seconds=5,
            renewal_interval_seconds=1.0,
            instance_id="test-instance-1",
            service_name=service_name,
        )

        reconciler = MockLeaderReconciler(
            reconciliation_config=reconciliation_config,
            election_config=election_config,
            etcd_client=None,  # Mock mode
            resources=resources,
        )

        await reconciler.start_async()

        try:
            # Should become leader immediately in mock mode
            await asyncio.sleep(0.2)

            assert reconciler.is_leader is True
            assert reconciler.list_resources_calls >= 1
        finally:
            await reconciler.stop_async()

    async def test_lease_renewal(
        self,
        reconciler: MockLeaderReconciler,
        etcd_client: MockEtcdClient,
    ):
        """Test that lease is renewed periodically."""
        await reconciler.start_async()

        try:
            await asyncio.sleep(0.2)
            assert reconciler.is_leader is True

            # Wait for renewal
            await asyncio.sleep(1.5)  # > renewal_interval

            assert etcd_client.refresh_lease_calls >= 1
        finally:
            await reconciler.stop_async()

    async def test_lease_renewal_failure_steps_down(
        self,
        reconciler: MockLeaderReconciler,
        etcd_client: MockEtcdClient,
    ):
        """Test that lease renewal failure causes step down."""
        await reconciler.start_async()

        try:
            await asyncio.sleep(0.2)
            assert reconciler.is_leader is True

            # Make renewal fail
            etcd_client.should_fail_refresh = True

            # Wait for renewal attempt
            await asyncio.sleep(1.5)

            # Should have stepped down
            assert reconciler.is_leader is False
        finally:
            await reconciler.stop_async()

    async def test_stats_includes_leader_info(self, reconciler: MockLeaderReconciler):
        """Test that stats includes leader election information."""
        await reconciler.start_async()

        try:
            await asyncio.sleep(0.2)

            stats = reconciler.stats

            assert "is_leader" in stats
            assert "current_leader_id" in stats
            assert "instance_id" in stats
            assert "service_name" in stats
            assert "running" in stats
            assert "total_reconciled" in stats
        finally:
            await reconciler.stop_async()

    async def test_on_elected_callback(self, reconciler: MockLeaderReconciler):
        """Test that on_elected callbacks are called."""
        callback_called = False

        async def async_callback():
            nonlocal callback_called
            callback_called = True

        reconciler.on_elected(async_callback)

        await reconciler.start_async()

        try:
            await asyncio.sleep(0.2)
            assert reconciler.is_leader is True
            assert callback_called is True
        finally:
            await reconciler.stop_async()

    async def test_on_demoted_callback(self, reconciler: MockLeaderReconciler):
        """Test that on_demoted callbacks are called."""
        demoted_called = False

        def sync_callback():
            nonlocal demoted_called
            demoted_called = True

        reconciler.on_demoted(sync_callback)

        await reconciler.start_async()

        try:
            await asyncio.sleep(0.2)
            assert reconciler.is_leader is True
        finally:
            await reconciler.stop_async()

        assert demoted_called is True

    async def test_instance_id_property(self, reconciler: MockLeaderReconciler):
        """Test instance_id property returns correct value."""
        assert reconciler.instance_id == "test-instance-1"

    async def test_current_leader_id_when_leader(self, reconciler: MockLeaderReconciler):
        """Test current_leader_id is set to self when leader."""
        await reconciler.start_async()

        try:
            await asyncio.sleep(0.2)
            assert reconciler.is_leader is True
            assert reconciler.current_leader_id == reconciler.instance_id
        finally:
            await reconciler.stop_async()

    async def test_leader_election_retries_on_failure(
        self,
        resources: list[SampleResource],
    ):
        """Test that leader election retries on failure."""
        service_name = get_unique_service_name("retry_leader")
        reconciliation_config = ReconciliationConfig(
            interval_seconds=0.1,
            initial_delay_seconds=0.0,
            max_concurrent_reconciles=5,
            service_name=service_name,
        )
        election_config = LeaderElectionConfig(
            lease_ttl_seconds=5,
            renewal_interval_seconds=1.0,
            instance_id="test-instance-1",
            service_name=service_name,
        )

        etcd_client = MockEtcdClient()
        etcd_client.should_fail_grant = True

        reconciler = MockLeaderReconciler(
            reconciliation_config=reconciliation_config,
            election_config=election_config,
            etcd_client=etcd_client,
            resources=resources,
        )

        await reconciler.start_async()

        try:
            # Wait longer for retries (leader election has 1s sleep on failure)
            await asyncio.sleep(2.5)

            # Should have retried multiple times
            assert etcd_client.grant_lease_calls >= 2
            assert reconciler.is_leader is False

            # Now allow success
            etcd_client.should_fail_grant = False

            await asyncio.sleep(1.5)

            # Should eventually become leader
            assert reconciler.is_leader is True
        finally:
            await reconciler.stop_async()

    async def test_start_async_prevents_double_start(self, reconciler: MockLeaderReconciler):
        """Test that calling start_async twice doesn't cause issues."""
        await reconciler.start_async()

        try:
            # Second start should be no-op
            await reconciler.start_async()
            assert reconciler.is_running is True
        finally:
            await reconciler.stop_async()


class TestLeaderElectionEdgeCases:
    """Edge case tests for leader election."""

    def _get_configs(self, prefix: str = "edge") -> tuple[ReconciliationConfig, LeaderElectionConfig]:
        """Create configuration for edge case tests with unique service name."""
        service_name = get_unique_service_name(prefix)
        return (
            ReconciliationConfig(
                interval_seconds=0.1,
                initial_delay_seconds=0.0,
                service_name=service_name,
            ),
            LeaderElectionConfig(
                lease_ttl_seconds=5,
                renewal_interval_seconds=1.0,
                instance_id="edge-instance",
                service_name=service_name,
            ),
        )

    async def test_graceful_shutdown_during_election(self):
        """Test graceful shutdown during election process."""
        reconciliation_config, election_config = self._get_configs("shutdown")
        etcd_client = MockEtcdClient()

        # Make election slow
        original_grant = etcd_client.grant_lease

        async def slow_grant(ttl):
            await asyncio.sleep(0.5)
            return await original_grant(ttl)

        etcd_client.grant_lease = slow_grant

        reconciler = MockLeaderReconciler(
            reconciliation_config=reconciliation_config,
            election_config=election_config,
            etcd_client=etcd_client,
            resources=[],
        )

        await reconciler.start_async()

        # Stop immediately during election
        await asyncio.sleep(0.1)
        await reconciler.stop_async()

        # Should have stopped gracefully
        assert reconciler.is_running is False

    async def test_callback_exception_handling(self):
        """Test that callback exceptions don't break the service."""
        reconciliation_config, election_config = self._get_configs("callback_err")

        reconciler = MockLeaderReconciler(
            reconciliation_config=reconciliation_config,
            election_config=election_config,
            etcd_client=None,  # Mock mode
            resources=[],
        )

        def failing_callback():
            raise RuntimeError("Callback error")

        reconciler.on_elected(failing_callback)

        await reconciler.start_async()

        try:
            # Should not crash despite callback failure
            await asyncio.sleep(0.2)
            assert reconciler.is_leader is True
            assert reconciler.is_running is True
        finally:
            await reconciler.stop_async()

    async def test_multiple_callbacks(self):
        """Test that multiple callbacks are all called."""
        reconciliation_config, election_config = self._get_configs("multi_cb")
        calls = []

        reconciler = MockLeaderReconciler(
            reconciliation_config=reconciliation_config,
            election_config=election_config,
            etcd_client=None,  # Mock mode
            resources=[],
        )

        reconciler.on_elected(lambda: calls.append("elected1"))
        reconciler.on_elected(lambda: calls.append("elected2"))

        await reconciler.start_async()

        try:
            await asyncio.sleep(0.2)
            assert "elected1" in calls
            assert "elected2" in calls
        finally:
            await reconciler.stop_async()

        # Check demoted callbacks were called
        assert reconciler.on_demoted_called >= 1

    async def test_polling_disabled_no_reconcile_loop(self):
        """Test that polling_enabled=False skips the reconcile loop (ADR-015).

        When polling is disabled, the service should still become leader
        but not start the periodic reconciliation loop. This allows
        pure watch-triggered reconciliation via WatchTriggeredHostedService.
        """
        service_name = get_unique_service_name("polling_disabled")
        reconciliation_config = ReconciliationConfig(
            interval_seconds=0.1,
            initial_delay_seconds=0.0,
            polling_enabled=False,  # Disable polling
            max_concurrent_reconciles=5,
            service_name=service_name,
        )
        election_config = LeaderElectionConfig(
            lease_ttl_seconds=5,
            renewal_interval_seconds=1.0,
            instance_id="test-instance-polling-disabled",
            service_name=service_name,
        )

        resources = [SampleResource(id="resource-1", name="Test Resource")]
        reconciler = MockLeaderReconciler(
            reconciliation_config=reconciliation_config,
            election_config=election_config,
            etcd_client=None,  # Mock mode
            resources=resources,
        )

        await reconciler.start_async()

        try:
            # Should become leader immediately in mock mode
            await asyncio.sleep(0.3)

            assert reconciler.is_leader is True
            assert reconciler.on_elected_called >= 1
            # Should NOT have called list_resources (no polling)
            assert reconciler.list_resources_calls == 0
            assert len(reconciler.reconcile_calls) == 0
        finally:
            await reconciler.stop_async()

    async def test_polling_enabled_runs_reconcile_loop(self):
        """Test that polling_enabled=True (default) runs the reconcile loop."""
        service_name = get_unique_service_name("polling_enabled")
        reconciliation_config = ReconciliationConfig(
            interval_seconds=0.1,
            initial_delay_seconds=0.0,
            polling_enabled=True,  # Explicit for clarity
            max_concurrent_reconciles=5,
            service_name=service_name,
        )
        election_config = LeaderElectionConfig(
            lease_ttl_seconds=5,
            renewal_interval_seconds=1.0,
            instance_id="test-instance-polling-enabled",
            service_name=service_name,
        )

        resources = [SampleResource(id="resource-1", name="Test Resource")]
        reconciler = MockLeaderReconciler(
            reconciliation_config=reconciliation_config,
            election_config=election_config,
            etcd_client=None,  # Mock mode
            resources=resources,
        )

        await reconciler.start_async()

        try:
            # Should become leader immediately in mock mode
            await asyncio.sleep(0.3)

            assert reconciler.is_leader is True
            assert reconciler.on_elected_called >= 1
            # SHOULD have called list_resources (polling is enabled)
            assert reconciler.list_resources_calls >= 1
            assert len(reconciler.reconcile_calls) >= 1
        finally:
            await reconciler.stop_async()
