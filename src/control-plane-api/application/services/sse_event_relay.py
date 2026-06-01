import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

import redis.asyncio as redis
from neuroglia.hosting.abstractions import HostedService
from neuroglia.serialization.json import JsonSerializer

from application.settings import app_settings

if TYPE_CHECKING:
    from neuroglia.hosting.web import WebApplicationBuilder

logger = logging.getLogger(__name__)


# Batching configuration (ADR-013)
BATCH_INTERVAL_SECONDS = 1.0  # Time window for collecting events
MAX_BATCH_SIZE = 50  # Maximum events per batch
BATCHABLE_EVENT_TYPES = {
    "worker.metrics.updated",
    "worker.lab.stats_updated",  # ADR-041: Per-lab metrics from WebSocket (high frequency ~3s/lab)
}


@dataclass
class SSEClientSubscription:
    """Subscription details for an SSE client with filtering support."""

    client_id: str
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    worker_ids: set[str] | None = None
    event_types: set[str] | None = None

    def matches_event(self, event_type: str, data: dict) -> bool:
        """Check if event matches client's filter criteria.

        Args:
            event_type: Type of the event
            data: Event data dictionary

        Returns:
            True if event matches filters (or no filters set), False otherwise
        """
        # If event_types filter is set, check if event type matches
        if self.event_types is not None and event_type not in self.event_types:
            return False

        # If worker_ids filter is set, check if worker_id in data matches
        if self.worker_ids is not None:
            worker_id = data.get("worker_id")
            if worker_id is None or worker_id not in self.worker_ids:
                return False

        return True


