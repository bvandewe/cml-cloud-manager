"""Lab Record Reconciler - Reactive watch-based lab action execution.

AD-023: Watches etcd `/lab_records/` prefix for pending actions projected by
control-plane-api. When a lab action is requested (start/stop/wipe/delete),
the CPA projects the pending action to etcd, and this service reacts immediately
by executing the corresponding CML API call and reporting the result back.

Flow:
    1. User clicks "Start Lab" in UI → CPA ControlLabCommand
    2. CPA sets pending_action in MongoDB and emits LabActionRequestedDomainEvent
    3. EtcdProjector writes /lcm/lab_records/{id}/pending_action to etcd
    4. This service watches the prefix and reacts:
       a. Parse the pending action (action, lab_id, worker_id)
       b. Resolve worker host via CPA API
       c. Execute CML API call (start_lab, stop_lab, wipe_lab, delete_lab)
       d. Report success via complete_lab_action() or failure via fail_lab_action()
    5. CPA clears pending_action → EtcdProjector deletes etcd key

Lifecycle:
    Managed by LabletReconciler leader election — only the elected leader
    runs the watch to avoid duplicate CML API calls across replicas.
    Pattern follows LabDiscoveryService (singleton, start/stop by leader).

All persistence goes through Control Plane API (ADR-001).
"""

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from integration.services.cml_labs_spi import CmlLabsSpiClient, LabState
from lcm_core.integration.clients import ControlPlaneApiClient
from lcm_core.integration.clients.etcd_client import EtcdClient, EtcdEvent

from application.settings import Settings

if TYPE_CHECKING:
    from neuroglia.dependency_injection import ServiceCollection
    from neuroglia.dependency_injection.service_provider import ServiceProviderBase

logger = logging.getLogger(__name__)

# Supported lab actions (maps to CML SPI methods)
SUPPORTED_ACTIONS = {"start", "stop", "wipe", "delete"}
DELETE_STOP_STATES = {LabState.STARTED, LabState.BOOTED, LabState.QUEUED}
DELETE_STOPPED_STATES = {LabState.STOPPED, LabState.DEFINED_ON_CORE}


