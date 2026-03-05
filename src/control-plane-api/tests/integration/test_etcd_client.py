"""Integration tests for etcd client and state store.

These tests require a running etcd instance. Use docker-compose to start one:
    docker-compose up -d etcd

Run with: pytest tests/integration/test_etcd_client.py -v
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from integration.exceptions import EtcdConnectionException
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
        key_prefix="/lcm-test",  # Use test prefix to avoid conflicts
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
        await client.delete_prefix("/")  # Deletes everything under /lcm-test/
    except Exception:
        pass
    await client.close()


@pytest.fixture
async def state_store(etcd_client: EtcdClient) -> AsyncGenerator[EtcdStateStore, None]:
    """Create state store for tests."""
    yield EtcdStateStore(etcd_client)


# ============================================================================
# EtcdClient Tests - Key-Value Operations
# ============================================================================


@pytest.mark.integration
class TestEtcdClientKeyValueOperations:
    """Test basic key-value operations."""

    async def test_put_and_get(self, etcd_client: EtcdClient) -> None:
        """Test storing and retrieving a value."""
        key = f"/test/{uuid.uuid4()}"
        value = "test-value-123"

        await etcd_client.put(key, value)
        result = await etcd_client.get(key)

        assert result is not None
        assert result.value == value
        assert result.key == key

    async def test_get_nonexistent_key(self, etcd_client: EtcdClient) -> None:
        """Test getting a key that doesn't exist."""
        result = await etcd_client.get("/nonexistent/key")
        assert result is None

    async def test_put_and_delete(self, etcd_client: EtcdClient) -> None:
        """Test deleting a key."""
        key = f"/test/{uuid.uuid4()}"

        await etcd_client.put(key, "value")
        assert await etcd_client.get(key) is not None

        deleted = await etcd_client.delete(key)
        assert deleted is True

        assert await etcd_client.get(key) is None

    async def test_delete_nonexistent_key(self, etcd_client: EtcdClient) -> None:
        """Test deleting a key that doesn't exist."""
        deleted = await etcd_client.delete("/nonexistent/key")
        assert deleted is False

    async def test_get_prefix(self, etcd_client: EtcdClient) -> None:
        """Test getting multiple keys by prefix."""
        prefix = f"/test/prefix/{uuid.uuid4()}"

        # Create multiple keys
        await etcd_client.put(f"{prefix}/key1", "value1")
        await etcd_client.put(f"{prefix}/key2", "value2")
        await etcd_client.put(f"{prefix}/key3", "value3")

        results = await etcd_client.get_prefix(prefix)

        assert len(results) == 3
        values = {kv.value for kv in results}
        assert values == {"value1", "value2", "value3"}

    async def test_delete_prefix(self, etcd_client: EtcdClient) -> None:
        """Test deleting multiple keys by prefix."""
        prefix = f"/test/delete-prefix/{uuid.uuid4()}"

        await etcd_client.put(f"{prefix}/key1", "value1")
        await etcd_client.put(f"{prefix}/key2", "value2")

        deleted_count = await etcd_client.delete_prefix(prefix)
        assert deleted_count >= 2

        results = await etcd_client.get_prefix(prefix)
        assert len(results) == 0

    async def test_put_if_not_exists_success(self, etcd_client: EtcdClient) -> None:
        """Test conditional put when key doesn't exist."""
        key = f"/test/{uuid.uuid4()}"

        success = await etcd_client.put_if_not_exists(key, "first-value")
        assert success is True

        result = await etcd_client.get(key)
        assert result is not None
        assert result.value == "first-value"

    async def test_put_if_not_exists_failure(self, etcd_client: EtcdClient) -> None:
        """Test conditional put when key already exists."""
        key = f"/test/{uuid.uuid4()}"

        # First put succeeds
        await etcd_client.put(key, "existing-value")

        # Second put should fail
        success = await etcd_client.put_if_not_exists(key, "new-value")
        assert success is False

        # Value should be unchanged
        result = await etcd_client.get(key)
        assert result is not None
        assert result.value == "existing-value"


# ============================================================================
# EtcdClient Tests - Lease Operations
# ============================================================================


