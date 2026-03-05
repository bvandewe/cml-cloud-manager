"""LeaderElectedHostedService base class.

Extends ReconciliationHostedService with leader election via etcd.
Only the leader instance runs the reconciliation loop.

This is designed as an interim solution in lcm-core that will eventually
migrate to the Neuroglia framework.
"""

import asyncio
import logging
import os
import socket
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from lcm_core.infrastructure.hosted_services.reconciliation_hosted_service import (
    ReconciliationConfig,
    ReconciliationHostedService,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class LeaderElectionConfig:
    """Configuration for leader election via etcd."""

    # etcd connection
    etcd_endpoints: list[str] = field(default_factory=lambda: ["localhost:2379"])

    # Election parameters
    election_key_prefix: str = "/elections"
    lease_ttl_seconds: int = 15
    renewal_interval_seconds: float = 5.0

    # Instance identification
    instance_id: str = field(default_factory=lambda: f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}")
    service_name: str = "service"

    @property
    def election_key(self) -> str:
        """Get the full election key for this service."""
        return f"{self.election_key_prefix}/{self.service_name}/leader"

    @classmethod
    def from_env(cls, service_name: str) -> "LeaderElectionConfig":
        """Create configuration from environment variables.

        Environment variables:
        - ETCD_ENDPOINTS: Comma-separated etcd endpoints (default: localhost:2379)
        - LEADER_TTL: Lease TTL in seconds (default: 15)
        - INSTANCE_ID: Instance identifier (default: hostname-uuid)
        """
        endpoints_str = os.environ.get("ETCD_ENDPOINTS", "localhost:2379")
        endpoints = [ep.strip() for ep in endpoints_str.split(",")]

        ttl = int(os.environ.get("LEADER_TTL", "15"))
        instance_id = os.environ.get("INSTANCE_ID", f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}")

        return cls(
            etcd_endpoints=endpoints,
            lease_ttl_seconds=ttl,
            instance_id=instance_id,
            service_name=service_name,
        )


class LeaderElectedHostedService(ReconciliationHostedService[T], Generic[T]):
    """
    Reconciliation service with leader election via etcd.

    Only the leader instance runs the reconciliation loop. Non-leaders
    watch for leadership changes and take over if the leader fails.

    Uses etcd lease mechanism:
    1. Acquire lease with TTL
    2. Attempt to write election key with lease
    3. If successful, become leader
    4. Continuously renew lease while leader
    5. If lease expires or is revoked, step down

    Example:
        class MyScheduler(LeaderElectedHostedService[MyResource]):
            def __init__(
                self,
                etcd_client: EtcdClient,
                api_client: ControlPlaneApiClient,
            ):
                super().__init__(
                    reconciliation_config=ReconciliationConfig(
                        interval_seconds=30,
                        service_name="my-scheduler",
                    ),
                    election_config=LeaderElectionConfig.from_env("my-scheduler"),
                    etcd_client=etcd_client,
                )
                self._api = api_client

            async def list_resources(self):
                return await self._api.get_pending_items()

            async def reconcile(self, resource):
                # Only runs when this instance is leader
                ...
    """

    def __init__(
        self,
        reconciliation_config: ReconciliationConfig | None = None,
        election_config: LeaderElectionConfig | None = None,
        etcd_client: Any | None = None,  # Type: EtcdClient from integration
    ):
        """Initialize the leader-elected reconciliation service.

        Args:
            reconciliation_config: Configuration for the reconciliation loop.
            election_config: Configuration for leader election.
            etcd_client: etcd client for leader election. If None, mock mode is used.
        """
        super().__init__(reconciliation_config)
        self._election_config = election_config or LeaderElectionConfig()
        self._etcd = etcd_client

        # Leader state
        self._is_leader = False
        self._current_leader_id: str | None = None
        self._lease: Any | None = None  # etcd lease object

        # Background tasks
        self._leader_task: asyncio.Task[None] | None = None
        self._renewal_task: asyncio.Task[None] | None = None

        # Callbacks
        self._on_elected_callbacks: list[Callable[[], Any]] = []
        self._on_demoted_callbacks: list[Callable[[], Any]] = []

    @property
    def is_leader(self) -> bool:
        """Check if this instance is currently the leader."""
        return self._is_leader

    @property
    def current_leader_id(self) -> str | None:
        """Get the current leader's instance ID (may be another instance)."""
        return self._current_leader_id

    @property
    def instance_id(self) -> str:
        """Get this instance's ID."""
        return self._election_config.instance_id

    def on_elected(self, callback: Callable[[], Any]) -> None:
        """Register callback for when this instance becomes leader."""
        self._on_elected_callbacks.append(callback)

    def on_demoted(self, callback: Callable[[], Any]) -> None:
        """Register callback for when this instance loses leadership."""
        self._on_demoted_callbacks.append(callback)

    async def start_async(self) -> None:
        """Start the leader election and reconciliation service."""
        if self._started:
            logger.warning(f"{self._config.service_name}: Already started")
            return

        logger.info(f"{self._config.service_name}: Starting leader-elected service " f"(instance_id={self._election_config.instance_id})")

        # Connect etcd client if available (must happen before leader election)
        if self._etcd is not None and hasattr(self._etcd, "connect"):
            try:
                await self._etcd.connect()
                logger.info(f"{self._config.service_name}: etcd client connected")
            except Exception as e:
                logger.warning(f"{self._config.service_name}: Failed to connect etcd, falling back to mock mode: {e}")
                self._etcd = None  # Fall back to mock mode

        self._init_metrics()
        self._stopping = False
        self._started = True
        self._semaphore = asyncio.Semaphore(self._config.max_concurrent_reconciles)

        # Start leader election in background
        self._leader_task = asyncio.create_task(self._leader_election_loop(), name=f"{self._config.service_name}_leader_election")

        logger.info(f"{self._config.service_name}: Started leader election")

    async def stop_async(self) -> None:
        """Stop the service and release leadership if held."""
        if not self._started:
            return

        logger.info(f"{self._config.service_name}: Stopping leader-elected service")
        self._stopping = True

        # Stop renewal task first
        if self._renewal_task:
            self._renewal_task.cancel()
            try:
                await self._renewal_task
            except asyncio.CancelledError:
                pass
            self._renewal_task = None

        # Step down from leadership
        if self._is_leader:
            await self._step_down()

        # Cancel leader election task
        if self._leader_task:
            self._leader_task.cancel()
            try:
                await self._leader_task
            except asyncio.CancelledError:
                pass
            self._leader_task = None

        # Cancel reconciliation task
        if self._reconcile_task:
            self._reconcile_task.cancel()
            try:
                await self._reconcile_task
            except asyncio.CancelledError:
                pass
            self._reconcile_task = None

        self._started = False
        logger.info(f"{self._config.service_name}: Stopped")

    async def _leader_election_loop(self) -> None:
        """Main loop for leader election attempts."""
        while not self._stopping:
            try:
                if not self._is_leader:
                    await self._try_become_leader()
                else:
                    # Already leader, just wait
                    await asyncio.sleep(self._election_config.renewal_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"{self._config.service_name}: Error in leader election: {e}")
                await asyncio.sleep(1.0)

    async def _try_become_leader(self) -> None:
        """Attempt to become the leader."""
        if self._etcd is None:
            # Mock mode - always become leader
            logger.info(f"{self._config.service_name}: Mock mode - becoming leader immediately")
            await self._become_leader()
            return

        try:
            # Grant a lease
            self._lease = await self._etcd.grant_lease(self._election_config.lease_ttl_seconds)

            # Try to acquire the election key
            acquired = await self._etcd.put_if_not_exists(
                key=self._election_config.election_key,
                value=self._election_config.instance_id,
                lease=self._lease,
            )

            if acquired:
                await self._become_leader()
            else:
                # Someone else is leader, watch for changes
                current_leader = await self._etcd.get(self._election_config.election_key)
                self._current_leader_id = current_leader
                logger.info(f"{self._config.service_name}: Not leader. Current leader: {current_leader}")

                # Wait before retrying
                await asyncio.sleep(self._election_config.lease_ttl_seconds / 2)

        except Exception as e:
            logger.error(f"{self._config.service_name}: Failed to acquire leadership: {e}")
            if self._lease:
                try:
                    await self._etcd.revoke_lease(self._lease)
                except Exception:
                    pass
                self._lease = None
            await asyncio.sleep(1.0)

    async def _become_leader(self) -> None:
        """Handle becoming the leader."""
        self._is_leader = True
        self._current_leader_id = self._election_config.instance_id

        logger.info(f"{self._config.service_name}: 🎉 Became leader (instance_id={self.instance_id})")

        # Start lease renewal
        if self._etcd is not None and self._lease is not None:
            self._renewal_task = asyncio.create_task(self._lease_renewal_loop(), name=f"{self._config.service_name}_lease_renewal")

        # Start reconciliation loop (if polling enabled)
        # Note: Watch-triggered reconciliation (WatchTriggeredHostedService) still works
        # regardless of this setting - this only controls periodic polling.
        if self._config.polling_enabled:
            self._reconcile_task = asyncio.create_task(self._run_reconciliation_loop(), name=f"{self._config.service_name}_reconcile_loop")
        else:
            logger.info(f"{self._config.service_name}: Polling disabled - using watch-only mode (ADR-015)")

        # Notify callbacks
        for callback in self._on_elected_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                logger.error(f"{self._config.service_name}: Error in on_elected callback: {e}")

    async def _step_down(self) -> None:
        """Handle stepping down from leadership."""
        was_leader = self._is_leader
        self._is_leader = False

        if was_leader:
            logger.info(f"{self._config.service_name}: Stepping down from leadership")

            # Stop reconciliation loop
            if self._reconcile_task:
                self._reconcile_task.cancel()
                try:
                    await self._reconcile_task
                except asyncio.CancelledError:
                    pass
                self._reconcile_task = None

            # Revoke lease (releases election key)
            if self._etcd is not None and self._lease is not None:
                try:
                    await self._etcd.revoke_lease(self._lease)
                except Exception as e:
                    logger.warning(f"{self._config.service_name}: Error revoking lease: {e}")
                self._lease = None

            # Notify callbacks
            for callback in self._on_demoted_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback()
                    else:
                        callback()
                except Exception as e:
                    logger.error(f"{self._config.service_name}: Error in on_demoted callback: {e}")

    async def resign_leadership(self) -> None:
        """Voluntarily resign leadership.

        This allows another instance to become leader.
        Useful for maintenance or testing scenarios.
        """
        if not self._is_leader:
            logger.warning(f"{self._config.service_name}: Cannot resign - not currently leader")
            return

        logger.info(f"{self._config.service_name}: Voluntarily resigning leadership")
        await self._step_down()

    async def _lease_renewal_loop(self) -> None:
        """Continuously renew the etcd lease while leader."""
        while not self._stopping and self._is_leader:
            try:
                await asyncio.sleep(self._election_config.renewal_interval_seconds)

                if self._etcd is not None and self._lease is not None:
                    await self._etcd.refresh_lease(self._lease)
                    logger.debug(f"{self._config.service_name}: Lease renewed")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"{self._config.service_name}: Lease renewal failed: {e}")
                # Lost leadership
                await self._step_down()
                break

    async def _run_reconciliation_loop(self) -> None:
        """Override to only run when leader."""
        # Initial delay
        if self._config.initial_delay_seconds > 0:
            logger.debug(f"{self._config.service_name}: Waiting {self._config.initial_delay_seconds}s before first reconcile")
            await asyncio.sleep(self._config.initial_delay_seconds)

        while not self._stopping and self._is_leader:
            try:
                await self._reconcile_all()
            except asyncio.CancelledError:
                logger.debug(f"{self._config.service_name}: Reconciliation loop cancelled")
                break
            except Exception as e:
                logger.exception(f"{self._config.service_name}: Error in reconciliation loop: {e}")

            # Wait for next cycle (but check leadership)
            if not self._stopping and self._is_leader:
                await asyncio.sleep(self._config.interval_seconds)

    @property
    def stats(self) -> dict[str, Any]:
        """Get current service statistics including leader status."""
        base_stats = super().stats
        return {
            **base_stats,
            "is_leader": self._is_leader,
            "current_leader_id": self._current_leader_id,
            "instance_id": self._election_config.instance_id,
            "service_name": self._config.service_name,
        }
