"""Event Deduplication Service for idempotent CloudEvent processing.

Prevents duplicate processing of CloudEvents by tracking processed event IDs
in etcd with TTL (Time-To-Live) for automatic cleanup.
"""

import logging

from integration.services.etcd_client import EtcdClient

log = logging.getLogger(__name__)


class EventDeduplicationService:
    """Service for preventing duplicate event processing.

    Uses etcd to store processed event IDs with a configurable TTL.
    This ensures idempotent event handling even across service restarts.

    Example:
        ```python
        if await dedup.is_processed(event_id):
            return  # Skip duplicate

        # Process event...

        await dedup.mark_processed(event_id)
        ```
    """

    def __init__(
        self,
        etcd_client: EtcdClient,
        key_prefix: str = "/lcm/events/processed",
        default_ttl_hours: int = 24,
    ) -> None:
        """Initialize the deduplication service.

        Args:
            etcd_client: Client for etcd operations
            key_prefix: Prefix for event keys in etcd
            default_ttl_hours: Default TTL for processed event records
        """
        self._etcd = etcd_client
        self._key_prefix = key_prefix
        self._default_ttl_hours = default_ttl_hours

    async def is_processed(self, event_id: str) -> bool:
        """Check if an event has already been processed.

        Args:
            event_id: Unique identifier for the event

        Returns:
            True if the event was already processed, False otherwise
        """
        key = f"{self._key_prefix}/{event_id}"
        try:
            value = await self._etcd.get(key)
            return value is not None
        except Exception as e:
            log.warning(f"Failed to check event deduplication for {event_id}: {e}")
            # On error, assume not processed to avoid skipping events
            return False

    async def mark_processed(
        self,
        event_id: str,
        ttl_hours: int | None = None,
    ) -> None:
        """Mark an event as processed with TTL.

        Args:
            event_id: Unique identifier for the event
            ttl_hours: TTL in hours (defaults to configured default)
        """
        key = f"{self._key_prefix}/{event_id}"
        ttl = (ttl_hours or self._default_ttl_hours) * 3600  # Convert to seconds
        try:
            # Grant a lease with the desired TTL
            lease = await self._etcd.grant_lease(ttl=ttl)
            # Put the key with the lease attached
            await self._etcd.put(key, "1", lease_id=lease.id)
            log.debug(f"Marked event {event_id} as processed (TTL: {ttl}s, lease: {lease.id})")
        except Exception as e:
            log.error(f"Failed to mark event {event_id} as processed: {e}")
            # Don't raise - event was processed, just not recorded
            # Next time will be treated as new (better than losing event)

    async def clear_processed(self, event_id: str) -> None:
        """Clear the processed marker for an event (for testing/debugging).

        Args:
            event_id: Unique identifier for the event
        """
        key = f"{self._key_prefix}/{event_id}"
        try:
            await self._etcd.delete(key)
            log.debug(f"Cleared processed marker for event {event_id}")
        except Exception as e:
            log.warning(f"Failed to clear processed marker for {event_id}: {e}")

    async def get_processed_count(self) -> int:
        """Get count of currently tracked processed events.

        Returns:
            Number of processed events with active TTL
        """
        try:
            events = await self._etcd.get_prefix(self._key_prefix)
            return len(events) if events else 0
        except Exception as e:
            log.warning(f"Failed to get processed event count: {e}")
            return 0
