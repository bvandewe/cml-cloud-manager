"""Scheduler Hosted Service.

Leader-elected reconciliation service for LabletSession scheduling.
Extends WatchTriggeredHostedService from lcm_core to provide:
- Automatic leader election via etcd
- etcd watch for immediate scheduling on session creation
- Reconciliation loop that only runs on the leader
- Placement decisions via PlacementEngine

Watch Pattern (ADR-006):
    control-plane-api publishes session state to etcd (/lcm/sessions/{id}/state)
    resource-scheduler watches for PENDING sessions and triggers immediate scheduling
"""

import json
import logging
import time
from typing import Any

from infrastructure.observability import (
    measure_scheduling_latency,
    record_etcd_capacity_fetch,
    record_scale_up_decision,
    record_scheduling_decision,
    record_scheduling_failure,
    record_scheduling_retry,
    record_scheduling_success,
)
from lcm_core.domain.entities import LabletSessionReadModel
from lcm_core.domain.enums import CMLWorkerStatus, LabletSessionStatus
from lcm_core.infrastructure.hosted_services import (
    LeaderElectionConfig,
    ReconciliationConfig,
    ReconciliationResult,
    ReconciliationStatus,
    WatchConfig,
    WatchTriggeredHostedService,
)
from lcm_core.integration.clients import ControlPlaneApiClient, EtcdClient
from lcm_core.integration.clients.etcd_client import EtcdEvent
from neuroglia.dependency_injection.service_provider import ServiceProviderBase

from application.services.placement_engine import PlacementEngine, SchedulingDecision
from application.settings import Settings

logger = logging.getLogger(__name__)


