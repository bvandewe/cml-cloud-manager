"""Lablet Reconciler Hosted Service.

Leader-elected reconciliation service for LabletSession lifecycle management.
Extends WatchTriggeredHostedService from lcm_core to provide:
- Automatic leader election via etcd
- etcd watch for immediate reconciliation on state changes
- Reconciliation loop that only runs on the leader
- Lab lifecycle management via CML Labs API

Domain: Application Layer (Workloads)
SPI: CML Labs API (Labs, Nodes, Interfaces)

Canonical State Machine (from LabletSessionStatus enum):
    SCHEDULED → INSTANTIATING → READY → RUNNING → STOPPING → ARCHIVED
                                                             ↘ TERMINATED (from any state)

States handled by this reconciler:
    - SCHEDULED: Check timeslot approach → transition to INSTANTIATING
    - INSTANTIATING: Import lab, start lab, provision LDS → transition to READY
    - READY: Verify lab is still running (transition to RUNNING via CloudEvent)
    - RUNNING: Sync check, timeslot expiry → transition to STOPPING
    - STOPPING: Archive LDS, stop/wipe/delete lab → transition to ARCHIVED

Reconciliation Pattern:
    SPEC (LabletSession from Control Plane API) ←→ OBSERVE (CML Lab state) → ACT (reconcile)

Watch Pattern (ADR-006):
    control-plane-api publishes session state to etcd (/lcm/sessions/{id}/state)
    lablet-controller watches etcd prefix and triggers immediate reconciliation
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from integration.services.cml_labs_spi import CmlLabsSpiClient, LabState, NodeInfo
from integration.services.lds_spi import DeviceAccessInfo, LdsSpiClient, LdsSpiError
from lcm_core.domain.entities import LabletSessionReadModel
from lcm_core.domain.entities.read_models.lab_record_read_model import LabRecordReadModel
from lcm_core.domain.entities.read_models.lablet_definition_read_model import LabletDefinitionReadModel
from lcm_core.domain.enums import LabletSessionStatus
from lcm_core.domain.enums.lab_record_status import LabRecordStatus
from lcm_core.infrastructure.hosted_services import (
    LeaderElectionConfig,
    ReconciliationConfig,
    ReconciliationResult,
    WatchConfig,
    WatchTriggeredHostedService,
)
from lcm_core.integration.clients import ControlPlaneApiClient, EtcdClient
from lcm_core.integration.clients.etcd_client import EtcdEvent

from application.services.resource_observer import ResourceObserver
from application.settings import Settings

if TYPE_CHECKING:
    from neuroglia.dependency_injection import ServiceCollection

    from application.hosted_services.content_sync_service import ContentSyncService
    from application.hosted_services.lab_discovery_service import LabDiscoveryService
    from application.hosted_services.lab_record_reconciler import LabRecordReconciler
    from application.hosted_services.timeslot_watcher_service import TimeslotWatcherService

# Sprint C (ADR-034) — pipeline execution imports
from application.models.pipeline_context import PipelineContext
from application.services.lifecycle_phase_handler import LifecyclePhaseHandler
from application.services.pipeline_executor import PipelineExecutor, StepDispatcher

logger = logging.getLogger(__name__)


class LabletReconciler(WatchTriggeredHostedService[LabletSessionReadModel]):
    """
    Leader-elected hosted service for LabletSession lifecycle management with etcd watch.

    This service:
    1. Uses etcd for leader election (only leader reconciles)
    2. Watches etcd for session state changes (immediate reconciliation)
    3. Periodically fetches sessions needing reconciliation (fallback polling)
    4. For each session:
       - Compare desired state with actual CML lab state
       - Take action (import, start, stop, wipe, delete)
       - Update status in Control Plane API

    Dual-mode reconciliation:
    - **Watch (reactive)**: Immediate reconcile when etcd state changes
    - **Polling (fallback)**: Periodic reconcile every interval_seconds

    Extends WatchTriggeredHostedService which provides:
    - Automatic leader election via etcd
    - Reconciliation loop pattern with watch support
    - Metrics and stats
    - Exponential backoff on failures

    Domain: Application Layer - Workload Management
    SPI: CML Labs API

    All mutations go through Control Plane API (ADR-001).
    """

    def __init__(
        self,
        api_client: ControlPlaneApiClient,
        etcd_client: EtcdClient,
        cml_labs_client: CmlLabsSpiClient,
        lds_client: LdsSpiClient,
        settings: Settings,
        resource_observer: "ResourceObserver | None" = None,
        lab_discovery_service: "LabDiscoveryService | None" = None,
        lab_record_reconciler: "LabRecordReconciler | None" = None,
        content_sync_service: "ContentSyncService | None" = None,
        timeslot_watcher_service: "TimeslotWatcherService | None" = None,
    ) -> None:
        """Initialize the lablet reconciler.

        Args:
            api_client: Client for Control Plane API.
            etcd_client: Client for etcd leader election and watch.
            cml_labs_client: CML Labs SPI client.
            lds_client: LDS Reservations SPI client.
            settings: Application settings.
            resource_observer: Optional resource observer (ADR-030, for live resource observation).
            lab_discovery_service: Optional lab discovery service (started on leader election).
            lab_record_reconciler: Optional lab record reconciler (AD-023, started on leader election).
            content_sync_service: Optional content sync service (AD-CS-001, started on leader election).
            timeslot_watcher_service: Optional timeslot watcher (AD-TIMESLOT-001, started on leader election).
        """
        # Configure reconciliation (polling fallback)
        # ADR-015: polling_enabled can be set to False for watch-only mode
        reconciliation_config = ReconciliationConfig(
            interval_seconds=settings.reconcile_interval,
            initial_delay_seconds=5.0,
            polling_enabled=settings.reconcile_polling_enabled,
            max_concurrent_reconciles=10,  # Labs are lightweight - can parallelize
            service_name="lablet-controller",
        )

        # Configure leader election
        election_config = LeaderElectionConfig(
            etcd_endpoints=settings.etcd_endpoints,
            lease_ttl_seconds=settings.leader_lease_ttl,
            service_name="lablet-controller",
        )

        # Configure etcd watch for reactive reconciliation
        watch_config = WatchConfig(
            enabled=settings.etcd_watch_enabled,
            prefix="/sessions/",  # Watch /lcm/sessions/* for state changes
            debounce_seconds=0.5,
        )

        super().__init__(
            reconciliation_config=reconciliation_config,
            election_config=election_config,
            watch_config=watch_config,
            etcd_client=etcd_client,
        )

        self._api = api_client
        self._cml_labs = cml_labs_client
        self._lds = lds_client
        self._settings = settings
        self._resource_observer = resource_observer

        # Extended metrics
        self._labs_imported = 0
        self._labs_started = 0
        self._labs_stopped = 0
        self._labs_deleted = 0
        self._lab_sync_count = 0
        self._labs_reused = 0
        self._bindings_created = 0
        self._bindings_released = 0
        self._runs_recorded = 0
        self._lds_sessions_created = 0
        self._lds_sessions_archived = 0

        # Cache for definition lookups
        self._definition_cache: dict[str, LabletDefinitionReadModel] = {}

        # Cache for worker details (worker_id → worker dict from CPA)
        # Follows the same caching pattern as LabRecordReconciler._worker_host_cache (AD-023)
        self._worker_cache: dict[str, dict] = {}

        # Run history: session_id → lab run start time (for recording run cycles)
        self._lab_run_started_at: dict[str, datetime] = {}

        # Local tracking for resolved lab IDs (session_id → cml_lab_id)
        # Bridges the gap between lab resolution and mark_session_ready,
        # since update_instance_lab_id was removed in Phase 7G.
        self._resolved_lab_ids: dict[str, str] = {}

        # Lab discovery service (started when this instance becomes leader)
        self._lab_discovery_service: LabDiscoveryService | None = lab_discovery_service

        # Lab record reconciler (AD-023: reactive watch for lab pending actions)
        self._lab_record_reconciler: LabRecordReconciler | None = lab_record_reconciler

        # Content sync service (AD-CS-001: reactive watch for definition content sync)
        self._content_sync_service: ContentSyncService | None = content_sync_service

        # Timeslot watcher service (AD-TIMESLOT-001: proactive deadline detection)
        self._timeslot_watcher_service: TimeslotWatcherService | None = timeslot_watcher_service

        # Sprint C (ADR-034): Pipeline execution infrastructure
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._active_handlers: dict[str, LifecyclePhaseHandler] = {}
        self._pipeline_executor = PipelineExecutor()
        self._pipeline_retry_counts: dict[str, int] = {}

    # =========================================================================
    # Leader Lifecycle (start/stop lab discovery)
    # =========================================================================

    async def _become_leader(self) -> None:
        """Handle becoming the leader.

        Extends parent to start the lab discovery service loop.
        Lab discovery is a periodic concern that should only run on the leader
        to avoid duplicate CML API calls across replicas.
        """
        await super()._become_leader()

        # Start lab discovery service (if configured)
        if self._lab_discovery_service:
            await self._lab_discovery_service.start_async()
            logger.info(f"{self._config.service_name}: Started lab discovery service (leader-only)")
        else:
            logger.info(f"{self._config.service_name}: Lab discovery service not configured")

        # Start lab record reconciler (AD-023: reactive watch for lab pending actions)
        if self._lab_record_reconciler:
            await self._lab_record_reconciler.start_async()
            logger.info(f"{self._config.service_name}: Started lab record reconciler (leader-only)")
        else:
            logger.info(f"{self._config.service_name}: Lab record reconciler not configured")

        # Start content sync service (AD-CS-001: reactive watch for definition content sync)
        if self._content_sync_service:
            await self._content_sync_service.start_async()
            logger.info(f"{self._config.service_name}: Started content sync service (leader-only)")
        else:
            logger.info(f"{self._config.service_name}: Content sync service not configured")

        # Start timeslot watcher service (AD-TIMESLOT-001: proactive deadline detection)
        if self._timeslot_watcher_service:
            await self._timeslot_watcher_service.start_async()
            logger.info(f"{self._config.service_name}: Started timeslot watcher service (leader-only)")
        else:
            logger.info(f"{self._config.service_name}: Timeslot watcher service not configured")

    async def _step_down(self) -> None:
        """Handle stepping down from leadership.

        Extends parent to cancel active pipeline handlers, stop child services,
        and clear per-session state.
        """
        # Sprint C (ADR-034): Cancel all active pipeline handlers
        for key, handler in list(self._active_handlers.items()):
            logger.info(f"{self._config.service_name}: Cancelling pipeline handler '{key}'")
            try:
                await handler.stop()
            except Exception:
                logger.warning(f"{self._config.service_name}: Error stopping handler '{key}', continuing cleanup", exc_info=True)
        self._active_handlers.clear()
        self._session_locks.clear()
        self._pipeline_retry_counts.clear()

        # Stop timeslot watcher service (AD-TIMESLOT-001) — reverse start order
        if self._timeslot_watcher_service:
            await self._timeslot_watcher_service.stop_async()
            logger.info(f"{self._config.service_name}: Stopped timeslot watcher service")

        # Stop content sync service (AD-CS-001) — reverse start order
        if self._content_sync_service:
            await self._content_sync_service.stop_async()
            logger.info(f"{self._config.service_name}: Stopped content sync service")

        # Stop lab record reconciler (AD-023)
        if self._lab_record_reconciler:
            await self._lab_record_reconciler.stop_async()
            logger.info(f"{self._config.service_name}: Stopped lab record reconciler")

        # Stop lab discovery service
        if self._lab_discovery_service:
            await self._lab_discovery_service.stop_async()
            logger.info(f"{self._config.service_name}: Stopped lab discovery service")

        await super()._step_down()

    # =========================================================================
    # Watch-Triggered Reconciliation (WatchTriggeredHostedService)
    # =========================================================================

    @property
    def watch_prefix(self) -> str:
        """Get the etcd key prefix to watch for session state changes.

        Watches /lcm/sessions/ for state changes published by control-plane-api.
        Key structure: /lcm/sessions/{session_id}/state
        """
        prefix = getattr(self._settings, "etcd_key_prefix", "/lcm").rstrip("/")
        return f"{prefix}/sessions/"

    async def on_watch_event(self, event: EtcdEvent) -> str | None:
        """Process watch event and extract session ID for reconciliation.

        Handles two types of events:
        - /sessions/{id}/state → triggers reconciliation (returns session_id)
        - /sessions/{id}/observe_resources → handles observation request inline (returns None)

        Args:
            event: etcd watch event with key like /sessions/{id}/state

        Returns:
            Session ID to reconcile, or None to skip.
        """
        # Key format: /sessions/{session_id}/state or /sessions/{session_id}/observe_resources
        key_stripped = event.key
        prefix = getattr(self._settings, "etcd_key_prefix", "/lcm").rstrip("/")
        if prefix and key_stripped.startswith(prefix):
            key_stripped = key_stripped[len(prefix) :]

        parts = key_stripped.strip("/").split("/")

        if len(parts) >= 2 and parts[0] == "sessions":
            session_id = parts[1]

            # ADR-030: Handle observe_resources requests inline (don't trigger full reconciliation)
            if len(parts) >= 3 and parts[2] == "observe_resources" and event.value:
                await self._handle_observe_resources_event(session_id, event.value)
                return None

            logger.info(f"Watch event: {event.type} for session {session_id} (new_state={event.value})")
            return session_id

        return None

    async def fetch_resource_by_id(self, resource_id: str) -> LabletSessionReadModel | None:
        """Fetch a single session by ID for targeted watch-triggered reconciliation.

        Enriches the read model with worker connection details (IP, credentials)
        when worker_id is set but worker_ip is missing. The CPA DTO only stores
        worker_id; connection details are resolved from the CMLWorker aggregate.

        Args:
            resource_id: The session ID to fetch.

        Returns:
            LabletSessionReadModel or None if not found.
        """
        try:
            session_data = await self._api.get_lablet_session(resource_id)
            if session_data:
                session = LabletSessionReadModel.from_dict(session_data)
                # Enrich with worker details if worker assigned but IP missing
                if session.worker_id and not session.worker_ip:
                    await self._enrich_with_worker_details(session)
                return session
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch session {resource_id}: {e}")
            return None

    # =========================================================================
    # Resource Listing (ReconciliationHostedService)
    # =========================================================================

    async def list_resources(self) -> list[LabletSessionReadModel]:
        """Fetch all sessions needing reconciliation from Control Plane API.

        Returns all non-terminal sessions. This ensures the startup
        reconciliation sweep (AD-031) picks up ALL resources that the
        watch stream would also react to. The reconcile() method
        gracefully handles statuses without dedicated handlers.

        Returns:
            List of LabletSessionReadModel objects to reconcile.
        """
        try:
            # Fetch all non-terminated sessions
            sessions_data = await self._api.get_lablet_sessions()
            sessions = [LabletSessionReadModel.from_dict(data) for data in sessions_data]

            # Filter to non-terminal statuses — matches what on_watch_event()
            # would trigger reconciliation for. Terminal statuses (STOPPED,
            # ARCHIVED, TERMINATED) don't need reconciliation.
            terminal_statuses = {
                LabletSessionStatus.STOPPED,
                LabletSessionStatus.ARCHIVED,
                LabletSessionStatus.TERMINATED,
            }
            needs_reconcile = [s for s in sessions if s.status and LabletSessionStatus(s.status) not in terminal_statuses]

            # Enrich sessions with worker connection details when missing
            for session in needs_reconcile:
                if session.worker_id and not session.worker_ip:
                    await self._enrich_with_worker_details(session)

            logger.debug(f"Found {len(needs_reconcile)} sessions needing reconciliation")
            return needs_reconcile

        except Exception as e:
            logger.error(f"Failed to list lablet sessions: {e}")
            return []

    def get_resource_id(self, resource: LabletSessionReadModel) -> str:
        """Extract unique ID from session for tracking."""
        return resource.id

    def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        """Get or create a per-session asyncio.Lock (lazy initialization).

        ADR-034 §3: Serializes reconciliation per session_id to prevent
        duplicate handler creation from watch+polling race conditions.

        Args:
            session_id: The session ID to get the lock for.

        Returns:
            asyncio.Lock for the given session.
        """
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]

    async def reconcile(self, instance: LabletSessionReadModel) -> ReconciliationResult:
        """Reconcile a single lablet session — serialized per session_id.

        ADR-034 §3: Wraps the actual reconciliation logic in a per-session
        asyncio.Lock to prevent concurrent handler management for the same
        session from watch and polling paths.

        Args:
            instance: The LabletSession to reconcile.

        Returns:
            ReconciliationResult indicating success/requeue/fail.
        """
        lock = self._get_session_lock(instance.id)
        async with lock:
            return await self._reconcile_inner(instance)

    async def _reconcile_inner(self, instance: LabletSessionReadModel) -> ReconciliationResult:
        """Reconcile a single lablet session.

        Args:
            instance: The LabletSession to reconcile.

        Returns:
            ReconciliationResult indicating success/requeue/fail.
        """
        instance_id = instance.id
        logger.debug(f"Reconciling session {instance_id} (status={instance.status})")

        try:
            # Parse status to canonical enum (case-insensitive)
            try:
                status = LabletSessionStatus(instance.status)
            except ValueError:
                logger.warning(f"Unknown session status: {instance.status}")
                return ReconciliationResult.success()

            # ADR-031 §7.4: Early timeslot expiry check before status-based routing.
            # If the timeslot has expired and the session is not yet in a terminal
            # or stopping state, expire it immediately.
            if instance.timeslot_end and status not in (
                LabletSessionStatus.STOPPING,
                LabletSessionStatus.STOPPED,
                LabletSessionStatus.ARCHIVED,
                LabletSessionStatus.TERMINATED,
            ):
                now = datetime.now(timezone.utc)
                timeslot_end = instance.timeslot_end
                if isinstance(timeslot_end, str):
                    timeslot_end = datetime.fromisoformat(timeslot_end.replace("Z", "+00:00"))
                if timeslot_end.tzinfo is None:
                    timeslot_end = timeslot_end.replace(tzinfo=timezone.utc)
                if now >= timeslot_end:
                    return await self._handle_expired(instance)

            # Validate worker assignment
            if not instance.worker_id:
                if status == LabletSessionStatus.SCHEDULED:
                    # Not yet assigned by resource-scheduler — skip silently
                    return ReconciliationResult.success()
                return ReconciliationResult.failed(f"Session {instance_id} has no worker_id in {status.value} state")

            # Validate worker connection details (required for CML API access)
            if not instance.worker_ip and status in (
                LabletSessionStatus.INSTANTIATING,
                LabletSessionStatus.READY,
                LabletSessionStatus.RUNNING,
                LabletSessionStatus.STOPPING,
            ):
                logger.warning(f"Session {instance_id} has worker_id={instance.worker_id} but no worker_ip — worker details resolution may have failed")
                return ReconciliationResult.failed(f"Worker connection details missing for session {instance_id} (worker_id={instance.worker_id})")

            # Route to appropriate handler based on current status
            if status == LabletSessionStatus.SCHEDULED:
                return await self._handle_scheduled(instance)
            elif status == LabletSessionStatus.INSTANTIATING:
                return await self._handle_instantiating(instance)
            elif status == LabletSessionStatus.READY:
                return await self._handle_ready(instance)
            elif status == LabletSessionStatus.RUNNING:
                return await self._handle_running(instance)
            elif status == LabletSessionStatus.STOPPING:
                return await self._handle_stopping(instance)
            else:
                logger.warning(f"Unhandled reconcilable status: {status}")
                return ReconciliationResult.success()

        except Exception as e:
            logger.exception(f"Error reconciling session {instance_id}: {e}")
            return ReconciliationResult.failed(str(e), e)

    # =========================================================================
    # STATUS HANDLERS (State Machine)
    # =========================================================================

    async def _handle_scheduled(self, instance: LabletSessionReadModel) -> ReconciliationResult:
        """Handle SCHEDULED session - check if timeslot is approaching.

        For on-demand sessions (no timeslot_start), immediately transition
        to INSTANTIATING. For time-slotted sessions, wait until the boot
        lead time window before transitioning.

        Boot lead time resolution (AD-P10-01):
            1. Definition-level boot_lead_time_minutes (if set)
            2. Global fallback: settings.worker_bootup_delay_minutes
        """
        should_instantiate = False

        if not instance.timeslot_start:
            # On-demand session — instantiate immediately
            should_instantiate = True
        else:
            now = datetime.now(timezone.utc)

            # Resolve boot lead time: definition-specific or global fallback
            boot_lead_time_minutes = self._settings.worker_bootup_delay_minutes
            definition = await self._get_definition(instance.definition_id)
            if definition and getattr(definition, "boot_lead_time_minutes", None):
                boot_lead_time_minutes = definition.boot_lead_time_minutes

            boot_window = boot_lead_time_minutes * 60  # seconds

            if isinstance(instance.timeslot_start, str):
                timeslot_start = datetime.fromisoformat(instance.timeslot_start.replace("Z", "+00:00"))
            else:
                timeslot_start = instance.timeslot_start

            # Ensure timeslot_start is timezone-aware (assume UTC if naive)
            if timeslot_start.tzinfo is None:
                timeslot_start = timeslot_start.replace(tzinfo=timezone.utc)

            time_until_start = (timeslot_start - now).total_seconds()
            should_instantiate = time_until_start <= boot_window

        if should_instantiate:
            # Use dedicated start_instantiation API for type-safe SCHEDULED → INSTANTIATING
            await self._api.start_instantiation(session_id=instance.id)
            logger.info(f"Session {instance.id} transitioning to INSTANTIATING")
            return ReconciliationResult.requeue("Transitioning to instantiation")

        return ReconciliationResult.success()

    async def _handle_instantiating(self, instance: LabletSessionReadModel) -> ReconciliationResult:
        """Handle INSTANTIATING session — delegate to LifecyclePhaseHandler (ADR-034 Sprint C).

        Fire-and-check pattern:
        1. If handler exists and is running → return success (self-driving)
        2. If handler finished → check result, retry or terminate
        3. If no handler → start new one with pipeline from definition

        AD-PIPELINE-009: No backward compatibility — definitions MUST have pipelines.
        AD-PIPELINE-007: Failed pipelines are retried by reconciler, not auto-terminated.
        """
        handler_key = f"{instance.id}:instantiate"

        # --- Check existing handler ---
        if handler_key in self._active_handlers:
            handler = self._active_handlers[handler_key]

            if handler.is_running:
                # Handler is self-driving — no action needed
                return ReconciliationResult.success("Pipeline handler running")

            # Handler finished — inspect result
            result = handler.result
            del self._active_handlers[handler_key]

            if result is None:
                # Handler crashed (unhandled exception) — treat as failure
                logger.error(f"Pipeline handler for session {instance.id} finished with no result (crash)")
                # Fall through to restart
            elif result.status in ("completed", "partial"):
                # Pipeline succeeded — transition already handled by mark_ready step
                logger.info(f"Pipeline completed for session {instance.id} ({result.status})")
                return ReconciliationResult.success(f"Pipeline {result.status}")
            elif result.status == "failed":
                # Pipeline failed — check retry budget
                retry_count = self._pipeline_retry_counts.get(handler_key, 0) + 1
                max_retries = result.max_retries  # From pipeline_def, 0 = unlimited

                if max_retries > 0 and retry_count >= max_retries:
                    logger.error(f"Pipeline for session {instance.id} exhausted {retry_count}/{max_retries} retries: {result.error}")
                    try:
                        await self._api.terminate_session(
                            session_id=instance.id,
                            terminated_by="lablet-controller",
                            reason=f"Pipeline failed after {retry_count} attempts: {result.error}",
                        )
                    except Exception as e:
                        logger.error(f"Failed to terminate session {instance.id}: {e}")
                    return ReconciliationResult.failed("Max pipeline retries exhausted")

                # Budget remaining — record retry count and fall through to restart
                self._pipeline_retry_counts[handler_key] = retry_count
                logger.warning(f"Pipeline for session {instance.id} failed (attempt {retry_count}), will retry: {result.error}")

        # --- Get pipeline definition ---
        pipeline_def = await self._get_pipeline_def(instance, "instantiate")
        if not pipeline_def:
            logger.error(f"No 'instantiate' pipeline defined for session {instance.id} (definition_id={instance.definition_id})")
            try:
                await self._api.terminate_session(
                    session_id=instance.id,
                    terminated_by="lablet-controller",
                    reason="No 'instantiate' pipeline defined in LabletDefinition",
                )
            except Exception as e:
                logger.error(f"Failed to terminate session {instance.id}: {e}")
            return ReconciliationResult.failed("No pipeline defined")

        # --- Start new handler ---
        context = await self._build_pipeline_context(instance)
        step_dispatcher = self._build_step_dispatcher()

        # Restore existing progress for resumability (AD-PIPELINE-007)
        existing_progress = instance.instantiation_progress if instance.instantiation_progress else None

        handler = LifecyclePhaseHandler(
            session_id=instance.id,
            pipeline_name="instantiate",
            pipeline_def=pipeline_def,
            context=context,
            executor=self._pipeline_executor,
            step_dispatcher=step_dispatcher,
            existing_progress=existing_progress,
        )
        self._active_handlers[handler_key] = handler
        await handler.start()
        logger.info(f"Started pipeline handler for session {instance.id} (key={handler_key})")
        return ReconciliationResult.success("Pipeline handler started")

    async def _provision_lds_session(self, instance: LabletSessionReadModel, cml_lab_id: str) -> ReconciliationResult:
        """Provision an LDS session for a BOOTED lab.

        After successful provisioning, creates a UserSession child entity via CPA,
        then calls mark_session_ready to atomically transition to READY.

        AD-P4-03: Device mapping uses CML node label as device_label,
        and node tags encode protocol:port pairs.

        Note: This method is kept for backward compatibility and is also called
        by ``_step_lds_provision()`` in the pipeline.

        Args:
            instance: The LabletSession with a BOOTED lab.
            cml_lab_id: The CML lab ID (from instance or local tracking).

        Returns:
            ReconciliationResult indicating success or failure.
        """
        try:
            # 1. Fetch lablet definition for form_qualified_name
            definition = await self._get_definition(instance.definition_id)
            if not definition or not definition.form_qualified_name:
                return ReconciliationResult.failed(f"Definition {instance.definition_id} has no form_qualified_name")

            # 2. Get lab topology — nodes with tags for device mapping
            nodes = await self._cml_labs.get_lab_nodes(
                host=instance.worker_ip,
                lab_id=cml_lab_id,
                username=instance.worker_cml_username,
                password=instance.worker_cml_password,
            )

            # 3. Create LDS session
            region = instance.worker_aws_region
            session_info = await self._lds.create_session(
                username=instance.name,  # Use session name as candidate ID
                first_name="Lablet",
                last_name="User",
                scheduled_date=datetime.now(timezone.utc).isoformat(),
                form_qualified_name=definition.form_qualified_name,
                region=region,
            )

            lds_session_id = session_info.session_id
            logger.info(f"LDS session {lds_session_id} created for session {instance.id}")

            # 4. Build device access info from CML nodes
            devices = self._build_device_access_list(nodes, instance.worker_ip or "")

            if devices:
                # 5. Set devices on LDS session (part 1)
                await self._lds.set_devices(
                    session_id=lds_session_id,
                    part_num=1,
                    devices=devices,
                    region=region,
                )
                logger.info(f"Set {len(devices)} devices on LDS session {lds_session_id}")

            # 6. Get lablet launch URL
            launch_url = await self._lds.get_lablet_launch_url(
                session_id=lds_session_id,
                region=region,
            )

            # 7. Create UserSession child entity via CPA
            user_session_data = await self._api.create_user_session(
                session_id=instance.id,
                lds_session_id=lds_session_id,
                lds_login_url=launch_url,
                cml_lab_id=cml_lab_id,
            )
            user_session_id = user_session_data.get("id", lds_session_id)

            # 8. Transition to READY via control plane API
            await self._api.mark_session_ready(
                session_id=instance.id,
                user_session_id=user_session_id,
                cml_lab_id=cml_lab_id,
            )

            # Clean up local lab ID tracking (now persisted in CPA)
            self._resolved_lab_ids.pop(instance.id, None)

            self._lds_sessions_created += 1
            self._labs_started += 1
            logger.info(f"Session {instance.id} marked READY (user_session={user_session_id})")
            return ReconciliationResult.success()

        except LdsSpiError as e:
            logger.error(f"LDS provisioning failed for session {instance.id}: {e}")
            return ReconciliationResult.failed(f"LDS provisioning failed: {e}")
        except Exception as e:
            logger.error(f"Failed to provision LDS session for session {instance.id}: {e}")
            return ReconciliationResult.failed(str(e), e)

    async def _handle_expired(self, instance: LabletSessionReadModel) -> ReconciliationResult:
        """Handle timeslot expiry — expire the session via CPA (§7.4).

        Called from the early expiry check in ``reconcile()`` when
        ``datetime.now(utc) >= timeslot_end`` and the session is not
        yet in a terminal or stopping state.

        Delegates to ``ControlPlaneApiClient.expire_session()`` which
        unbinds the LabRecord, closes the run, and releases capacity
        (but does NOT release ports — ports belong to the LabRecord).
        """
        try:
            await self._api.expire_session(
                session_id=instance.id,
                reason="timeslot_expired",
            )
            logger.info(f"⏰ Session {instance.id} expired (timeslot ended)")
            return ReconciliationResult.requeue("Session expired — cleanup in progress")
        except Exception as e:
            logger.error(f"Failed to expire session {instance.id}: {e}")
            return ReconciliationResult.failed(f"Expiry failed: {e}")

    # =========================================================================
    # PIPELINE HELPERS (ADR-034 Sprint C)
    # =========================================================================

    async def _get_pipeline_def(self, instance: LabletSessionReadModel, pipeline_name: str) -> dict[str, Any] | None:
        """Fetch the named pipeline definition from the LabletDefinition.

        Args:
            instance: Session read model (carries definition_id).
            pipeline_name: Key into definition.pipelines (e.g. "instantiate").

        Returns:
            Pipeline dict (steps, max_retries, retry_backoff, …) or None.
        """
        definition = await self._get_definition(instance.definition_id)
        if not definition:
            logger.error(f"Definition not found for session {instance.id}: {instance.definition_id}")
            return None

        pipelines = getattr(definition, "pipelines", None) or {}
        pipeline_def = pipelines.get(pipeline_name)
        if not pipeline_def:
            logger.warning(f"No '{pipeline_name}' pipeline in definition {instance.definition_id}")
        return pipeline_def

    async def _build_pipeline_context(self, instance: LabletSessionReadModel) -> PipelineContext:
        """Build a PipelineContext from the session and reconciler services.

        The context is an immutable bag passed to every step handler
        through the executor.

        Args:
            instance: Session read model being reconciled.

        Returns:
            Fully-populated PipelineContext.
        """
        definition = await self._get_definition(instance.definition_id)

        return PipelineContext(
            session=instance,
            definition=definition,
            worker_ip=instance.worker_ip or "",
            worker_cml_username=instance.worker_cml_username or "",
            worker_cml_password=instance.worker_cml_password or "",
            api=self._api,
            cml=self._cml_labs,
            lds=self._lds,
        )

    def _build_step_dispatcher(self) -> StepDispatcher:
        """Build a step dispatcher closure for the pipeline executor.

        The executor calls ``step_dispatcher(handler_name, session, progress)``
        and expects the return value to be ``result_data: dict``.

        This closure resolves ``_step_{handler_name}`` on the reconciler,
        invokes it with ``(instance, progress)``, and extracts ``result_data``
        from the handler's return dict (existing step handlers return
        ``{"step": ..., "status": ..., "result_data": {...}}``).

        If the handler reports ``status="failed"``, a RuntimeError is raised
        so the executor records the step as failed with retry/timeout logic.
        """
        reconciler = self

        async def _dispatch(handler_name: str, session: LabletSessionReadModel, progress: dict[str, Any]) -> dict[str, Any]:
            method = getattr(reconciler, f"_step_{handler_name}", None)
            if method is None:
                raise RuntimeError(f"Unknown pipeline step handler: _step_{handler_name}")

            result = await method(session, progress)

            status = result.get("status", "completed")
            if status == "failed":
                raise RuntimeError(result.get("error", f"Step {handler_name} failed"))

            return result.get("result_data", {})

        return _dispatch

    def _get_step_result_data(self, progress: dict[str, Any], step_name: str) -> dict[str, Any] | None:
        """Extract result_data from a completed step in the progress dict.

        Works with the Sprint C dict-of-dicts progress format used by
        PipelineExecutor (``{step_name: {status, result_data, ...}}``).

        Args:
            progress: Full pipeline progress dict.
            step_name: Name of the step to look up.

        Returns:
            The result_data dict, or None if step not found / not completed.
        """
        step_info = progress.get(step_name)
        if not step_info or not isinstance(step_info, dict):
            return None
        return step_info.get("result_data")

    # =========================================================================
    # PIPELINE STEPS (ADR-031 Option A — inline methods)
    # =========================================================================

    async def _step_content_sync(self, instance: LabletSessionReadModel, progress: dict[str, Any]) -> dict[str, Any]:
        """Step 1: Verify definition content is synced and available (§6).

        Fail-fast prerequisite — if content is not synced, there is no
        point importing a lab (LDS provisioning requires the form and content).
        """
        definition = await self._get_definition(instance.definition_id)
        if not definition:
            return {"step": "content_sync", "status": "failed", "error": "Definition not found"}

        if not getattr(definition, "content_sync_enabled", False):
            return {"step": "content_sync", "status": "skipped"}

        sync_status = getattr(definition, "sync_status", None)
        if sync_status == "synced":
            return {
                "step": "content_sync",
                "status": "completed",
                "result_data": {
                    "sync_status": sync_status,
                    "form_qualified_name": definition.form_qualified_name,
                },
            }

        # Not synced — optionally trigger sync and fail (will retry on next reconcile)
        if self._content_sync_service and sync_status in (None, "not_synced", "sync_failed"):
            try:
                await self._content_sync_service.request_sync(definition.id)
            except Exception as e:
                logger.warning(f"Could not trigger content sync for {definition.id}: {e}")

        return {
            "step": "content_sync",
            "status": "failed",
            "error": f"Content not synced (status: {sync_status}). Waiting for sync.",
        }

    async def _step_variables(self, instance: LabletSessionReadModel, progress: dict[str, Any]) -> dict[str, Any]:
        """Step 2: Resolve session variables — placeholder (§5).

        Currently a no-op. Future: call variable resolution service.
        """
        definition = await self._get_definition(instance.definition_id)
        variables = getattr(definition, "variables", None) if definition else None
        if not variables:
            return {"step": "variables", "status": "skipped"}

        # Future: resolve variables from definition defaults
        resolved = {var.get("name"): var.get("default_value") for var in variables if var.get("default_value")}
        return {
            "step": "variables",
            "status": "completed",
            "result_data": {"resolved_variables": resolved},
        }

    async def _step_lab_resolve(self, instance: LabletSessionReadModel, progress: dict[str, Any]) -> dict[str, Any]:
        """Step 3: Resolve lab — reuse existing or import fresh (P9-4/5/8).

        Reuses the existing ``_resolve_lab_for_instance()`` logic.
        Returns ``cml_lab_id`` and ``lab_record_id`` in result_data.
        """
        # Resolve topology YAML from definition
        topology_yaml = instance.topology_yaml
        if not topology_yaml:
            definition = await self._get_definition(instance.definition_id)
            if definition:
                topology_yaml = getattr(definition, "cml_yaml_content", None) or definition.topology_yaml
            if not topology_yaml:
                return {
                    "step": "lab_resolve",
                    "status": "failed",
                    "error": f"No topology YAML found for definition {instance.definition_id}",
                }

        # Check if lab already resolved (from previous attempts or session state)
        cml_lab_id = instance.cml_lab_id or self._resolved_lab_ids.get(instance.id)

        if not cml_lab_id:
            lab_id = await self._resolve_lab_for_instance(instance, topology_yaml=topology_yaml)
            if not lab_id:
                return {
                    "step": "lab_resolve",
                    "status": "failed",
                    "error": "Lab resolution failed: unable to import or reuse a lab",
                }
            cml_lab_id = lab_id
            self._resolved_lab_ids[instance.id] = lab_id

            if lab_id != getattr(instance, "_freshly_imported_lab_id", None):
                self._labs_reused += 1
                logger.info(f"♻️ Reusing lab {lab_id} for session {instance.id}")
            else:
                self._labs_imported += 1
                logger.info(f"📦 Imported lab {lab_id} for session {instance.id}")

        # Resolve lab_record_id
        lab_record_id = await self._find_lab_record_id(cml_lab_id, instance.worker_id)

        return {
            "step": "lab_resolve",
            "status": "completed",
            "result_data": {
                "cml_lab_id": cml_lab_id,
                "lab_record_id": lab_record_id,
            },
        }

    async def _step_ports_alloc(self, instance: LabletSessionReadModel, progress: dict[str, Any]) -> dict[str, Any]:
        """Step 4: Allocate real ports from worker pool via CPA (§3.6).

        Ports are stored on the LabRecord, keyed by lab_record_id in etcd.
        """
        definition = await self._get_definition(instance.definition_id)
        if not definition or not getattr(definition, "port_template", None):
            return {"step": "ports_alloc", "status": "skipped"}

        resolve_data = self._get_step_result_data(progress, "lab_resolve")
        lab_record_id = resolve_data.get("lab_record_id") if resolve_data else None
        if not lab_record_id:
            return {"step": "ports_alloc", "status": "failed", "error": "No lab_record_id from lab_resolve"}

        try:
            result = await self._api.allocate_lab_record_ports(
                lab_record_id=lab_record_id,
                worker_id=instance.worker_id,
            )
            return {
                "step": "ports_alloc",
                "status": "completed",
                "result_data": result,
            }
        except Exception as e:
            return {"step": "ports_alloc", "status": "failed", "error": str(e)}

    async def _step_tags_sync(self, instance: LabletSessionReadModel, progress: dict[str, Any]) -> dict[str, Any]:
        """Step 5: Write allocated port numbers to CML node tags (§3.7, AD-TAGS-001).

        After ports_alloc, write protocol:port tags to each CML node via
        PATCH /api/v0/labs/{lab_id}/nodes/{node_id}.
        Tags persist across start/stop/wipe — they are topology-level metadata.
        """
        ports_data = self._get_step_result_data(progress, "ports_alloc")
        if not ports_data:
            return {"step": "tags_sync", "status": "skipped"}

        allocated_ports = ports_data.get("allocated_ports", {})
        if not allocated_ports:
            return {"step": "tags_sync", "status": "skipped"}

        resolve_data = self._get_step_result_data(progress, "lab_resolve")
        cml_lab_id = resolve_data.get("cml_lab_id") if resolve_data else None
        if not cml_lab_id:
            return {"step": "tags_sync", "status": "failed", "error": "No cml_lab_id from lab_resolve"}

        # Group allocated ports by node label.
        # Port names follow convention: "{node_label}_{protocol}"
        # (from PortTemplate.from_cml_nodes)
        node_tags: dict[str, list[str]] = {}
        for port_name, port_number in allocated_ports.items():
            parts = port_name.rsplit("_", 1)
            if len(parts) != 2:
                continue
            node_label, protocol = parts
            tag = f"{protocol}:{port_number}"
            node_tags.setdefault(node_label, []).append(tag)

        # Get CML lab nodes to find node IDs
        try:
            nodes = await self._cml_labs.get_lab_nodes(
                host=instance.worker_ip,
                lab_id=cml_lab_id,
                username=instance.worker_cml_username,
                password=instance.worker_cml_password,
            )
        except Exception as e:
            return {"step": "tags_sync", "status": "failed", "error": f"Failed to get lab nodes: {e}"}

        # Write tags to each matching node via PATCH
        synced_nodes = []
        for node in nodes:
            node_label = node.label
            # Sanitize label to match port_name convention (replace non-alphanumeric with _)
            safe_label = re.sub(r"[^a-zA-Z0-9_-]", "_", node_label)
            if safe_label in node_tags:
                try:
                    await self._cml_labs.patch_node_tags(
                        host=instance.worker_ip,
                        lab_id=cml_lab_id,
                        node_id=node.id,
                        tags=node_tags[safe_label],
                        username=instance.worker_cml_username,
                        password=instance.worker_cml_password,
                    )
                    synced_nodes.append(node_label)
                except Exception as e:
                    # AD-TAGS-001: Tag sync failures are non-fatal warnings
                    logger.warning(f"Failed to sync tags for node {node_label} in lab {cml_lab_id}: {e}")

        return {
            "step": "tags_sync",
            "status": "completed",
            "result_data": {
                "synced_nodes": synced_nodes,
                "tag_count": sum(len(t) for t in node_tags.values()),
            },
        }

    async def _step_lab_binding(self, instance: LabletSessionReadModel, progress: dict[str, Any]) -> dict[str, Any]:
        """Step 6: Bind LabRecord to session and create LabRunRecord (§4.3).

        Calls CPA ``bind_lab_to_session()`` which:
        1. Creates a LabRunRecord (runtime tracking, NO port fields)
        2. Sets ``active_lablet_session_id`` on LabRecord
        3. Denormalizes ``LabRecord.allocated_ports`` onto LabletSession
        """
        resolve_data = self._get_step_result_data(progress, "lab_resolve")
        cml_lab_id = resolve_data.get("cml_lab_id") if resolve_data else None
        lab_record_id = resolve_data.get("lab_record_id") if resolve_data else None

        if not cml_lab_id or not lab_record_id:
            return {
                "step": "lab_binding",
                "status": "failed",
                "error": "No cml_lab_id or lab_record_id from lab_resolve",
            }

        try:
            result = await self._api.bind_lab_to_session(
                session_id=instance.id,
                worker_id=instance.worker_id,
                lab_record_id=lab_record_id,
            )
            self._bindings_created += 1
            return {
                "step": "lab_binding",
                "status": "completed",
                "result_data": result,
            }
        except Exception as e:
            return {"step": "lab_binding", "status": "failed", "error": str(e)}

    async def _step_lab_start(self, instance: LabletSessionReadModel, progress: dict[str, Any]) -> dict[str, Any]:
        """Step 7: Start the CML lab and wait for BOOTED.

        If lab is already BOOTED (reuse case), completes immediately.
        If lab is STOPPED/DEFINED_ON_CORE, starts it.
        If lab is STARTED/QUEUED, returns ``failed`` to retry on next cycle.
        """
        resolve_data = self._get_step_result_data(progress, "lab_resolve")
        cml_lab_id = resolve_data.get("cml_lab_id") if resolve_data else None
        if not cml_lab_id:
            return {"step": "lab_start", "status": "failed", "error": "No cml_lab_id from lab_resolve"}

        try:
            lab_state = await self._cml_labs.get_lab_state(
                host=instance.worker_ip,
                lab_id=cml_lab_id,
                username=instance.worker_cml_username,
                password=instance.worker_cml_password,
            )
        except Exception as e:
            return {"step": "lab_start", "status": "failed", "error": f"Failed to get lab state: {e}"}

        if lab_state == LabState.BOOTED:
            # Lab is running — record run start and complete
            self._lab_run_started_at[instance.id] = datetime.now(timezone.utc)
            self._labs_started += 1
            return {
                "step": "lab_start",
                "status": "completed",
                "result_data": {"lab_state": "BOOTED", "cml_lab_id": cml_lab_id},
            }

        if lab_state in (LabState.STOPPED, LabState.DEFINED_ON_CORE):
            # Start the lab
            try:
                await self._cml_labs.start_lab(
                    host=instance.worker_ip,
                    lab_id=cml_lab_id,
                    username=instance.worker_cml_username,
                    password=instance.worker_cml_password,
                )
                logger.info(f"Lab {cml_lab_id} start initiated for session {instance.id}")
            except Exception as e:
                return {"step": "lab_start", "status": "failed", "error": f"Failed to start lab: {e}"}

        # Lab is starting or queued — retry on next reconcile cycle
        # Return "failed" so the step stays pending and is retried
        return {
            "step": "lab_start",
            "status": "failed",
            "error": f"Lab in state {lab_state}, waiting for BOOTED",
        }

    async def _step_lds_provision(self, instance: LabletSessionReadModel, progress: dict[str, Any]) -> dict[str, Any]:
        """Step 8: Provision LDS session with device mapping (§2.2).

        Reuses the existing ``_provision_lds_session()`` flow:
        1. Create LDS session with form_qualified_name
        2. Map CML nodes to LDS devices
        3. Get lablet launch URL
        4. Create UserSession child entity via CPA
        """
        resolve_data = self._get_step_result_data(progress, "lab_resolve")
        cml_lab_id = resolve_data.get("cml_lab_id") if resolve_data else None
        if not cml_lab_id:
            return {"step": "lds_provision", "status": "failed", "error": "No cml_lab_id from lab_resolve"}

        definition = await self._get_definition(instance.definition_id)
        if not definition or not definition.form_qualified_name:
            return {"step": "lds_provision", "status": "skipped"}

        try:
            # Get lab topology — nodes with tags for device mapping
            nodes = await self._cml_labs.get_lab_nodes(
                host=instance.worker_ip,
                lab_id=cml_lab_id,
                username=instance.worker_cml_username,
                password=instance.worker_cml_password,
            )

            # Create LDS session
            region = instance.worker_aws_region
            session_info = await self._lds.create_session(
                username=instance.name,
                first_name="Lablet",
                last_name="User",
                scheduled_date=datetime.now(timezone.utc).isoformat(),
                form_qualified_name=definition.form_qualified_name,
                region=region,
            )
            lds_session_id = session_info.session_id
            logger.info(f"LDS session {lds_session_id} created for session {instance.id}")

            # Build and set device access info
            devices = self._build_device_access_list(nodes, instance.worker_ip or "")
            if devices:
                await self._lds.set_devices(
                    session_id=lds_session_id,
                    part_num=1,
                    devices=devices,
                    region=region,
                )
                logger.info(f"Set {len(devices)} devices on LDS session {lds_session_id}")

            # Get lablet launch URL
            launch_url = await self._lds.get_lablet_launch_url(
                session_id=lds_session_id,
                region=region,
            )

            # Create UserSession child entity via CPA
            user_session_data = await self._api.create_user_session(
                session_id=instance.id,
                lds_session_id=lds_session_id,
                lds_login_url=launch_url,
                cml_lab_id=cml_lab_id,
            )
            user_session_id = user_session_data.get("id", lds_session_id)

            self._lds_sessions_created += 1
            return {
                "step": "lds_provision",
                "status": "completed",
                "result_data": {
                    "lds_session_id": lds_session_id,
                    "user_session_id": user_session_id,
                    "launch_url": launch_url,
                    "device_count": len(devices),
                },
            }

        except LdsSpiError as e:
            return {"step": "lds_provision", "status": "failed", "error": f"LDS provisioning failed: {e}"}
        except Exception as e:
            return {"step": "lds_provision", "status": "failed", "error": str(e)}

    async def _step_mark_ready(self, instance: LabletSessionReadModel, progress: dict[str, Any]) -> dict[str, Any]:
        """Step 9: Atomic transition to READY.

        Calls ``mark_session_ready()`` with the resolved CML lab ID
        and user session ID.
        """
        resolve_data = self._get_step_result_data(progress, "lab_resolve")
        cml_lab_id = resolve_data.get("cml_lab_id") if resolve_data else None
        if not cml_lab_id:
            return {"step": "mark_ready", "status": "failed", "error": "No cml_lab_id from lab_resolve"}

        # Get user_session_id from lds_provision (if it ran)
        lds_data = self._get_step_result_data(progress, "lds_provision")
        user_session_id = (lds_data.get("user_session_id") if lds_data else None) or ""

        try:
            await self._api.mark_session_ready(
                session_id=instance.id,
                user_session_id=user_session_id,
                cml_lab_id=cml_lab_id,
            )

            # Clean up local lab ID tracking (now persisted in CPA)
            self._resolved_lab_ids.pop(instance.id, None)

            logger.info(f"✅ Session {instance.id} marked READY (pipeline complete)")
            return {
                "step": "mark_ready",
                "status": "completed",
                "result_data": {"cml_lab_id": cml_lab_id, "user_session_id": user_session_id},
            }
        except Exception as e:
            return {"step": "mark_ready", "status": "failed", "error": str(e)}

    async def _handle_ready(self, instance: LabletSessionReadModel) -> ReconciliationResult:
        """Handle READY session - verify LDS session is provisioned.

        In READY state, the lab is BOOTED and LDS session is provisioned.
        The transition to RUNNING will happen via CloudEvent (session.started)
        when the user launches the lab.

        For now, we just verify the lab is still running.
        """
        if not instance.cml_lab_id:
            return ReconciliationResult.failed("No CML lab ID in READY state")

        try:
            # Verify lab is still running
            lab_state = await self._cml_labs.get_lab_state(
                host=instance.worker_ip,
                lab_id=instance.cml_lab_id,
                username=instance.worker_cml_username,
                password=instance.worker_cml_password,
            )

            if lab_state and lab_state != LabState.BOOTED:
                logger.warning(f"Lab {instance.cml_lab_id} unexpectedly not BOOTED in READY state (state={lab_state})")

            return ReconciliationResult.success()

        except Exception as e:
            logger.warning(f"Failed to verify lab state for READY session {instance.id}: {e}")
            return ReconciliationResult.success()  # Don't fail on sync issues

    async def _handle_running(self, instance: LabletSessionReadModel) -> ReconciliationResult:
        """Handle RUNNING session - sync state, observe resources, check timeslot.

        ADR-030: Observes resources before transitioning to STOPPING.
        CML Labs SPI: GET /api/v0/labs/{id}/state
        """
        if not instance.cml_lab_id:
            return ReconciliationResult.failed("No CML lab ID")

        try:
            # Check if timeslot has ended
            if instance.timeslot_end:
                now = datetime.now(timezone.utc)
                if isinstance(instance.timeslot_end, str):
                    timeslot_end = datetime.fromisoformat(instance.timeslot_end.replace("Z", "+00:00"))
                else:
                    timeslot_end = instance.timeslot_end

                if now >= timeslot_end:
                    # AD-OLR-001: Observe resources before transitioning
                    await self._observe_and_report(instance)

                    # Timeslot ended - transition to STOPPING
                    await self._api.transition_session(
                        session_id=instance.id,
                        new_status=LabletSessionStatus.STOPPING,
                        reason="Timeslot ended",
                    )
                    logger.info(f"Session {instance.id} timeslot ended, transitioning to {LabletSessionStatus.STOPPING}")
                    return ReconciliationResult.requeue("Timeslot ended")

            # Verify lab is still running
            lab_state = await self._cml_labs.get_lab_state(
                host=instance.worker_ip,
                lab_id=instance.cml_lab_id,
                username=instance.worker_cml_username,
                password=instance.worker_cml_password,
            )

            if lab_state and lab_state != LabState.BOOTED:
                logger.warning(f"Lab {instance.cml_lab_id} is not BOOTED (state={lab_state})")
                # Could auto-restart or report error
                # For now, just log

            self._lab_sync_count += 1
            return ReconciliationResult.success()

        except Exception as e:
            logger.warning(f"Failed to sync lab state for session {instance.id}: {e}")
            return ReconciliationResult.success()  # Don't fail on sync issues

    async def _observe_and_report(self, instance: LabletSessionReadModel) -> None:
        """Observe live CML lab resources and report to CPA.

        Best-effort: failures are logged but do not block session lifecycle.
        AD-OLR-001: Observation at COLLECTING/STOPPING boundary.
        ADR-030: Resource & Port Observation — "Learn from Live"
        """
        if not self._settings.resource_observation_enabled:
            logger.debug(f"Resource observation disabled — skipping for session {instance.id}")
            return

        if not self._resource_observer:
            logger.debug(f"Resource observer not configured — skipping observation for session {instance.id}")
            return

        try:
            timeout = self._settings.resource_observation_timeout_seconds
            observation = await asyncio.wait_for(
                self._resource_observer.observe(
                    host=instance.worker_ip,
                    lab_id=instance.cml_lab_id,
                    username=instance.worker_cml_username,
                    password=instance.worker_cml_password,
                ),
                timeout=timeout,
            )
            if observation:
                await self._api.report_resource_observations(
                    session_id=instance.id,
                    observed_resources=observation.to_dict(),
                    observed_ports=observation.observed_ports,
                )
                logger.info(
                    f"Resource observation reported for session {instance.id}: "
                    f"cpu={observation.total_cpu_cores}, mem={observation.total_memory_mb}MB, "
                    f"nodes={observation.actual_node_count}, ports={len(observation.observed_ports)}"
                )
            else:
                logger.warning(f"No resource observation available for session {instance.id}")
        except TimeoutError:
            logger.warning(f"Resource observation timed out for session {instance.id} (timeout={self._settings.resource_observation_timeout_seconds}s)")
        except Exception as e:
            logger.warning(f"Resource observation failed for session {instance.id}: {e}")

    async def _handle_observe_resources_event(self, session_id: str, value: str) -> None:
        """Handle manual observation request from etcd watch.

        ADR-030 / AD-OLR-007: Triggered when admin requests observation via
        CPA API → domain event → etcd projector → this handler.

        1. Parse the request payload
        2. Fetch session details from CPA
        3. Call _observe_and_report() (reuses Phase 5 logic)
        4. Always delete the etcd key (observation complete or not applicable)
        """
        import json

        logger.info(f"Handling observe_resources request for session {session_id}")

        try:
            data = json.loads(value)
            requested_by = data.get("requested_by", "unknown")
            logger.info(f"Observe resources requested by {requested_by} for session {session_id}")

            # Fetch session from CPA
            instance = await self.fetch_resource_by_id(session_id)
            if instance and instance.status == LabletSessionStatus.RUNNING.value:
                await self._observe_and_report(instance)
            else:
                status = instance.status if instance else "not found"
                logger.warning(f"Cannot observe session {session_id}: status={status} (must be RUNNING)")
        except Exception as e:
            logger.warning(f"Failed to handle observe_resources for session {session_id}: {e}")
        finally:
            # Always delete the etcd key to avoid re-triggering
            try:
                if self._etcd:
                    await self._etcd.delete(f"/sessions/{session_id}/observe_resources")
                    logger.debug(f"Deleted observe_resources key for session {session_id}")
            except Exception as e:
                logger.warning(f"Failed to delete observe_resources key for session {session_id}: {e}")

    async def _handle_stopping(self, instance: LabletSessionReadModel) -> ReconciliationResult:
        """Handle STOPPING session - archive LDS, record run, stop/wipe lab.

        This handler covers the full teardown lifecycle:
        1. Archive LDS session (graceful - won't block on failure)
        2. Record lab run completion (P9-7)
        3. Stop the lab if running
        4. Wipe the lab (don't delete → available for reuse)
        5. Transition to ARCHIVED

        Note: Lab binding/unbinding is now handled by session termination
        lifecycle (Phase 7G). No explicit bind/unbind calls needed.

        CML Labs SPI: PUT /api/v0/labs/{id}/stop, PUT /api/v0/labs/{id}/wipe
        LDS SPI: POST /lab_session/{id}/release
        """
        # Archive LDS session first (graceful — won't block cleanup on failure)
        await self._archive_lds_session(instance)

        # P9-7: Record lab run completion
        await self._record_lab_run_completed(instance)

        if not instance.cml_lab_id:
            await self._api.transition_session(
                session_id=instance.id,
                new_status=LabletSessionStatus.ARCHIVED,
                reason="No lab to clean up",
            )
            return ReconciliationResult.success()

        try:
            lab_state = await self._cml_labs.get_lab_state(
                host=instance.worker_ip,
                lab_id=instance.cml_lab_id,
                username=instance.worker_cml_username,
                password=instance.worker_cml_password,
            )

            if lab_state == LabState.BOOTED:
                # Stop the lab first
                await self._cml_labs.stop_lab(
                    host=instance.worker_ip,
                    lab_id=instance.cml_lab_id,
                    username=instance.worker_cml_username,
                    password=instance.worker_cml_password,
                )
                return ReconciliationResult.requeue("Lab stop initiated")

            elif lab_state in (LabState.STARTED, LabState.QUEUED):
                return ReconciliationResult.requeue(f"Lab in state {lab_state}, waiting for stop")

            elif lab_state in (LabState.STOPPED, LabState.DEFINED_ON_CORE):
                # Lab is stopped — wipe (keep topology for reuse, don't delete)
                await self._cml_labs.wipe_lab(
                    host=instance.worker_ip,
                    lab_id=instance.cml_lab_id,
                    username=instance.worker_cml_username,
                    password=instance.worker_cml_password,
                )
                # Update lab record status to WIPED (available for reuse)
                await self._update_lab_record_status(instance.cml_lab_id, instance.worker_id, "wiped")
                await self._api.transition_session(
                    session_id=instance.id,
                    new_status=LabletSessionStatus.ARCHIVED,
                    reason="Lab wiped and available for reuse",
                )
                self._labs_stopped += 1
                logger.info(f"Session {instance.id} archived (lab {instance.cml_lab_id} wiped for reuse)")
                return ReconciliationResult.success()

            else:
                return ReconciliationResult.requeue(f"Lab in state {lab_state}, waiting")

        except Exception as e:
            logger.error(f"Failed to stop/cleanup lab for instance {instance.id}: {e}")
            return ReconciliationResult.failed(str(e), e)

    # NOTE: _handle_pending_cleanup removed — cleanup is now part of _handle_stopping.
    # The canonical state machine uses: STOPPING → ARCHIVED (no PENDING_CLEANUP/CLEANED_UP).

    # =========================================================================
    # LAB RESOLUTION (P9-4/5/8)
    # =========================================================================

    async def _resolve_lab_for_instance(self, instance: LabletSessionReadModel, topology_yaml: str | None = None) -> str | None:
        """Resolve a lab for an instance: reuse existing or import fresh.

        Lab Resolution Strategy (Architecture §5.4):
        1. Fetch LabletDefinition to check lab_reuse_enabled flag (P9-8)
        2. If reuse enabled, query CPA for existing LabRecords on this worker
           matching the definition's topology:
           a. WIPED lab → bind and start (fastest ~20s)
           b. STOPPED lab → wipe first, then start (~30s)
        3. If no reusable lab found or reuse disabled → fresh import (~90s)

        Args:
            instance: The LabletSession needing a lab.
            topology_yaml: Resolved topology YAML (from definition or session).

        Returns:
            CML lab ID (from reuse or import), or None on failure.
        """
        definition = await self._get_definition(instance.definition_id)

        # P9-8: Check if lab reuse is enabled for this definition
        if definition and definition.lab_reuse_enabled:
            reused_lab_id = await self._try_reuse_existing_lab(instance, definition)
            if reused_lab_id:
                return reused_lab_id

        # Fallback: fresh import
        return await self._import_fresh_lab(instance, topology_yaml=topology_yaml)

    async def _try_reuse_existing_lab(
        self,
        instance: LabletSessionReadModel,
        definition: LabletDefinitionReadModel,
    ) -> str | None:
        """Try to find and reuse an existing lab on the worker.

        Queries CPA for LabRecords on this worker that are in reusable states
        (WIPED or STOPPED) and match the definition's topology (by node_count).

        Priority: WIPED > STOPPED (wiped is faster to restart).

        Args:
            instance: The LabletSession needing a lab.
            definition: The LabletDefinition with topology spec.

        Returns:
            Reused CML lab ID, or None if no reusable lab found.
        """
        if not instance.worker_id:
            return None

        try:
            # Query CPA for reusable labs on this worker
            lab_records = await self._api.get_lab_records_for_worker(
                worker_id=instance.worker_id,
            )

            if not lab_records:
                return None

            # Parse into read models for structured access
            candidates = [LabRecordReadModel.from_dict(lr) for lr in lab_records]

            # Filter to reusable candidates matching the topology
            wiped_candidates: list[LabRecordReadModel] = []
            stopped_candidates: list[LabRecordReadModel] = []

            for lr in candidates:
                # Must match definition's node count (basic topology match)
                if definition.node_count and lr.node_count != definition.node_count:
                    continue

                # Must not already have an active pending action
                if lr.has_pending_action:
                    continue

                if lr.status == LabRecordStatus.WIPED.value:
                    wiped_candidates.append(lr)
                elif lr.status == LabRecordStatus.STOPPED.value:
                    stopped_candidates.append(lr)

            # Priority 1: WIPED lab → just start (~20s)
            if wiped_candidates:
                lab = wiped_candidates[0]
                logger.info(f"♻️ Found WIPED lab {lab.lab_id} on worker {instance.worker_id} for reuse (instance={instance.id})")
                return lab.lab_id

            # Priority 2: STOPPED lab → wipe first, then start (~30s)
            if stopped_candidates:
                lab = stopped_candidates[0]
                logger.info(f"♻️ Found STOPPED lab {lab.lab_id} on worker {instance.worker_id} — wiping for reuse (instance={instance.id})")
                # Wipe the lab to prepare for reuse
                await self._cml_labs.wipe_lab(
                    host=instance.worker_ip,
                    lab_id=lab.lab_id,
                    username=instance.worker_cml_username,
                    password=instance.worker_cml_password,
                )
                # Update lab record status to WIPED via CPA
                await self._update_lab_record_status(lab.lab_id, instance.worker_id, "wiped")
                return lab.lab_id

            logger.debug(f"No reusable labs found on worker {instance.worker_id}")
            return None

        except Exception as e:
            logger.warning(f"Lab reuse lookup failed for instance {instance.id}: {e}")
            return None

    async def _import_fresh_lab(self, instance: LabletSessionReadModel, topology_yaml: str | None = None) -> str | None:
        """Import a fresh lab from topology YAML.

        Args:
            instance: The LabletSession needing a lab.
            topology_yaml: Resolved topology YAML (from definition or session fallback).

        Returns:
            New CML lab ID, or None on failure.
        """
        effective_yaml = topology_yaml or instance.topology_yaml
        if not effective_yaml:
            logger.error(f"No topology YAML available for session {instance.id}")
            return None

        try:
            lab_id = await self._cml_labs.import_lab(
                host=instance.worker_ip,
                topology_yaml=effective_yaml,
                title=instance.name,
                username=instance.worker_cml_username,
                password=instance.worker_cml_password,
            )
            # Tag as freshly imported (used for metrics, not persisted)
            instance._freshly_imported_lab_id = lab_id  # type: ignore[attr-defined]
            return lab_id
        except Exception as e:
            logger.error(f"Failed to import lab for instance {instance.id}: {e}")
            return None

    # =========================================================================
    # LAB BINDING MANAGEMENT (P9-6)
    # =========================================================================

    async def _bind_lab_to_instance(self, instance: LabletSessionReadModel) -> None:
        """Lab binding is now handled at schedule time via lab_record_id param.

        Phase 7G: bind_lab_to_lablet() was removed from ControlPlaneApiClient.
        Lab binding is done implicitly when schedule_session() is called with
        a lab_record_id. This method is kept as a no-op for backward compatibility
        with any callers that haven't been updated yet.

        Args:
            instance: The LabletSession (unused).
        """
        # No-op: lab binding absorbed into schedule_session() in Phase 7G
        pass

    async def _release_lab_binding(self, instance: LabletSessionReadModel) -> None:
        """Lab unbinding is now handled by session termination lifecycle.

        Phase 7G: unbind_lab_from_lablet() was removed from ControlPlaneApiClient.
        Unbinding is handled automatically when the session is terminated/archived.
        This method is kept as a no-op for backward compatibility.

        Args:
            instance: The LabletSession (unused).
        """
        # No-op: unbinding handled by session termination in Phase 7G
        pass

    # =========================================================================
    # RUN HISTORY (P9-7)
    # =========================================================================

    async def _record_lab_run_completed(self, instance: LabletSessionReadModel) -> None:
        """Record a completed lab run via CPA.

        Called during STOPPING phase. Creates a LabRunRecord documenting
        the start→stop execution cycle.

        Args:
            instance: The LabletSession whose run is ending.
        """
        if not instance.cml_lab_id or not instance.worker_id:
            return

        try:
            lab_record_id = await self._find_lab_record_id(instance.cml_lab_id, instance.worker_id)
            if not lab_record_id:
                return

            # Get run start time from tracking dict, or use timeslot_start as fallback
            started_at = self._lab_run_started_at.pop(instance.id, None)
            started_at_str = started_at.isoformat() if started_at else None
            stopped_at_str = datetime.now(timezone.utc).isoformat()

            await self._api.record_lab_run_completed(
                lab_record_id=lab_record_id,
                started_at=started_at_str,
                stopped_at=stopped_at_str,
                started_by="lablet-controller",
                stop_reason="timeslot_end",
                lablet_session_id=instance.id,
                final_state="stopped",
            )
            self._runs_recorded += 1
            logger.info(f"📝 Recorded lab run for session {instance.id}")

        except Exception as e:
            logger.warning(f"Failed to record lab run for session {instance.id}: {e}")

    # =========================================================================
    # LAB RECORD HELPERS
    # =========================================================================

    async def _find_lab_record_id(self, cml_lab_id: str, worker_id: str) -> str | None:
        """Find the LabRecord aggregate ID for a CML lab on a specific worker.

        Queries CPA for lab records matching the worker and CML lab ID.

        Args:
            cml_lab_id: CML native lab ID.
            worker_id: Worker aggregate ID.

        Returns:
            LabRecord aggregate ID, or None if not found.
        """
        try:
            lab_records = await self._api.get_lab_records_for_worker(worker_id=worker_id)
            for lr in lab_records:
                if lr.get("lab_id") == cml_lab_id:
                    return lr.get("id")
        except Exception as e:
            logger.warning(f"Failed to find LabRecord for lab {cml_lab_id} on worker {worker_id}: {e}")

        return None

    async def _update_lab_record_status(
        self,
        cml_lab_id: str,
        worker_id: str,
        new_status: str,
    ) -> None:
        """Update a lab record's status via CPA.

        Graceful: logs failures but does not propagate exceptions.

        Args:
            cml_lab_id: CML native lab ID.
            worker_id: Worker aggregate ID.
            new_status: New LabRecordStatus value (lowercase).
        """
        try:
            lab_record_id = await self._find_lab_record_id(cml_lab_id, worker_id)
            if lab_record_id:
                await self._api.update_lab_record_status(
                    lab_record_id=lab_record_id,
                    new_status=new_status,
                )
        except Exception as e:
            logger.warning(f"Failed to update lab record status for lab {cml_lab_id}: {e}")

    # =========================================================================
    # LDS HELPERS
    # =========================================================================

    @staticmethod
    def _build_device_access_list(nodes: list[NodeInfo], worker_ip: str) -> list[DeviceAccessInfo]:
        """Build LDS device access info from CML node topology.

        AD-P4-03: CML node label = device_label, tags encode protocol:port.
        Tags format: ["serial:5041", "vnc:5044", "ssh:22"]

        Args:
            nodes: CML lab nodes with labels and tags.
            worker_ip: Worker IP address for device host.

        Returns:
            List of DeviceAccessInfo for LDS device provisioning.
        """
        devices: list[DeviceAccessInfo] = []

        for node in nodes:
            if not node.tags:
                continue

            for tag in node.tags:
                # Parse "protocol:port" format
                if ":" not in tag:
                    continue

                parts = tag.split(":", 1)
                if len(parts) != 2:
                    continue

                protocol = parts[0].strip()
                try:
                    port = int(parts[1].strip())
                except ValueError:
                    logger.warning(f"Invalid port in tag '{tag}' for node '{node.label}'")
                    continue

                devices.append(
                    DeviceAccessInfo(
                        device_label=node.label,
                        protocol=protocol,
                        host=worker_ip,
                        port=port,
                    )
                )

        return devices

    async def _get_definition(self, definition_id: str) -> LabletDefinitionReadModel | None:
        """Fetch lablet definition, using cache for repeated lookups.

        Args:
            definition_id: The definition ID to fetch.

        Returns:
            LabletDefinitionReadModel or None.
        """
        if definition_id in self._definition_cache:
            return self._definition_cache[definition_id]

        try:
            data = await self._api.get_lablet_definition(definition_id)
            if data:
                definition = LabletDefinitionReadModel.from_dict(data)
                self._definition_cache[definition_id] = definition
                return definition
        except Exception as e:
            logger.error(f"Failed to fetch definition {definition_id}: {e}")

        return None

    async def _archive_lds_session(self, instance: LabletSessionReadModel) -> None:
        """Archive the LDS session for a session.

        Graceful: logs failures but does not propagate exceptions.

        Args:
            instance: Session with LDS session to archive.
        """
        if not instance.lds_session_id:
            return

        try:
            await self._lds.archive_session(
                session_id=instance.lds_session_id,
                region=instance.worker_aws_region,
            )
            self._lds_sessions_archived += 1
            logger.info(f"Archived LDS session {instance.lds_session_id} for instance {instance.id}")
        except LdsSpiError as e:
            logger.warning(f"Failed to archive LDS session {instance.lds_session_id}: {e}")
        except Exception as e:
            logger.warning(f"Unexpected error archiving LDS session {instance.lds_session_id}: {e}")

    # =========================================================================
    # WORKER DETAILS RESOLUTION
    # =========================================================================

    async def _enrich_with_worker_details(self, session: LabletSessionReadModel) -> None:
        """Enrich a session read model with worker connection details.

        The CPA DTO only includes worker_id. Connection details (IP, credentials)
        are resolved from the CMLWorker aggregate via CPA and cached locally.

        Follows the same caching pattern as LabRecordReconciler._resolve_worker_host()
        and LabDiscoveryService._resolve_worker_host().

        Args:
            session: The session to enrich (mutated in-place).
        """
        if not session.worker_id:
            return

        worker = await self._get_cached_worker(session.worker_id)
        if not worker:
            return

        # Resolve host IP (private or public based on settings)
        session.worker_ip = self._extract_host_from_worker(worker)

        # Resolve CML credentials: per-worker or global fallback
        session.worker_cml_username = self._settings.cml_worker_api_username
        session.worker_cml_password = self._settings.cml_worker_api_password

        # Resolve AWS region
        session.worker_aws_region = worker.get("aws_region")

    async def _get_cached_worker(self, worker_id: str) -> dict | None:
        """Get worker data from cache or CPA.

        Uses a local cache to avoid repeated CPA lookups for the same worker.

        Args:
            worker_id: CML worker ID.

        Returns:
            Worker data dictionary, or None if unavailable.
        """
        if worker_id in self._worker_cache:
            return self._worker_cache[worker_id]

        try:
            worker = await self._api.get_worker(worker_id)
            if not worker:
                logger.warning(f"Worker {worker_id} not found via CPA")
                return None

            self._worker_cache[worker_id] = worker
            return worker

        except Exception as e:
            logger.error(f"Failed to resolve worker {worker_id}: {e}")
            return None

    def _extract_host_from_worker(self, worker: dict) -> str | None:
        """Extract host address from worker data.

        Follows the same logic as LabDiscoveryService._resolve_worker_host()
        and LabRecordReconciler._extract_host_from_worker().

        Args:
            worker: Worker data from Control Plane API.

        Returns:
            Host address string, or None if unavailable.
        """
        if self._settings.use_private_ip_for_monitoring:
            host = worker.get("private_ip") or worker.get("public_ip")
        else:
            host = worker.get("public_ip") or worker.get("private_ip")

        # Fallback to https_endpoint
        if not host:
            https_endpoint = worker.get("https_endpoint", "")
            if https_endpoint:
                host = https_endpoint.replace("https://", "").split(":")[0]

        return host or None

    # =========================================================================
    # SERVICE INFO
    # =========================================================================

    @property
    def stats(self) -> dict[str, Any]:
        """Get reconciler statistics."""
        base_stats = super().stats
        base_stats.update(
            {
                "labs_imported": self._labs_imported,
                "labs_started": self._labs_started,
                "labs_stopped": self._labs_stopped,
                "labs_deleted": self._labs_deleted,
                "labs_reused": self._labs_reused,
                "lab_sync_count": self._lab_sync_count,
                "bindings_created": self._bindings_created,
                "bindings_released": self._bindings_released,
                "runs_recorded": self._runs_recorded,
                "lds_sessions_created": self._lds_sessions_created,
                "lds_sessions_archived": self._lds_sessions_archived,
                "cached_workers": len(self._worker_cache),
                "cached_definitions": len(self._definition_cache),
            }
        )
        return base_stats

    async def check_readiness(self) -> tuple[bool, str]:
        """Check if the reconciler is ready."""
        if not self._started:
            return False, "Reconciler not started"

        if not self.is_leader:
            return True, "Standby mode (not leader)"

        return True, "Leader and running"

    def get_extra_info(self) -> dict[str, Any]:
        """Get extra info for /info endpoint."""
        return {
            "is_leader": self.is_leader,
            "current_leader_id": self.current_leader_id,
            "instance_id": self.instance_id,
            "stats": self.stats,
        }

    @classmethod
    def configure(
        cls,
        services: "ServiceCollection",
        settings: Settings,
    ) -> None:
        """Configure DI registration.

        Registers LabletReconciler as both a concrete singleton and as a
        HostedService for automatic lifecycle management by the Neuroglia
        framework (start_async/stop_async called on app startup/shutdown).

        Also registers LabDiscoveryService as a singleton (not as HostedService).
        The discovery service is started/stopped by the leader LabletReconciler
        in _become_leader()/_step_down(), ensuring only the elected leader
        runs discovery to avoid duplicate CML API calls.

        NOTE: The HostedService factory return type MUST be the concrete type
        (not HostedService) because Neuroglia's get_services() deduplicates
        based on factory return type annotation. Two factories both returning
        HostedService would cause the second to be silently skipped.

        Args:
            services: Neuroglia service collection.
            settings: Application settings.
        """
        from neuroglia.hosting.abstractions import HostedService

        from application.hosted_services.content_sync_service import ContentSyncService
        from application.hosted_services.lab_discovery_service import LabDiscoveryService
        from application.hosted_services.lab_record_reconciler import LabRecordReconciler
        from application.hosted_services.timeslot_watcher_service import TimeslotWatcherService

        # Register ResourceObserver as singleton (ADR-030, lifecycle managed by reconciler)
        ResourceObserver.configure(services)

        # Register LabDiscoveryService as singleton (lifecycle managed by reconciler)
        LabDiscoveryService.configure(services)

        # Register LabRecordReconciler as singleton (AD-023, lifecycle managed by reconciler)
        LabRecordReconciler.configure(services)

        # Register ContentSyncService as singleton (AD-CS-001, lifecycle managed by reconciler)
        ContentSyncService.configure(services)

        # Register TimeslotWatcherService as singleton (AD-TIMESLOT-001, lifecycle managed by reconciler)
        TimeslotWatcherService.configure(services)

        def factory(sp) -> LabletReconciler:
            # Resolve optional resource observer (ADR-030)
            try:
                resource_observer = sp.get_required_service(ResourceObserver)
            except Exception:
                resource_observer = None
                logger.warning("ResourceObserver not available — resource observation disabled")

            # Resolve optional lab discovery service
            try:
                lab_discovery = sp.get_required_service(LabDiscoveryService)
            except Exception:
                lab_discovery = None
                logger.warning("LabDiscoveryService not available — discovery disabled")

            # Resolve optional lab record reconciler (AD-023)
            try:
                lab_record_reconciler = sp.get_required_service(LabRecordReconciler)
            except Exception:
                lab_record_reconciler = None
                logger.warning("LabRecordReconciler not available — lab action reconciliation disabled")

            # Resolve optional content sync service (AD-CS-001)
            try:
                content_sync = sp.get_required_service(ContentSyncService)
            except Exception:
                content_sync = None
                logger.warning("ContentSyncService not available — content sync disabled")

            # Resolve optional timeslot watcher service (AD-TIMESLOT-001)
            try:
                timeslot_watcher = sp.get_required_service(TimeslotWatcherService)
            except Exception:
                timeslot_watcher = None
                logger.warning("TimeslotWatcherService not available — proactive timeslot detection disabled")

            return cls(
                api_client=sp.get_required_service(ControlPlaneApiClient),
                etcd_client=sp.get_required_service(EtcdClient),
                cml_labs_client=sp.get_required_service(CmlLabsSpiClient),
                lds_client=sp.get_required_service(LdsSpiClient),
                settings=settings,
                resource_observer=resource_observer,
                lab_discovery_service=lab_discovery,
                lab_record_reconciler=lab_record_reconciler,
                content_sync_service=content_sync,
                timeslot_watcher_service=timeslot_watcher,
            )

        def hosted_service_factory(sp) -> LabletReconciler:
            return sp.get_required_service(cls)

        # NOTE: implementation_type=cls is required so Neuroglia's get_implementation_type()
        # returns the actual class, not a string from inspect.signature().return_annotation.
        # String annotations (-> "ClassName") cause TypeError in _is_service_instance_of()
        # because isinstance() cannot accept a string as its second argument.
        services.add_singleton(cls, implementation_type=cls, implementation_factory=factory)
        services.add_singleton(HostedService, implementation_type=cls, implementation_factory=hosted_service_factory)
