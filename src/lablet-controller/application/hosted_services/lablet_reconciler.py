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
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from lcm_core.domain.entities import LabletSessionReadModel
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
from integration.services.cml_labs_spi import CmlLabsSpiClient, LabState, NodeInfo
from integration.services.lds_spi import DeviceAccessInfo, LdsSpiClient, LdsSpiError

if TYPE_CHECKING:
    from neuroglia.dependency_injection import ServiceCollection

    from application.hosted_services.content_sync_service import ContentSyncService
    from application.hosted_services.lab_discovery_service import LabDiscoveryService
    from application.hosted_services.lab_record_reconciler import LabRecordReconciler
    from application.hosted_services.timeslot_watcher_service import TimeslotWatcherService

# Sprint C (ADR-034) — pipeline execution imports
# ADR-038: Import step_handlers package to trigger @step_handler registration
import application.services.step_handlers  # noqa: F401
from application.models.pipeline_context import PipelineContext
from application.models.pipeline_result import PipelineResult
from application.services.lifecycle_phase_handler import LifecyclePhaseHandler
from application.services.pipeline_executor import PipelineExecutor, StepDispatcher
from application.services.pipeline_template_resolver import PipelineTemplateResolver

# ADR-038 Task 3: Extracted reconciler helpers
from application.services.reconciler_helpers import definition_cache as _def_cache
from application.services.reconciler_helpers import lab_record_helpers as _lab_rec
from application.services.reconciler_helpers import lab_resolution as _lab_res
from application.services.reconciler_helpers import lds_helpers as _lds_h
from application.services.reconciler_helpers import observation_helpers as _obs_h
from application.services.reconciler_helpers import run_history as _run_hist
from application.services.reconciler_helpers import worker_helpers as _worker_h
from application.services.step_registry import get_handler

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

        # ADR-038: Pipeline template resolver for extends/insert/override support
        self._template_resolver = PipelineTemplateResolver()

        # Track sessions whose labs were freshly imported (not reused).
        # Used by failure cleanup to decide whether to delete the CML lab
        # and LabRecord (freshly imported) vs. just stop/wipe (reused).
        self._freshly_imported_sessions: set[str] = set()

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
                LabletSessionStatus.COLLECTING,
                LabletSessionStatus.GRADING,
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
            elif status == LabletSessionStatus.COLLECTING:
                return await self._handle_collecting(instance)
            elif status == LabletSessionStatus.GRADING:
                return await self._handle_grading(instance)
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

    # =========================================================================
    # GENERIC PIPELINE PHASE HANDLER (ADR-038 Task 4)
    # =========================================================================

    async def _handle_pipeline_phase(
        self,
        instance: LabletSessionReadModel,
        pipeline_name: str,
        *,
        on_max_retry_exhausted: Callable | None = None,
    ) -> ReconciliationResult:
        """Generic fire-and-check handler for pipeline-driven lifecycle phases.

        Implements the common pattern shared by _handle_instantiating,
        _handle_collecting, _handle_grading, and _handle_stopping:

        1. If handler exists and is running → return success (self-driving)
        2. If handler finished → check result, retry or terminate
        3. If no handler → start new one with pipeline from definition

        Args:
            instance: The session to handle.
            pipeline_name: Pipeline name in the definition (e.g., "instantiate", "teardown").
            on_max_retry_exhausted: Optional async callback ``(instance, result, retry_count)``
                invoked before termination when the pipeline has exhausted its retry budget.
                Used by _handle_instantiating for lab cleanup.
        """
        handler_key = f"{instance.id}:{pipeline_name}"

        # --- Check existing handler ---
        if handler_key in self._active_handlers:
            handler = self._active_handlers[handler_key]

            if handler.is_running:
                return ReconciliationResult.success(f"{pipeline_name} pipeline handler running")

            # Handler finished — inspect result
            result = handler.result
            del self._active_handlers[handler_key]

            if result is None:
                logger.error(f"{pipeline_name} pipeline handler for session {instance.id} finished with no result (crash)")
            elif result.status in ("completed", "partial"):
                logger.info(f"{pipeline_name} pipeline completed for session {instance.id} ({result.status})")
                return ReconciliationResult.success(f"{pipeline_name} pipeline {result.status}")
            elif result.status == "failed":
                retry_count = self._pipeline_retry_counts.get(handler_key, 0) + 1
                max_retries = result.max_retries

                if max_retries > 0 and retry_count >= max_retries:
                    logger.error(f"{pipeline_name} pipeline for session {instance.id} exhausted {retry_count}/{max_retries} retries: {result.error}")
                    if on_max_retry_exhausted:
                        await on_max_retry_exhausted(instance, result, retry_count)
                    try:
                        await self._api.terminate_session(
                            session_id=instance.id,
                            terminated_by="lablet-controller",
                            reason=f"{pipeline_name} pipeline failed after {retry_count} attempts: {result.error}",
                        )
                    except Exception as e:
                        logger.error(f"Failed to terminate session {instance.id}: {e}")
                    return ReconciliationResult.failed(f"Max {pipeline_name} pipeline retries exhausted")

                self._pipeline_retry_counts[handler_key] = retry_count
                logger.warning(f"{pipeline_name} pipeline for session {instance.id} failed (attempt {retry_count}), will retry: {result.error}")

        # --- Get pipeline definition ---
        pipeline_def = await self._get_pipeline_def(instance, pipeline_name)
        if not pipeline_def:
            logger.error(f"No '{pipeline_name}' pipeline defined for session {instance.id} (definition_id={instance.definition_id})")
            try:
                await self._api.terminate_session(
                    session_id=instance.id,
                    terminated_by="lablet-controller",
                    reason=f"No '{pipeline_name}' pipeline defined in LabletDefinition",
                )
            except Exception as e:
                logger.error(f"Failed to terminate session {instance.id}: {e}")
            return ReconciliationResult.failed(f"No {pipeline_name} pipeline defined")

        # --- Start new handler ---
        context = await self._build_pipeline_context(instance)
        step_dispatcher = self._build_step_dispatcher()
        existing_progress = self._get_existing_progress(instance, pipeline_name)

        handler = LifecyclePhaseHandler(
            session_id=instance.id,
            pipeline_name=pipeline_name,
            pipeline_def=pipeline_def,
            context=context,
            executor=self._pipeline_executor,
            step_dispatcher=step_dispatcher,
            existing_progress=existing_progress,
            on_complete=self._make_pipeline_run_callback(instance, pipeline_name),
        )
        self._active_handlers[handler_key] = handler
        await handler.start()
        logger.info(f"Started {pipeline_name} pipeline handler for session {instance.id} (key={handler_key})")
        return ReconciliationResult.success(f"{pipeline_name} pipeline handler started")

    async def _cleanup_failed_instantiation(self, instance: LabletSessionReadModel, result: PipelineResult, retry_count: int) -> None:
        """Clean up lab resources after instantiation pipeline exhausts retry budget.

        Strategy differs based on lab origin:
        - Reused lab: stop + wipe only (preserve CML lab & LabRecord)
        - Freshly imported lab: stop + wipe + delete CML lab + mark LabRecord deleted
        """
        cleanup_lab_id = instance.cml_lab_id or self._resolved_lab_ids.get(instance.id)
        is_freshly_imported = instance.id in self._freshly_imported_sessions

        if cleanup_lab_id and instance.worker_ip:
            lab_origin = "freshly imported" if is_freshly_imported else "reused"
            logger.info(f"🧹 Cleaning up {lab_origin} lab {cleanup_lab_id} on worker {instance.worker_ip} before termination (session {instance.id})")
            # Step 1: Stop the lab (common to both paths)
            try:
                await self._cml_labs.stop_lab(
                    host=instance.worker_ip,
                    lab_id=cleanup_lab_id,
                    username=instance.worker_cml_username,
                    password=instance.worker_cml_password,
                )
            except Exception as stop_err:
                logger.warning(f"Failed to stop lab {cleanup_lab_id} during cleanup: {stop_err}")
            # Step 2: Wipe the lab (common to both paths)
            try:
                await self._cml_labs.wipe_lab(
                    host=instance.worker_ip,
                    lab_id=cleanup_lab_id,
                    username=instance.worker_cml_username,
                    password=instance.worker_cml_password,
                )
            except Exception as wipe_err:
                logger.warning(f"Failed to wipe lab {cleanup_lab_id} during cleanup: {wipe_err}")

            if is_freshly_imported:
                # Freshly imported lab: delete the CML lab from the worker
                # and mark the LabRecord as deleted (terminal state).
                try:
                    await self._cml_labs.delete_lab(
                        host=instance.worker_ip,
                        lab_id=cleanup_lab_id,
                        username=instance.worker_cml_username,
                        password=instance.worker_cml_password,
                    )
                    logger.info(f"🗑️ Deleted freshly imported lab {cleanup_lab_id} from worker {instance.worker_ip}")
                except Exception as del_err:
                    logger.warning(f"Failed to delete lab {cleanup_lab_id} during cleanup: {del_err}")
                await self._update_lab_record_status(
                    cml_lab_id=cleanup_lab_id,
                    worker_id=instance.worker_id,
                    new_status=LabRecordStatus.DELETED.value,
                )
            else:
                # Reused lab: keep the CML lab and LabRecord intact.
                # Update LabRecord status to WIPED so it can be reused again.
                await self._update_lab_record_status(
                    cml_lab_id=cleanup_lab_id,
                    worker_id=instance.worker_id,
                    new_status=LabRecordStatus.WIPED.value,
                )

        self._resolved_lab_ids.pop(instance.id, None)
        self._freshly_imported_sessions.discard(instance.id)

    async def _handle_instantiating(self, instance: LabletSessionReadModel) -> ReconciliationResult:
        """Handle INSTANTIATING session — fire-and-check with lab cleanup on failure."""
        return await self._handle_pipeline_phase(instance, "instantiate", on_max_retry_exhausted=self._cleanup_failed_instantiation)

    async def _provision_lds_session(self, instance: LabletSessionReadModel, cml_lab_id: str) -> ReconciliationResult:
        """Provision an LDS session for a running (STARTED) lab.

        After successful provisioning, creates a UserSession child entity via CPA,
        then calls mark_session_ready to atomically transition to READY.

        AD-P4-03: Device mapping uses CML node label as device_label,
        and node tags encode protocol:port pairs.

        Note: This method is kept for backward compatibility and is also called
        by ``_step_lds_provision()`` in the pipeline.

        Args:
            instance: The LabletSession with a running lab.
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
            self._freshly_imported_sessions.discard(instance.id)

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

        If the definition uses ``extends`` (ADR-038 pipeline templates),
        the template is resolved before returning.

        Args:
            instance: Session read model (carries definition_id).
            pipeline_name: Key into definition.pipelines (e.g. "instantiate").

        Returns:
            Fully-resolved pipeline dict (steps, max_retries, retry_backoff, …) or None.
        """
        definition = await self._get_definition(instance.definition_id)
        if not definition:
            logger.error(f"Definition not found for session {instance.id}: {instance.definition_id}")
            return None

        pipelines = getattr(definition, "pipelines", None) or {}
        pipeline_def = pipelines.get(pipeline_name)
        if not pipeline_def:
            logger.warning(f"No '{pipeline_name}' pipeline in definition {instance.definition_id}")
            return None

        # ADR-038: Resolve template references (extends/insert_after/overrides/remove)
        try:
            pipeline_def = self._template_resolver.resolve(pipeline_def)
        except Exception:
            logger.exception(
                "Failed to resolve pipeline template for '%s' in definition %s — using raw definition",
                pipeline_name,
                instance.definition_id,
            )
            # Fall through with the unresolved definition
        return pipeline_def

    def _make_pipeline_run_callback(
        self,
        instance: LabletSessionReadModel,
        pipeline_name: str,
    ) -> Callable[[PipelineResult], Any]:
        """Create an on_complete callback that records the pipeline run via CPA.

        Sprint F (ADR-034): After any lifecycle pipeline completes, we record
        the execution result on the LabRecord via the Control Plane API. The
        callback is fire-and-forget — errors are logged but do not affect
        pipeline outcome.

        Args:
            instance: The LabletSession being processed.
            pipeline_name: Name of the pipeline (e.g. "instantiate", "teardown").

        Returns:
            Async callable accepting PipelineResult.
        """
        lab_record_id = instance.lab_record_id
        session_id = instance.id

        async def _record_pipeline_run(result: PipelineResult) -> None:
            if not lab_record_id:
                logger.debug(
                    "No lab_record_id for session %s — skipping pipeline run recording",
                    session_id,
                )
                return
            try:
                started_at = None
                completed_at = None
                if result.duration_seconds and result.duration_seconds > 0:
                    completed_at_dt = datetime.now(timezone.utc)
                    started_at_dt = completed_at_dt - timedelta(seconds=result.duration_seconds)
                    started_at = started_at_dt.isoformat()
                    completed_at = completed_at_dt.isoformat()

                await self._api.append_pipeline_run(
                    lab_record_id=lab_record_id,
                    pipeline_name=pipeline_name,
                    status=result.status,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_seconds=result.duration_seconds,
                    steps_completed=result.steps_completed,
                    steps_failed=result.steps_failed,
                    steps_skipped=result.steps_skipped,
                    step_results=result.outputs if result.outputs else None,
                    error_message=result.error,
                    triggered_by="lablet-controller",
                    lablet_session_id=session_id,
                )
                logger.info(
                    "Recorded pipeline run: session=%s, pipeline=%s, status=%s, duration=%.1fs",
                    session_id,
                    pipeline_name,
                    result.status,
                    result.duration_seconds,
                )
            except Exception as e:
                logger.warning(
                    "Failed to record pipeline run for session %s pipeline %s: %s",
                    session_id,
                    pipeline_name,
                    e,
                )

        return _record_pipeline_run

    def _get_existing_progress(self, instance: LabletSessionReadModel, pipeline_name: str) -> dict[str, Any] | None:
        """Get existing pipeline progress for resumability (ADR-034 Sprint F).

        Args:
            instance: Session read model carrying progress dicts.
            pipeline_name: Pipeline key (e.g. "instantiate", "teardown").

        Returns:
            Progress dict for the executor, or None if no prior progress.
        """
        if instance.pipeline_progress:
            progress = instance.pipeline_progress.get(pipeline_name)
            if progress:
                return progress
        return None

    async def _build_pipeline_context(self, instance: LabletSessionReadModel) -> PipelineContext:
        """Build a PipelineContext from the session and reconciler services.

        The context is an immutable bag passed to every step handler
        through the executor.

        ADR-038 Task 1: Enriched with helper callables and shared tracking
        state so registry step handlers achieve full parity with the
        reconciler's original ``_step_*`` methods.

        Args:
            instance: Session read model being reconciled.

        Returns:
            Fully-populated PipelineContext.
        """
        definition = await self._get_definition(instance.definition_id)

        # Content sync request callable (wraps optional service)
        async def _request_content_sync(definition_id: str) -> None:
            if self._content_sync_service and hasattr(self._content_sync_service, "request_sync"):
                await self._content_sync_service.request_sync(definition_id)  # type: ignore[attr-defined]

        return PipelineContext(
            session=instance,
            definition=definition,
            worker_ip=instance.worker_ip or "",
            worker_cml_username=instance.worker_cml_username or "",
            worker_cml_password=instance.worker_cml_password or "",
            api=self._api,
            cml=self._cml_labs,
            lds=self._lds,
            # ADR-038 Task 1: Helper callables (bound methods from reconciler)
            resolve_lab_for_instance=self._resolve_lab_for_instance,
            find_lab_record_id=self._find_lab_record_id,
            register_lab_record=self._register_lab_record,
            update_lab_record_status=self._update_lab_record_status,
            build_device_access_list=self._build_device_access_list,
            record_lab_run_completed=self._record_lab_run_completed,
            request_content_sync=_request_content_sync,
            # ADR-038 Task 1: Shared mutable tracking state (by reference)
            resolved_lab_ids=self._resolved_lab_ids,
            freshly_imported_sessions=self._freshly_imported_sessions,
        )

    def _build_step_dispatcher(self) -> StepDispatcher:
        """Build a step dispatcher closure for the pipeline executor.

        ADR-038: Resolves handlers from the StepHandlerRegistry instead of
        using getattr(self, f"_step_{handler_name}"). Handlers are standalone
        async functions registered via the @step_handler decorator.

        Falls back to getattr(self, f"_step_{handler_name}") for any handlers
        not yet migrated to the registry (backward compatibility).

        The dispatcher adapts between the executor's dict-based protocol and
        the registry's StepResult-based protocol.
        """
        reconciler = self

        async def _dispatch(
            handler_name: str,
            session: LabletSessionReadModel,
            progress: dict[str, Any],
            context: PipelineContext | None = None,
            params: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            # ADR-038: Try registry first
            handler_fn = get_handler(handler_name)
            if handler_fn is not None:
                if context is None:
                    context = await reconciler._build_pipeline_context(session)
                step_result = await handler_fn(session, progress, context, params)
                # Convert StepResult to legacy dict format
                result_dict = step_result.to_dict()
                status = result_dict.get("status", "completed")
                if status == "failed":
                    raise RuntimeError(result_dict.get("error", f"Step {handler_name} failed"))
                return result_dict.get("result_data", {})

            # Fallback: legacy getattr-based dispatch (backward compat)
            method = getattr(reconciler, f"_step_{handler_name}", None)
            if method is None:
                raise RuntimeError(f"Unknown pipeline step handler: {handler_name} (not in registry or reconciler)")

            result = await method(session, progress)

            status = result.get("status", "completed")
            if status == "failed":
                raise RuntimeError(result.get("error", f"Step {handler_name} failed"))

            return result.get("result_data", {})

        return _dispatch

    # =========================================================================
    # STATUS HANDLERS
    # =========================================================================

    async def _handle_ready(self, instance: LabletSessionReadModel) -> ReconciliationResult:
        """Handle READY session - verify LDS session is provisioned.

        In READY state, the lab is STARTED (running) and LDS session is provisioned.
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

            if lab_state and lab_state != LabState.STARTED:
                logger.warning(f"Lab {instance.cml_lab_id} unexpectedly not STARTED in READY state (state={lab_state})")

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
                # Ensure timeslot_end is timezone-aware (assume UTC if naive)
                if timeslot_end.tzinfo is None:
                    timeslot_end = timeslot_end.replace(tzinfo=timezone.utc)

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

            if lab_state and lab_state != LabState.STARTED:
                logger.warning(f"Lab {instance.cml_lab_id} is not STARTED (state={lab_state})")
                # Could auto-restart or report error
                # For now, just log

            self._lab_sync_count += 1
            return ReconciliationResult.success()

        except Exception as e:
            logger.warning(f"Failed to sync lab state for session {instance.id}: {e}")
            return ReconciliationResult.success()  # Don't fail on sync issues

    async def _observe_and_report(self, instance: LabletSessionReadModel) -> None:
        """Observe live CML lab resources and report to CPA."""
        await _obs_h.observe_and_report(instance, self._resource_observer, self._api, self._settings)

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

    async def _handle_collecting(self, instance: LabletSessionReadModel) -> ReconciliationResult:
        """Handle COLLECTING session — fire-and-check for evidence collection pipeline."""
        return await self._handle_pipeline_phase(instance, "collect_evidence")

    async def _handle_grading(self, instance: LabletSessionReadModel) -> ReconciliationResult:
        """Handle GRADING session — fire-and-check for grading pipeline."""
        return await self._handle_pipeline_phase(instance, "compute_grading")

    async def _handle_stopping(self, instance: LabletSessionReadModel) -> ReconciliationResult:
        """Handle STOPPING session — fire-and-check for teardown pipeline."""
        return await self._handle_pipeline_phase(instance, "teardown")

    # NOTE: _handle_pending_cleanup removed — cleanup is now part of _handle_stopping.
    # The canonical state machine uses: STOPPING → ARCHIVED (no PENDING_CLEANUP/CLEANED_UP).

    # =========================================================================
    # LAB RESOLUTION (P9-4/5/8)
    # =========================================================================

    async def _resolve_lab_for_instance(self, instance: LabletSessionReadModel, topology_yaml: str | None = None) -> str | None:
        """Resolve a lab for an instance: reuse existing or import fresh."""
        return await _lab_res.resolve_lab_for_instance(instance, self._api, self._cml_labs, self._definition_cache, topology_yaml)

    async def _try_reuse_existing_lab(
        self,
        instance: LabletSessionReadModel,
        definition: LabletDefinitionReadModel,
    ) -> str | None:
        """Try to find and reuse an existing lab on the worker."""
        return await _lab_res.try_reuse_existing_lab(instance, definition, self._api, self._cml_labs)

    async def _import_fresh_lab(self, instance: LabletSessionReadModel, topology_yaml: str | None = None) -> str | None:
        """Import a fresh lab from topology YAML."""
        return await _lab_res.import_fresh_lab(instance, self._cml_labs, topology_yaml)

    # =========================================================================
    # RUN HISTORY (P9-7)
    # =========================================================================

    async def _record_lab_run_completed(self, instance: LabletSessionReadModel) -> None:
        """Record a completed lab run via CPA."""
        if await _run_hist.record_lab_run_completed(instance, self._api, self._lab_run_started_at):
            self._runs_recorded += 1

    # =========================================================================
    # LAB RECORD HELPERS
    # =========================================================================

    async def _find_lab_record_id(self, cml_lab_id: str, worker_id: str) -> str | None:
        """Find the LabRecord aggregate ID for a CML lab on a specific worker."""
        return await _lab_rec.find_lab_record_id(cml_lab_id, worker_id, self._api)

    async def _register_lab_record(self, cml_lab_id: str, instance: LabletSessionReadModel) -> str | None:
        """Register a CML lab as a LabRecord in CPA via discover_lab_records()."""
        return await _lab_rec.register_lab_record(cml_lab_id, instance, self._api, self._cml_labs)

    async def _update_lab_record_status(
        self,
        cml_lab_id: str,
        worker_id: str,
        new_status: str,
    ) -> None:
        """Update a lab record's status via CPA."""
        await _lab_rec.update_lab_record_status(cml_lab_id, worker_id, new_status, self._api)

    # =========================================================================
    # LDS HELPERS
    # =========================================================================

    @staticmethod
    def _build_device_access_list(nodes: list[NodeInfo], worker_ip: str) -> list[DeviceAccessInfo]:
        """Build LDS device access info from CML node topology."""
        return _lds_h.build_device_access_list(nodes, worker_ip)

    async def _get_definition(self, definition_id: str) -> LabletDefinitionReadModel | None:
        """Fetch lablet definition, using cache for repeated lookups."""
        return await _def_cache.get_definition(definition_id, self._api, self._definition_cache)

    async def _archive_lds_session(self, instance: LabletSessionReadModel) -> None:
        """Archive the LDS session for a session."""
        if await _lds_h.archive_lds_session(instance, self._lds):
            self._lds_sessions_archived += 1

    # =========================================================================
    # WORKER DETAILS RESOLUTION
    # =========================================================================

    async def _enrich_with_worker_details(self, session: LabletSessionReadModel) -> None:
        """Enrich a session read model with worker connection details."""
        await _worker_h.enrich_with_worker_details(session, self._api, self._settings, self._worker_cache)

    async def _get_cached_worker(self, worker_id: str) -> dict | None:
        """Get worker data from cache or CPA."""
        return await _worker_h.get_cached_worker(worker_id, self._api, self._worker_cache)

    def _extract_host_from_worker(self, worker: dict) -> str | None:
        """Extract host address from worker data."""
        return _worker_h.extract_host_from_worker(worker, self._settings)

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
