"""Async etcd client for state coordination using HTTP/JSON API.

This module provides a native async etcd client using httpx with:
- Connection pooling and retry logic
- Key-value operations (get, put, delete)
- Lease management for leader election
- Watch functionality for reactive updates
- Health check capabilities

Uses etcd's v3 HTTP/JSON API (gRPC-gateway) for compatibility and native async support.
Key patterns follow ADR-005: etcd for state coordination, MongoDB for spec storage.
"""

import asyncio
import base64
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from integration.exceptions import (
    EtcdConnectionException,
    EtcdLeaseExpiredException,
    EtcdWatchCancelledException,
)

if TYPE_CHECKING:
    from neuroglia.hosting.web import WebApplicationBuilder

log = logging.getLogger(__name__)


@dataclass
class EtcdConfig:
    """Configuration for etcd client connection."""

    host: str
    port: int
    timeout: int = 5
    retry_attempts: int = 3
    retry_delay: float = 1.0
    key_prefix: str = "/lcm"
    lease_ttl: int = 30


@dataclass
class EtcdKeyValue:
    """Represents a key-value pair from etcd."""

    key: str
    value: str
    mod_revision: int
    create_revision: int
    version: int
    lease_id: int | None = None


@dataclass
class EtcdWatchEvent:
    """Represents a watch event from etcd."""

    key: str
    value: str | None  # None for DELETE events
    event_type: str  # "PUT" or "DELETE"
    mod_revision: int


@dataclass
class EtcdLease:
    """Represents an etcd lease."""

    lease_id: int
    ttl: int
    granted_ttl: int


