"""Cleanup Hosted Service.

Periodic background service to clean up terminated worker records.
Uses leader election to ensure only one instance runs cleanup.

Part of ADR-014 (Worker Orphan Detection) - cleanup of terminated records
is handled by resource-scheduler, while orphan detection is in worker-controller.
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from lcm_core.infrastructure.hosted_services import LeaderElectionConfig
from lcm_core.integration.clients import ControlPlaneApiClient, EtcdClient
from neuroglia.hosting.abstractions import HostedService

from application.settings import Settings

if TYPE_CHECKING:
    from neuroglia.dependency_injection import ServiceCollection

logger = logging.getLogger(__name__)


class CleanupHostedService(HostedService):
    """
    Leader-elected periodic cleanup service for terminated workers.

    This service:
    1. Uses etcd for leader election (only leader runs cleanup)
    2. Periodically invokes the cleanup terminated workers endpoint
    3. Reports cleanup results in logs

    Cleanup operations:
    - Remove TERMINATED worker records older than retention period
    - This prevents database bloat from accumulated terminated records
    """

    def __init__(
        self,
        api_client: ControlPlaneApiClient,
        etcd_client: EtcdClient,
        settings: Settings,
    ) -> None:
        """Initialize the cleanup hosted service.

        Args:
            api_client: Client for Control Plane API calls.
            etcd_client: Client for etcd leader election.
            settings: Application settings.
        """
        super().__init__()
        self._api = api_client
        self._etcd = etcd_client
        self._settings = settings

        # Leader election configuration
        self._election_config = LeaderElectionConfig(
            etcd_endpoints=settings.etcd_endpoints,
            lease_ttl_seconds=settings.leader_lease_ttl,
            service_name="cleanup-service",
        )

        # State
        self._is_leader = False
        self._started = False
        self._cleanup_task: asyncio.Task | None = None
        self._leader_task: asyncio.Task | None = None

        # Metrics
        self._cleanup_runs = 0
        self._last_cleanup_at: str | None = None
        self._last_cleanup_result: dict[str, Any] | None = None

    async def start_async(self) -> None:
        """Start the cleanup service."""
        if not self._settings.cleanup_enabled:
            logger.info("Cleanup service disabled by configuration")
            return

        self._started = True
        logger.info(f"Starting cleanup service (interval={self._settings.cleanup_interval_seconds}s, retention={self._settings.cleanup_retention_days} days)")

        # Start leader election
        self._leader_task = asyncio.create_task(self._leader_loop())

    async def stop_async(self) -> None:
        """Stop the cleanup service."""
        self._started = False
        self._is_leader = False

        # Cancel tasks
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        if self._leader_task:
            self._leader_task.cancel()
            try:
                await self._leader_task
            except asyncio.CancelledError:
                pass

        logger.info("Cleanup service stopped")

    async def _leader_loop(self) -> None:
        """Leader election loop - runs cleanup when leader."""
        while self._started:
            try:
                # Try to acquire leadership
                if await self._try_become_leader():
                    if not self._is_leader:
                        logger.info("Cleanup service acquired leadership")
                        self._is_leader = True
                        # Start cleanup loop
                        if self._cleanup_task is None or self._cleanup_task.done():
                            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
                else:
                    if self._is_leader:
                        logger.info("Cleanup service lost leadership")
                        self._is_leader = False
                        # Cancel cleanup
                        if self._cleanup_task:
                            self._cleanup_task.cancel()

                # Wait before next election attempt
                await asyncio.sleep(self._election_config.renewal_interval_seconds)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in leader loop: {e}")
                await asyncio.sleep(5.0)

    async def _try_become_leader(self) -> bool:
        """Attempt to acquire or maintain leadership."""
        try:
            return await self._etcd.try_acquire_leadership(
                key=f"/lcm/{self._election_config.service_name}/leader",
                lease_ttl=self._election_config.lease_ttl_seconds,
            )
        except Exception as e:
            logger.warning(f"Leader election failed: {e}")
            return False

    async def _cleanup_loop(self) -> None:
        """Periodic cleanup loop - only runs when leader."""
        while self._started and self._is_leader:
            try:
                await self._run_cleanup()

                # Wait for next interval
                await asyncio.sleep(self._settings.cleanup_interval_seconds)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
                await asyncio.sleep(60.0)  # Wait before retrying

    async def _run_cleanup(self) -> None:
        """Run a single cleanup operation."""
        logger.info(f"Running cleanup (retention={self._settings.cleanup_retention_days} days)")

        try:
            result = await self._api.cleanup_terminated_workers(
                retention_days=self._settings.cleanup_retention_days,
                dry_run=False,
            )

            self._cleanup_runs += 1
            self._last_cleanup_result = result

            from datetime import datetime, timezone

            self._last_cleanup_at = datetime.now(timezone.utc).isoformat()

            # Log results
            deleted_count = result.get("deleted_count", 0)
            if deleted_count > 0:
                logger.info(f"✅ Cleanup complete: {deleted_count} terminated workers deleted")
            else:
                logger.debug("Cleanup complete: no workers to delete")

        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            self._last_cleanup_result = {"error": str(e)}

    # =========================================================================
    # Service Info
    # =========================================================================

    @property
    def stats(self) -> dict[str, Any]:
        """Get cleanup service statistics."""
        return {
            "enabled": self._settings.cleanup_enabled,
            "is_leader": self._is_leader,
            "cleanup_runs": self._cleanup_runs,
            "last_cleanup_at": self._last_cleanup_at,
            "last_cleanup_result": self._last_cleanup_result,
            "interval_seconds": self._settings.cleanup_interval_seconds,
            "retention_days": self._settings.cleanup_retention_days,
        }

    @classmethod
    def configure(
        cls,
        services: "ServiceCollection",
        settings: Settings,
    ) -> None:
        """Configure DI registration.

        Args:
            services: Neuroglia service collection.
            settings: Application settings.
        """

        def factory(sp) -> CleanupHostedService:
            return cls(
                api_client=sp.get_required_service(ControlPlaneApiClient),
                etcd_client=sp.get_required_service(EtcdClient),
                settings=settings,
            )

        # NOTE: implementation_type=cls ensures Neuroglia resolves the actual class,
        # not a string from inspect.signature().return_annotation.
        services.add_singleton(cls, implementation_type=cls, implementation_factory=factory)
