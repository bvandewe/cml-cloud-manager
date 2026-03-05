"""Leader Election Service for High-Availability services using etcd.

This module provides a high-level leader election service built on EtcdStateStore:
- Campaign for leadership on startup
- Maintain leadership via lease renewal (background keepalive)
- Watch for leader changes (standby mode)
- Graceful leadership handoff on shutdown
- Callbacks for leadership acquired/lost events

Key patterns follow ADR-006: etcd leader election for Scheduler and Resource Controller HA.
Only the leader runs scheduling/reconciliation loops; standbys watch for leader failure.

Usage:
    ```python
    leader_service = LeaderElectionService(
        etcd=state_store,
        service_name="scheduler",
        instance_id="scheduler-1",
        lease_ttl=15,
    )

    @leader_service.on_leadership_acquired
    async def handle_acquired():
        print("I am now the leader!")

    @leader_service.on_leadership_lost
    async def handle_lost():
        print("I lost leadership!")

    await leader_service.start_async()
    # ... service runs ...
    await leader_service.stop_async()
    ```
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from integration.exceptions import EtcdConnectionException, EtcdLeaseExpiredException
from integration.services.etcd_client import EtcdLease
from integration.services.etcd_state_store import EtcdStateStore, LeaderInfo

if TYPE_CHECKING:
    from neuroglia.dependency_injection import ServiceProviderBase
    from neuroglia.hosting.web import WebApplicationBuilder

log = logging.getLogger(__name__)


class LeaderElectionState(str, Enum):
    """State of the leader election service."""

    STOPPED = "STOPPED"
    CAMPAIGNING = "CAMPAIGNING"
    LEADER = "LEADER"
    STANDBY = "STANDBY"
    STOPPING = "STOPPING"


@dataclass
class LeaderElectionConfig:
    """Configuration for the leader election service."""

    service_name: str
    instance_id: str | None = None  # Auto-generated if not provided
    lease_ttl: int = 15  # TTL in seconds (15s as per ADR)
    campaign_interval: float = 5.0  # Interval between campaign attempts when standby
    keepalive_interval: float | None = None  # Defaults to TTL / 3

    def __post_init__(self) -> None:
        """Generate instance ID if not provided."""
        if not self.instance_id:
            self.instance_id = f"{self.service_name}-{uuid.uuid4().hex[:8]}"

        if self.keepalive_interval is None:
            self.keepalive_interval = max(1.0, self.lease_ttl / 3)


@dataclass
class LeaderElectionStatus:
    """Current status of the leader election service."""

    state: LeaderElectionState
    instance_id: str
    is_leader: bool
    leader_id: str | None = None
    leadership_acquired_at: datetime | None = None
    lease_id: int | None = None


# Type alias for callbacks
LeadershipCallback = Callable[[], Awaitable[None]]


class LeaderElectionService:
    """High-level leader election service using etcd leases.

    This service provides a complete leader election implementation with:
    - Automatic campaign for leadership on startup
    - Background lease keepalive to maintain leadership
    - Leadership change detection and callbacks
    - Graceful leadership handoff on shutdown

    The service follows the "leader takes action" pattern where only the leader
    executes scheduling/reconciliation loops while standbys remain idle.

    Example:
        ```python
        service = LeaderElectionService(
            etcd=state_store,
            service_name="resource-scheduler",
            instance_id="scheduler-pod-abc123",
        )

        @service.on_leadership_acquired
        async def start_scheduling():
            # Start the scheduling loop
            pass

        @service.on_leadership_lost
        async def stop_scheduling():
            # Stop the scheduling loop gracefully
            pass

        await service.start_async()
        ```
    """

    def __init__(
        self,
        etcd: EtcdStateStore,
        service_name: str,
        instance_id: str | None = None,
        lease_ttl: int = 15,
        campaign_interval: float = 5.0,
    ) -> None:
        """Initialize the leader election service.

        Args:
            etcd: EtcdStateStore instance for leader election operations
            service_name: Name of the service for leader election namespace
            instance_id: Unique identifier for this instance (auto-generated if None)
            lease_ttl: Lease TTL in seconds (default 15s per ADR-006)
            campaign_interval: Interval between campaign attempts when standby
        """
        self._etcd = etcd
        self._config = LeaderElectionConfig(
            service_name=service_name,
            instance_id=instance_id,
            lease_ttl=lease_ttl,
            campaign_interval=campaign_interval,
        )

        # State management
        self._state = LeaderElectionState.STOPPED
        self._is_leader = False
        self._lease: EtcdLease | None = None
        self._leadership_acquired_at: datetime | None = None

        # Background tasks
        self._keepalive_task: asyncio.Task[None] | None = None
        self._campaign_task: asyncio.Task[None] | None = None
        self._running = False

        # Callbacks
        self._on_leadership_acquired_callbacks: list[LeadershipCallback] = []
        self._on_leadership_lost_callbacks: list[LeadershipCallback] = []

        log.info(f"📋 LeaderElectionService initialized: service={self._config.service_name}, instance={self._config.instance_id}")

    # -------------------------------------------------------------------------
    # Public Properties
    # -------------------------------------------------------------------------

    @property
    def is_leader(self) -> bool:
        """Check if this instance is currently the leader.

        Returns:
            True if this instance holds leadership
        """
        return self._is_leader

    @property
    def state(self) -> LeaderElectionState:
        """Get the current state of the leader election service.

        Returns:
            Current LeaderElectionState
        """
        return self._state

    @property
    def instance_id(self) -> str:
        """Get the instance identifier.

        Returns:
            The unique instance ID
        """
        return self._config.instance_id  # type: ignore

    @property
    def service_name(self) -> str:
        """Get the service name.

        Returns:
            The service name for this leader election
        """
        return self._config.service_name

    @property
    def lease_id(self) -> int | None:
        """Get the current lease ID if leader.

        Returns:
            The lease ID or None if not leader
        """
        return self._lease.lease_id if self._lease else None

    # -------------------------------------------------------------------------
    # Callback Registration (Decorator Pattern)
    # -------------------------------------------------------------------------

    def on_leadership_acquired(
        self,
        callback: LeadershipCallback,
    ) -> LeadershipCallback:
        """Register a callback for when leadership is acquired.

        Can be used as a decorator:
            @service.on_leadership_acquired
            async def handle_acquired():
                pass

        Args:
            callback: Async function to call when leadership is acquired

        Returns:
            The callback (for decorator usage)
        """
        self._on_leadership_acquired_callbacks.append(callback)
        log.debug(f"Registered leadership acquired callback: {callback.__name__}")
        return callback

    def on_leadership_lost(
        self,
        callback: LeadershipCallback,
    ) -> LeadershipCallback:
        """Register a callback for when leadership is lost.

        Can be used as a decorator:
            @service.on_leadership_lost
            async def handle_lost():
                pass

        Args:
            callback: Async function to call when leadership is lost

        Returns:
            The callback (for decorator usage)
        """
        self._on_leadership_lost_callbacks.append(callback)
        log.debug(f"Registered leadership lost callback: {callback.__name__}")
        return callback

    # -------------------------------------------------------------------------
    # Lifecycle Methods
    # -------------------------------------------------------------------------

    async def start_async(self) -> None:
        """Start the leader election process.

        This will:
        1. Attempt to acquire leadership immediately
        2. If successful, start lease keepalive loop
        3. If not, enter standby mode and campaign periodically

        Raises:
            RuntimeError: If already running
        """
        if self._running:
            raise RuntimeError("LeaderElectionService is already running")

        log.info(f"🚀 Starting leader election for {self._config.service_name} as {self._config.instance_id}")

        self._running = True
        self._state = LeaderElectionState.CAMPAIGNING

        # Initial campaign attempt
        await self._try_acquire_leadership()

        # Start background campaign/keepalive loop
        self._campaign_task = asyncio.create_task(
            self._campaign_loop(),
            name=f"leader-election-{self._config.service_name}",
        )

    async def stop_async(self) -> None:
        """Stop the leader election process and release leadership.

        This will:
        1. Stop background tasks gracefully
        2. Release leadership (if held)
        3. Revoke the lease

        Note:
            Safe to call multiple times.
        """
        if not self._running:
            log.debug("LeaderElectionService already stopped")
            return

        log.info(f"🛑 Stopping leader election for {self._config.service_name}")
        self._state = LeaderElectionState.STOPPING
        self._running = False

        # Cancel background tasks
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
            self._keepalive_task = None

        if self._campaign_task and not self._campaign_task.done():
            self._campaign_task.cancel()
            try:
                await self._campaign_task
            except asyncio.CancelledError:
                pass
            self._campaign_task = None

        # Release leadership if held
        if self._is_leader and self._lease:
            await self._release_leadership()

        self._state = LeaderElectionState.STOPPED
        log.info(f"✅ Leader election stopped for {self._config.service_name}")

    # -------------------------------------------------------------------------
    # Status Methods
    # -------------------------------------------------------------------------

    async def get_status(self) -> LeaderElectionStatus:
        """Get the current status of this leader election service.

        Returns:
            LeaderElectionStatus with current state information
        """
        current_leader = None
        try:
            leader_info = await self._etcd.get_current_leader(self._config.service_name)
            current_leader = leader_info.leader_id if leader_info else None
        except Exception as e:
            log.warning(f"Failed to get current leader: {e}")

        return LeaderElectionStatus(
            state=self._state,
            instance_id=self._config.instance_id,  # type: ignore
            is_leader=self._is_leader,
            leader_id=current_leader,
            leadership_acquired_at=self._leadership_acquired_at,
            lease_id=self._lease.lease_id if self._lease else None,
        )

    async def get_current_leader(self) -> LeaderInfo | None:
        """Get information about the current leader.

        Returns:
            LeaderInfo or None if no leader exists
        """
        return await self._etcd.get_current_leader(self._config.service_name)

    # -------------------------------------------------------------------------
    # Internal: Campaign Loop
    # -------------------------------------------------------------------------

    async def _campaign_loop(self) -> None:
        """Background loop that campaigns for leadership when not leader."""
        log.debug(f"Starting campaign loop for {self._config.service_name}")

        while self._running:
            try:
                if self._is_leader:
                    # We are leader - keepalive runs in separate task
                    await asyncio.sleep(1.0)
                else:
                    # We are standby - try to acquire leadership
                    await self._try_acquire_leadership()

                    if not self._is_leader:
                        # Still not leader, wait before next attempt
                        await asyncio.sleep(self._config.campaign_interval)

            except asyncio.CancelledError:
                log.debug("Campaign loop cancelled")
                break
            except Exception as e:
                log.error(f"Error in campaign loop: {e}", exc_info=True)
                await asyncio.sleep(self._config.campaign_interval)

    async def _try_acquire_leadership(self) -> bool:
        """Attempt to acquire leadership.

        Returns:
            True if leadership was acquired
        """
        try:
            log.debug(f"Attempting to acquire leadership for {self._config.service_name}")

            is_leader, lease = await self._etcd.try_acquire_leadership(
                service_name=self._config.service_name,
                leader_id=self._config.instance_id,  # type: ignore
                lease_ttl=self._config.lease_ttl,
            )

            if is_leader and lease:
                await self._on_become_leader(lease)
                return True
            else:
                if self._state != LeaderElectionState.STANDBY:
                    self._state = LeaderElectionState.STANDBY
                    log.debug(f"Entering standby mode for {self._config.service_name} (another leader exists)")
                return False

        except EtcdConnectionException as e:
            log.warning(f"etcd connection error during leadership attempt: {e}")
            return False
        except Exception as e:
            log.error(f"Failed to acquire leadership: {e}", exc_info=True)
            return False

    async def _on_become_leader(self, lease: EtcdLease) -> None:
        """Handle becoming the leader.

        Args:
            lease: The acquired lease
        """
        self._is_leader = True
        self._lease = lease
        self._state = LeaderElectionState.LEADER
        self._leadership_acquired_at = datetime.now(timezone.utc)

        log.info(f"🏆 Acquired leadership for {self._config.service_name} as {self._config.instance_id} (lease={lease.lease_id})")

        # Start keepalive task
        self._keepalive_task = asyncio.create_task(
            self._keepalive_loop(),
            name=f"leader-keepalive-{self._config.service_name}",
        )

        # Notify callbacks
        await self._notify_leadership_acquired()

    async def _notify_leadership_acquired(self) -> None:
        """Notify all registered callbacks that leadership was acquired."""
        for callback in self._on_leadership_acquired_callbacks:
            try:
                log.debug(f"Calling leadership acquired callback: {callback.__name__}")
                await callback()
            except Exception as e:
                log.error(
                    f"Error in leadership acquired callback {callback.__name__}: {e}",
                    exc_info=True,
                )

    # -------------------------------------------------------------------------
    # Internal: Keepalive Loop
    # -------------------------------------------------------------------------

    async def _keepalive_loop(self) -> None:
        """Background loop that maintains lease while leader."""
        log.debug(f"Starting keepalive loop for {self._config.service_name}")
        keepalive_interval = self._config.keepalive_interval or 5.0

        while self._running and self._is_leader:
            try:
                if self._lease:
                    await self._refresh_lease()
                await asyncio.sleep(keepalive_interval)

            except asyncio.CancelledError:
                log.debug("Keepalive loop cancelled")
                break
            except EtcdLeaseExpiredException:
                log.warning(f"Lease expired for {self._config.service_name}")
                await self._on_lose_leadership()
                break
            except EtcdConnectionException as e:
                log.warning(f"etcd connection error during keepalive: {e}")
                # Continue trying - temporary connection issues shouldn't lose leadership
                await asyncio.sleep(1.0)
            except Exception as e:
                log.error(f"Error in keepalive loop: {e}", exc_info=True)
                await asyncio.sleep(1.0)

    async def _refresh_lease(self) -> None:
        """Refresh the leadership lease."""
        if not self._lease:
            return

        try:
            refreshed = await self._etcd._etcd.refresh_lease(self._lease.lease_id)
            if refreshed:
                log.debug(f"Refreshed lease {self._lease.lease_id} for {self._config.service_name} (TTL={refreshed.ttl})")
            else:
                raise EtcdLeaseExpiredException(f"Lease {self._lease.lease_id} expired")
        except EtcdLeaseExpiredException:
            raise
        except Exception as e:
            log.warning(f"Failed to refresh lease: {e}")
            raise

    # -------------------------------------------------------------------------
    # Internal: Lose Leadership
    # -------------------------------------------------------------------------

    async def _on_lose_leadership(self) -> None:
        """Handle losing leadership."""
        was_leader = self._is_leader
        self._is_leader = False
        self._lease = None
        self._leadership_acquired_at = None
        self._state = LeaderElectionState.STANDBY

        if was_leader:
            log.warning(f"⚠️ Lost leadership for {self._config.service_name}")
            await self._notify_leadership_lost()

    async def _notify_leadership_lost(self) -> None:
        """Notify all registered callbacks that leadership was lost."""
        for callback in self._on_leadership_lost_callbacks:
            try:
                log.debug(f"Calling leadership lost callback: {callback.__name__}")
                await callback()
            except Exception as e:
                log.error(
                    f"Error in leadership lost callback {callback.__name__}: {e}",
                    exc_info=True,
                )

    async def _release_leadership(self) -> None:
        """Release leadership gracefully."""
        if not self._lease:
            return

        try:
            log.info(f"Releasing leadership for {self._config.service_name}")
            await self._etcd.release_leadership(
                service_name=self._config.service_name,
                lease_id=self._lease.lease_id,
            )
        except Exception as e:
            log.warning(f"Error releasing leadership: {e}")
        finally:
            await self._on_lose_leadership()

    # -------------------------------------------------------------------------
    # Service Configuration (Neuroglia DI Pattern)
    # -------------------------------------------------------------------------

    @staticmethod
    def configure_factory(
        service_name: str,
        instance_id: str | None = None,
        lease_ttl: int = 15,
    ) -> Callable[["WebApplicationBuilder"], None]:
        """Create a configuration function for dependency injection.

        This is a factory method that creates a configure function with
        pre-bound parameters, following the Neuroglia DI pattern.

        Args:
            service_name: Name of the service for leader election
            instance_id: Unique instance ID (auto-generated if None)
            lease_ttl: Lease TTL in seconds

        Returns:
            A configure function suitable for builder.configure()

        Example:
            ```python
            builder.configure(
                LeaderElectionService.configure_factory(
                    service_name="resource-scheduler",
                    lease_ttl=15,
                )
            )
            ```
        """

        def configure(builder: "WebApplicationBuilder") -> None:
            """Configure LeaderElectionService in the application builder."""
            log.info(f"🔧 Configuring LeaderElectionService for {service_name}...")

            def _factory(sp: "ServiceProviderBase") -> "LeaderElectionService":
                etcd_state_store = sp.get_required_service(EtcdStateStore)
                return LeaderElectionService(
                    etcd=etcd_state_store,
                    service_name=service_name,
                    instance_id=instance_id,
                    lease_ttl=lease_ttl,
                )

            builder.services.add_singleton(LeaderElectionService, implementation_factory=_factory)
            log.info(f"✅ LeaderElectionService registered for {service_name}")

        return configure
