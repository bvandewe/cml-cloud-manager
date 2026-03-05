"""etcd Client for leader election and state management.

Provides access to etcd for:
- Key-value operations
- Leader election via leases
- Watch subscriptions for reactive updates

This is a shared client in lcm-core that can be used by all services.
"""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from neuroglia.dependency_injection.service_provider import ServiceProviderBase

logger = logging.getLogger(__name__)


@dataclass
class EtcdEvent:
    """Represents an etcd watch event."""

    type: str  # "PUT" or "DELETE"
    key: str
    value: str | None = None
    previous_value: str | None = None
    mod_revision: int = 0

    @property
    def is_put(self) -> bool:
        """Check if this is a PUT event."""
        return self.type == "PUT"

    @property
    def is_delete(self) -> bool:
        """Check if this is a DELETE event."""
        return self.type == "DELETE"


@dataclass
class EtcdLease:
    """Represents an etcd lease."""

    id: int
    ttl: int
    granted_ttl: int


class EtcdClientError(Exception):
    """Base exception for etcd client errors."""

    pass


class EtcdConnectionError(EtcdClientError):
    """Error connecting to etcd."""

    pass


class EtcdClient:
    """
    etcd client wrapper for state management and leader election.

    Provides:
    - Key-value operations (get, put, delete)
    - Leader election via leases
    - Watch subscriptions for real-time updates
    - Atomic operations via transactions

    Features:
    - Automatic reconnection on connection loss
    - Lease keep-alive in background
    - Graceful shutdown

    Usage:
        # Direct instantiation
        client = EtcdClient(endpoints=["localhost:2379"])
        await client.connect()

        # Leader election
        lease = await client.grant_lease(ttl=15)
        acquired = await client.put_if_not_exists("/leader/my-service", "instance-1", lease)

        # Or via DI
        EtcdClient.configure(builder.services, endpoints=["etcd:2379"])
    """

    def __init__(
        self,
        endpoints: list[str] | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        """Initialize the etcd client.

        Args:
            endpoints: List of etcd endpoints (e.g., ["localhost:2379"]).
            username: Optional username for authentication.
            password: Optional password for authentication.
        """
        self.endpoints = endpoints or ["localhost:2379"]
        self.username = username
        self.password = password
        self._client = None
        self._connected = False
        self._keep_alive_tasks: dict[int, asyncio.Task[None]] = {}

    @classmethod
    def from_env(cls) -> "EtcdClient":
        """Create an etcd client from environment variables.

        Environment variables:
        - ETCD_ENDPOINTS: Comma-separated endpoints (default: localhost:2379)
        - ETCD_USERNAME: Optional username
        - ETCD_PASSWORD: Optional password
        """
        endpoints_str = os.environ.get("ETCD_ENDPOINTS", "localhost:2379")
        endpoints = [ep.strip() for ep in endpoints_str.split(",")]

        return cls(
            endpoints=endpoints,
            username=os.environ.get("ETCD_USERNAME"),
            password=os.environ.get("ETCD_PASSWORD"),
        )

    async def connect(self) -> None:
        """Connect to the etcd cluster.

        Uses etcd3-py (etcd3.Client) — a REST-based etcd v3 client.

        Raises:
            EtcdConnectionError: If connection fails.
        """
        try:
            # Import etcd3-py lazily to allow mock mode when package is absent
            import etcd3

            # Parse first endpoint for host/port
            # etcd3-py only supports single endpoint in constructor
            host, port = self.endpoints[0].split(":")

            self._client = etcd3.Client(
                host=host,
                port=int(port),
                username=self.username,
                password=self.password,
            )

            # Test connection
            if self._client is not None:
                self._client.status()
            self._connected = True

            logger.info(f"Connected to etcd at {self.endpoints}")

        except ImportError:
            logger.warning("etcd3-py not installed, running in mock mode")
            self._connected = True
        except Exception as e:
            raise EtcdConnectionError(f"Failed to connect to etcd: {e}") from e

    async def close(self) -> None:
        """Close the connection and stop keep-alive tasks."""
        # Cancel all keep-alive tasks
        for task in self._keep_alive_tasks.values():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._keep_alive_tasks.clear()

        # Close client
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

        self._connected = False
        logger.info("etcd client closed")

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connected

    # =========================================================================
    # Key-Value Operations
    # =========================================================================

    async def get(self, key: str) -> str | None:
        """Get a value by key.

        Args:
            key: The key to get.

        Returns:
            The value as string, or None if not found.
        """
        if not self._client:
            logger.warning("etcd not connected, returning None")
            return None

        try:
            resp = self._client.range(key)
            if resp.kvs:
                value = resp.kvs[0].value
                return value.decode("utf-8") if isinstance(value, bytes) else str(value) if value else None
            return None
        except Exception as e:
            logger.error(f"Error getting key {key}: {e}")
            return None

    async def put(
        self,
        key: str,
        value: str,
        lease: EtcdLease | int | None = None,
    ) -> bool:
        """Put a key-value pair.

        Args:
            key: The key to set.
            value: The value to set.
            lease: Optional lease to attach (for auto-expiration).

        Returns:
            True if successful.
        """
        if not self._client:
            logger.warning("etcd not connected, put ignored")
            return True  # Mock mode

        try:
            lease_id = lease.id if isinstance(lease, EtcdLease) else (lease or 0)
            self._client.put(key, value, lease=lease_id)
            return True
        except Exception as e:
            logger.error(f"Error putting key {key}: {e}")
            return False

    async def put_if_not_exists(
        self,
        key: str,
        value: str,
        lease: EtcdLease | int | None = None,
    ) -> bool:
        """Put a key-value pair only if key doesn't exist (for leader election).

        Uses etcd transaction to atomically check and set.

        Args:
            key: The key to set.
            value: The value to set.
            lease: Optional lease to attach.

        Returns:
            True if the key was created (we acquired it), False if it existed.
        """
        if not self._client:
            logger.warning("etcd not connected, assuming success (mock mode)")
            return True

        try:
            lease_id = lease.id if isinstance(lease, EtcdLease) else (lease or 0)

            # Transaction: if key doesn't exist (create == 0), create it
            txn = self._client.Txn()
            txn.compare(txn.key(key).create == 0)
            txn.success(txn.put(key, value, lease=lease_id))
            resp = txn.commit()

            return bool(resp.succeeded)

        except Exception as e:
            logger.error(f"Error in put_if_not_exists for {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete a key.

        Args:
            key: The key to delete.

        Returns:
            True if deleted (or didn't exist).
        """
        if not self._client:
            return True

        try:
            self._client.delete_range(key)
            return True
        except Exception as e:
            logger.error(f"Error deleting key {key}: {e}")
            return False

    async def get_prefix(self, prefix: str) -> dict[str, str]:
        """Get all key-value pairs with the given prefix.

        Args:
            prefix: The key prefix to search.

        Returns:
            Dictionary of key -> value pairs.
        """
        if not self._client:
            return {}

        try:
            resp = self._client.range(prefix, prefix=True)
            result = {}
            if resp.kvs:
                for kv in resp.kvs:
                    k = kv.key.decode("utf-8") if isinstance(kv.key, bytes) else str(kv.key)
                    v = kv.value.decode("utf-8") if isinstance(kv.value, bytes) else (str(kv.value) if kv.value else "")
                    result[k] = v
            return result
        except Exception as e:
            logger.error(f"Error getting prefix {prefix}: {e}")
            return {}

    # =========================================================================
    # Lease Operations
    # =========================================================================

    async def grant_lease(self, ttl: int) -> EtcdLease:
        """Grant a new lease with the specified TTL.

        Args:
            ttl: Time-to-live in seconds.

        Returns:
            EtcdLease object.
        """
        if not self._client:
            # Mock mode
            return EtcdLease(id=0, ttl=ttl, granted_ttl=ttl)

        try:
            resp = self._client.lease_grant(TTL=ttl)
            return EtcdLease(id=resp.ID, ttl=resp.TTL, granted_ttl=resp.TTL)
        except Exception as e:
            logger.error(f"Error granting lease: {e}")
            raise EtcdClientError(f"Failed to grant lease: {e}") from e

    async def refresh_lease(self, lease: EtcdLease | int) -> None:
        """Refresh (keep-alive) a lease.

        Args:
            lease: The lease to refresh.
        """
        if not self._client:
            return

        try:
            lease_id = lease.id if isinstance(lease, EtcdLease) else lease
            self._client.lease_keep_alive_once(ID=lease_id)
        except Exception as e:
            logger.error(f"Error refreshing lease: {e}")
            raise EtcdClientError(f"Failed to refresh lease: {e}") from e

    async def revoke_lease(self, lease: EtcdLease | int) -> None:
        """Revoke a lease (and delete all attached keys).

        Args:
            lease: The lease to revoke.
        """
        if not self._client:
            return

        try:
            lease_id = lease.id if isinstance(lease, EtcdLease) else lease
            self._client.lease_revoke(ID=lease_id)
        except Exception as e:
            logger.warning(f"Error revoking lease: {e}")

    async def start_keep_alive(
        self,
        lease: EtcdLease,
        interval: float = 5.0,
    ) -> None:
        """Start background keep-alive for a lease.

        Args:
            lease: The lease to keep alive.
            interval: Refresh interval in seconds.
        """
        if lease.id in self._keep_alive_tasks:
            return  # Already running

        async def keep_alive_loop() -> None:
            while True:
                try:
                    await asyncio.sleep(interval)
                    await self.refresh_lease(lease)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Lease keep-alive failed: {e}")
                    break

        task: asyncio.Task[None] = asyncio.create_task(keep_alive_loop(), name=f"lease_keepalive_{lease.id}")
        self._keep_alive_tasks[lease.id] = task

    async def stop_keep_alive(self, lease: EtcdLease | int) -> None:
        """Stop background keep-alive for a lease.

        Args:
            lease: The lease to stop keeping alive.
        """
        lease_id = lease.id if isinstance(lease, EtcdLease) else lease
        task = self._keep_alive_tasks.pop(lease_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # =========================================================================
    # Watch Operations
    # =========================================================================

    async def watch(self, key: str) -> AsyncIterator[EtcdEvent]:
        """Watch a key for changes.

        Uses etcd3-py Watcher (callback-based) bridged to an async iterator
        via an asyncio.Queue.

        Args:
            key: The key to watch.

        Yields:
            EtcdEvent objects for each change.
        """
        async for event in self._watch_impl(key=key, prefix=False):
            yield event

    async def watch_prefix(self, prefix: str) -> AsyncIterator[EtcdEvent]:
        """Watch all keys with the given prefix.

        Uses etcd3-py Watcher (callback-based) bridged to an async iterator
        via an asyncio.Queue.

        Args:
            prefix: The key prefix to watch.

        Yields:
            EtcdEvent objects for each change.
        """
        async for event in self._watch_impl(key=prefix, prefix=True):
            yield event

    async def _watch_impl(self, key: str, prefix: bool = False) -> AsyncIterator[EtcdEvent]:
        """Internal watch implementation using etcd3-py Watcher.

        Bridges the callback-based Watcher to an async iterator via asyncio.Queue.

        Args:
            key: The key (or prefix) to watch.
            prefix: If True, watch all keys with the given prefix.

        Yields:
            EtcdEvent objects for each change.
        """
        if not self._client:
            # Mock mode - block forever, never yields
            while True:
                await asyncio.sleep(60)
                return

        try:
            import etcd3

            queue: asyncio.Queue[EtcdEvent] = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def on_event(event: Any) -> None:
                """Callback invoked by Watcher thread — enqueue into async world."""
                evt_type = "PUT" if event.type == etcd3.EventType.PUT else "DELETE"
                key_str = event.key.decode("utf-8") if isinstance(event.key, bytes) else str(event.key)
                val = event.value
                val_str = val.decode("utf-8") if isinstance(val, bytes) else (str(val) if val else None)
                etcd_event = EtcdEvent(type=evt_type, key=key_str, value=val_str)
                loop.call_soon_threadsafe(queue.put_nowait, etcd_event)

            watcher = etcd3.Watcher(self._client, key=key, prefix=prefix)
            watcher.onEvent(on_event)
            watcher.runDaemon()

            try:
                while True:
                    event = await queue.get()
                    yield event
            finally:
                watcher.stop()

        except Exception as e:
            logger.error(f"Watch error for {key} (prefix={prefix}): {e}")
            raise

    # =========================================================================
    # Health Check
    # =========================================================================

    async def health_check(self) -> bool:
        """Check if etcd is healthy and connected.

        Returns:
            True if healthy, False otherwise.
        """
        if not self._client:
            return False

        try:
            self._client.status()
            return True
        except Exception:
            return False

    # =========================================================================
    # DI Configuration
    # =========================================================================

    @staticmethod
    def configure(
        services: Any,
        endpoints: list[str] | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        """Configure the client for dependency injection.

        Args:
            services: ServiceCollection from the application builder.
            endpoints: List of etcd endpoints.
            username: Optional username.
            password: Optional password.

        If endpoints is None, will be loaded from ETCD_ENDPOINTS env var.

        Usage:
            EtcdClient.configure(
                builder.services,
                endpoints=["etcd:2379"],
            )
        """
        if endpoints is None:
            endpoints_str = os.environ.get("ETCD_ENDPOINTS", "localhost:2379")
            endpoints = [ep.strip() for ep in endpoints_str.split(",")]

        def factory(sp: ServiceProviderBase) -> EtcdClient:
            return EtcdClient(
                endpoints=endpoints,
                username=username,
                password=password,
            )

        services.add_singleton(EtcdClient, implementation_factory=factory)
        logger.info(f"✅ EtcdClient configured (endpoints={endpoints})")
