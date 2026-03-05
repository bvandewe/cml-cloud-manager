"""Integration tests for LeaderElectionService.

These tests require a running etcd instance. Use docker-compose to start one:
    docker-compose up -d etcd

Run with: pytest tests/integration/test_leader_election_service.py -v
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest
from application.services.leader_election_service import (
    LeaderElectionConfig,
    LeaderElectionService,
    LeaderElectionState,
)
from integration.services.etcd_client import EtcdClient, EtcdConfig
from integration.services.etcd_state_store import EtcdStateStore

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def etcd_config() -> EtcdConfig:
    """Create test etcd configuration."""
    return EtcdConfig(
        host="localhost",
        port=2379,
        timeout=5,
        retry_attempts=3,
        retry_delay=0.5,
        key_prefix="/lcm-test-leader",  # Use test prefix to avoid conflicts
        lease_ttl=10,
    )


@pytest.fixture
async def etcd_client(etcd_config: EtcdConfig) -> AsyncGenerator[EtcdClient, None]:
    """Create and cleanup etcd client for tests."""
    client = EtcdClient(etcd_config)

    # Verify connection
    healthy = await client.health()
    if not healthy:
        pytest.skip("etcd is not available - skipping integration tests")

    yield client

    # Cleanup: delete all test keys
    try:
        await client.delete_prefix("/")  # Deletes everything under /lcm-test-leader/
    except Exception:
        pass
    await client.close()


@pytest.fixture
async def state_store(etcd_client: EtcdClient) -> AsyncGenerator[EtcdStateStore, None]:
    """Create state store for tests."""
    yield EtcdStateStore(etcd_client)


@pytest.fixture
def unique_service_name() -> str:
    """Generate a unique service name for test isolation."""
    return f"test-service-{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def leader_service(
    state_store: EtcdStateStore,
    unique_service_name: str,
) -> AsyncGenerator[LeaderElectionService, None]:
    """Create and cleanup a leader election service for tests."""
    service = LeaderElectionService(
        etcd=state_store,
        service_name=unique_service_name,
        instance_id=f"leader-{uuid.uuid4().hex[:8]}",
        lease_ttl=5,  # Short TTL for faster tests
        campaign_interval=1.0,
    )

    yield service

    # Cleanup: stop service if running
    if service._running:
        await service.stop_async()


# ============================================================================
# LeaderElectionConfig Tests
# ============================================================================


@pytest.mark.unit
class TestLeaderElectionConfig:
    """Test LeaderElectionConfig initialization."""

    def test_config_with_all_parameters(self) -> None:
        """Test config with all parameters specified."""
        config = LeaderElectionConfig(
            service_name="test-service",
            instance_id="test-instance-1",
            lease_ttl=15,
            campaign_interval=3.0,
            keepalive_interval=4.0,
        )

        assert config.service_name == "test-service"
        assert config.instance_id == "test-instance-1"
        assert config.lease_ttl == 15
        assert config.campaign_interval == 3.0
        assert config.keepalive_interval == 4.0

    def test_config_auto_generates_instance_id(self) -> None:
        """Test that instance_id is auto-generated if not provided."""
        config = LeaderElectionConfig(service_name="my-service")

        assert config.instance_id is not None
        assert config.instance_id.startswith("my-service-")
        assert len(config.instance_id) > len("my-service-")

    def test_config_auto_calculates_keepalive_interval(self) -> None:
        """Test that keepalive_interval defaults to TTL/3."""
        config = LeaderElectionConfig(
            service_name="test-service",
            lease_ttl=15,
        )

        assert config.keepalive_interval == 5.0  # 15 / 3

    def test_config_keepalive_minimum_of_one_second(self) -> None:
        """Test that keepalive_interval has a minimum of 1 second."""
        config = LeaderElectionConfig(
            service_name="test-service",
            lease_ttl=2,  # Would give 0.67 without minimum
        )

        assert config.keepalive_interval is not None
        assert config.keepalive_interval >= 1.0


# ============================================================================
# LeaderElectionService - Basic Tests
# ============================================================================


@pytest.mark.integration
class TestLeaderElectionServiceBasics:
    """Test basic leader election service operations."""

    async def test_service_initialization(
        self,
        state_store: EtcdStateStore,
        unique_service_name: str,
    ) -> None:
        """Test service initializes with correct defaults."""
        service = LeaderElectionService(
            etcd=state_store,
            service_name=unique_service_name,
        )

        assert service.service_name == unique_service_name
        assert service.instance_id is not None
        assert service.is_leader is False
        assert service.state == LeaderElectionState.STOPPED
        assert service.lease_id is None

    async def test_service_start_and_stop(
        self,
        leader_service: LeaderElectionService,
    ) -> None:
        """Test service can be started and stopped."""
        assert leader_service.state == LeaderElectionState.STOPPED

        await leader_service.start_async()

        # Should be either LEADER or STANDBY after start
        assert leader_service.state in [
            LeaderElectionState.LEADER,
            LeaderElectionState.STANDBY,
            LeaderElectionState.CAMPAIGNING,
        ]

        await leader_service.stop_async()

        assert leader_service.state == LeaderElectionState.STOPPED
        assert leader_service.is_leader is False

    async def test_service_acquires_leadership_when_alone(
        self,
        leader_service: LeaderElectionService,
    ) -> None:
        """Test that a single service acquires leadership."""
        await leader_service.start_async()

        # Wait a moment for leadership acquisition
        await asyncio.sleep(0.5)

        assert leader_service.is_leader is True
        assert leader_service.state == LeaderElectionState.LEADER
        assert leader_service.lease_id is not None

        await leader_service.stop_async()

    async def test_service_double_start_raises_error(
        self,
        leader_service: LeaderElectionService,
    ) -> None:
        """Test that starting an already running service raises error."""
        await leader_service.start_async()

        with pytest.raises(RuntimeError, match="already running"):
            await leader_service.start_async()

        await leader_service.stop_async()

    async def test_service_double_stop_is_safe(
        self,
        leader_service: LeaderElectionService,
    ) -> None:
        """Test that stopping an already stopped service is safe."""
        await leader_service.start_async()
        await leader_service.stop_async()

        # Second stop should not raise
        await leader_service.stop_async()

        assert leader_service.state == LeaderElectionState.STOPPED


# ============================================================================
# LeaderElectionService - Leader Election Tests
# ============================================================================


@pytest.mark.integration
class TestLeaderElectionServiceElection:
    """Test leader election scenarios with multiple candidates."""

    async def test_first_candidate_becomes_leader(
        self,
        state_store: EtcdStateStore,
        unique_service_name: str,
    ) -> None:
        """Test that the first candidate becomes leader."""
        leader1 = LeaderElectionService(
            etcd=state_store,
            service_name=unique_service_name,
            instance_id="candidate-1",
            lease_ttl=5,
        )

        await leader1.start_async()
        await asyncio.sleep(0.5)

        assert leader1.is_leader is True
        assert leader1.state == LeaderElectionState.LEADER

        await leader1.stop_async()

    async def test_second_candidate_becomes_standby(
        self,
        state_store: EtcdStateStore,
        unique_service_name: str,
    ) -> None:
        """Test that the second candidate becomes standby."""
        leader1 = LeaderElectionService(
            etcd=state_store,
            service_name=unique_service_name,
            instance_id="candidate-1",
            lease_ttl=5,
        )

        leader2 = LeaderElectionService(
            etcd=state_store,
            service_name=unique_service_name,
            instance_id="candidate-2",
            lease_ttl=5,
        )

        try:
            await leader1.start_async()
            await asyncio.sleep(0.5)

            await leader2.start_async()
            await asyncio.sleep(0.5)

            assert leader1.is_leader is True
            assert leader2.is_leader is False
            assert leader2.state == LeaderElectionState.STANDBY

        finally:
            await leader1.stop_async()
            await leader2.stop_async()

    async def test_standby_takes_over_when_leader_stops(
        self,
        state_store: EtcdStateStore,
        unique_service_name: str,
    ) -> None:
        """Test that standby takes over when leader stops."""
        leader1 = LeaderElectionService(
            etcd=state_store,
            service_name=unique_service_name,
            instance_id="candidate-1",
            lease_ttl=5,
            campaign_interval=0.5,  # Fast campaign for quicker test
        )

        leader2 = LeaderElectionService(
            etcd=state_store,
            service_name=unique_service_name,
            instance_id="candidate-2",
            lease_ttl=5,
            campaign_interval=0.5,
        )

        try:
            # Start leader1 first
            await leader1.start_async()
            await asyncio.sleep(0.5)
            assert leader1.is_leader is True

            # Start leader2 as standby
            await leader2.start_async()
            await asyncio.sleep(0.5)
            assert leader2.is_leader is False

            # Stop leader1 (releases leadership)
            await leader1.stop_async()

            # Wait for leader2 to take over
            await asyncio.sleep(2.0)  # Give time for campaign

            assert leader2.is_leader is True
            assert leader2.state == LeaderElectionState.LEADER

        finally:
            if leader1._running:
                await leader1.stop_async()
            if leader2._running:
                await leader2.stop_async()

    async def test_get_current_leader(
        self,
        state_store: EtcdStateStore,
        unique_service_name: str,
    ) -> None:
        """Test getting current leader information."""
        leader1 = LeaderElectionService(
            etcd=state_store,
            service_name=unique_service_name,
            instance_id="candidate-1",
            lease_ttl=5,
        )

        try:
            await leader1.start_async()
            await asyncio.sleep(0.5)

            leader_info = await leader1.get_current_leader()

            assert leader_info is not None
            assert leader_info.leader_id == "candidate-1"
            assert leader_info.service_name == unique_service_name

        finally:
            await leader1.stop_async()


# ============================================================================
# LeaderElectionService - Callback Tests
# ============================================================================


@pytest.mark.integration
class TestLeaderElectionServiceCallbacks:
    """Test leadership change callbacks."""

    async def test_leadership_acquired_callback_called(
        self,
        state_store: EtcdStateStore,
        unique_service_name: str,
    ) -> None:
        """Test that leadership acquired callback is called."""
        acquired_events: list[str] = []

        leader = LeaderElectionService(
            etcd=state_store,
            service_name=unique_service_name,
            instance_id="candidate-1",
            lease_ttl=5,
        )

        @leader.on_leadership_acquired
        async def handle_acquired() -> None:
            acquired_events.append("acquired")

        try:
            await leader.start_async()
            await asyncio.sleep(0.5)

            assert len(acquired_events) == 1
            assert acquired_events[0] == "acquired"

        finally:
            await leader.stop_async()

    async def test_leadership_lost_callback_called_on_stop(
        self,
        state_store: EtcdStateStore,
        unique_service_name: str,
    ) -> None:
        """Test that leadership lost callback is called when stopping."""
        lost_events: list[str] = []

        leader = LeaderElectionService(
            etcd=state_store,
            service_name=unique_service_name,
            instance_id="candidate-1",
            lease_ttl=5,
        )

        @leader.on_leadership_lost
        async def handle_lost() -> None:
            lost_events.append("lost")

        try:
            await leader.start_async()
            await asyncio.sleep(0.5)
            assert leader.is_leader is True

            await leader.stop_async()

            assert len(lost_events) == 1
            assert lost_events[0] == "lost"

        finally:
            if leader._running:
                await leader.stop_async()

    async def test_multiple_callbacks_all_called(
        self,
        state_store: EtcdStateStore,
        unique_service_name: str,
    ) -> None:
        """Test that multiple callbacks are all called."""
        events: list[str] = []

        leader = LeaderElectionService(
            etcd=state_store,
            service_name=unique_service_name,
            instance_id="candidate-1",
            lease_ttl=5,
        )

        @leader.on_leadership_acquired
        async def handle_acquired_1() -> None:
            events.append("acquired-1")

        @leader.on_leadership_acquired
        async def handle_acquired_2() -> None:
            events.append("acquired-2")

        try:
            await leader.start_async()
            await asyncio.sleep(0.5)

            assert "acquired-1" in events
            assert "acquired-2" in events

        finally:
            await leader.stop_async()

    async def test_callback_error_does_not_stop_service(
        self,
        state_store: EtcdStateStore,
        unique_service_name: str,
    ) -> None:
        """Test that callback errors don't crash the service."""
        acquired_events: list[str] = []

        leader = LeaderElectionService(
            etcd=state_store,
            service_name=unique_service_name,
            instance_id="candidate-1",
            lease_ttl=5,
        )

        @leader.on_leadership_acquired
        async def handle_acquired_error() -> None:
            raise ValueError("Intentional error in callback")

        @leader.on_leadership_acquired
        async def handle_acquired_success() -> None:
            acquired_events.append("success")

        try:
            await leader.start_async()
            await asyncio.sleep(0.5)

            # Service should still be running despite error
            assert leader.is_leader is True
            assert "success" in acquired_events

        finally:
            await leader.stop_async()


