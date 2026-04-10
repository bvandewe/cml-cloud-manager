"""Worker Reconciler Hosted Service.

Leader-elected reconciliation service for CMLWorker lifecycle management.
Extends WatchTriggeredHostedService from lcm_core to provide:
- Automatic leader election via etcd
- Reconciliation loop that only runs on the leader
- etcd watch for immediate reconciliation on state changes
- Worker lifecycle management (provision, start, stop, terminate)
- Metrics collection (CloudWatch + CML System API)

Domain: Infrastructure Layer (Compute Resources)
SPI: AWS EC2, CloudWatch, CML System API

Reconciliation Pattern:
    SPEC (Worker from Control Plane API) ←→ OBSERVE (EC2 + CML state) → ACT (reconcile)

Watch Pattern (ADR-006):
    control-plane-api publishes worker state to etcd (/lcm/workers/{id}/state)
    worker-controller watches etcd prefix and triggers immediate reconciliation
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from infrastructure.observability import (
    record_scale_down_evaluation,
    record_scaling_event,
)
from integration.services.aws_cloudwatch_spi import AwsCloudWatchSpiClient
from integration.services.aws_ec2_spi import AwsCredentials, AwsEc2SpiClient
from integration.services.cml_system_spi import CmlSystemSpiClient
from lcm_core.domain.entities import CMLWorkerReadModel
from lcm_core.domain.enums import CMLWorkerStatus
from lcm_core.infrastructure.hosted_services import (
    LeaderElectionConfig,
    ReconciliationConfig,
    ReconciliationResult,
    WatchConfig,
    WatchTriggeredHostedService,
)
from lcm_core.integration.clients import ControlPlaneApiClient, EtcdClient
from lcm_core.integration.clients.etcd_client import EtcdEvent

from application.settings import Settings

if TYPE_CHECKING:
    from neuroglia.dependency_injection import ServiceCollection

logger = logging.getLogger(__name__)

# Settings cache TTL in seconds (5 minutes)
_DISCOVERY_SETTINGS_CACHE_TTL = 300


@dataclass
class CachedDiscoverySettings:
    """Cached discovery settings from Control Plane API (ADR-012)."""

    enabled: bool
    regions: list[str]
    ami_name_pattern: str
    scan_interval_seconds: int
    fetched_at: datetime


class WorkerReconciler(WatchTriggeredHostedService[CMLWorkerReadModel]):
    """
    Leader-elected hosted service for CMLWorker lifecycle management with etcd watch.

    This service:
    1. Uses etcd for leader election (only leader reconciles)
    2. Watches etcd for worker state changes (immediate reconciliation)
    3. Periodically fetches workers needing reconciliation (fallback polling)
    4. For each worker:
       - Compare desired state with actual EC2/CML state
       - Take action to align (provision, start, stop, terminate)
       - Collect and report metrics

    Dual-mode reconciliation:
    - **Watch (reactive)**: Immediate reconcile when etcd state changes
    - **Polling (fallback)**: Periodic reconcile every interval_seconds

    Extends WatchTriggeredHostedService which provides:
    - Automatic leader election via etcd
    - Reconciliation loop pattern with watch support
    - Metrics and stats
    - Exponential backoff on failures

    Domain: Infrastructure Layer - Compute Resource Management
    SPI: AWS EC2 + CloudWatch + CML System API

    All mutations go through Control Plane API (ADR-001).
    """

    def __init__(
        self,
        api_client: ControlPlaneApiClient,
        etcd_client: EtcdClient,
        ec2_client: AwsEc2SpiClient,
        cloudwatch_client: AwsCloudWatchSpiClient,
        cml_client: CmlSystemSpiClient,
        settings: Settings,
    ) -> None:
        """Initialize the worker reconciler.

        Args:
            api_client: Client for Control Plane API.
            etcd_client: Client for etcd leader election and watch.
            ec2_client: AWS EC2 SPI client.
            cloudwatch_client: AWS CloudWatch SPI client.
            cml_client: CML System SPI client.
            settings: Application settings.
        """
        # Configure reconciliation (polling fallback)
        # ADR-015: polling_enabled can be set to False for watch-only mode
        reconciliation_config = ReconciliationConfig(
            interval_seconds=settings.reconcile_interval,
            initial_delay_seconds=5.0,
            polling_enabled=settings.reconcile_polling_enabled,
            max_concurrent_reconciles=5,  # Workers are expensive - limit parallelism
            service_name="worker-controller",
        )

        # Configure leader election
        election_config = LeaderElectionConfig(
            etcd_endpoints=settings.etcd_endpoints,
            lease_ttl_seconds=settings.leader_lease_ttl,
            service_name="worker-controller",
        )

        # Configure etcd watch for reactive reconciliation
        watch_config = WatchConfig(
            enabled=settings.etcd_watch_enabled,
            prefix="/workers/",  # Watch /lcm/workers/* for state changes
            debounce_seconds=0.5,
        )

        super().__init__(
            reconciliation_config=reconciliation_config,
            election_config=election_config,
            watch_config=watch_config,
            etcd_client=etcd_client,
        )

        self._api = api_client
        self._ec2 = ec2_client
        self._cloudwatch = cloudwatch_client
        self._cml = cml_client
        self._settings = settings

        # Extended metrics
        self._provisioned_count = 0
        self._started_count = 0
        self._stopped_count = 0
        self._terminated_count = 0
        self._metrics_collected_count = 0
        self._activity_checks_count = 0
        self._auto_pauses_triggered_count = 0
        self._license_registrations_count = 0
        self._license_deregistrations_count = 0

        # Scale-down tracking (Phase 3 - Auto-Scaling)
        self._scale_down_count = 0
        self._last_scale_down_at: datetime | None = None
        self._running_worker_count = 0  # Updated each reconciliation cycle

        # Independent metrics collection task (runs on leader regardless of poll/watch mode)
        self._metrics_task: asyncio.Task[None] | None = None

        # Independent discovery task (runs on leader only — ADR-020)
        self._discovery_task: asyncio.Task[None] | None = None
        self._cached_discovery_settings: CachedDiscoverySettings | None = None

        # Discovery statistics
        self._discovery_runs = 0
        self._total_discovered = 0
        self._total_imported = 0
        self._total_orphans_terminated = 0
        self._last_discovery_at: datetime | None = None
        self._last_discovery_error: str | None = None

    # =========================================================================
    # Leader Lifecycle (start/stop metrics + discovery)
    # =========================================================================

    async def _become_leader(self) -> None:
        """Handle becoming the leader.

        Extends parent to start independent loops for:
        - Metrics collection (proactive, timer-driven)
        - Worker discovery (proactive, timer-driven)

        Both are separate from reconciliation because they are periodic concerns
        that should run regardless of watch-only vs poll mode (AD-018, AD-020).
        """
        await super()._become_leader()

        # Start independent metrics collection loop
        poll_interval = getattr(self._settings, "metrics_poll_interval", 300) or 300
        self._metrics_task = asyncio.create_task(
            self._run_metrics_collection_loop(),
            name=f"{self._config.service_name}_metrics_loop",
        )
        logger.info(f"{self._config.service_name}: Started independent metrics collection loop (interval={poll_interval}s)")

        # Start independent discovery loop (AD-020)
        if self._settings.worker_discovery_enabled:
            self._discovery_task = asyncio.create_task(
                self._run_discovery_loop(),
                name=f"{self._config.service_name}_discovery_loop",
            )
            logger.info(f"{self._config.service_name}: Started independent discovery loop (interval={self._settings.worker_discovery_interval}s)")
        else:
            logger.info(f"{self._config.service_name}: Worker discovery is disabled")

    async def _step_down(self) -> None:
        """Handle stepping down from leadership.

        Extends parent to stop the metrics and discovery loops.
        """
        # Stop metrics collection task
        if self._metrics_task:
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass
            self._metrics_task = None
            logger.info(f"{self._config.service_name}: Stopped metrics collection loop")

        # Stop discovery task (AD-020)
        if self._discovery_task:
            self._discovery_task.cancel()
            try:
                await self._discovery_task
            except asyncio.CancelledError:
                pass
            self._discovery_task = None
            logger.info(f"{self._config.service_name}: Stopped discovery loop")

        await super()._step_down()

    # =========================================================================
    # Watch-Triggered Reconciliation (WatchTriggeredHostedService)
    # =========================================================================

    @property
    def watch_prefix(self) -> str:
        """Get the etcd key prefix to watch for worker state changes.

        Watches /lcm/workers/ for state changes published by control-plane-api.
        Key structure:
        - /lcm/workers/{worker_id}/state - Actual EC2 state (updated by worker-controller)
        - /lcm/workers/{worker_id}/desired_state - User-requested state (ADR-015)
        - /lcm/workers/{worker_id}/license - Pending license operation (ADR-016)

        ADR-015: When desired_state changes (e.g., user requests stop/start),
        this triggers immediate reconciliation without waiting for polling.

        ADR-016: When license pending operation changes (register/deregister),
        this triggers immediate license reconciliation without waiting for polling.
        """
        prefix = getattr(self._settings, "etcd_key_prefix", "/lcm").rstrip("/")
        return f"{prefix}/workers/"

    async def on_watch_event(self, event: EtcdEvent) -> str | None:
        """Process watch event and extract worker ID for reconciliation.

        Args:
            event: etcd watch event with key like:
                - /workers/{id}/state
                - /workers/{id}/desired_state
                - /workers/{id}/license

        Returns:
            Worker ID to reconcile, or None to skip.
        """
        # Key format: /workers/{worker_id}/state or /workers/{worker_id}/desired_state or /workers/{worker_id}/license
        # Split: ['', 'workers', '{worker_id}', 'state|desired_state|license']
        key_stripped = event.key
        prefix = getattr(self._settings, "etcd_key_prefix", "/lcm").rstrip("/")
        if prefix and key_stripped.startswith(prefix):
            key_stripped = key_stripped[len(prefix) :]

        parts = key_stripped.strip("/").split("/")

        if len(parts) >= 2 and parts[0] == "workers":
            worker_id = parts[1]
            key_type = parts[2] if len(parts) >= 3 else "unknown"
            logger.info(f"Watch event: {event.type} for worker {worker_id} key={key_type} (value={event.value})")
            return worker_id

        return None

    async def fetch_resource_by_id(self, resource_id: str) -> CMLWorkerReadModel | None:
        """Fetch a single worker by ID for targeted watch-triggered reconciliation.

        Args:
            resource_id: The worker ID to fetch.

        Returns:
            CMLWorkerReadModel or None if not found.
        """
        try:
            worker_data = await self._api.get_worker(resource_id)
            if worker_data:
                return CMLWorkerReadModel.from_dict(worker_data)
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch worker {resource_id}: {e}")
            return None

    # =========================================================================
    # Resource Listing (ReconciliationHostedService)
    # =========================================================================

    async def list_resources(self) -> list[CMLWorkerReadModel]:
        """Fetch all workers needing reconciliation from Control Plane API.

        Returns all non-terminal workers. This ensures the startup
        reconciliation sweep (AD-031) picks up ALL resources that the
        watch stream would also react to. The reconcile() method
        gracefully handles statuses without dedicated handlers.

        Returns:
            List of CMLWorkerReadModel objects to reconcile.
        """
        try:
            workers_data = await self._api.get_workers()
            workers = [CMLWorkerReadModel.from_dict(data) for data in workers_data]

            # Filter to non-terminal statuses — matches what on_watch_event()
            # would trigger reconciliation for. Terminal statuses (STOPPED,
            # TERMINATED, FAILED, UNKNOWN) don't need active reconciliation
            # unless a desired_state change arrives via the watch stream.
            terminal_statuses = {
                CMLWorkerStatus.STOPPED,
                CMLWorkerStatus.TERMINATED,
                CMLWorkerStatus.SHUTTING_DOWN,
                CMLWorkerStatus.FAILED,
                CMLWorkerStatus.UNKNOWN,
            }
            needs_reconcile = [w for w in workers if w.status and w.status not in terminal_statuses]

            # Track running worker count for scale-down decisions (Phase 3)
            self._running_worker_count = sum(1 for w in workers if w.status == CMLWorkerStatus.RUNNING)

            logger.debug(f"Found {len(needs_reconcile)} workers needing reconciliation (of {len(workers)} total, {self._running_worker_count} running)")
            return needs_reconcile

        except Exception as e:
            logger.error(f"Failed to list workers: {e}")
            return []

    def get_resource_id(self, resource: CMLWorkerReadModel) -> str:
        """Extract unique ID from worker for tracking."""
        return resource.id

    async def reconcile(self, worker: CMLWorkerReadModel) -> ReconciliationResult:
        """Reconcile a single worker.

        Args:
            worker: The CMLWorker to reconcile.

        Returns:
            ReconciliationResult indicating success/requeue/fail.
        """
        worker_id = worker.id
        logger.debug(f"Reconciling worker {worker_id} (status={worker.status}, desired={worker.desired_status})")

        try:
            # Route to appropriate handler based on current status
            if worker.status == CMLWorkerStatus.PENDING:
                return await self._handle_pending(worker)
            elif worker.status == CMLWorkerStatus.PROVISIONING:
                return await self._handle_provisioning(worker)
            elif worker.status == CMLWorkerStatus.STARTING:
                return await self._handle_starting(worker)
            elif worker.status == CMLWorkerStatus.RUNNING:
                return await self._handle_running(worker)
            elif worker.status in (CMLWorkerStatus.STOPPING, CMLWorkerStatus.DRAINING):
                return await self._handle_stopping(worker)
            elif worker.status == CMLWorkerStatus.STOPPED:
                return await self._handle_stopped(worker)
            elif worker.status == CMLWorkerStatus.TERMINATING:
                return await self._handle_terminating(worker)
            else:
                logger.warning(f"Unknown worker status: {worker.status}")
                return ReconciliationResult.success()

        except Exception as e:
            logger.exception(f"Error reconciling worker {worker_id}: {e}")
            return ReconciliationResult.failed(str(e), e)

    # =========================================================================
    # STATUS HANDLERS (State Machine)
    # =========================================================================

    async def _handle_pending(self, worker: CMLWorkerReadModel) -> ReconciliationResult:
        """Handle PENDING worker - provision EC2 instance.

        Cloud Provider SPI: EC2 RunInstances

        Flow (ADR-016, ADR-018):
        1. Fetch worker template from control-plane-api by template_name
        2. Get per-region infrastructure config (security group, subnet) from settings
        3. Resolve AMI name → AMI ID via EC2 DescribeImages
        4. Launch EC2 instance via run_instance()
        5. Update worker status to PROVISIONING with EC2 instance ID
        """
        logger.info(f"Provisioning EC2 instance for worker {worker.id} (template={worker.template_name})")

        try:
            # 1. Resolve template configuration
            template_name = worker.template_name
            if not template_name:
                return ReconciliationResult.failed("Worker has no template_name - cannot provision without template configuration")

            template_data = await self._api.get_worker_template(template_name)
            if not template_data:
                return ReconciliationResult.failed(f"Worker template '{template_name}' not found in control-plane-api")

            instance_type = template_data.get("instance_type") or worker.instance_type
            ami_name_pattern = template_data.get("ami_name_pattern")
            if not instance_type:
                return ReconciliationResult.failed("No instance_type in template or worker")

            # 2. Get per-region infrastructure config (ADR-018)
            aws_region = worker.aws_region or self._settings.aws_region
            region_config = self._settings.get_region_config(aws_region)
            if not region_config:
                return ReconciliationResult.failed(f"No infrastructure config for region '{aws_region}'. Add region to config/aws_regions.yaml")

            if not region_config.subnet_id:
                return ReconciliationResult.failed(f"No subnet_id configured for region '{aws_region}'")

            if not region_config.security_group_ids:
                return ReconciliationResult.failed(f"No security_group_ids configured for region '{aws_region}'")

            # 3. Resolve AMI name → AMI ID
            ami_name = ami_name_pattern or worker.ami_name
            if not ami_name:
                return ReconciliationResult.failed("No AMI name pattern in template or worker - cannot resolve AMI ID")

            ami_ids = await self._ec2.get_ami_ids_by_name(ami_name)
            if not ami_ids:
                return ReconciliationResult.failed(f"No AMI found matching name pattern '{ami_name}' in region '{aws_region}'")
            # Use the first (most recent) matching AMI
            ami_id = ami_ids[0]
            logger.info(f"Resolved AMI: name='{ami_name}' → id='{ami_id}' (of {len(ami_ids)} matches)")

            # 4. Build instance tags
            tags = {
                "Name": f"cml-worker-{worker.name}",
                "lcm:worker_id": worker.id,
                "lcm:template_name": template_name,
                "lcm:managed_by": "lablet-cloud-manager",
            }
            if region_config.default_tags:
                # Region defaults first, then worker-specific tags override
                merged_tags = dict(region_config.default_tags)
                merged_tags.update(tags)
                tags = merged_tags

            # 5. Launch EC2 instance
            logger.info(f"Launching EC2 instance: ami={ami_id}, type={instance_type}, subnet={region_config.subnet_id}, sgs={region_config.security_group_ids}")
            instance_id = await self._ec2.run_instance(
                ami_id=ami_id,
                instance_type=instance_type,
                subnet_id=region_config.subnet_id,
                security_group_ids=region_config.security_group_ids,
                key_name=region_config.key_name,
                tags=tags,
            )

            # 6. Update worker status to PROVISIONING with EC2 instance ID
            await self._api.update_worker_status(
                worker_id=worker.id,
                status=CMLWorkerStatus.PROVISIONING,
                ec2_instance_id=instance_id,
            )

            logger.info(f"Worker {worker.id} provisioning started: ec2_instance_id={instance_id}, template={template_name}, region={aws_region}")
            self._provisioned_count += 1

            # Scaling audit: EC2 provisioning initiated
            record_scaling_event(
                action="ec2_provision_initiated",
                worker_id=worker.id,
                template=template_name,
            )

            # Requeue to check provisioning progress on next cycle
            return ReconciliationResult.requeue("EC2 instance launched, waiting for running state")

        except Exception as e:
            logger.error(f"Failed to provision worker {worker.id}: {e}", exc_info=True)
            # Scaling audit: EC2 provisioning failed
            record_scaling_event(
                action="ec2_provision_failed",
                worker_id=worker.id,
                template=worker.template_name or "",
                reason=str(e),
                success=False,
            )
            # Update worker status to ERROR so it's not retried indefinitely
            try:
                await self._api.update_worker_status(
                    worker_id=worker.id,
                    status=CMLWorkerStatus.FAILED,
                )
            except Exception as status_err:
                logger.error(f"Failed to update worker {worker.id} status to FAILED: {status_err}")
            return ReconciliationResult.failed(str(e), e)

    async def _handle_provisioning(self, worker: CMLWorkerReadModel) -> ReconciliationResult:
        """Handle PROVISIONING worker - check if EC2 is ready.

        Cloud Provider SPI: EC2 DescribeInstances
        """
        if not worker.ec2_instance_id:
            return ReconciliationResult.failed("Worker in PROVISIONING but no EC2 instance ID")

        # Check EC2 state
        state = await self._ec2.get_instance_state(worker.ec2_instance_id)
        if not state:
            return ReconciliationResult.failed(f"EC2 instance {worker.ec2_instance_id} not found")

        if state.state == "running":
            # Instance is ready - update to RUNNING and record IP
            await self._api.update_worker_status(
                worker_id=worker.id,
                status=CMLWorkerStatus.RUNNING,
                ip_address=state.public_ip or state.private_ip,
            )
            logger.info(f"Worker {worker.id} provisioned and running at {state.public_ip or state.private_ip}")
            self._provisioned_count += 1

            # Report EC2 instance details (AMI info) to CPA
            await self._report_ec2_details(worker.id, state)

            return ReconciliationResult.success()

        elif state.state == "pending":
            # Still starting up - requeue
            return ReconciliationResult.requeue("EC2 instance still pending")

        else:
            # Unexpected state
            return ReconciliationResult.failed(f"EC2 instance in unexpected state: {state.state}")

    async def _handle_starting(self, worker: CMLWorkerReadModel) -> ReconciliationResult:
        """Handle STARTING worker - start stopped EC2 instance.

        Cloud Provider SPI: EC2 StartInstances
        """
        if not worker.ec2_instance_id:
            return ReconciliationResult.failed("Worker in STARTING but no EC2 instance ID")

        # Check current EC2 state
        state = await self._ec2.get_instance_state(worker.ec2_instance_id)
        if not state:
            return ReconciliationResult.failed(f"EC2 instance {worker.ec2_instance_id} not found")

        if state.state == "running":
            # Already running - update status
            await self._api.update_worker_status(
                worker_id=worker.id,
                status=CMLWorkerStatus.RUNNING,
                ip_address=state.public_ip or state.private_ip,
            )
            logger.info(f"Worker {worker.id} is now running")
            self._started_count += 1

            # Report EC2 instance details (IPs, AMI info) to CPA
            # Critical: stop/start assigns a new public IP — must update
            await self._report_ec2_details(worker.id, state)

            return ReconciliationResult.success()

        elif state.state == "stopped":
            # Start the instance
            await self._ec2.start_instance(worker.ec2_instance_id)
            return ReconciliationResult.requeue("EC2 start initiated, waiting for running state")

        elif state.state == "pending":
            # Starting up - requeue
            return ReconciliationResult.requeue("EC2 instance starting")

        else:
            return ReconciliationResult.failed(f"Cannot start EC2 instance in state: {state.state}")

    async def _handle_running(self, worker: CMLWorkerReadModel) -> ReconciliationResult:
        """Handle RUNNING worker - sync state, collect metrics, and detect activity.

        Cloud Provider SPI: EC2, CloudWatch, CML System API
        """
        # Check if desired state is different
        if worker.desired_status == CMLWorkerStatus.STOPPED:
            # Transition to stopping
            await self._api.update_worker_status(
                worker_id=worker.id,
                status=CMLWorkerStatus.STOPPING,
            )
            return ReconciliationResult.requeue("Transitioning to STOPPING")

        if worker.desired_status == CMLWorkerStatus.TERMINATED:
            # Transition to terminating
            await self._api.update_worker_status(
                worker_id=worker.id,
                status=CMLWorkerStatus.TERMINATING,
            )
            return ReconciliationResult.requeue("Transitioning to TERMINATING")

        # Verify EC2 is still running
        if worker.ec2_instance_id:
            state = await self._ec2.get_instance_state(worker.ec2_instance_id)
            if state and state.state != "running":
                # EC2 state mismatch - update status
                await self._api.update_worker_status(
                    worker_id=worker.id,
                    status=self._map_ec2_state_to_worker_status(state.state),
                )
                return ReconciliationResult.requeue("EC2 state changed")

        # Note: Metrics collection runs independently via _run_metrics_collection_loop.
        # Reconciliation only handles state alignment and on-demand requests.

        # Handle on-demand refresh request (if set by user via CPA)
        if worker.refresh_requested_at:
            logger.info(f"Worker {worker.id} has pending refresh request (at {worker.refresh_requested_at})")
            await self._handle_on_demand_refresh(worker)

        # Reconcile license operations (ADR-016)
        await self._reconcile_license(worker)

        # Activity detection and auto-pause (if enabled)
        idle_result: dict[str, Any] | None = None
        if worker.is_idle_detection_enabled:
            idle_result = await self._detect_activity(worker)
            self._activity_checks_count += 1

        # Scale-down evaluation (Phase 3 - Auto-Scaling)
        if self._settings.scale_down_enabled and idle_result:
            drained = await self._evaluate_scale_down(worker, idle_result)
            if drained:
                return ReconciliationResult.requeue("Worker drained for scale-down")

        return ReconciliationResult.success()

    async def _handle_stopping(self, worker: CMLWorkerReadModel) -> ReconciliationResult:
        """Handle STOPPING/DRAINING worker - stop EC2 instance.

        Cloud Provider SPI: EC2 StopInstances
        """
        if not worker.ec2_instance_id:
            # No EC2 instance - just update status
            await self._api.update_worker_status(
                worker_id=worker.id,
                status=CMLWorkerStatus.STOPPED,
            )
            return ReconciliationResult.success()

        state = await self._ec2.get_instance_state(worker.ec2_instance_id)
        if not state:
            await self._api.update_worker_status(
                worker_id=worker.id,
                status=CMLWorkerStatus.STOPPED,
            )
            return ReconciliationResult.success()

        if state.state == "stopped":
            await self._api.update_worker_status(
                worker_id=worker.id,
                status=CMLWorkerStatus.STOPPED,
            )
            logger.info(f"Worker {worker.id} is now stopped")
            self._stopped_count += 1
            return ReconciliationResult.success()

        elif state.state == "running":
            # Stop the instance
            await self._ec2.stop_instance(worker.ec2_instance_id)
            return ReconciliationResult.requeue("EC2 stop initiated, waiting for stopped state")

        elif state.state == "stopping":
            return ReconciliationResult.requeue("EC2 instance stopping")

        else:
            return ReconciliationResult.failed(f"Cannot stop EC2 instance in state: {state.state}")

    async def _handle_stopped(self, worker: CMLWorkerReadModel) -> ReconciliationResult:
        """Handle STOPPED worker - start or terminate based on desired state.

        A stopped worker is at rest. If the desired state differs, initiate
        the appropriate transition:
        - desired=running  → transition to STARTING (EC2 StartInstances via _handle_starting)
        - desired=terminated → transition to TERMINATING (EC2 TerminateInstances via _handle_terminating)
        - otherwise        → no-op (worker is at desired state)
        """
        if worker.desired_status == CMLWorkerStatus.RUNNING:
            logger.info(f"Starting stopped worker {worker.id} (desired=running)")
            await self._api.update_worker_status(
                worker_id=worker.id,
                status=CMLWorkerStatus.STARTING,
            )
            return ReconciliationResult.requeue("Transitioning STOPPED → STARTING")

        if worker.desired_status == CMLWorkerStatus.TERMINATED:
            logger.info(f"Terminating stopped worker {worker.id} (desired=terminated)")
            await self._api.update_worker_status(
                worker_id=worker.id,
                status=CMLWorkerStatus.TERMINATING,
            )
            return ReconciliationResult.requeue("Transitioning STOPPED → TERMINATING")

        # Worker is stopped and desired is stopped (or not set) — at rest
        return ReconciliationResult.success()

    async def _handle_terminating(self, worker: CMLWorkerReadModel) -> ReconciliationResult:
        """Handle TERMINATING worker - terminate EC2 instance.

        Cloud Provider SPI: EC2 TerminateInstances
        """
        if not worker.ec2_instance_id:
            await self._api.update_worker_status(
                worker_id=worker.id,
                status=CMLWorkerStatus.TERMINATED,
            )
            return ReconciliationResult.success()

        state = await self._ec2.get_instance_state(worker.ec2_instance_id)
        if not state:
            await self._api.update_worker_status(
                worker_id=worker.id,
                status=CMLWorkerStatus.TERMINATED,
            )
            return ReconciliationResult.success()

        if state.state == "terminated":
            await self._api.update_worker_status(
                worker_id=worker.id,
                status=CMLWorkerStatus.TERMINATED,
            )
            logger.info(f"Worker {worker.id} is now terminated")
            self._terminated_count += 1
            return ReconciliationResult.success()

        elif state.state != "shutting-down":
            # Terminate the instance
            await self._ec2.terminate_instance(worker.ec2_instance_id)
            return ReconciliationResult.requeue("EC2 terminate initiated")

        else:
            return ReconciliationResult.requeue("EC2 instance shutting down")

    # =========================================================================
    # METRICS COLLECTION (Independent Loop)
    # =========================================================================

    async def _run_metrics_collection_loop(self) -> None:
        """Run independent metrics collection loop.

        Periodically polls all RUNNING workers for utilization metrics
        (CloudWatch, CML stats, CML application data) and reports to CPA.

        This loop runs independently of reconciliation because:
        - Metrics collection is proactive (timer-driven), not reactive (event-driven)
        - It should run regardless of watch-only vs poll mode
        - Architecturally analogous to the discovery loop (periodic, independent)

        Lifecycle: Started in _become_leader(), stopped in _step_down().
        """
        poll_interval = getattr(self._settings, "metrics_poll_interval", 300) or 300
        logger.info(f"{self._config.service_name}: Starting metrics collection loop (interval={poll_interval}s)")

        # Brief initial delay to let reconciliation settle first
        await asyncio.sleep(15)

        while self._is_leader and not self._stopping:
            loop_start = datetime.now(timezone.utc)
            try:
                await self._collect_all_worker_metrics()
            except asyncio.CancelledError:
                logger.info(f"{self._config.service_name}: Metrics collection loop cancelled")
                raise
            except Exception as e:
                logger.error(
                    f"{self._config.service_name}: Error in metrics collection loop: {e}",
                    exc_info=True,
                )

            # Recalculate in case settings changed
            poll_interval = getattr(self._settings, "metrics_poll_interval", 300) or 300
            elapsed = (datetime.now(timezone.utc) - loop_start).total_seconds()
            sleep_time = max(0, poll_interval - elapsed)

            logger.debug(f"{self._config.service_name}: Metrics loop sleeping {sleep_time:.0f}s (poll_interval={poll_interval}s, elapsed={elapsed:.1f}s)")
            await asyncio.sleep(sleep_time)

        logger.info(f"{self._config.service_name}: Metrics collection loop ended")

    async def _collect_all_worker_metrics(self) -> None:
        """Collect and report metrics for all RUNNING workers.

        Fetches the list of RUNNING workers from the Control Plane API,
        then collects and reports metrics for each one.
        """
        try:
            workers_data = await self._api.get_workers(status=CMLWorkerStatus.RUNNING)
        except Exception as e:
            logger.warning(f"{self._config.service_name}: Failed to fetch RUNNING workers for metrics: {e}")
            return

        if not workers_data:
            logger.debug(f"{self._config.service_name}: No RUNNING workers to collect metrics for")
            return

        workers = [CMLWorkerReadModel.from_dict(data) for data in workers_data]

        logger.info(f"{self._config.service_name}: Collecting metrics for {len(workers)} RUNNING worker(s)")

        success_count = 0
        error_count = 0
        for worker in workers:
            try:
                await self._collect_and_report_metrics(worker)
                self._metrics_collected_count += 1
                success_count += 1
            except Exception as e:
                error_count += 1
                logger.warning(f"{self._config.service_name}: Failed metrics for worker {worker.id}: {e}")

        logger.info(f"{self._config.service_name}: Metrics collection completed ({success_count} succeeded, {error_count} failed)")

    async def _collect_and_report_metrics(self, worker: CMLWorkerReadModel) -> None:
        """Collect metrics from CloudWatch and CML System API.

        Args:
            worker: Worker to collect metrics for.
        """
        collected_at = datetime.now(timezone.utc).isoformat()
        poll_interval = getattr(self._settings, "metrics_poll_interval", 300) or 300
        next_refresh_at = (datetime.now(timezone.utc) + timedelta(seconds=int(poll_interval))).isoformat()

        metrics: dict[str, Any] = {
            "collected_at": collected_at,
            "poll_interval": poll_interval,
            "next_refresh_at": next_refresh_at,
        }

        # Collect EC2 metrics from CloudWatch
        if worker.ec2_instance_id:
            try:
                ec2_metrics = await self._cloudwatch.get_ec2_metrics(worker.ec2_instance_id)
                metrics["ec2"] = {
                    "cpu_utilization": ec2_metrics.cpu_utilization,
                    "network_in_bytes": ec2_metrics.network_in_bytes,
                    "network_out_bytes": ec2_metrics.network_out_bytes,
                }
            except Exception as e:
                logger.warning(f"Failed to collect CloudWatch metrics for {worker.id}: {e}")

        # Collect CML system stats
        if worker.ip_address:
            try:
                cml_stats = await self._cml.get_system_stats(
                    host=worker.ip_address,
                    username=worker.cml_username,
                    password=worker.cml_password,
                )
                metrics["cml"] = {
                    "cpu_percent": cml_stats.cpu.percent,
                    "memory_total": cml_stats.memory.total,
                    "memory_used": cml_stats.memory.used,
                    "memory_free": cml_stats.memory.free,
                    "disk_total": cml_stats.disk.total,
                    "disk_used": cml_stats.disk.used,
                    "disk_free": cml_stats.disk.free,
                }
            except Exception as e:
                logger.warning(f"Failed to collect CML stats for {worker.id}: {type(e).__name__}: {e}")

        # Report utilization metrics to Control Plane API
        try:
            await self._api.report_worker_metrics(
                worker_id=worker.id,
                metrics=metrics,
            )
        except Exception as e:
            logger.warning(f"Failed to report metrics for {worker.id}: {e}")

        # Collect and report CML application data (system_info, health, license)
        # This is separate from utilization metrics - includes version, compute nodes, etc.
        if worker.ip_address:
            await self._collect_and_report_cml_data(worker, collected_at)

        # Backfill AMI details if missing (self-healing for imported/discovered workers)
        # Workers imported while already running never pass through the PROVISIONING→RUNNING
        # transition where _report_ec2_details is normally called. This check ensures AMI
        # metadata (name, description, creation date) gets populated on the next metrics cycle.
        if worker.ec2_instance_id and not worker.ami_name:
            try:
                state = await self._ec2.get_instance_state(worker.ec2_instance_id)
                if state:
                    await self._report_ec2_details(worker.id, state)
                    logger.info(f"Backfilled EC2/AMI details for worker {worker.id}")
            except Exception as e:
                logger.warning(f"Failed to backfill AMI details for {worker.id}: {e}")

    async def _collect_and_report_cml_data(
        self,
        worker: CMLWorkerReadModel,
        collected_at: str,
    ) -> None:
        """Collect CML application data and report to Control Plane API.

        Gathers system_info (version, readiness, compute nodes), system_health,
        and license information from the CML API.

        The system_info dict is built with keys matching what the CPA's
        CMLMetricsUpdatedDomainEvent handler expects (see CML_TELEMETRY_REMEDIATION.md).

        Args:
            worker: Worker to collect CML data for.
            collected_at: ISO 8601 timestamp of collection.
        """
        cml_data: dict[str, Any] = {"collected_at": collected_at}

        # Get CML system info (no auth required - version, readiness)
        try:
            system_info = await self._cml.get_system_info(host=worker.ip_address)
            cml_data["cml_version"] = system_info.version
            cml_data["ready"] = system_info.ready
        except Exception as e:
            logger.warning(f"Failed to get CML system info for {worker.id}: {type(e).__name__}: {e}")
            # Without system info, we can't report meaningful CML data
            return

        # Get CML system stats (authenticated - full resource data)
        # Builds the system_info dict with all keys the CPA expects:
        #   all_cpu_count, all_cpu_percent, all_memory_total/free/used,
        #   all_disk_total/free/used, controller_disk_total/free/used,
        #   allocated_cpus, allocated_memory, total_nodes, running_nodes,
        #   computes: {<uuid>: {hostname, is_controller, stats: {...}}}
        try:
            cml_stats = await self._cml.get_system_stats(
                host=worker.ip_address,
                username=worker.cml_username,
                password=worker.cml_password,
            )
            # Build system_info dict in the format expected by CPA
            system_info_dict: dict[str, Any] = {
                # Aggregate stats (all compute hosts)
                "all_cpu_count": cml_stats.cpu.count,
                "all_cpu_percent": cml_stats.cpu.percent,
                "all_memory_total": cml_stats.memory.total,
                "all_memory_free": cml_stats.memory.free,
                "all_memory_used": cml_stats.memory.used,
                "all_disk_total": cml_stats.disk.total,
                "all_disk_free": cml_stats.disk.free,
                "all_disk_used": cml_stats.disk.used,
                # Controller disk stats
                "controller_disk_total": cml_stats.controller_disk.total,
                "controller_disk_free": cml_stats.controller_disk.free,
                "controller_disk_used": cml_stats.controller_disk.used,
            }

            # Aggregate dominfo from all compute nodes
            total_allocated_cpus = 0
            total_allocated_memory = 0
            total_nodes = 0
            total_running_nodes = 0
            computes_dict: dict[str, Any] = {}

            for node in cml_stats.computes:
                total_allocated_cpus += node.stats.dominfo.allocated_cpus
                total_allocated_memory += node.stats.dominfo.allocated_memory
                total_nodes += node.stats.dominfo.total_nodes
                total_running_nodes += node.stats.dominfo.running_nodes

                # Per-compute node entry (full stats for CPA parsing)
                computes_dict[node.compute_id] = {
                    "hostname": node.hostname,
                    "is_controller": node.is_controller,
                    "stats": {
                        "cpu": {
                            "count": node.stats.cpu.count,
                            "percent": node.stats.cpu.percent,
                        },
                        "memory": {
                            "total": node.stats.memory.total,
                            "free": node.stats.memory.free,
                            "used": node.stats.memory.used,
                        },
                        "disk": {
                            "total": node.stats.disk.total,
                            "free": node.stats.disk.free,
                            "used": node.stats.disk.used,
                        },
                        "dominfo": {
                            "allocated_cpus": node.stats.dominfo.allocated_cpus,
                            "allocated_memory": node.stats.dominfo.allocated_memory,
                            "total_nodes": node.stats.dominfo.total_nodes,
                            "total_orphans": node.stats.dominfo.total_orphans,
                            "running_nodes": node.stats.dominfo.running_nodes,
                            "running_orphans": node.stats.dominfo.running_orphans,
                        },
                    },
                }

            system_info_dict["allocated_cpus"] = total_allocated_cpus
            system_info_dict["allocated_memory"] = total_allocated_memory
            system_info_dict["total_nodes"] = total_nodes
            system_info_dict["running_nodes"] = total_running_nodes
            system_info_dict["computes"] = computes_dict

            cml_data["system_info"] = system_info_dict
        except Exception as e:
            logger.warning(f"Failed to get CML system stats for {worker.id}: {type(e).__name__}: {e}")
            cml_data["system_info"] = {}

        # Get CML system health (authenticated - full health data)
        try:
            health = await self._cml.get_system_health(
                host=worker.ip_address,
                username=worker.cml_username,
                password=worker.cml_password,
            )
            # Build system_health dict with full data for CPA
            health_computes: dict[str, Any] = {}
            for ch in health.computes:
                health_computes[ch.compute_id] = {
                    "hostname": ch.hostname,
                    "is_controller": ch.is_controller,
                    "kvm_vmx_enabled": ch.kvm_vmx_enabled,
                    "enough_cpus": ch.enough_cpus,
                    "lld_connected": ch.lld_connected,
                    "lld_synced": ch.lld_synced,
                    "libvirt": ch.libvirt,
                    "fabric": ch.fabric,
                    "device_mux": ch.device_mux,
                    "refplat_images_available": ch.refplat_images_available,
                    "docker_shim": ch.docker_shim,
                    "valid": ch.valid,
                    "admission_state": ch.admission_state,
                }
            cml_data["system_health"] = {
                "valid": health.valid,
                "is_licensed": health.is_licensed,
                "is_enterprise": health.is_enterprise,
                "computes": health_computes,
                "controller": {
                    "core_connected": health.controller.core_connected,
                    "nodes_loaded": health.controller.nodes_loaded,
                    "images_loaded": health.controller.images_loaded,
                    "valid": health.controller.valid,
                },
            }
        except Exception as e:
            logger.warning(f"Failed to get CML system health for {worker.id}: {type(e).__name__}: {e}")
            # Fallback: derive minimal health from system_info readiness
            cml_data["system_health"] = {
                "valid": cml_data.get("ready", False),
                "is_licensed": False,
                "is_enterprise": False,
                "computes": {},
                "controller": {},
            }

        # Get CML license info (authenticated - full license data)
        try:
            license_info = await self._cml.get_license_info(
                host=worker.ip_address,
                username=worker.cml_username,
                password=worker.cml_password,
            )
            cml_data["license_info"] = {
                # Derived fields for CPA domain event handler
                "is_valid": license_info.is_valid,
                "registration_status": license_info.registration_status,
                "authorization_status": license_info.authorization_status,
                "node_limit": license_info.node_limit,
                "nodes_in_use": license_info.nodes_in_use,
                "expires": license_info.expires_at,
                "product": license_info.product,
                "is_enterprise": license_info.is_enterprise,
                "smart_account": license_info.smart_account,
                "virtual_account": license_info.virtual_account,
                # Full nested structure for License Details modal
                "registration": license_info.raw_response.get("registration", {}),
                "authorization": license_info.raw_response.get("authorization", {}),
                "features": license_info.features,
                "transport": license_info.raw_response.get("transport", {}),
                "udi": license_info.raw_response.get("udi", {}),
                "product_license": license_info.raw_response.get("product_license", {}),
                "reservation_mode": license_info.raw_response.get("reservation_mode", False),
            }
            # Refine health with actual license data
            if "system_health" in cml_data:
                cml_data["system_health"]["is_licensed"] = license_info.is_valid
        except Exception as e:
            logger.warning(f"Failed to get CML license info for {worker.id}: {type(e).__name__}: {e}")

        # Default labs_count to 0 (updated by lablet-controller's labs sync)
        cml_data["labs_count"] = 0

        # Report CML data to Control Plane API
        try:
            await self._api.report_worker_cml_data(
                worker_id=worker.id,
                cml_data=cml_data,
            )
            logger.debug(
                f"Reported CML data for worker {worker.id}: "
                f"version={cml_data.get('cml_version')}, ready={cml_data.get('ready')}, "
                f"cpu_count={cml_data.get('system_info', {}).get('all_cpu_count')}, "
                f"computes={len(cml_data.get('system_info', {}).get('computes', {}))}"
            )
        except Exception as e:
            logger.warning(f"Failed to report CML data for {worker.id}: {type(e).__name__}: {e}")

    # =========================================================================
    # WORKER DISCOVERY (Independent Loop — AD-020)
    # =========================================================================

    async def _run_discovery_loop(self) -> None:
        """Run independent worker discovery loop.

        Periodically scans configured AWS regions for EC2 instances matching
        the AMI pattern and submits them to CPA for registration. Also performs
        garbage collection of orphaned workers (ADR-014).

        This loop runs under leader election so only one replica discovers,
        preventing redundant AWS API calls and race conditions (AD-020).

        Lifecycle: Started in _become_leader(), stopped in _step_down().
        """
        logger.info(f"{self._config.service_name}: Starting discovery loop (interval={self._settings.worker_discovery_interval}s)")

        # Initial delay to let reconciliation settle
        await asyncio.sleep(10)

        while self._is_leader and not self._stopping:
            loop_start = datetime.now(timezone.utc)
            try:
                # Refresh settings from API (with cache)
                discovery_settings = await self._get_discovery_settings()

                if discovery_settings.enabled:
                    await self._run_discovery(discovery_settings)
                else:
                    logger.debug(f"{self._config.service_name}: Discovery disabled via API settings, skipping run")
            except asyncio.CancelledError:
                logger.info(f"{self._config.service_name}: Discovery loop cancelled")
                raise
            except Exception as e:
                self._last_discovery_error = str(e)
                logger.error(
                    f"{self._config.service_name}: Error in discovery loop: {e}",
                    exc_info=True,
                )

            # Get current interval from cached settings
            interval = self._cached_discovery_settings.scan_interval_seconds if self._cached_discovery_settings else self._settings.worker_discovery_interval
            elapsed = (datetime.now(timezone.utc) - loop_start).total_seconds()
            sleep_time = max(0, interval - elapsed)

            logger.debug(f"{self._config.service_name}: Discovery loop sleeping {sleep_time:.0f}s (interval={interval}s, elapsed={elapsed:.1f}s)")
            await asyncio.sleep(sleep_time)

        logger.info(f"{self._config.service_name}: Discovery loop ended")

    async def _get_discovery_settings(self) -> CachedDiscoverySettings:
        """Get discovery settings with caching and fallback chain (ADR-012).

        Configuration Hierarchy:
            1. SystemSettings.discovery (MongoDB via API) — Takes precedence
            2. WORKER_DISCOVERY_* (env vars) — Fallback
            3. AWS_REGION (env var) — Final fallback for regions

        Returns:
            CachedDiscoverySettings with current configuration.
        """
        now = datetime.now(timezone.utc)

        # Check if cache is still valid
        if self._cached_discovery_settings is not None:
            age = (now - self._cached_discovery_settings.fetched_at).total_seconds()
            if age < _DISCOVERY_SETTINGS_CACHE_TTL:
                return self._cached_discovery_settings

        # Try to fetch from API
        try:
            api_settings = await self._api.get_discovery_settings()

            if api_settings and api_settings.get("regions"):
                self._cached_discovery_settings = CachedDiscoverySettings(
                    enabled=api_settings.get("enabled", True),
                    regions=api_settings.get("regions", []),
                    ami_name_pattern=api_settings.get("ami_name_pattern", ""),
                    scan_interval_seconds=api_settings.get("scan_interval_seconds", 300),
                    fetched_at=now,
                )
                logger.debug(f"{self._config.service_name}: Using discovery settings from API: regions={self._cached_discovery_settings.regions}")
                return self._cached_discovery_settings

        except Exception as e:
            logger.warning(f"{self._config.service_name}: Failed to fetch discovery settings from API: {e}")

        # Fallback to environment variables
        self._cached_discovery_settings = CachedDiscoverySettings(
            enabled=self._settings.worker_discovery_enabled,
            regions=self._settings.discovery_regions,
            ami_name_pattern=self._settings.worker_discovery_ami_name or "",
            scan_interval_seconds=self._settings.worker_discovery_interval,
            fetched_at=now,
        )
        logger.debug(f"{self._config.service_name}: Using discovery settings from env vars: regions={self._cached_discovery_settings.regions}")
        return self._cached_discovery_settings

    async def _run_discovery(self, discovery_settings: CachedDiscoverySettings) -> None:
        """Execute a single discovery run across all configured regions.

        Implements ADR-014 discovery + garbage collection pattern:
        1. DISCOVERY: Scan EC2 for instances matching AMI pattern
        2. GARBAGE COLLECTION: Detect and mark orphaned workers as TERMINATED

        Args:
            discovery_settings: Current discovery configuration.
        """
        self._discovery_runs += 1
        self._last_discovery_at = datetime.now(timezone.utc)

        logger.info(f"{self._config.service_name}: Starting discovery run #{self._discovery_runs} (regions={discovery_settings.regions})")

        total_discovered = 0
        total_imported = 0
        total_orphans = 0

        for region in discovery_settings.regions:
            try:
                discovered, imported, discovered_ids = await self._discover_in_region(region, discovery_settings.ami_name_pattern)
                total_discovered += discovered
                total_imported += imported

                # ADR-014: Garbage collection — detect orphaned workers
                orphans = await self._garbage_collect_orphans(region, discovered_ids)
                total_orphans += orphans

            except Exception as e:
                logger.error(f"{self._config.service_name}: Discovery failed in region {region}: {e}")

        self._total_discovered += total_discovered
        self._total_imported += total_imported
        self._total_orphans_terminated += total_orphans

        logger.info(f"{self._config.service_name}: Discovery run #{self._discovery_runs} complete: discovered={total_discovered}, imported={total_imported}, orphans_terminated={total_orphans}")

    async def _discover_in_region(self, region: str, ami_name_pattern: str = "") -> tuple[int, int, set[str]]:
        """Discover and import workers in a specific AWS region.

        Args:
            region: AWS region to scan.
            ami_name_pattern: AMI name pattern to filter instances.

        Returns:
            Tuple of (discovered_count, imported_count, discovered_instance_ids).
        """
        ami_pattern = ami_name_pattern or self._settings.worker_discovery_ami_name or ""

        logger.debug(f"{self._config.service_name}: Scanning region {region} for AMI pattern '{ami_pattern}'")

        # Create a per-region EC2 client
        credentials = AwsCredentials(
            access_key_id=self._settings.aws_access_key_id or "",
            secret_access_key=self._settings.aws_secret_access_key or "",
            region=region,
        )
        ec2_client = AwsEc2SpiClient(credentials)

        try:
            # Resolve AMI name pattern to AMI IDs
            ami_ids = await ec2_client.get_ami_ids_by_name(ami_pattern)

            if not ami_ids:
                logger.debug(f"{self._config.service_name}: No AMIs found matching '{ami_pattern}' in {region}")
                return 0, 0, set()

            # List instances using those AMIs
            instances = await ec2_client.list_instances_by_ami(ami_ids)

            if not instances:
                logger.debug(f"{self._config.service_name}: No instances found for AMIs {ami_ids} in {region}")
                return 0, 0, set()

            # Convert to format expected by Control Plane API
            discovered_data = [
                {
                    "instance_id": inst.instance_id,
                    "state": inst.state,
                    "public_ip": inst.public_ip,
                    "private_ip": inst.private_ip,
                    "instance_type": inst.instance_type,
                    "image_id": inst.image_id,
                    "launch_time": inst.launch_time.isoformat() if inst.launch_time else None,
                    "name": inst.name,
                }
                for inst in instances
            ]

            # Build set of discovered instance IDs for garbage collection (ADR-014)
            discovered_instance_ids = {inst.instance_id for inst in instances}

            # Submit to Control Plane API for persistence (ADR-001)
            result = await self._api.bulk_import_workers(
                discovered_instances=discovered_data,
                aws_region=region,
                source="worker-controller-discovery",
            )

            total_imported = result.get("total_imported", 0)
            total_found = result.get("total_found", len(discovered_data))

            if total_imported > 0:
                imported_ids = result.get("imported", [])
                logger.info(f"{self._config.service_name}: Imported {total_imported} new workers in {region}: {imported_ids}")

            return total_found, total_imported, discovered_instance_ids

        except Exception as e:
            logger.error(f"{self._config.service_name}: Discovery scan failed in {region}: {e}")
            return 0, 0, set()

    async def _garbage_collect_orphans(self, region: str, discovered_instance_ids: set[str]) -> int:
        """Detect and mark orphaned workers as TERMINATED (ADR-014).

        An orphan is a worker in the database whose EC2 instance no longer exists.
        This can happen when instances are terminated via AWS Console, CLI, or auto-scaling.

        Pattern:
            1. Get all non-terminated workers for this region from Control Plane API
            2. For each worker not in the discovered set, verify via EC2 API
            3. If EC2 confirms instance doesn't exist or is terminated, mark as TERMINATED

        Args:
            region: AWS region that was scanned.
            discovered_instance_ids: Set of EC2 instance IDs found during discovery.

        Returns:
            Number of orphans marked as terminated.
        """
        try:
            # Get all workers for this region that are not already terminated
            db_workers = await self._api.get_workers(aws_region=region)

            if not db_workers:
                return 0

            # Create per-region EC2 client for verification
            credentials = AwsCredentials(
                access_key_id=self._settings.aws_access_key_id or "",
                secret_access_key=self._settings.aws_secret_access_key or "",
                region=region,
            )
            ec2_client = AwsEc2SpiClient(credentials)

            orphan_count = 0
            for worker in db_workers:
                instance_id = worker.get("ec2_instance_id") or worker.get("aws_instance_id")
                worker_id = worker.get("id")
                worker_name = worker.get("name", worker_id)
                raw_status = worker.get("status") or ""
                try:
                    worker_status = CMLWorkerStatus(raw_status)
                except ValueError:
                    worker_status = CMLWorkerStatus.UNKNOWN

                if not instance_id or not worker_id:
                    continue

                if worker_status in (CMLWorkerStatus.TERMINATED, CMLWorkerStatus.SHUTTING_DOWN):
                    continue

                if instance_id in discovered_instance_ids:
                    continue  # Not an orphan — instance exists

                # Verify via direct EC2 API call
                ec2_state = await ec2_client.get_instance_state(instance_id)

                if ec2_state is None or ec2_state.state == "terminated":
                    try:
                        await self._api.mark_worker_terminated(
                            worker_id=worker_id,
                            reason="orphan_detection",
                            terminated_by="worker-controller-discovery",
                        )
                        orphan_count += 1
                        logger.info(f"{self._config.service_name}: Marked orphan worker {worker_name} ({worker_id}) as TERMINATED (EC2 instance {instance_id} not found)")
                    except Exception as e:
                        logger.error(f"{self._config.service_name}: Failed to mark worker {worker_id} as terminated: {e}")

            if orphan_count > 0:
                logger.info(f"{self._config.service_name}: Garbage collection in {region}: {orphan_count} orphaned worker(s) terminated")

            return orphan_count

        except Exception as e:
            logger.error(f"{self._config.service_name}: Garbage collection failed in region {region}: {e}")
            return 0

    # =========================================================================
    # EC2 DETAILS REPORTING
    # =========================================================================

    async def _report_ec2_details(self, worker_id: str, state: Any) -> None:
        """Report EC2 instance details (including AMI info) to Control Plane API.

        Fetches AMI metadata (name, description, creation date) from EC2
        and reports along with instance IPs and type.

        Args:
            worker_id: Worker ID to update.
            state: Ec2InstanceState with instance details.
        """
        ec2_details: dict[str, Any] = {
            "public_ip": state.public_ip,
            "private_ip": state.private_ip,
            "instance_type": state.instance_type,
            "ami_id": state.image_id,
        }

        # Fetch AMI details (name, description, creation date) if image_id is available
        if state.image_id:
            try:
                ami_info = await self._ec2.describe_image(state.image_id)
                if ami_info:
                    ec2_details["ami_name"] = ami_info.get("name")
                    ec2_details["ami_description"] = ami_info.get("description")
                    ec2_details["ami_creation_date"] = ami_info.get("creation_date")
                    logger.info(f"AMI details for worker {worker_id}: {ami_info.get('name')} ({state.image_id})")
            except Exception as e:
                logger.warning(f"Failed to fetch AMI details for {state.image_id}: {e}")

        # Report to CPA
        try:
            await self._api.update_worker_ec2_details(
                worker_id=worker_id,
                ec2_details=ec2_details,
            )
            logger.debug(f"Reported EC2 details for worker {worker_id}")
        except Exception as e:
            logger.warning(f"Failed to report EC2 details for {worker_id}: {e}")

    # =========================================================================
    # ON-DEMAND REFRESH
    # =========================================================================

    async def _handle_on_demand_refresh(self, worker: CMLWorkerReadModel) -> None:
        """Handle a user-triggered on-demand data refresh.

        Performs a full data collection (EC2 details + CML data) and reports
        everything to CPA. The refresh_requested_at flag is cleared by the
        CML data command handler after it processes the update.

        Args:
            worker: Worker with pending refresh request.
        """
        logger.info(f"Performing on-demand refresh for worker {worker.id}")

        # Refresh EC2 details (AMI info, IPs)
        if worker.ec2_instance_id:
            try:
                state = await self._ec2.get_instance_state(worker.ec2_instance_id)
                if state:
                    await self._report_ec2_details(worker.id, state)
                    logger.info(f"On-demand refresh: EC2 details updated for {worker.id}")
            except Exception as e:
                logger.warning(f"On-demand refresh: Failed to refresh EC2 details for {worker.id}: {e}")

        # CML data is already collected by _collect_and_report_metrics (called just before us)
        # The _collect_and_report_cml_data method runs as part of _collect_and_report_metrics
        # So we don't need to call it again here.

        logger.info(f"On-demand refresh completed for worker {worker.id}")

    # =========================================================================
    # ACTIVITY DETECTION
    # =========================================================================

    async def _detect_activity(self, worker: CMLWorkerReadModel) -> dict[str, Any] | None:
        """Detect worker activity and trigger auto-pause if idle.

        Calls Control Plane API to execute the full idle detection workflow:
        1. Fetch telemetry events from CML
        2. Update worker activity state
        3. Check idle status and eligibility
        4. Auto-pause if conditions met

        Args:
            worker: Worker to check for activity.

        Returns:
            Idle detection result dict with keys like is_idle, idle_minutes,
            eligible_for_pause, auto_pause_triggered. None on error.
        """
        try:
            result = await self._api.detect_worker_idle(
                worker_id=worker.id,
                force_check=False,
            )

            # Log detection result
            if result.get("error"):
                logger.warning(f"Activity detection for worker {worker.id} had error: {result.get('error')}")
                return None
            elif result.get("auto_pause_triggered"):
                logger.info(f"Worker {worker.id} auto-paused after {result.get('idle_minutes', 0):.1f} minutes idle")
                self._auto_pauses_triggered_count += 1
            elif result.get("is_idle"):
                logger.debug(f"Worker {worker.id} is idle ({result.get('idle_minutes', 0):.1f} min) but not yet eligible for pause")
            else:
                logger.debug(f"Worker {worker.id} activity check complete: active")

            return result

        except Exception as e:
            logger.warning(f"Failed to detect activity for worker {worker.id}: {e}")
            return None

    async def _evaluate_scale_down(self, worker: CMLWorkerReadModel, idle_result: dict[str, Any]) -> bool:
        """Evaluate whether a running worker should be drained for scale-down.

        Phase 3 - Auto-Scaling: Triggers graceful drain when:
        1. Worker is idle and eligible for pause (from idle detection)
        2. Auto-pause was NOT already triggered (avoid double-action)
        3. Running worker count exceeds min_workers constraint
        4. Scale-down cooldown has elapsed since last drain

        This is complementary to auto-pause:
        - Auto-pause: Stops individual workers based on per-worker idle policy
        - Scale-down: Reduces fleet size when over-provisioned

        Args:
            worker: The running worker being evaluated.
            idle_result: Result from detect_worker_idle API call.

        Returns:
            True if drain was initiated, False otherwise.
        """
        # Skip if auto-pause already handled this worker
        if idle_result.get("auto_pause_triggered"):
            record_scale_down_evaluation(worker.id, "skipped_auto_pause")
            return False

        # Worker must be idle and eligible
        if not idle_result.get("is_idle"):
            record_scale_down_evaluation(worker.id, "skipped_not_idle")
            return False
        if not idle_result.get("eligible_for_pause"):
            record_scale_down_evaluation(worker.id, "skipped_not_eligible")
            return False

        # Respect min_workers constraint
        if self._running_worker_count <= self._settings.min_workers:
            logger.debug(f"Scale-down: Worker {worker.id} is idle but running_count ({self._running_worker_count}) <= min_workers ({self._settings.min_workers})")
            record_scale_down_evaluation(
                worker.id,
                "skipped_min_workers",
                running_count=self._running_worker_count,
                min_workers=self._settings.min_workers,
            )
            return False

        # Respect cooldown period
        if self._last_scale_down_at:
            cooldown = timedelta(seconds=self._settings.scale_down_cooldown_seconds)
            elapsed = datetime.now(timezone.utc) - self._last_scale_down_at
            if elapsed < cooldown:
                remaining = (cooldown - elapsed).total_seconds()
                logger.debug(f"Scale-down: Worker {worker.id} is idle but cooldown active ({remaining:.0f}s remaining)")
                record_scale_down_evaluation(worker.id, "skipped_cooldown")
                return False

        # All checks passed — drain the worker
        idle_minutes = idle_result.get("idle_minutes", 0)
        logger.info(f"Scale-down: Draining worker {worker.id} (idle {idle_minutes:.1f} min, running_count={self._running_worker_count}, min_workers={self._settings.min_workers})")

        try:
            await self._api.drain_worker(
                worker_id=worker.id,
                reason="scale_down",
                requested_by="worker-controller",
            )

            self._last_scale_down_at = datetime.now(timezone.utc)
            self._scale_down_count += 1
            # Decrement local count so subsequent workers in this cycle
            # also respect the min_workers constraint accurately
            self._running_worker_count -= 1

            logger.info(f"Scale-down: Worker {worker.id} drain initiated (total scale-downs={self._scale_down_count})")
            record_scale_down_evaluation(
                worker.id,
                "drained",
                idle_minutes=idle_minutes,
                running_count=self._running_worker_count,
                min_workers=self._settings.min_workers,
            )
            record_scaling_event(
                action="scale_down_initiated",
                worker_id=worker.id,
                reason=f"idle {idle_minutes:.1f} min",
            )
            return True

        except Exception as e:
            logger.error(f"Scale-down: Failed to drain worker {worker.id}: {e}", exc_info=True)
            record_scaling_event(
                action="scale_down_failed",
                worker_id=worker.id,
                reason=str(e),
                success=False,
            )
            return False

    # =========================================================================
    # LICENSE RECONCILIATION (ADR-016)
    # =========================================================================

    async def _reconcile_license(self, worker: CMLWorkerReadModel) -> None:
        """Reconcile pending license operations.

        ADR-016: License operations are initiated via control-plane-api which
        stores the intent (pending_operation). This method detects pending
        operations and executes them via the CML System API.

        Flow:
        1. Check if worker.license.pending_operation is set
        2. Mark operation as started (via Control Plane API)
        3. Execute CML API call (register/deregister)
        4. Report success or failure (via Control Plane API)

        Args:
            worker: Worker to check for pending license operations.
        """
        license_state = worker.license

        # Skip if no pending operation
        if not license_state.pending_operation:
            return

        # Need credentials and IP to execute license operations
        if not worker.ip_address:
            logger.warning(f"Worker {worker.id} has pending license operation but no IP address")
            return

        if license_state.pending_operation == "register":
            await self._execute_license_registration(worker)
        elif license_state.pending_operation == "deregister":
            await self._execute_license_deregistration(worker)
        else:
            logger.warning(f"Unknown pending license operation: {license_state.pending_operation}")

    async def _execute_license_registration(self, worker: CMLWorkerReadModel) -> None:
        """Execute pending license registration via CML System API.

        Args:
            worker: Worker with pending license registration.
        """
        worker_id = worker.id
        license_token = worker.license.pending_token

        if not license_token:
            logger.error(f"Worker {worker_id} has pending registration but no token")
            await self._api.fail_license_registration(
                worker_id=worker_id,
                error_message="No license token provided",
            )
            return

        logger.info(f"Executing license registration for worker {worker_id}")

        try:
            # Mark registration as started
            await self._api.start_license_registration(worker_id=worker_id)

            # Execute CML API call
            success, message = await self._cml.register_license(
                host=worker.ip_address,
                token=license_token,
                username=worker.cml_username,
                password=worker.cml_password,
                reregister=False,  # TODO: Get from pending state if needed
            )

            if success:
                # Report success
                await self._api.complete_license_registration(
                    worker_id=worker_id,
                    registration_status="COMPLETED",
                    smart_account=None,  # CML API doesn't return these
                    virtual_account=None,
                )
                logger.info(f"✅ License registered for worker {worker_id}")
                self._license_registrations_count += 1
            else:
                # Report failure
                await self._api.fail_license_registration(
                    worker_id=worker_id,
                    error_message=message,
                )
                logger.warning(f"❌ License registration failed for worker {worker_id}: {message}")

        except Exception as e:
            logger.exception(f"Error during license registration for worker {worker_id}: {e}")
            await self._api.fail_license_registration(
                worker_id=worker_id,
                error_message=str(e),
            )

    async def _execute_license_deregistration(self, worker: CMLWorkerReadModel) -> None:
        """Execute pending license deregistration via CML System API.

        Args:
            worker: Worker with pending license deregistration.
        """
        worker_id = worker.id
        logger.info(f"Executing license deregistration for worker {worker_id}")

        try:
            # Mark deregistration as started
            await self._api.start_license_deregistration(worker_id=worker_id)

            # Execute CML API call
            success, message = await self._cml.deregister_license(
                host=worker.ip_address,
                username=worker.cml_username,
                password=worker.cml_password,
            )

            if success:
                # Report success
                await self._api.complete_license_deregistration(
                    worker_id=worker_id,
                    message=message,
                )
                logger.info(f"✅ License deregistered for worker {worker_id}")
                self._license_deregistrations_count += 1
            else:
                # Report failure
                await self._api.fail_license_deregistration(
                    worker_id=worker_id,
                    error_message=message,
                )
                logger.warning(f"❌ License deregistration failed for worker {worker_id}: {message}")

        except Exception as e:
            logger.exception(f"Error during license deregistration for worker {worker_id}: {e}")
            await self._api.fail_license_deregistration(
                worker_id=worker_id,
                error_message=str(e),
            )

    def _map_ec2_state_to_worker_status(self, ec2_state: str) -> CMLWorkerStatus:
        """Map EC2 state to worker status."""
        mapping: dict[str, CMLWorkerStatus] = {
            "pending": CMLWorkerStatus.PROVISIONING,
            "running": CMLWorkerStatus.RUNNING,
            "stopping": CMLWorkerStatus.STOPPING,
            "stopped": CMLWorkerStatus.STOPPED,
            "shutting-down": CMLWorkerStatus.TERMINATING,
            "terminated": CMLWorkerStatus.TERMINATED,
        }
        return mapping.get(ec2_state, CMLWorkerStatus.UNKNOWN)

    # =========================================================================
    # SERVICE INFO
    # =========================================================================

    @property
    def stats(self) -> dict[str, Any]:
        """Get reconciler statistics."""
        base_stats = super().stats
        base_stats.update(
            {
                "provisioned_count": self._provisioned_count,
                "started_count": self._started_count,
                "stopped_count": self._stopped_count,
                "terminated_count": self._terminated_count,
                "metrics_collected_count": self._metrics_collected_count,
                "activity_checks_count": self._activity_checks_count,
                "auto_pauses_triggered_count": self._auto_pauses_triggered_count,
                "scale_down_count": self._scale_down_count,
                "license_registrations_count": self._license_registrations_count,
                "license_deregistrations_count": self._license_deregistrations_count,
                "running_worker_count": self._running_worker_count,
                "scale_down_enabled": self._settings.scale_down_enabled,
            }
        )
        return base_stats

    async def check_readiness(self) -> tuple[bool, str]:
        """Check if the reconciler is ready."""
        # Ready if we're the leader and started
        if not self._started:
            return False, "Reconciler not started"

        if not self.is_leader:
            # Standby instances are still "ready" for probes
            return True, "Standby mode (not leader)"

        return True, "Leader and started"

    def get_extra_info(self) -> dict[str, Any]:
        """Get extra info for /info endpoint."""
        return {
            "is_leader": self.is_leader,
            "current_leader_id": self.current_leader_id,
            "instance_id": self.instance_id,
            "stats": self.stats,
            "discovery": {
                "enabled": self._settings.worker_discovery_enabled,
                "running": self._discovery_task is not None and not self._discovery_task.done(),
                "runs": self._discovery_runs,
                "total_discovered": self._total_discovered,
                "total_imported": self._total_imported,
                "total_orphans_terminated": self._total_orphans_terminated,
                "last_run_at": self._last_discovery_at.isoformat() if self._last_discovery_at else None,
                "last_error": self._last_discovery_error,
                "settings_source": "api" if self._cached_discovery_settings and self._cached_discovery_settings.regions else "env",
            },
        }

    @classmethod
    def configure(
        cls,
        services: "ServiceCollection",
        settings: Settings,
    ) -> None:
        """Configure DI registration.

        Registers WorkerReconciler as both a concrete singleton and as a
        HostedService for automatic lifecycle management by the Neuroglia
        framework (start_async/stop_async called on app startup/shutdown).

        NOTE: The HostedService factory return type MUST be the concrete type
        (not HostedService) because Neuroglia's get_services() deduplicates
        based on factory return type annotation. Two factories both returning
        HostedService would cause the second to be silently skipped.

        Args:
            services: Neuroglia service collection.
            settings: Application settings.
        """
        from neuroglia.hosting.abstractions import HostedService

        def factory(sp) -> WorkerReconciler:
            return cls(
                api_client=sp.get_required_service(ControlPlaneApiClient),
                etcd_client=sp.get_required_service(EtcdClient),
                ec2_client=sp.get_required_service(AwsEc2SpiClient),
                cloudwatch_client=sp.get_required_service(AwsCloudWatchSpiClient),
                cml_client=sp.get_required_service(CmlSystemSpiClient),
                settings=settings,
            )

        def hosted_service_factory(sp) -> WorkerReconciler:
            return sp.get_required_service(cls)

        # NOTE: implementation_type=cls is required so Neuroglia's get_implementation_type()
        # returns the actual class, not a string from inspect.signature().return_annotation.
        # String annotations (-> "ClassName") cause TypeError in _is_service_instance_of()
        # because isinstance() cannot accept a string as its second argument.
        services.add_singleton(cls, implementation_type=cls, implementation_factory=factory)
        services.add_singleton(HostedService, implementation_type=cls, implementation_factory=hosted_service_factory)
