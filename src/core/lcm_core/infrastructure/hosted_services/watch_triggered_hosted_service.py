"""Watch-triggered Reconciliation Hosted Service.

Extends LeaderElectedHostedService with etcd watch capabilities for
reactive reconciliation. Supports dual-mode operation:
- Polling (fallback): Periodic reconciliation on interval
- Watch (reactive): Immediate reconciliation on etcd state changes

This enables faster response to state changes while maintaining
reliability through polling fallback.

Key patterns:
    /lcm/workers/{id}/state     - CMLWorker status changes
    /lcm/sessions/{id}/state   - LabletSession status changes

Usage:
    class MyReconciler(WatchTriggeredHostedService[MyResource]):
        @property
        def watch_prefix(self) -> str:
            return "/workers/"  # Watch all worker state changes

        async def on_watch_event(self, event: EtcdEvent) -> str | None:
            # Extract resource ID from event key
            # /workers/{id}/state -> returns {id}
            parts = event.key.split("/")
            if len(parts) >= 3 and parts[2] == "state":
                return parts[1]
            return None
"""

import asyncio
import logging
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from lcm_core.infrastructure.hosted_services.leader_elected_hosted_service import (
    LeaderElectedHostedService,
    LeaderElectionConfig,
)
from lcm_core.infrastructure.hosted_services.reconciliation_hosted_service import (
    ReconciliationConfig,
)
from lcm_core.integration.clients.etcd_client import EtcdClient, EtcdEvent

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class WatchConfig:
    """Configuration for etcd watch functionality."""

    # Watch settings
    enabled: bool = True
    prefix: str = ""  # Key prefix to watch (e.g., "/workers/")
    reconnect_delay_seconds: float = 1.0
    max_reconnect_attempts: int = 10

    # Debounce settings (prevent rapid-fire reconciliation)
    debounce_seconds: float = 0.5  # Minimum time between triggered reconciles

    # Startup sweep: run one full reconciliation cycle when becoming leader
    # to pick up resources that entered a non-terminal state before this
    # instance started watching (e.g., INSTANTIATING sessions after restart).
    startup_reconcile_enabled: bool = True
    startup_reconcile_delay_seconds: float = 2.0  # Small delay to let watch settle