@pytest.mark.integration
class TestEtcdClientLeaseOperations:
    """Test lease management operations."""

    async def test_grant_lease(self, etcd_client: EtcdClient) -> None:
        """Test creating a lease."""
        lease = await etcd_client.grant_lease(ttl=30)

        assert lease.lease_id > 0
        assert lease.ttl > 0
        assert lease.granted_ttl == 30

    async def test_put_with_lease(self, etcd_client: EtcdClient) -> None:
        """Test storing a key with a lease."""
        lease = await etcd_client.grant_lease(ttl=60)
        key = f"/test/{uuid.uuid4()}"

        await etcd_client.put(key, "ephemeral-value", lease_id=lease.lease_id)

        result = await etcd_client.get(key)
        assert result is not None
        assert result.lease_id == lease.lease_id

    async def test_revoke_lease_deletes_keys(self, etcd_client: EtcdClient) -> None:
        """Test that revoking a lease deletes associated keys."""
        lease = await etcd_client.grant_lease(ttl=60)
        key = f"/test/{uuid.uuid4()}"

        await etcd_client.put(key, "ephemeral-value", lease_id=lease.lease_id)
        assert await etcd_client.get(key) is not None

        await etcd_client.revoke_lease(lease.lease_id)

        result = await etcd_client.get(key)
        assert result is None

    async def test_refresh_lease(self, etcd_client: EtcdClient) -> None:
        """Test refreshing a lease."""
        lease = await etcd_client.grant_lease(ttl=10)

        refreshed = await etcd_client.refresh_lease(lease.lease_id)

        assert refreshed is not None
        assert refreshed.lease_id == lease.lease_id
        assert refreshed.ttl > 0


# ============================================================================
# EtcdClient Tests - Health & Status
# ============================================================================


@pytest.mark.integration
class TestEtcdClientHealthStatus:
    """Test health check and status operations."""

    async def test_health_check(self, etcd_client: EtcdClient) -> None:
        """Test health check returns true when connected."""
        healthy = await etcd_client.health()
        assert healthy is True

    async def test_status(self, etcd_client: EtcdClient) -> None:
        """Test getting cluster status."""
        status = await etcd_client.status()

        assert "version" in status
        assert "db_size" in status
        assert "leader" in status


# ============================================================================
# EtcdStateStore Tests - Instance State
# ============================================================================


@pytest.mark.integration
class TestEtcdStateStoreSessionState:
    """Test instance state operations."""

    async def test_set_and_get_session_state(self, state_store: EtcdStateStore) -> None:
        """Test setting and getting instance state."""
        session_id = str(uuid.uuid4())

        await state_store.set_session_state(session_id, "RUNNING")
        state = await state_store.get_session_state(session_id)

        assert state == "RUNNING"

    async def test_get_nonexistent_session_state(self, state_store: EtcdStateStore) -> None:
        """Test getting state for nonexistent instance."""
        state = await state_store.get_session_state("nonexistent-id")
        assert state is None

    async def test_delete_session_state(self, state_store: EtcdStateStore) -> None:
        """Test deleting instance state."""
        session_id = str(uuid.uuid4())

        await state_store.set_session_state(session_id, "TERMINATED")
        deleted = await state_store.delete_session_state(session_id)

        assert deleted is True
        assert await state_store.get_session_state(session_id) is None

    async def test_get_sessions_by_state(self, state_store: EtcdStateStore) -> None:
        """Test getting all instances in a specific state."""
        # Create instances in different states
        pending_ids = [str(uuid.uuid4()) for _ in range(3)]
        running_ids = [str(uuid.uuid4()) for _ in range(2)]

        for inst_id in pending_ids:
            await state_store.set_session_state(inst_id, "PENDING")
        for inst_id in running_ids:
            await state_store.set_session_state(inst_id, "RUNNING")

        # Query by state
        pending_results = await state_store.get_sessions_by_state("PENDING")
        running_results = await state_store.get_sessions_by_state("RUNNING")

        assert set(pending_ids).issubset(set(pending_results))
        assert set(running_ids).issubset(set(running_results))

    async def test_get_all_session_states(self, state_store: EtcdStateStore) -> None:
        """Test getting all instance states."""
        session_id = str(uuid.uuid4())
        await state_store.set_session_state(session_id, "COLLECTING")

        all_states = await state_store.get_all_session_states()

        assert session_id in all_states
        assert all_states[session_id] == "COLLECTING"


# ============================================================================
# EtcdStateStore Tests - Worker State
# ============================================================================


@pytest.mark.integration
class TestEtcdStateStoreWorkerState:
    """Test worker state operations."""

    async def test_set_and_get_worker_state(self, state_store: EtcdStateStore) -> None:
        """Test setting and getting worker state."""
        worker_id = str(uuid.uuid4())

        await state_store.set_worker_state(worker_id, "ACTIVE")
        state = await state_store.get_worker_state(worker_id)

        assert state == "ACTIVE"

    async def test_delete_worker_state(self, state_store: EtcdStateStore) -> None:
        """Test deleting worker state."""
        worker_id = str(uuid.uuid4())

        await state_store.set_worker_state(worker_id, "DRAINING")
        deleted = await state_store.delete_worker_state(worker_id)

        assert deleted is True
        assert await state_store.get_worker_state(worker_id) is None


# ============================================================================
# EtcdStateStore Tests - Port Allocation
# ============================================================================