# ============================================================================
# LeaderElectionService - Status Tests
# ============================================================================


@pytest.mark.integration
class TestLeaderElectionServiceStatus:
    """Test leader election status reporting."""

    async def test_get_status_when_stopped(
        self,
        leader_service: LeaderElectionService,
    ) -> None:
        """Test status when service is stopped."""
        status = await leader_service.get_status()

        assert status.state == LeaderElectionState.STOPPED
        assert status.is_leader is False
        assert status.lease_id is None
        assert status.leadership_acquired_at is None

    async def test_get_status_when_leader(
        self,
        leader_service: LeaderElectionService,
    ) -> None:
        """Test status when service is leader."""
        await leader_service.start_async()
        await asyncio.sleep(0.5)

        status = await leader_service.get_status()

        assert status.state == LeaderElectionState.LEADER
        assert status.is_leader is True
        assert status.instance_id == leader_service.instance_id
        assert status.leader_id == leader_service.instance_id
        assert status.lease_id is not None
        assert status.leadership_acquired_at is not None

        await leader_service.stop_async()

    async def test_get_status_when_standby(
        self,
        state_store: EtcdStateStore,
        unique_service_name: str,
    ) -> None:
        """Test status when service is standby."""
        leader1 = LeaderElectionService(
            etcd=state_store,
            service_name=unique_service_name,
            instance_id="candidate-1",
            lease_ttl=5,
        )

        leader2 = LeaderElectionService(
            etcd=state_store,
            service_name=unique_service_name,
            instance_id="candidate-2",
            lease_ttl=5,
        )

        try:
            await leader1.start_async()
            await asyncio.sleep(0.5)

            await leader2.start_async()
            await asyncio.sleep(0.5)

            status = await leader2.get_status()

            assert status.state == LeaderElectionState.STANDBY
            assert status.is_leader is False
            assert status.instance_id == "candidate-2"
            assert status.leader_id == "candidate-1"  # Current leader

        finally:
            await leader1.stop_async()
            await leader2.stop_async()