class SSEEventRelay:
    """Relay service for broadcasting events to SSE clients.

    This service maintains a registry of connected SSE clients and
    broadcasts worker-related events to subscribed clients with optional filtering.
    It uses Redis Pub/Sub to synchronize events across multiple instances (API/Worker).

    Features (ADR-013):
    - Server-side filtering by worker_ids and event_types
    - Event batching for high-frequency events (metrics)
    """

    REDIS_CHANNEL = "lablet-cloud-manager:events"

    def __init__(self, serializer: JsonSerializer):
        self._clients: dict[str, SSEClientSubscription] = {}
        self._lock = asyncio.Lock()
        self._redis_client = None
        self._redis_pubsub = None
        self._listen_task = None
        self._serializer = serializer
        self._shutdown_event = asyncio.Event()

        # Batching support (ADR-013)
        self._batch_buffer: dict[str, list[dict]] = {}
        self._batch_task: asyncio.Task | None = None
        self._batching_enabled = True

    @property
    def shutdown_event(self) -> asyncio.Event:
        """Shared shutdown signal for SSE generator loops."""
        return self._shutdown_event

    async def start_redis_listener(self):
        """Start listening to Redis Pub/Sub channel."""
        async with self._lock:
            if not app_settings.redis_enabled:
                logger.warning("Redis disabled, SSE events will not be synchronized across processes")
                return

            if self._listen_task and not self._listen_task.done():
                logger.warning("Redis listener already running")
                return

            try:
                self._redis_client = redis.from_url(app_settings.redis_url, decode_responses=True)
                self._redis_pubsub = self._redis_client.pubsub()
                await self._redis_pubsub.subscribe(self.REDIS_CHANNEL)
                logger.info(f"Subscribed to Redis channel: {self.REDIS_CHANNEL}")

                async def listen():
                    try:
                        async for message in self._redis_pubsub.listen():
                            if message["type"] == "message":
                                await self._handle_redis_message(message["data"])
                    except asyncio.CancelledError:
                        logger.info("Redis listener task cancelled")
                        raise
                    except Exception as e:
                        logger.error(f"Redis listener error: {e}")

                self._listen_task = asyncio.create_task(listen())
            except Exception as e:
                logger.error(f"Failed to start Redis listener: {e}")

    async def stop_redis_listener(self):
        """Stop listening to Redis Pub/Sub channel."""
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        if self._redis_pubsub:
            await self._redis_pubsub.unsubscribe(self.REDIS_CHANNEL)
            await self._redis_pubsub.close()

        if self._redis_client:
            await self._redis_client.close()

    async def _handle_redis_message(self, message_data: str):
        """Handle message received from Redis."""
        try:
            event = json.loads(message_data)
            # Broadcast to local clients only (internal method)
            await self._broadcast_local(event)
        except Exception as e:
            logger.error(f"Failed to handle Redis message: {e}")

    async def register_client(
        self,
        worker_ids: set[str] | None = None,
        event_types: set[str] | None = None,
    ) -> tuple[str, asyncio.Queue]:
        """Register a new SSE client with optional filters.

        Args:
            worker_ids: Optional set of worker IDs to filter events by
            event_types: Optional set of event types to filter by

        Returns:
            Tuple of (client_id, event_queue)
        """
        client_id = str(uuid4())
        subscription = SSEClientSubscription(client_id=client_id, worker_ids=worker_ids, event_types=event_types)
        async with self._lock:
            self._clients[client_id] = subscription
        filters_str = []
        if worker_ids:
            filters_str.append(f"worker_ids={worker_ids}")
        if event_types:
            filters_str.append(f"event_types={event_types}")
        filter_desc = f" with filters: {', '.join(filters_str)}" if filters_str else ""
        logger.info(f"SSE client registered: {client_id}{filter_desc} (total: {len(self._clients)})")
        return client_id, subscription.event_queue

    async def unregister_client(self, client_id: str) -> None:
        async with self._lock:
            if client_id in self._clients:
                del self._clients[client_id]
                logger.info(f"SSE client unregistered: {client_id} (remaining: {len(self._clients)})")

    async def start_batch_timer(self) -> None:
        """Start the batch flush timer (ADR-013)."""
        if self._batch_task and not self._batch_task.done():
            return

        async def batch_loop():
            while self._batching_enabled:
                try:
                    await asyncio.sleep(BATCH_INTERVAL_SECONDS)
                    await self._flush_all_batches()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in batch flush loop: {e}")

        self._batch_task = asyncio.create_task(batch_loop())
        logger.debug("Batch timer started")

    async def stop_batch_timer(self) -> None:
        """Stop the batch flush timer."""
        self._batching_enabled = False
        if self._batch_task:
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass
        # Flush any remaining batches
        await self._flush_all_batches()

    async def _flush_all_batches(self) -> None:
        """Flush all accumulated batch buffers (ADR-013)."""
        for event_type in list(self._batch_buffer.keys()):
            await self._flush_batch(event_type)

    async def _flush_batch(self, event_type: str) -> None:
        """Flush accumulated events as a batch (ADR-013).

        Args:
            event_type: The event type to flush
        """
        events = self._batch_buffer.get(event_type, [])
        if not events:
            return

        batch_event = {
            "batch_id": str(uuid4()),
            "count": len(events),
            "events": events,
        }
        # Clear buffer before broadcasting to avoid duplicates
        self._batch_buffer[event_type] = []

        # Broadcast as batch event (add .batch suffix)
        await self._broadcast_immediate(f"{event_type}.batch", batch_event, source="sse-batch")

    async def _add_to_batch(self, event_type: str, data: dict) -> None:
        """Add event to batch buffer (ADR-013).

        Args:
            event_type: Type of event
            data: Event data
        """
        if event_type not in self._batch_buffer:
            self._batch_buffer[event_type] = []

        self._batch_buffer[event_type].append(data)

        # Flush if max batch size reached
        if len(self._batch_buffer[event_type]) >= MAX_BATCH_SIZE:
            await self._flush_batch(event_type)

    async def broadcast_event(self, event_type: str, data: dict, source: str = "lablet-cloud-manager") -> None:
        """Broadcast event to all matching clients via Redis Pub/Sub.

        High-frequency events (defined in BATCHABLE_EVENT_TYPES) are batched
        and sent periodically to reduce network overhead (ADR-013).

        Args:
            event_type: Type of event (e.g., "worker.metrics.updated")
            data: Event data dictionary (must include worker_id if filtering by worker)
            source: Event source identifier
        """
        # Check if event should be batched (ADR-013)
        if self._batching_enabled and event_type in BATCHABLE_EVENT_TYPES:
            await self._add_to_batch(event_type, data)
            return

        # Immediate broadcast for non-batchable events
        await self._broadcast_immediate(event_type, data, source)

    async def _broadcast_immediate(self, event_type: str, data: dict, source: str = "lablet-cloud-manager") -> None:
        """Immediately broadcast event without batching.

        Args:
            event_type: Type of event
            data: Event data dictionary
            source: Event source identifier
        """
        event_message = {
            "type": event_type,
            "source": source,
            "time": datetime.now(timezone.utc).isoformat() + "Z",
            "data": data,
        }

        # Publish to Redis if enabled
        if self._redis_client:
            try:
                # Redis client requires bytes, string, int or float
                # JsonSerializer returns bytearray, so we need to convert to bytes
                payload = self._serializer.serialize(event_message)
                if isinstance(payload, bytearray):
                    payload = bytes(payload)
                await self._redis_client.publish(self.REDIS_CHANNEL, payload)
            except Exception as e:
                logger.error(f"Failed to publish event to Redis: {e}")
                # Fallback to local broadcast if Redis fails
                await self._broadcast_local(event_message)
        else:
            # Local broadcast only
            await self._broadcast_local(event_message)

    async def _broadcast_local(self, event_message: dict) -> None:
        """Broadcast event to locally connected clients."""
        event_type = event_message["type"]
        data = event_message["data"]

        async with self._lock:
            matching_clients = [subscription for subscription in self._clients.values() if subscription.matches_event(event_type, data)]

        broadcast_count = 0
        for subscription in matching_clients:
            try:
                await asyncio.wait_for(subscription.event_queue.put(event_message), timeout=0.1)
                broadcast_count += 1
            except asyncio.TimeoutError:
                logger.warning(f"SSE client {subscription.client_id} queue full, event dropped")
            except Exception as e:
                logger.error(f"Failed to queue event for SSE client {subscription.client_id}: {e}")

        if broadcast_count > 0:
            logger.debug(f"Broadcasted event {event_type} to {broadcast_count}/{len(self._clients)} clients")

    def get_connected_clients_count(self) -> int:
        return len(self._clients)