class EtcdClient:
    """Async etcd client using HTTP/JSON API (gRPC-gateway).

    This client provides:
    - Native async key-value operations (get, put, delete)
    - Lease management for leader election and ephemeral keys
    - Watch functionality for reactive state updates
    - Connection pooling via httpx
    - Automatic retry on transient failures
    - Health check for monitoring

    Example:
        ```python
        client = EtcdClient(EtcdConfig(host="localhost", port=2379))
        await client.put("my-key", "my-value")
        value = await client.get("my-key")
        ```
    """

    def __init__(self, config: EtcdConfig):
        """Initialize the etcd client.

        Args:
            config: etcd connection configuration
        """
        self._config = config
        self._base_url = f"http://{config.host}:{config.port}"
        self._client: httpx.AsyncClient | None = None
        self._active_watches: dict[int, bool] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx client.

        Returns:
            Configured httpx AsyncClient
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._config.timeout),
            )
        return self._client

    async def _request(self, method: str, path: str, json_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make an HTTP request to etcd with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path
            json_data: Optional JSON body

        Returns:
            Response JSON as dictionary

        Raises:
            EtcdConnectionException: If all retries fail
        """
        last_error: Exception | None = None

        for attempt in range(self._config.retry_attempts):
            try:
                client = await self._get_client()
                response = await client.request(method, path, json=json_data)
                response.raise_for_status()
                return response.json()
            except httpx.ConnectError as e:
                last_error = e
                log.warning(f"etcd connection attempt {attempt + 1}/{self._config.retry_attempts} failed: {e}")
                if attempt < self._config.retry_attempts - 1:
                    await asyncio.sleep(self._config.retry_delay * (attempt + 1))
                    # Reset client to force reconnection
                    if self._client:
                        await self._client.aclose()
                        self._client = None
            except httpx.HTTPStatusError as e:
                # Don't retry on 4xx errors (client errors)
                if 400 <= e.response.status_code < 500:
                    raise EtcdConnectionException(f"etcd API error: {e.response.text}") from e
                last_error = e
                log.warning(f"etcd request attempt {attempt + 1}/{self._config.retry_attempts} failed: {e}")
                if attempt < self._config.retry_attempts - 1:
                    await asyncio.sleep(self._config.retry_delay * (attempt + 1))
            except Exception as e:
                last_error = e
                log.warning(f"etcd request attempt {attempt + 1}/{self._config.retry_attempts} failed: {e}")
                if attempt < self._config.retry_attempts - 1:
                    await asyncio.sleep(self._config.retry_delay * (attempt + 1))

        raise EtcdConnectionException(f"Failed after {self._config.retry_attempts} attempts: {last_error}")

    @staticmethod
    def _encode_key(key: str) -> str:
        """Encode a key to base64 for etcd API.

        Args:
            key: The key string

        Returns:
            Base64 encoded key
        """
        return base64.b64encode(key.encode("utf-8")).decode("utf-8")

    @staticmethod
    def _decode_key(encoded: str) -> str:
        """Decode a base64 key from etcd API.

        Args:
            encoded: Base64 encoded key

        Returns:
            Decoded key string
        """
        return base64.b64decode(encoded).decode("utf-8")

    @staticmethod
    def _encode_value(value: str) -> str:
        """Encode a value to base64 for etcd API.

        Args:
            value: The value string

        Returns:
            Base64 encoded value
        """
        return base64.b64encode(value.encode("utf-8")).decode("utf-8")

    @staticmethod
    def _decode_value(encoded: str) -> str:
        """Decode a base64 value from etcd API.

        Args:
            encoded: Base64 encoded value

        Returns:
            Decoded value string
        """
        return base64.b64decode(encoded).decode("utf-8")

    def _prefixed_key(self, key: str) -> str:
        """Add the configured prefix to a key.

        Args:
            key: The key without prefix

        Returns:
            The key with prefix applied
        """
        if key.startswith(self._config.key_prefix):
            return key
        return f"{self._config.key_prefix}{key}"

    def _strip_prefix(self, key: str) -> str:
        """Remove the configured prefix from a key.

        Args:
            key: The key with prefix

        Returns:
            The key without prefix
        """
        if key.startswith(self._config.key_prefix):
            return key[len(self._config.key_prefix) :]
        return key

    @staticmethod
    def _range_end(prefix: str) -> str:
        """Calculate the range end for a prefix query.

        Args:
            prefix: The prefix to calculate range end for

        Returns:
            The range end key (prefix with last byte incremented)
        """
        # Range end is prefix with last byte incremented
        prefix_bytes = bytearray(prefix.encode("utf-8"))
        prefix_bytes[-1] = prefix_bytes[-1] + 1
        return prefix_bytes.decode("utf-8")

    # -------------------------------------------------------------------------
    # Key-Value Operations
    # -------------------------------------------------------------------------

    async def get(self, key: str) -> EtcdKeyValue | None:
        """Get a value by key.

        Args:
            key: The key to retrieve (prefix will be added automatically)

        Returns:
            EtcdKeyValue if found, None otherwise

        Raises:
            EtcdConnectionException: If connection fails
        """
        prefixed_key = self._prefixed_key(key)

        response = await self._request(
            "POST",
            "/v3/kv/range",
            {"key": self._encode_key(prefixed_key)},
        )

        kvs = response.get("kvs", [])
        if not kvs:
            return None

        kv = kvs[0]
        return EtcdKeyValue(
            key=self._strip_prefix(self._decode_key(kv["key"])),
            value=self._decode_value(kv["value"]) if kv.get("value") else "",
            mod_revision=int(kv.get("mod_revision", 0)),
            create_revision=int(kv.get("create_revision", 0)),
            version=int(kv.get("version", 0)),
            lease_id=int(kv["lease"]) if kv.get("lease") else None,
        )

    async def get_prefix(self, prefix: str) -> list[EtcdKeyValue]:
        """Get all key-value pairs with a given prefix.

        Args:
            prefix: The prefix to search for (base prefix will be added)

        Returns:
            List of matching EtcdKeyValue objects

        Raises:
            EtcdConnectionException: If connection fails
        """
        prefixed_key = self._prefixed_key(prefix)
        range_end = self._range_end(prefixed_key)

        response = await self._request(
            "POST",
            "/v3/kv/range",
            {
                "key": self._encode_key(prefixed_key),
                "range_end": self._encode_key(range_end),
            },
        )

        kvs = response.get("kvs", [])
        return [
            EtcdKeyValue(
                key=self._strip_prefix(self._decode_key(kv["key"])),
                value=self._decode_value(kv["value"]) if kv.get("value") else "",
                mod_revision=int(kv.get("mod_revision", 0)),
                create_revision=int(kv.get("create_revision", 0)),
                version=int(kv.get("version", 0)),
                lease_id=int(kv["lease"]) if kv.get("lease") else None,
            )
            for kv in kvs
        ]

    async def put(self, key: str, value: str, lease_id: int | None = None) -> None:
        """Store a key-value pair.

        Args:
            key: The key to store (prefix will be added automatically)
            value: The value to store
            lease_id: Optional lease ID to attach to the key

        Raises:
            EtcdConnectionException: If connection fails
        """
        prefixed_key = self._prefixed_key(key)

        request_data: dict[str, Any] = {
            "key": self._encode_key(prefixed_key),
            "value": self._encode_value(value),
        }
        if lease_id:
            request_data["lease"] = str(lease_id)

        await self._request("POST", "/v3/kv/put", request_data)
        log.debug(f"Put key: {key}")

    async def put_if_not_exists(self, key: str, value: str, lease_id: int | None = None) -> bool:
        """Store a key-value pair only if the key doesn't exist (CAS operation).

        Args:
            key: The key to store (prefix will be added automatically)
            value: The value to store
            lease_id: Optional lease ID to attach to the key

        Returns:
            True if the key was created, False if it already existed

        Raises:
            EtcdConnectionException: If connection fails
        """
        prefixed_key = self._prefixed_key(key)

        put_request: dict[str, Any] = {
            "key": self._encode_key(prefixed_key),
            "value": self._encode_value(value),
        }
        if lease_id:
            put_request["lease"] = str(lease_id)

        # Transaction: create only if version == 0 (key doesn't exist)
        txn_request = {
            "compare": [
                {
                    "key": self._encode_key(prefixed_key),
                    "target": "CREATE",
                    "create_revision": "0",
                }
            ],
            "success": [{"request_put": put_request}],
            "failure": [],
        }

        response = await self._request("POST", "/v3/kv/txn", txn_request)
        return response.get("succeeded", False)

    async def delete(self, key: str) -> bool:
        """Delete a key.

        Args:
            key: The key to delete (prefix will be added automatically)

        Returns:
            True if the key was deleted, False if it didn't exist

        Raises:
            EtcdConnectionException: If connection fails
        """
        prefixed_key = self._prefixed_key(key)

        response = await self._request(
            "POST",
            "/v3/kv/deleterange",
            {"key": self._encode_key(prefixed_key)},
        )

        deleted = int(response.get("deleted", 0))
        log.debug(f"Delete key: {key}, success: {deleted > 0}")
        return deleted > 0

    async def delete_prefix(self, prefix: str) -> int:
        """Delete all keys with a given prefix.

        Args:
            prefix: The prefix of keys to delete (base prefix will be added)

        Returns:
            Number of keys deleted

        Raises:
            EtcdConnectionException: If connection fails
        """
        prefixed_key = self._prefixed_key(prefix)
        range_end = self._range_end(prefixed_key)

        response = await self._request(
            "POST",
            "/v3/kv/deleterange",
            {
                "key": self._encode_key(prefixed_key),
                "range_end": self._encode_key(range_end),
            },
        )

        deleted = int(response.get("deleted", 0))
        log.debug(f"Delete prefix: {prefix}, count: {deleted}")
        return deleted

    # -------------------------------------------------------------------------
    # Lease Management
    # -------------------------------------------------------------------------

    async def grant_lease(self, ttl: int | None = None) -> EtcdLease:
        """Create a new lease.

        Args:
            ttl: Time-to-live in seconds (uses default from config if not specified)

        Returns:
            The created lease

        Raises:
            EtcdConnectionException: If connection fails
        """
        lease_ttl = ttl or self._config.lease_ttl

        response = await self._request(
            "POST",
            "/v3/lease/grant",
            {"TTL": str(lease_ttl)},
        )

        lease_id = int(response.get("ID", 0))
        actual_ttl = int(response.get("TTL", lease_ttl))

        log.debug(f"Granted lease: {lease_id} with TTL: {actual_ttl}s")
        return EtcdLease(
            lease_id=lease_id,
            ttl=actual_ttl,
            granted_ttl=lease_ttl,
        )

    async def refresh_lease(self, lease_id: int) -> EtcdLease | None:
        """Refresh a lease to keep it alive.

        Args:
            lease_id: The lease ID to refresh

        Returns:
            Updated lease info, or None if lease expired

        Raises:
            EtcdLeaseExpiredException: If the lease has expired
            EtcdConnectionException: If connection fails
        """
        try:
            response = await self._request(
                "POST",
                "/v3/lease/keepalive",
                {"ID": str(lease_id)},
            )

            result = response.get("result", {})
            ttl = int(result.get("TTL", 0))

            if ttl <= 0:
                raise EtcdLeaseExpiredException(f"Lease {lease_id} has expired")

            return EtcdLease(
                lease_id=lease_id,
                ttl=ttl,
                granted_ttl=ttl,  # Keepalive doesn't return granted TTL
            )
        except EtcdConnectionException as e:
            if "lease not found" in str(e).lower():
                raise EtcdLeaseExpiredException(f"Lease {lease_id} not found") from e
            raise

    async def revoke_lease(self, lease_id: int) -> None:
        """Revoke a lease, deleting all keys attached to it.

        Args:
            lease_id: The lease ID to revoke

        Raises:
            EtcdConnectionException: If connection fails
        """
        await self._request(
            "POST",
            "/v3/lease/revoke",
            {"ID": str(lease_id)},
        )
        log.debug(f"Revoked lease: {lease_id}")

    async def get_lease_info(self, lease_id: int) -> EtcdLease | None:
        """Get information about a lease.

        Args:
            lease_id: The lease ID to query

        Returns:
            Lease info or None if not found

        Raises:
            EtcdConnectionException: If connection fails
        """
        try:
            response = await self._request(
                "POST",
                "/v3/lease/timetolive",
                {"ID": str(lease_id)},
            )

            ttl = int(response.get("TTL", -1))
            if ttl < 0:
                return None

            return EtcdLease(
                lease_id=lease_id,
                ttl=ttl,
                granted_ttl=int(response.get("grantedTTL", ttl)),
            )
        except EtcdConnectionException:
            return None

    async def lease_keepalive(self, lease_id: int, interval: float | None = None) -> AsyncIterator[EtcdLease]:
        """Start a keepalive loop for a lease.

        This returns an async iterator that yields lease info on each refresh.
        The loop continues until cancelled or the lease expires.

        Args:
            lease_id: The lease ID to keep alive
            interval: Refresh interval in seconds (defaults to TTL/3)

        Yields:
            Updated lease info on each refresh

        Raises:
            EtcdLeaseExpiredException: If the lease expires
        """
        lease_info = await self.get_lease_info(lease_id)
        if not lease_info:
            raise EtcdLeaseExpiredException(f"Lease {lease_id} not found")

        refresh_interval = interval or max(1, lease_info.granted_ttl // 3)

        while True:
            try:
                lease = await self.refresh_lease(lease_id)
                if lease:
                    yield lease
                await asyncio.sleep(refresh_interval)
            except EtcdLeaseExpiredException:
                log.warning(f"Lease {lease_id} expired during keepalive")
                raise
            except asyncio.CancelledError:
                log.debug(f"Lease keepalive cancelled for {lease_id}")
                raise

    # -------------------------------------------------------------------------
    # Watch Operations
    # -------------------------------------------------------------------------

    async def watch(self, key: str, start_revision: int | None = None) -> AsyncIterator[EtcdWatchEvent]:
        """Watch a key for changes.

        Args:
            key: The key to watch (prefix will be added automatically)
            start_revision: Optional revision to start watching from

        Yields:
            Watch events for the key

        Raises:
            EtcdWatchCancelledException: If the watch is cancelled
            EtcdConnectionException: If connection fails
        """
        prefixed_key = self._prefixed_key(key)

        watch_id = id(asyncio.current_task())
        self._active_watches[watch_id] = True

        try:
            async for event in self._watch_stream(prefixed_key, start_revision=start_revision):
                if not self._active_watches.get(watch_id, False):
                    break
                yield event
        except asyncio.CancelledError:
            raise EtcdWatchCancelledException(f"Watch cancelled for key: {key}")
        finally:
            self._active_watches.pop(watch_id, None)

    async def watch_prefix(self, prefix: str, start_revision: int | None = None) -> AsyncIterator[EtcdWatchEvent]:
        """Watch all keys with a given prefix for changes.

        Args:
            prefix: The prefix to watch (base prefix will be added)
            start_revision: Optional revision to start watching from

        Yields:
            Watch events for matching keys

        Raises:
            EtcdWatchCancelledException: If the watch is cancelled
            EtcdConnectionException: If connection fails
        """
        prefixed_key = self._prefixed_key(prefix)
        range_end = self._range_end(prefixed_key)

        watch_id = id(asyncio.current_task())
        self._active_watches[watch_id] = True

        try:
            async for event in self._watch_stream(prefixed_key, range_end=range_end, start_revision=start_revision):
                if not self._active_watches.get(watch_id, False):
                    break
                yield event
        except asyncio.CancelledError:
            raise EtcdWatchCancelledException(f"Watch cancelled for prefix: {prefix}")
        finally:
            self._active_watches.pop(watch_id, None)

    async def _watch_stream(
        self,
        key: str,
        range_end: str | None = None,
        start_revision: int | None = None,
    ) -> AsyncIterator[EtcdWatchEvent]:
        """Internal method to create a watch stream.

        Args:
            key: The key to watch (already prefixed)
            range_end: Optional range end for prefix watches
            start_revision: Optional revision to start from

        Yields:
            Watch events
        """
        import json as json_module

        create_request: dict[str, Any] = {
            "key": self._encode_key(key),
        }
        if range_end:
            create_request["range_end"] = self._encode_key(range_end)
        if start_revision:
            create_request["start_revision"] = str(start_revision)

        request_data = {"create_request": create_request}

        # Use streaming endpoint
        client = await self._get_client()

        try:
            async with client.stream(
                "POST",
                "/v3/watch",
                json=request_data,
                timeout=None,  # No timeout for watch streams
            ) as response:
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue

                    try:
                        data = json_module.loads(line)
                        result = data.get("result", {})
                        events = result.get("events", [])

                        for event in events:
                            kv = event.get("kv", {})
                            event_type = event.get("type", "PUT")

                            yield EtcdWatchEvent(
                                key=self._strip_prefix(self._decode_key(kv["key"])),
                                value=self._decode_value(kv["value"]) if kv.get("value") else None,
                                event_type=event_type,
                                mod_revision=int(kv.get("mod_revision", 0)),
                            )
                    except (json_module.JSONDecodeError, KeyError) as e:
                        log.warning(f"Failed to parse watch event: {e}")
                        continue
        except httpx.ReadTimeout:
            # Timeout is expected for long-running watches, just reconnect
            pass

    def cancel_watch(self, watch_id: int) -> None:
        """Cancel an active watch.

        Args:
            watch_id: The watch ID to cancel (task id from watch call)
        """
        if watch_id in self._active_watches:
            self._active_watches[watch_id] = False

    # -------------------------------------------------------------------------
    # Health & Utilities
    # -------------------------------------------------------------------------

    async def health(self) -> bool:
        """Check if etcd connection is healthy.

        Returns:
            True if healthy, False otherwise
        """
        try:
            # Use maintenance status endpoint
            client = await self._get_client()
            response = await client.post("/v3/maintenance/status", json={})
            return response.status_code == 200
        except Exception as e:
            log.warning(f"etcd health check failed: {e}")
            return False

    async def status(self) -> dict[str, Any]:
        """Get etcd cluster status.

        Returns:
            Status information dictionary

        Raises:
            EtcdConnectionException: If connection fails
        """
        response = await self._request("POST", "/v3/maintenance/status", {})

        return {
            "version": response.get("version", "unknown"),
            "db_size": int(response.get("dbSize", 0)),
            "leader": int(response.get("leader", 0)),
            "raft_index": int(response.get("raftIndex", 0)),
            "raft_term": int(response.get("raftTerm", 0)),
        }

    async def close(self) -> None:
        """Close the etcd client connection."""
        if self._client:
            try:
                await self._client.aclose()
            except Exception as e:
                log.warning(f"Error closing etcd client: {e}")
            finally:
                self._client = None
            log.debug("etcd client connection closed")

    # -------------------------------------------------------------------------
    # Service Configuration (Neuroglia DI Pattern)
    # -------------------------------------------------------------------------

    @staticmethod
    def configure(builder: "WebApplicationBuilder") -> None:
        """Configure etcd client in the application builder.

        This method:
        1. Creates etcd configuration from application settings
        2. Creates an EtcdClient instance with the configuration
        3. Registers the client as a singleton in the DI container

        Args:
            builder: WebApplicationBuilder instance for service registration
        """
        from application.settings import app_settings

        log.info("🔧 Configuring etcd Client...")

        # Create configuration from settings
        config = EtcdConfig(
            host=app_settings.etcd_host,
            port=app_settings.etcd_port,
            timeout=app_settings.etcd_timeout,
            retry_attempts=app_settings.etcd_retry_attempts,
            retry_delay=app_settings.etcd_retry_delay,
            key_prefix=app_settings.etcd_key_prefix,
            lease_ttl=app_settings.etcd_lease_ttl,
        )

        # Create client instance
        etcd_client = EtcdClient(config)

        # Test connectivity (optional - can be disabled for faster startup)
        async def _check_health() -> None:
            try:
                if await etcd_client.health():
                    log.info("✅ etcd connection successful")
                else:
                    log.warning("⚠️ etcd health check returned unhealthy")
            except Exception as e:
                log.warning(f"⚠️ etcd health check failed: {e}")
                log.warning("⚠️ etcd operations may fail at runtime")

        # Schedule health check (non-blocking)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_check_health())
        except RuntimeError:
            # No running loop, skip async health check
            log.debug("Skipping async etcd health check (no running event loop)")

        # Register as singleton in DI container
        builder.services.add_singleton(EtcdClient, singleton=etcd_client)
        log.info(f"✅ etcd Client registered (host={config.host}:{config.port})")