@pytest.mark.integration
class TestEtcdStateStorePortAllocation:
    """Test port allocation operations."""

    async def test_allocate_session_ports(self, state_store: EtcdStateStore) -> None:
        """Test allocating ports for an instance."""
        worker_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        ports = {"http": 8080, "ssh": 2222}

        success = await state_store.allocate_session_ports(worker_id, session_id, ports)

        assert success is True

        allocation = await state_store.get_worker_ports(worker_id)
        assert allocation is not None
        assert session_id in allocation.allocations
        assert allocation.allocations[session_id] == ports

    async def test_port_allocation_conflict(self, state_store: EtcdStateStore) -> None:
        """Test that duplicate port allocation fails."""
        worker_id = str(uuid.uuid4())
        instance_1 = str(uuid.uuid4())
        instance_2 = str(uuid.uuid4())

        # First allocation
        await state_store.allocate_session_ports(worker_id, instance_1, {"http": 8080})

        # Second allocation with conflicting port
        success = await state_store.allocate_session_ports(worker_id, instance_2, {"http": 8080})

        assert success is False

    async def test_release_session_ports(self, state_store: EtcdStateStore) -> None:
        """Test releasing ports for an instance."""
        worker_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        ports = {"http": 8080, "ssh": 2222}

        await state_store.allocate_session_ports(worker_id, session_id, ports)
        released = await state_store.release_session_ports(worker_id, session_id)

        assert released == ports

        allocation = await state_store.get_worker_ports(worker_id)
        assert allocation is not None
        assert session_id not in allocation.allocations

    async def test_get_allocated_ports_for_worker(self, state_store: EtcdStateStore) -> None:
        """Test getting all allocated ports for a worker."""
        worker_id = str(uuid.uuid4())

        await state_store.allocate_session_ports(worker_id, str(uuid.uuid4()), {"http": 8080})
        await state_store.allocate_session_ports(worker_id, str(uuid.uuid4()), {"ssh": 2222, "api": 3000})

        allocated = await state_store.get_allocated_ports_for_worker(worker_id)

        assert allocated == {8080, 2222, 3000}


# ============================================================================
# EtcdStateStore Tests - Leader Election
# ============================================================================


@pytest.mark.integration
class TestEtcdStateStoreLeaderElection:
    """Test leader election operations."""

    async def test_acquire_leadership(self, state_store: EtcdStateStore) -> None:
        """Test acquiring leadership."""
        service_name = f"test-service-{uuid.uuid4()}"
        leader_id = "leader-1"

        is_leader, lease = await state_store.try_acquire_leadership(service_name, leader_id)

        assert is_leader is True
        assert lease is not None
        assert lease.lease_id > 0

        # Cleanup
        await state_store.release_leadership(service_name, lease.lease_id)

    async def test_leadership_conflict(self, state_store: EtcdStateStore) -> None:
        """Test that second leader candidate fails."""
        service_name = f"test-service-{uuid.uuid4()}"

        # First leader acquires
        is_leader_1, lease_1 = await state_store.try_acquire_leadership(service_name, "leader-1")
        assert is_leader_1 is True

        # Second leader fails
        is_leader_2, lease_2 = await state_store.try_acquire_leadership(service_name, "leader-2")
        assert is_leader_2 is False
        assert lease_2 is None

        # Cleanup
        if lease_1:
            await state_store.release_leadership(service_name, lease_1.lease_id)

    async def test_get_current_leader(self, state_store: EtcdStateStore) -> None:
        """Test getting current leader info."""
        service_name = f"test-service-{uuid.uuid4()}"
        leader_id = "leader-1"

        is_leader, lease = await state_store.try_acquire_leadership(service_name, leader_id)
        assert is_leader is True

        leader_info = await state_store.get_current_leader(service_name)

        assert leader_info is not None
        assert leader_info.leader_id == leader_id
        assert leader_info.service_name == service_name

        # Cleanup
        if lease:
            await state_store.release_leadership(service_name, lease.lease_id)

    async def test_release_leadership(self, state_store: EtcdStateStore) -> None:
        """Test releasing leadership."""
        service_name = f"test-service-{uuid.uuid4()}"

        is_leader, lease = await state_store.try_acquire_leadership(service_name, "leader-1")
        assert is_leader is True
        assert lease is not None

        await state_store.release_leadership(service_name, lease.lease_id)

        # Leadership should be available again
        is_leader_2, lease_2 = await state_store.try_acquire_leadership(service_name, "leader-2")
        assert is_leader_2 is True

        # Cleanup
        if lease_2:
            await state_store.release_leadership(service_name, lease_2.lease_id)


# ============================================================================
# Connection Error Handling Tests
# ============================================================================


@pytest.mark.integration
class TestEtcdConnectionErrorHandling:
    """Test connection error handling and retry logic."""

    async def test_invalid_host_raises_connection_exception(self) -> None:
        """Test that invalid host raises appropriate exception."""
        config = EtcdConfig(
            host="invalid-host-that-does-not-exist",
            port=2379,
            timeout=1,
            retry_attempts=1,
            retry_delay=0.1,
        )
        client = EtcdClient(config)

        with pytest.raises(EtcdConnectionException):
            await client.get("/test")