class SSEEventRelayHostedService(HostedService):
    """Hosted service wrapper for the SSEEventRelay.

    Provides start/stop hooks so the application lifecycle can manage
    the relay cleanly. A configure() helper is provided for DI registration.
    """

    def __init__(self, relay: SSEEventRelay):
        self._relay = relay
        self._started = False

    async def start_async(self):
        if self._started:
            return
        logger.info("Starting SSEEventRelayHostedService")
        await self._relay.start_redis_listener()
        await self._relay.start_batch_timer()  # ADR-013: Start batch timer
        self._started = True

    async def stop_async(self):
        if not self._started:
            return
        logger.info("Stopping SSEEventRelayHostedService")

        # ADR-013: Stop batch timer (flushes remaining batches)
        await self._relay.stop_batch_timer()

        # Signal all SSE generator loops to exit immediately
        self._relay.shutdown_event.set()

        try:
            await self._relay.broadcast_event(
                event_type="system.sse.shutdown",
                data={"message": "SSE relay shutting down"},
                source="sse-event-relay",
            )
        except Exception as e:
            logger.warning(f"Exception when broadcasting shutdown event: {e}")

        await self._relay.stop_redis_listener()
        self._started = False

    @staticmethod
    def configure(builder: "WebApplicationBuilder") -> None:
        """Register the relay and hosted service with the DI builder.

        Args:
            builder: Application builder instance
        """
        # Register SSEEventRelay as singleton
        builder.services.add_singleton(
            SSEEventRelay,
            implementation_factory=lambda provider: SSEEventRelay(provider.get_required_service(JsonSerializer)),
        )

        # Register SSEEventRelayHostedService with factory (depends on relay)
        builder.services.add_singleton(
            SSEEventRelayHostedService,
            implementation_factory=lambda provider: SSEEventRelayHostedService(provider.get_required_service(SSEEventRelay)),
        )

        # Attempt to also register as generic HostedService if available
        try:
            builder.services.add_singleton(
                HostedService,
                implementation_factory=lambda provider: provider.get_service(SSEEventRelayHostedService),
            )
        except Exception as e:
            logger.warning(f"Exception when registering SSEEventRelayHostedService: {e}")

        logger.info("✅ SSEEventRelayHostedService configured as singleton")