class WatchTriggeredHostedService(LeaderElectedHostedService[T], Generic[T]):
    """
    Leader-elected reconciliation service with etcd watch support.

    Provides dual-mode operation:
    1. **Polling (baseline)**: Runs every `interval_seconds` as fallback
    2. **Watch (reactive)**: Triggers immediate reconcile on etcd events

    When a watch event arrives:
    - Extract resource ID from the event key via `on_watch_event()`
    - Trigger immediate single-resource reconciliation
    - Debounce rapid events to prevent excessive reconciles

    Subclasses should:
    - Set `watch_prefix` property to the etcd key prefix to watch
    - Implement `on_watch_event()` to extract resource ID from events
    - Optionally implement `fetch_resource_by_id()` for efficient single-resource fetch

    Example:
        class WorkerReconciler(WatchTriggeredHostedService[CMLWorkerReadModel]):
            @property
            def watch_prefix(self) -> str:
                return "/workers/"

            async def on_watch_event(self, event: EtcdEvent) -> str | None:
                # /workers/{id}/state -> {id}
                parts = event.key.split("/")
                if len(parts) >= 3:
                    return parts[1]  # Return worker_id
                return None
    """

    def __init__(
        self,
        reconciliation_config: ReconciliationConfig | None = None,
        election_config: LeaderElectionConfig | None = None,
        watch_config: WatchConfig | None = None,
        etcd_client: EtcdClient | None = None,
    ):
        """Initialize the watch-triggered reconciliation service.

        Args:
            reconciliation_config: Configuration for the reconciliation loop.
            election_config: Configuration for leader election.
            watch_config: Configuration for etcd watch functionality.
            etcd_client: etcd client for leader election and watch.
        """
        super().__init__(
            reconciliation_config=reconciliation_config,
            election_config=election_config,
            etcd_client=etcd_client,
        )
        self._watch_config = watch_config or WatchConfig()

        # Watch state
        self._watch_task: asyncio.Task[None] | None = None
        self._startup_sweep_task: asyncio.Task[None] | None = None
        self._startup_sweep_active: bool = False  # ADR-043: True during startup sweep
        self._pending_reconciles: set[str] = set()  # Resource IDs pending reconcile
        self._debounce_task: asyncio.Task[None] | None = None
        self._last_watch_event_time: float = 0

        # Stats
        self._watch_events_received = 0
        self._watch_triggered_reconciles = 0

    @property
    @abstractmethod
    def watch_prefix(self) -> str:
        """Get the etcd key prefix to watch.

        Returns:
            Key prefix (e.g., "/workers/" or "/instances/")
        """
        pass

    @abstractmethod
    async def on_watch_event(self, event: EtcdEvent) -> str | None:
        """Process a watch event and extract resource ID.

        Called when an etcd watch event is received. Should extract
        the resource ID from the event key if applicable.

        Args:
            event: The etcd watch event.

        Returns:
            Resource ID to reconcile, or None to skip.
        """
        pass

    async def fetch_resource_by_id(self, resource_id: str) -> T | None:
        """Fetch a single resource by ID for targeted reconciliation.

        Override this for efficient single-resource fetch when a watch
        event triggers reconciliation. If not overridden, falls back
        to filtering from `list_resources()`.

        Args:
            resource_id: The resource ID to fetch.

        Returns:
            The resource, or None if not found.
        """
        # Default: filter from list_resources
        resources = await self.list_resources()
        for resource in resources:
            if self.get_resource_id(resource) == resource_id:
                return resource
        return None

    async def _become_leader(self) -> None:
        """Handle becoming the leader (extends parent to start watch + initial sweep)."""
        await super()._become_leader()

        # Start watch loop if enabled AND we have an etcd client
        if self._watch_config.enabled and self.watch_prefix:
            if self._etcd is None:
                logger.info(f"{self._config.service_name}: Watch enabled but no etcd client " f"(mock mode) — watch loop not started")
            else:
                self._watch_task = asyncio.create_task(
                    self._watch_loop(),
                    name=f"{self._config.service_name}_watch_loop",
                )
                logger.info(f"{self._config.service_name}: Started etcd watch on prefix '{self.watch_prefix}'")

        # Run a one-time startup reconciliation sweep to pick up any resources
        # that are already in non-terminal states (e.g., INSTANTIATING sessions
        # that were in-flight when this controller restarted). Without this,
        # watch-only mode would miss pre-existing resources since the watch
        # stream only delivers new events.
        if self._watch_config.startup_reconcile_enabled:
            self._startup_sweep_task = asyncio.create_task(
                self._startup_reconcile_sweep(),
                name=f"{self._config.service_name}_startup_sweep",
            )

    async def _startup_reconcile_sweep(self) -> None:
        """Run a one-time full reconciliation sweep at startup.

        Waits briefly to let the watch stream connect, then runs a single
        full reconciliation cycle. This ensures resources in non-terminal
        states (e.g., INSTANTIATING, SCHEDULED, RUNNING) are picked up
        even when polling is disabled (watch-only mode).

        ADR-043: Sets _startup_sweep_active=True so subclasses can broaden
        their list_resources() filter to include terminal resources that need
        EC2 state verification after a restart.
        """
        try:
            await asyncio.sleep(self._watch_config.startup_reconcile_delay_seconds)
            if self._stopping or not self._is_leader:
                return

            self._startup_sweep_active = True
            logger.info(f"{self._config.service_name}: 🔄 Running startup reconciliation sweep (full-sync)")
            await self._reconcile_all()
            logger.info(f"{self._config.service_name}: ✅ Startup reconciliation sweep complete")
        except asyncio.CancelledError:
            logger.debug(f"{self._config.service_name}: Startup sweep cancelled")
        except Exception as e:
            logger.exception(f"{self._config.service_name}: Startup reconciliation sweep failed: {e}")
        finally:
            self._startup_sweep_active = False

    async def _step_down(self) -> None:
        """Handle stepping down from leadership (extends parent to stop watch)."""
        # Stop startup sweep task
        if self._startup_sweep_task:
            self._startup_sweep_task.cancel()
            try:
                await self._startup_sweep_task
            except asyncio.CancelledError:
                pass
            self._startup_sweep_task = None

        # Stop watch task
        if self._watch_task:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass
            self._watch_task = None
            logger.info(f"{self._config.service_name}: Stopped etcd watch")

        # Stop debounce task
        if self._debounce_task:
            self._debounce_task.cancel()
            try:
                await self._debounce_task
            except asyncio.CancelledError:
                pass
            self._debounce_task = None

        await super()._step_down()

    async def _watch_loop(self) -> None:
        """Main watch loop - reconnects on errors."""
        reconnect_attempts = 0

        while not self._stopping and self._is_leader:
            try:
                await self._watch_stream()
                reconnect_attempts = 0  # Reset on successful connection
            except asyncio.CancelledError:
                logger.debug(f"{self._config.service_name}: Watch loop cancelled")
                break
            except Exception as e:
                reconnect_attempts += 1
                if reconnect_attempts > self._watch_config.max_reconnect_attempts:
                    logger.error(f"{self._config.service_name}: Watch failed after {reconnect_attempts} attempts, giving up: {e}")
                    break

                delay = self._watch_config.reconnect_delay_seconds * reconnect_attempts
                logger.warning(f"{self._config.service_name}: Watch error, reconnecting in {delay}s: {e}")
                await asyncio.sleep(delay)

    async def _watch_stream(self) -> None:
        """Watch the etcd prefix and process events."""
        if self._etcd is None:
            raise RuntimeError("No etcd client available — watch cannot run")

        logger.info(f"{self._config.service_name}: Watching etcd prefix: {self.watch_prefix}")

        async for event in self._etcd.watch_prefix(self.watch_prefix):
            if self._stopping or not self._is_leader:
                break

            self._watch_events_received += 1
            logger.debug(f"{self._config.service_name}: Watch event: {event.type} {event.key} (value={event.value})")

            # Extract resource ID from event
            resource_id = await self.on_watch_event(event)
            if resource_id:
                self._pending_reconciles.add(resource_id)
                self._schedule_debounced_reconcile()

    def _schedule_debounced_reconcile(self) -> None:
        """Schedule debounced reconciliation for pending resources."""
        if self._debounce_task and not self._debounce_task.done():
            return  # Already scheduled

        self._debounce_task = asyncio.create_task(
            self._debounced_reconcile(),
            name=f"{self._config.service_name}_debounce",
        )

    async def _debounced_reconcile(self) -> None:
        """Wait for debounce period then reconcile pending resources.

        Uses a drain-loop pattern to handle events that arrive during
        processing. When a reconcile handler triggers a state change
        (e.g., SCHEDULED → INSTANTIATING), the resulting etcd watch event
        adds new items to _pending_reconciles while this method is still
        running. Without the loop, those items would be orphaned because
        _schedule_debounced_reconcile() returns early when the debounce
        task is not yet done.
        """
        await asyncio.sleep(self._watch_config.debounce_seconds)

        # Drain-loop: keep processing until no new items arrive during
        # reconciliation. This prevents the race condition where a
        # self-induced watch event (from a handler's API call) is added
        # to _pending_reconciles but never processed.
        while self._pending_reconciles:
            if self._stopping or not self._is_leader:
                break

            # Drain current batch
            resource_ids = list(self._pending_reconciles)
            self._pending_reconciles.clear()

            logger.info(f"{self._config.service_name}: Watch-triggered reconcile for {len(resource_ids)} resources: {resource_ids}")

            for resource_id in resource_ids:
                if self._stopping or not self._is_leader:
                    break

                try:
                    resource = await self.fetch_resource_by_id(resource_id)
                    if resource:
                        self._watch_triggered_reconciles += 1
                        await self._reconcile_single(resource, resource_id)
                    else:
                        logger.debug(f"{self._config.service_name}: Resource {resource_id} not found, skipping")
                except Exception as e:
                    logger.exception(f"{self._config.service_name}: Error in watch-triggered reconcile for {resource_id}: {e}")

    @property
    def stats(self) -> dict[str, Any]:
        """Get current service statistics including watch stats."""
        base_stats = super().stats
        return {
            **base_stats,
            "watch_enabled": self._watch_config.enabled and bool(self.watch_prefix),
            "watch_prefix": self.watch_prefix,
            "watch_events_received": self._watch_events_received,
            "watch_triggered_reconciles": self._watch_triggered_reconciles,
            "pending_watch_reconciles": len(self._pending_reconciles),
        }