class SchedulerHostedService(WatchTriggeredHostedService[LabletSessionReadModel]):
    """
    Leader-elected hosted service for LabletSession scheduling with etcd watch.

    This service:
    1. Uses etcd for leader election (only leader schedules)
    2. Watches etcd for new PENDING sessions (immediate scheduling)
    3. Periodically fetches PENDING sessions (fallback polling)
    4. For each session, runs placement algorithm
    5. Executes scheduling decisions (assign to worker or request scale-up)

    Dual-mode scheduling:
    - **Watch (reactive)**: Immediate schedule when new session created
    - **Polling (fallback)**: Periodic schedule every interval_seconds

    Extends WatchTriggeredHostedService which provides:
    - Automatic leader election via etcd
    - Reconciliation loop pattern with watch support
    - Metrics and stats
    """

    def __init__(
        self,
        api_client: ControlPlaneApiClient,
        etcd_client: EtcdClient,
        placement_engine: PlacementEngine,
        settings: Settings,
    ) -> None:
        """Initialize the scheduler hosted service.

        Args:
            api_client: Client for Control Plane API calls.
            etcd_client: Client for etcd leader election and watch.
            placement_engine: Algorithm for placement decisions.
            settings: Application settings.
        """
        # Configure reconciliation (polling fallback)
        # ADR-015: polling_enabled can be set to False for watch-only mode
        reconciliation_config = ReconciliationConfig(
            interval_seconds=settings.reconcile_interval,
            initial_delay_seconds=5.0,
            polling_enabled=settings.reconcile_polling_enabled,
            max_concurrent_reconciles=10,  # Process up to 10 instances in parallel
            service_name="resource-scheduler",
        )

        # Configure leader election
        election_config = LeaderElectionConfig(
            etcd_endpoints=settings.etcd_endpoints,
            lease_ttl_seconds=settings.leader_lease_ttl,
            service_name="resource-scheduler",
        )

        # Configure etcd watch for reactive scheduling
        watch_config = WatchConfig(
            enabled=settings.etcd_watch_enabled,
            prefix="/sessions/",  # Watch /lcm/sessions/* for new sessions
            debounce_seconds=0.5,
        )

        super().__init__(
            reconciliation_config=reconciliation_config,
            election_config=election_config,
            watch_config=watch_config,
            etcd_client=etcd_client,
        )

        self._api = api_client
        self._placement_engine = placement_engine
        self._settings = settings

        # Cache for current reconciliation cycle
        self._cached_workers: list[dict[str, Any]] | None = None
        self._cached_templates: list[dict[str, Any]] | None = None
        self._definition_cache: dict[str, dict[str, Any]] = {}

        # etcd capacity cache (Phase 2: real-time capacity)
        self._etcd_capacities: dict[str, dict[str, Any]] = {}
        self._etcd_capacities_fetched_at: float = 0.0
        self._etcd_capacity_ttl: float = 30.0  # Cache for 30s within a cycle

        # Retry tracking (Phase 2: escalation after max retries)
        self._instance_retry_counts: dict[str, int] = {}  # instance_id -> retry count
        self._max_scheduling_retries: int = 5

        # Extended metrics
        self._successful_placements = 0
        self._failed_placements = 0
        self._scale_up_requests = 0

    # =========================================================================
    # Watch-Triggered Reconciliation (WatchTriggeredHostedService)
    # =========================================================================

    @property
    def watch_prefix(self) -> str:
        """Get the etcd key prefix to watch for session state changes.

        Watches /lcm/sessions/ for new PENDING sessions.
        Key structure: /lcm/sessions/{session_id}/state
        """
        prefix = getattr(self._settings, "etcd_key_prefix", "/lcm").rstrip("/")
        return f"{prefix}/sessions/"

    async def on_watch_event(self, event: EtcdEvent) -> str | None:
        """Process watch event and extract session ID for scheduling.

        Only triggers on PENDING sessions (new session creation).

        Args:
            event: etcd watch event with key like /sessions/{id}/state

        Returns:
            Session ID to schedule, or None to skip.
        """
        # Key format: /sessions/{session_id}/state
        key_stripped = event.key
        prefix = getattr(self._settings, "etcd_key_prefix", "/lcm").rstrip("/")
        if prefix and key_stripped.startswith(prefix):
            key_stripped = key_stripped[len(prefix) :]

        parts = key_stripped.strip("/").split("/")

        if len(parts) >= 3 and parts[0] == "sessions" and parts[2] == "state":
            session_id = parts[1]

            # Only schedule PENDING sessions (skip other state changes)
            if event.type == "PUT" and event.value and LabletSessionStatus(event.value) == LabletSessionStatus.PENDING:
                logger.info(f"Watch event: New PENDING session {session_id}")
                return session_id

        return None

    async def fetch_resource_by_id(self, resource_id: str) -> LabletSessionReadModel | None:
        """Fetch a single session by ID for targeted watch-triggered scheduling.

        Args:
            resource_id: The session ID to fetch.

        Returns:
            LabletSessionReadModel or None if not found.
        """
        try:
            session_data = await self._api.get_lablet_session(resource_id)
            if session_data:
                # Refresh worker cache and etcd capacity for scheduling decision
                self._cached_workers = await self._api.get_workers(status=CMLWorkerStatus.RUNNING)
                await self._refresh_etcd_capacities()
                return LabletSessionReadModel.from_dict(session_data)
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch session {resource_id}: {e}")
            return None

    # =========================================================================
    # Resource Listing (ReconciliationHostedService)
    # =========================================================================

    async def list_resources(self) -> list[LabletSessionReadModel]:
        """Fetch all PENDING sessions from Control Plane API.

        Also refreshes etcd capacity data for real-time placement decisions.

        Returns:
            List of LabletSessionReadModel objects to reconcile.
        """
        try:
            sessions_data = await self._api.get_lablet_sessions(status=LabletSessionStatus.PENDING)
            sessions = [LabletSessionReadModel.from_dict(data) for data in sessions_data]

            # Refresh caches for this cycle
            self._cached_workers = await self._api.get_workers(status=CMLWorkerStatus.RUNNING)
            self._definition_cache.clear()

            # Fetch worker templates for capacity-based selection (Phase 3)
            try:
                self._cached_templates = await self._api.get_worker_templates()
            except Exception as e:
                logger.warning(f"Failed to fetch worker templates (scale-up will use fallback): {e}")
                self._cached_templates = None

            # Phase 2: Fetch real-time capacity from etcd
            await self._refresh_etcd_capacities()

            worker_count = len(self._cached_workers or [])
            capacity_count = len(self._etcd_capacities)
            logger.debug(f"Found {len(sessions)} pending sessions, {worker_count} workers, {capacity_count} etcd capacity entries")
            return sessions

        except Exception as e:
            logger.error(f"Failed to list pending sessions: {e}")
            return []

    async def _refresh_etcd_capacities(self) -> None:
        """Fetch all worker capacity data from etcd.

        Uses a short TTL cache to avoid repeated fetches within the same
        reconciliation cycle. Falls back gracefully if etcd is unavailable.
        """
        now = time.monotonic()
        if (now - self._etcd_capacities_fetched_at) < self._etcd_capacity_ttl:
            logger.debug("Using cached etcd capacity data")
            return

        try:
            raw_data = await self._etcd.get_prefix("/workers/")
            capacities: dict[str, dict[str, Any]] = {}

            for key, value in raw_data.items():
                if not key.endswith("/capacity"):
                    continue
                try:
                    data = json.loads(value)
                    worker_id = data.get("worker_id", "")
                    if worker_id:
                        capacities[worker_id] = data
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in etcd key {key}")

            self._etcd_capacities = capacities
            self._etcd_capacities_fetched_at = now
            record_etcd_capacity_fetch(success=True, worker_count=len(capacities))
            logger.info(f"Refreshed etcd capacity data: {len(capacities)} workers")

        except Exception as e:
            record_etcd_capacity_fetch(success=False)
            logger.warning(f"Failed to fetch etcd capacity, using API data: {e}")
            # Keep stale cache or empty — PlacementEngine will fall back to API data

    def get_resource_id(self, resource: LabletSessionReadModel) -> str:
        """Extract unique ID from session for tracking."""
        return resource.id

    async def reconcile(self, instance: LabletSessionReadModel) -> ReconciliationResult:
        """Reconcile a single pending session.

        Args:
            instance: The LabletSession to schedule.

        Returns:
            ReconciliationResult indicating success/requeue/fail.
        """
        session_id = instance.id
        logger.debug(f"Reconciling session {session_id}")

        try:
            # Fetch definition (with caching)
            definition = await self._get_definition(instance.definition_id)
            if not definition:
                return ReconciliationResult.failed(f"Definition {instance.definition_id} not found")

            # Convert to dicts for placement engine (maintains compatibility)
            instance_dict = {
                "id": instance.id,
                "name": instance.name,
                "definition_id": instance.definition_id,
                "status": instance.status,
                "worker_id": instance.worker_id,
                "metadata": instance.metadata or {},
            }

            # Run placement algorithm (with etcd real-time capacity data)
            with measure_scheduling_latency() as latency_ctx:
                decision = self._placement_engine.schedule(
                    instance=instance_dict,
                    definition=definition,
                    workers=self._cached_workers or [],
                    etcd_capacities=self._etcd_capacities or None,
                    templates=self._cached_templates,
                )
                latency_ctx["action"] = decision.action

            # Record placement decision metric
            record_scheduling_decision(decision.action, decision.reason)

            # Execute the decision
            result = await self._execute_decision(session_id, decision, definition)

            # Track retry state (Phase 2)
            if result.status == ReconciliationStatus.SUCCESS:
                self._instance_retry_counts.pop(session_id, None)
            elif result.status == ReconciliationStatus.FAILED:
                retry_count = self._instance_retry_counts.get(session_id, 0) + 1
                self._instance_retry_counts[session_id] = retry_count
                record_scheduling_retry(session_id, retry_count)

                if retry_count >= self._max_scheduling_retries:
                    logger.error(f"Session {session_id} failed scheduling {retry_count} times. Escalating: requeue with extended backoff. Reason: {result.message}")
                    # Return requeue with longer delay to avoid tight failure loops
                    return ReconciliationResult.requeue(
                        f"Max retries ({retry_count}) reached, extended backoff",
                        after_seconds=300.0,  # 5-minute backoff after max retries
                    )
                else:
                    logger.warning(f"Session {session_id} scheduling retry {retry_count}/{self._max_scheduling_retries}")

            return result

        except Exception as e:
            logger.exception(f"Error reconciling session {session_id}: {e}")
            return ReconciliationResult.failed(str(e), e)

    async def _get_definition(self, definition_id: str) -> dict[str, Any] | None:
        """Get definition with caching within a reconcile cycle."""
        if definition_id in self._definition_cache:
            return self._definition_cache[definition_id]

        try:
            definition = await self._api.get_lablet_definition(definition_id)
            self._definition_cache[definition_id] = definition
            return definition
        except Exception as e:
            logger.error(f"Failed to fetch definition {definition_id}: {e}")
            return None

    async def _execute_decision(
        self,
        session_id: str,
        decision: SchedulingDecision,
        definition: dict[str, Any],
    ) -> ReconciliationResult:
        """Execute a scheduling decision.

        Args:
            session_id: Session being scheduled.
            decision: Placement decision from PlacementEngine.
            definition: LabletDefinition for the session.

        Returns:
            ReconciliationResult based on outcome.
        """
        if decision.action == "assign":
            return await self._handle_assign(session_id, decision, definition)
        elif decision.action == "scale_up":
            return await self._handle_scale_up(decision)
        elif decision.action == "wait":
            logger.debug(f"Waiting to schedule session {session_id}: {decision.reason}")
            # Requeue for next cycle
            return ReconciliationResult.requeue(decision.reason)
        else:
            return ReconciliationResult.failed(f"Unknown action: {decision.action}")

    async def _handle_assign(
        self,
        session_id: str,
        decision: SchedulingDecision,
        definition: dict[str, Any],
    ) -> ReconciliationResult:
        """Handle an 'assign' decision - schedule session to worker.

        Calls schedule_session() which atomically assigns the worker
        and transitions the session to SCHEDULED. Port allocation is
        deferred to the lablet-controller pipeline (ports_alloc step).

        Args:
            session_id: Session to assign.
            decision: Decision containing worker_id.
            definition: Definition (used for lab_record_id lookup).

        Returns:
            ReconciliationResult.
        """
        worker_id = decision.worker_id
        if not worker_id:
            self._failed_placements += 1
            return ReconciliationResult.failed("Assign decision missing worker_id")

        logger.info(f"Assigning session {session_id} to worker {worker_id}")

        try:
            # Port allocation is deferred to lablet-controller pipeline (ports_alloc step).
            # The scheduler only needs to verify port count availability (placement_engine),
            # not allocate specific port numbers. See ADR-031 Phase 4.
            allocated_ports: dict[str, int] = {}

            # Lab record ID — determined at schedule time if available from definition metadata
            lab_record_id = definition.get("lab_record_id", "")

            # Schedule the session (assigns worker, transitions to SCHEDULED)
            await self._api.schedule_session(
                session_id=session_id,
                worker_id=worker_id,
                allocated_ports=allocated_ports,
                lab_record_id=lab_record_id,
                scheduled_by="resource-scheduler",
            )

            self._successful_placements += 1
            record_scheduling_success(worker_id)
            logger.info(f"Successfully scheduled session {session_id} to worker {worker_id}")

            return ReconciliationResult.success(f"Scheduled to worker {worker_id}")

        except Exception as e:
            self._failed_placements += 1
            record_scheduling_failure(str(e))
            logger.error(f"Failed to schedule session {session_id}: {e}")
            return ReconciliationResult.failed(str(e), e)

    async def _handle_scale_up(self, decision: SchedulingDecision) -> ReconciliationResult:
        """Handle a 'scale_up' decision - request new worker provisioning.

        Args:
            decision: Decision containing worker_template.

        Returns:
            ReconciliationResult.
        """
        template = decision.worker_template
        if not template:
            return ReconciliationResult.failed("Scale-up decision missing worker_template")

        logger.info(f"Requesting scale-up with template {template}: {decision.reason}" + (f" (rejections: {decision.rejection_summary})" if decision.rejection_summary else ""))
        self._scale_up_requests += 1
        record_scale_up_decision(template, decision.reason)

        try:
            await self._api.request_scale_up(template, decision.reason)
            logger.info(f"Scale-up request submitted for template {template}")
            # Requeue - the session will be scheduled once worker is ready
            return ReconciliationResult.requeue("Waiting for scale-up")
        except Exception as e:
            logger.error(f"Failed to request scale-up: {e}")
            return ReconciliationResult.failed(str(e), e)

    @property
    def stats(self) -> dict:
        """Get extended scheduler statistics."""
        base = super().stats
        return {
            **base,
            "successful_placements": self._successful_placements,
            "failed_placements": self._failed_placements,
            "scale_up_requests": self._scale_up_requests,
        }

    async def check_readiness(self) -> tuple[bool, str]:
        """Check if scheduler is ready to accept traffic.

        Returns:
            Tuple of (is_ready, message).
        """
        # Check API connectivity
        try:
            if not await self._api.health_check():
                return False, "Control Plane API not reachable"
        except Exception as e:
            return False, f"API health check failed: {e}"

        return True, "OK"

    def get_extra_info(self) -> dict[str, Any]:
        """Get extra info for /info endpoint."""
        return {
            "leader": self.is_leader,
            "leader_id": self.current_leader_id,
            "instance_id": self.instance_id,
            "stats": self.stats,
        }

    @staticmethod
    def configure(services: Any, settings: Settings) -> None:
        """Configure the scheduler hosted service for DI.

        Args:
            services: ServiceCollection from the application builder.
            settings: Application settings.
        """

        def factory(sp: ServiceProviderBase) -> SchedulerHostedService:
            return SchedulerHostedService(
                api_client=sp.get_required_service(ControlPlaneApiClient),
                etcd_client=sp.get_required_service(EtcdClient),
                placement_engine=sp.get_required_service(PlacementEngine),
                settings=settings,
            )

        services.add_singleton(SchedulerHostedService, implementation_factory=factory)
        logger.info("✅ SchedulerHostedService configured")