# ============================================================================
# LeaderElectionService - Lease Keepalive Tests
# ============================================================================


@pytest.mark.integration
class TestLeaderElectionServiceKeepalive:
    """Test lease keepalive functionality."""

    async def test_leader_maintains_leadership_with_keepalive(
        self,
        state_store: EtcdStateStore,
        unique_service_name: str,
    ) -> None:
        """Test that leader maintains leadership through keepalive."""
        leader = LeaderElectionService(
            etcd=state_store,
            service_name=unique_service_name,
            instance_id="candidate-1",
            lease_ttl=3,  # Short TTL
        )

        try:
            await leader.start_async()
            await asyncio.sleep(0.5)
            assert leader.is_leader is True

            # Wait longer than TTL to verify keepalive works
            await asyncio.sleep(5.0)

            assert leader.is_leader is True
            assert leader.state == LeaderElectionState.LEADER

        finally:
            await leader.stop_async()


# ============================================================================
# LeaderElectionService - Edge Cases
# ============================================================================


@pytest.mark.integration
class TestLeaderElectionServiceEdgeCases:
    """Test edge cases and error handling."""

    async def test_multiple_services_same_instance_id(
        self,
        state_store: EtcdStateStore,
        unique_service_name: str,
    ) -> None:
        """Test behavior when multiple services have same instance ID."""
        # This should not normally happen, but we should handle it gracefully
        leader1 = LeaderElectionService(
            etcd=state_store,
            service_name=unique_service_name,
            instance_id="same-id",
            lease_ttl=5,
        )

        leader2 = LeaderElectionService(
            etcd=state_store,
            service_name=unique_service_name,
            instance_id="same-id",
            lease_ttl=5,
        )

        try:
            await leader1.start_async()
            await asyncio.sleep(0.5)
            assert leader1.is_leader is True

            await leader2.start_async()
            await asyncio.sleep(0.5)

            # Leader2 should be standby (can't acquire same leadership)
            assert leader2.is_leader is False

        finally:
            await leader1.stop_async()
            await leader2.stop_async()

    async def test_different_services_independent_leadership(
        self,
        state_store: EtcdStateStore,
    ) -> None:
        """Test that different services have independent leadership."""
        service_name_1 = f"service-1-{uuid.uuid4().hex[:8]}"
        service_name_2 = f"service-2-{uuid.uuid4().hex[:8]}"

        leader1 = LeaderElectionService(
            etcd=state_store,
            service_name=service_name_1,
            instance_id="instance-1",
            lease_ttl=5,
        )

        leader2 = LeaderElectionService(
            etcd=state_store,
            service_name=service_name_2,
            instance_id="instance-2",
            lease_ttl=5,
        )

        try:
            await leader1.start_async()
            await leader2.start_async()
            await asyncio.sleep(0.5)

            # Both should be leaders of their respective services
            assert leader1.is_leader is True
            assert leader2.is_leader is True

        finally:
            await leader1.stop_async()
            await leader2.stop_async()