class LabRecordReconciler:
    """Reactive watch-based reconciler for lab pending actions (AD-023).

    Watches etcd key prefix `/lab_records/` for PUT events containing
    pending action payloads. Executes the corresponding CML API action
    on the target worker and reports the result to Control Plane API.

    Configuration:
        LAB_RECORD_RECONCILE_ENABLED: Enable/disable (default: true)
        USE_PRIVATE_IP_FOR_MONITORING: Use private IP for CML API calls

    Statistics:
        Actions executed, successes, failures tracked for observability.
    """

    def __init__(
        self,
        api_client: ControlPlaneApiClient,
        etcd_client: EtcdClient,
        cml_labs_client: CmlLabsSpiClient,
        settings: Settings,
    ) -> None:
        """Initialize the lab record reconciler.

        Args:
            api_client: Client for Control Plane API.
            etcd_client: Client for etcd watch.
            cml_labs_client: CML Labs SPI client for lab actions.
            settings: Application settings.
        """
        self._api = api_client
        self._etcd = etcd_client
        self._cml_labs = cml_labs_client
        self._settings = settings
        self._running = False
        self._task: asyncio.Task[Any] | None = None

        # Worker host cache: worker_id → host address
        # Avoids repeated CPA lookups for the same worker within a session
        self._worker_host_cache: dict[str, str] = {}

        # Statistics
        self._actions_received = 0
        self._actions_succeeded = 0
        self._actions_failed = 0
        self._actions_skipped = 0
        self._last_action_at: str | None = None
        self._last_error: str | None = None

    # =========================================================================
    # Lifecycle (managed by LabletReconciler leader election)
    # =========================================================================

    async def start_async(self) -> None:
        """Start the lab record reconciler watch loop."""
        if not self._settings.lab_record_reconcile_enabled:
            logger.info("⏭️ Lab record reconciler is disabled (LAB_RECORD_RECONCILE_ENABLED=false)")
            return

        logger.info("🚀 Starting LabRecordReconciler (watching /lab_records/ prefix)")

        self._running = True
        self._worker_host_cache.clear()
        self._task = asyncio.create_task(self._watch_loop())

    async def stop_async(self) -> None:
        """Stop the lab record reconciler."""
        logger.info("🛑 Stopping LabRecordReconciler...")
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._worker_host_cache.clear()
        logger.info(f"✅ LabRecordReconciler stopped (received={self._actions_received}, succeeded={self._actions_succeeded}, failed={self._actions_failed}, skipped={self._actions_skipped})")

    # =========================================================================
    # Watch loop
    # =========================================================================

    async def _watch_loop(self) -> None:
        """Main watch loop — watches etcd for lab record pending action changes.

        Reconnects automatically on watch failures with exponential backoff.
        """
        reconnect_delay = 1.0
        max_delay = 30.0

        while self._running:
            try:
                prefix = self._get_watch_prefix()
                logger.info(f"LabRecordReconciler: Watching etcd prefix: {prefix}")

                async for event in self._etcd.watch_prefix(prefix):
                    if not self._running:
                        break

                    await self._handle_watch_event(event)

                    # Reset delay on successful event processing
                    reconnect_delay = 1.0

            except asyncio.CancelledError:
                logger.info("LabRecordReconciler: Watch cancelled")
                break
            except Exception as e:
                if not self._running:
                    break
                logger.error(f"LabRecordReconciler: Watch error: {e}", exc_info=True)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_delay)

    def _get_watch_prefix(self) -> str:
        """Get the full etcd key prefix to watch.

        Returns:
            Full prefix including the /lcm base (e.g., /lcm/lab_records/).
        """
        base = getattr(self._settings, "etcd_key_prefix", "/lcm").rstrip("/")
        return f"{base}/lab_records/"

    # =========================================================================
    # Event handling
    # =========================================================================

    async def _handle_watch_event(self, event: EtcdEvent) -> None:
        """Process a single watch event.

        Only handles PUT events (new pending actions). DELETE events are
        ignored (they indicate cleanup after action completion).

        Args:
            event: etcd watch event.
        """
        # Only react to PUT events (new pending actions)
        if event.type != "PUT":
            return

        # Parse key: /lcm/lab_records/{lab_record_id}/pending_action
        lab_record_id = self._extract_lab_record_id(event.key)
        if not lab_record_id:
            logger.warning(f"LabRecordReconciler: Could not parse lab_record_id from key: {event.key}")
            return

        # Parse the pending action payload
        try:
            payload = json.loads(event.value) if event.value else None
        except (json.JSONDecodeError, TypeError):
            logger.error(f"LabRecordReconciler: Invalid JSON in etcd value for {event.key}: {event.value}")
            return

        if not payload:
            return

        action = payload.get("action")
        lab_id = payload.get("lab_id")
        worker_id = payload.get("worker_id")

        if not all([action, lab_id, worker_id]):
            logger.error(f"LabRecordReconciler: Incomplete pending action for {lab_record_id}: {payload}")
            return

        if action not in SUPPORTED_ACTIONS:
            logger.warning(f"LabRecordReconciler: Unsupported action '{action}' for {lab_record_id}")
            self._actions_skipped += 1
            return

        self._actions_received += 1
        logger.info(f"LabRecordReconciler: Received pending action: {action} for lab_record={lab_record_id} (lab={lab_id}, worker={worker_id})")

        # Execute the action
        await self._execute_action(lab_record_id, action, lab_id, worker_id)

    def _extract_lab_record_id(self, key: str) -> str | None:
        """Extract lab_record_id from etcd key.

        Key format: /lcm/lab_records/{lab_record_id}/pending_action
        After stripping prefix: /lab_records/{lab_record_id}/pending_action

        Args:
            key: Full etcd key.

        Returns:
            Lab record ID, or None if key format is unexpected.
        """
        prefix = getattr(self._settings, "etcd_key_prefix", "/lcm").rstrip("/")
        if key.startswith(prefix):
            key = key[len(prefix) :]

        # Expected: /lab_records/{id}/pending_action
        parts = key.strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "lab_records" and parts[2] == "pending_action":
            return parts[1]

        return None

    # =========================================================================
    # Action execution
    # =========================================================================

    async def _execute_action(
        self,
        lab_record_id: str,
        action: str,
        lab_id: str,
        worker_id: str,
    ) -> None:
        """Execute a lab action via CML API and report result to CPA.

        Steps:
            1. Resolve worker host (CPA API + cache)
            2. Call CML Labs SPI (start/stop/wipe/delete)
            3. Report success or failure to CPA

        Args:
            lab_record_id: LabRecord aggregate ID.
            action: Action to execute (start, stop, wipe, delete).
            lab_id: CML lab ID on the worker.
            worker_id: CML worker ID hosting the lab.
        """
        host: str | None = None
        try:
            # Step 1: Resolve worker host
            host = await self._resolve_worker_host(worker_id)
            if not host:
                error_msg = f"Could not resolve host for worker {worker_id}"
                logger.error(f"LabRecordReconciler: {error_msg}")
                await self._report_failure(lab_record_id, error_msg)
                return

            # Step 2: Execute CML API call
            logger.info(f"LabRecordReconciler: Executing {action} on lab={lab_id} (worker={worker_id}, host={host})")
            await self._execute_cml_action(
                host=host,
                lab_record_id=lab_record_id,
                action=action,
                lab_id=lab_id,
                worker_id=worker_id,
            )

            # Step 3: Report success
            await self._report_success(lab_record_id, action)

        except Exception:
            refreshed_host = await self._resolve_worker_host(worker_id, force_refresh=True)
            if refreshed_host and refreshed_host != host:
                logger.warning(
                    "LabRecordReconciler: %s failed on cached host %s for worker=%s, retrying with refreshed host %s",
                    action,
                    host,
                    worker_id,
                    refreshed_host,
                )
                try:
                    await self._execute_cml_action(
                        host=refreshed_host,
                        lab_record_id=lab_record_id,
                        action=action,
                        lab_id=lab_id,
                        worker_id=worker_id,
                    )
                    await self._report_success(lab_record_id, action)
                    return
                except Exception as retry_error:
                    e = retry_error
                    host = refreshed_host

            error_msg = f"{action} failed for lab={lab_id} on worker={worker_id} (host={host or 'unresolved'}): {self._format_exception(e)}"
            logger.error(f"LabRecordReconciler: {error_msg}", exc_info=True)
            await self._report_failure(lab_record_id, error_msg)

    async def _execute_cml_action(
        self,
        host: str,
        lab_record_id: str,
        action: str,
        lab_id: str,
        worker_id: str,
    ) -> None:
        """Execute a CML action, expanding delete into stop-wipe-delete."""
        if action == "delete":
            await self._execute_delete_flow(
                host=host,
                lab_record_id=lab_record_id,
                lab_id=lab_id,
                worker_id=worker_id,
            )
            return

        if action == "start":
            await self._cml_labs.start_lab(host=host, lab_id=lab_id)
        elif action == "stop":
            await self._cml_labs.stop_lab(host=host, lab_id=lab_id)
        elif action == "wipe":
            await self._stop_before_wipe(host=host, lab_id=lab_id, lab_record_id=lab_record_id)
            await self._cml_labs.wipe_lab(host=host, lab_id=lab_id)

    async def _stop_before_wipe(self, host: str, lab_id: str, lab_record_id: str) -> None:
        """Stop the lab if it is running before wiping (CML rejects wipe on booted labs)."""
        state = await self._cml_labs.get_lab_state(host=host, lab_id=lab_id)
        if state in DELETE_STOP_STATES:
            logger.info("LabRecordReconciler: Lab %s is %s; stopping before wipe", lab_id, state.value)
            await self._cml_labs.stop_lab(host=host, lab_id=lab_id)
            await self._wait_for_lab_state(
                host=host,
                lab_id=lab_id,
                desired_states=DELETE_STOPPED_STATES,
                timeout_seconds=self._settings.lab_action_timeout_seconds,
                poll_interval_seconds=self._settings.lab_action_poll_interval_seconds,
            )
            await self._report_intermediate_status(
                lab_record_id=lab_record_id,
                new_status="stopped",
                cml_state=state.value,
            )

    async def _execute_delete_flow(
        self,
        host: str,
        lab_record_id: str,
        lab_id: str,
        worker_id: str,
    ) -> None:
        """Execute delete as a stop → wipe → delete sequence."""
        lab = await self._cml_labs.get_lab(host=host, lab_id=lab_id)
        if lab is None:
            logger.info(
                "LabRecordReconciler: Lab %s already absent on worker=%s; completing delete for lab_record=%s",
                lab_id,
                worker_id,
                lab_record_id,
            )
            return

        current_state = lab.state

        if current_state in DELETE_STOP_STATES:
            await self._cml_labs.stop_lab(host=host, lab_id=lab_id)
            current_state = await self._wait_for_lab_state(
                host=host,
                lab_id=lab_id,
                desired_states=DELETE_STOPPED_STATES,
                timeout_seconds=self._settings.lab_action_timeout_seconds,
                poll_interval_seconds=self._settings.lab_action_poll_interval_seconds,
            )
            await self._report_intermediate_status(
                lab_record_id=lab_record_id,
                new_status="stopped",
                cml_state=current_state.value,
            )

        await self._cml_labs.wipe_lab(host=host, lab_id=lab_id)
        await self._report_intermediate_status(
            lab_record_id=lab_record_id,
            new_status="wiped",
            cml_state=LabState.DEFINED_ON_CORE.value,
        )

        await self._cml_labs.delete_lab(host=host, lab_id=lab_id)
        await self._wait_for_lab_absence(
            host=host,
            lab_id=lab_id,
            timeout_seconds=self._settings.lab_action_timeout_seconds,
            poll_interval_seconds=self._settings.lab_action_poll_interval_seconds,
        )

    async def _wait_for_lab_state(
        self,
        host: str,
        lab_id: str,
        desired_states: set[LabState],
        timeout_seconds: int,
        poll_interval_seconds: int,
    ) -> LabState:
        """Poll until the lab reaches one of the desired states."""
        deadline = asyncio.get_running_loop().time() + timeout_seconds

        while True:
            state = await self._cml_labs.get_lab_state(host=host, lab_id=lab_id)
            if state in desired_states:
                return state

            if asyncio.get_running_loop().time() >= deadline:
                desired_values = ", ".join(sorted(state.value for state in desired_states))
                raise TimeoutError(f"Timed out waiting for lab {lab_id} to reach one of [{desired_values}]")

            await asyncio.sleep(poll_interval_seconds)

    async def _wait_for_lab_absence(
        self,
        host: str,
        lab_id: str,
        timeout_seconds: int,
        poll_interval_seconds: int,
    ) -> None:
        """Poll until the lab no longer exists in CML."""
        deadline = asyncio.get_running_loop().time() + timeout_seconds

        while True:
            lab = await self._cml_labs.get_lab(host=host, lab_id=lab_id)
            if lab is None:
                return

            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"Timed out waiting for lab {lab_id} to be deleted")

            await asyncio.sleep(poll_interval_seconds)

    async def _report_intermediate_status(
        self,
        lab_record_id: str,
        new_status: str,
        cml_state: str,
    ) -> None:
        """Report an intermediate delete-step status back to CPA."""
        try:
            await self._api.update_lab_record_status(
                lab_record_id=lab_record_id,
                new_status=new_status,
                cml_state=cml_state,
            )
        except Exception as e:
            logger.warning(
                "LabRecordReconciler: Failed to report intermediate status %s for %s: %s",
                new_status,
                lab_record_id,
                self._format_exception(e),
            )

    def _format_exception(self, error: Exception) -> str:
        """Format exception types consistently for controller logs and CPA failures."""
        message = str(error).strip()
        if message:
            return f"{type(error).__name__}: {message}"
        return type(error).__name__

    async def _resolve_worker_host(self, worker_id: str, force_refresh: bool = False) -> str | None:
        """Resolve the host address for a CML worker.

        Uses a local cache to avoid repeated CPA lookups for the same worker.
        Falls back to CPA API to get worker details.

        Args:
            worker_id: CML worker ID.

        Returns:
            Host address string, or None if unavailable.
        """
        # Check cache first
        if not force_refresh and worker_id in self._worker_host_cache:
            return self._worker_host_cache[worker_id]

        if force_refresh:
            self._worker_host_cache.pop(worker_id, None)

        try:
            worker = await self._api.get_worker(worker_id)
            if not worker:
                logger.warning(f"LabRecordReconciler: Worker {worker_id} not found via CPA")
                return None

            host = self._extract_host_from_worker(worker)
            if host:
                self._worker_host_cache[worker_id] = host
            return host

        except Exception as e:
            logger.error(f"LabRecordReconciler: Failed to resolve worker {worker_id}: {e}")
            return None

    def _extract_host_from_worker(self, worker: dict[str, Any]) -> str | None:
        """Extract host address from worker data.

        Follows the same logic as LabDiscoveryService._resolve_worker_host().

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
    # CPA Reporting
    # =========================================================================

    async def _report_success(self, lab_record_id: str, action: str) -> None:
        """Report successful action completion to Control Plane API.

        Args:
            lab_record_id: LabRecord aggregate ID.
            action: Action that was completed.
        """
        try:
            await self._api.complete_lab_action(
                lab_record_id=lab_record_id,
                action=action,
            )
            self._actions_succeeded += 1
            self._last_action_at = action
            logger.info(f"LabRecordReconciler: ✅ {action} completed for lab_record={lab_record_id}")
        except Exception as e:
            logger.error(f"LabRecordReconciler: Failed to report success for {lab_record_id}: {e}", exc_info=True)
            # Action succeeded on CML but CPA reporting failed — log but don't re-try here.
            # The pending_action will remain in etcd and trigger a retry on reconnect.

    async def _report_failure(self, lab_record_id: str, error_message: str) -> None:
        """Report action failure to Control Plane API.

        Args:
            lab_record_id: LabRecord aggregate ID.
            error_message: Error message describing the failure.
        """
        try:
            await self._api.fail_lab_action(
                lab_record_id=lab_record_id,
                error_message=error_message,
                transition_to_error=False,  # Don't auto-transition; let CPA decide
            )
            self._actions_failed += 1
            self._last_error = error_message
            logger.warning(f"LabRecordReconciler: ❌ Action failed for lab_record={lab_record_id}: {error_message}")
        except Exception as e:
            logger.error(
                f"LabRecordReconciler: Failed to report failure for {lab_record_id}: {e}",
                exc_info=True,
            )

    # =========================================================================
    # Observability
    # =========================================================================

    def get_stats(self) -> dict[str, Any]:
        """Get reconciler statistics.

        Returns:
            Dictionary with service statistics.
        """
        return {
            "running": self._running,
            "actions_received": self._actions_received,
            "actions_succeeded": self._actions_succeeded,
            "actions_failed": self._actions_failed,
            "actions_skipped": self._actions_skipped,
            "last_action": self._last_action_at,
            "last_error": self._last_error,
            "cached_workers": len(self._worker_host_cache),
        }

    # =========================================================================
    # DI Configuration
    # =========================================================================

    @classmethod
    def configure(
        cls,
        services: "ServiceCollection",
    ) -> None:
        """Configure DI registration.

        Registers LabRecordReconciler as a concrete singleton only.
        The service is NOT registered as a HostedService because its lifecycle
        is managed by LabletReconciler — started in _become_leader() and
        stopped in _step_down(). This ensures only the elected leader runs
        the watch, preventing duplicate CML API calls across replicas.

        Args:
            services: Neuroglia service collection.
        """

        def factory(sp: "ServiceProviderBase") -> LabRecordReconciler:
            return cls(
                api_client=sp.get_required_service(ControlPlaneApiClient),
                etcd_client=sp.get_required_service(EtcdClient),
                cml_labs_client=sp.get_required_service(CmlLabsSpiClient),
                settings=sp.get_required_service(Settings),
            )

        # NOTE: implementation_type=cls ensures Neuroglia resolves the actual class,
        # not a string from inspect.signature().return_annotation.
        services.add_singleton(cls, implementation_type=cls, implementation_factory=factory)
        logger.info("✅ LabRecordReconciler registered (lifecycle managed by LabletReconciler)")
