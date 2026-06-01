"""Lab Discovery Hosted Service.

Background service that periodically discovers labs on running CML workers
and syncs lab records to Control Plane API using typed LabRecordStatus lifecycle.

Discovery Pattern (§7 of LabRecord Architecture):
    SCAN (CML Labs API per worker)
    → DIFF (compare CML labs against existing LabRecords)
    → CREATE (new labs → DISCOVERED status)
    → UPDATE (existing labs → status + topology sync with SHA-256 checksums)
    → ORPHAN (DB labs not found on CML → mark ORPHANED, don't auto-delete)

All persistence goes through Control Plane API (ADR-001).
Polling is opt-in — enabled via LABS_REFRESH_ENABLED.
"""

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from lcm_core.domain.enums import LabRecordStatus
from lcm_core.integration.clients import ControlPlaneApiClient
from lcm_core.integration.clients.etcd_client import EtcdClient, EtcdEvent

from application.settings import Settings
from integration.services.cml_labs_spi import CmlLabsSpiClient, LabInfo, LabState

if TYPE_CHECKING:
    from neuroglia.dependency_injection import ServiceCollection
    from neuroglia.dependency_injection.service_provider import ServiceProviderBase

logger = logging.getLogger(__name__)


class LabDiscoveryService:
    """Background service for discovering and syncing lab records from CML workers.

    Uses CPA discover_lab_records() with typed LabRecordStatus, SHA-256 topology
    checksums, and orphan detection.

    Polling is optional — enabled via labs_refresh_enabled (default: true).
    The service runs at configurable intervals (labs_refresh_interval, default: 30 min).

    Configuration:
        LABS_REFRESH_ENABLED: Enable/disable polling (default: true)
        LABS_REFRESH_INTERVAL: Seconds between refreshes (default: 1800)
        USE_PRIVATE_IP_FOR_MONITORING: Use private IP for CML API calls

    All persistence goes through Control Plane API (ADR-001).
    """

    def __init__(
        self,
        api_client: ControlPlaneApiClient,
        cml_labs_client: CmlLabsSpiClient,
        etcd_client: EtcdClient,
        settings: Settings,
    ) -> None:
        """Initialize the lab discovery service.

        Args:
            api_client: Client for Control Plane API.
            cml_labs_client: CML Labs SPI client.
            etcd_client: Client for etcd watch (ADR-041 Phase 2).
            settings: Application settings.
        """
        self._api = api_client
        self._cml_labs = cml_labs_client
        self._etcd = etcd_client
        self._settings = settings
        self._running = False
        self._task: asyncio.Task | None = None
        self._watch_task: asyncio.Task | None = None

        # Statistics
        self._discovery_runs = 0
        self._total_labs_synced = 0
        self._total_labs_discovered = 0
        self._total_labs_updated = 0
        self._total_labs_orphaned = 0
        self._total_revisions_created = 0
        self._total_ports_registered = 0
        self._total_tags_synced = 0
        self._last_run_at: datetime | None = None
        self._last_error: str | None = None

        # Topology checksum cache: (worker_id, lab_id) → SHA-256 hex digest
        self._topology_checksums: dict[tuple[str, str], str] = {}

    # =========================================================================
    # HostedService lifecycle
    # =========================================================================

    async def start_async(self) -> None:
        """Start the lab discovery service."""
        self._running = True

        # Always start the etcd watch for targeted discovery (ADR-041 Phase 2)
        self._watch_task = asyncio.create_task(self._discovery_watch_loop())
        logger.info("🚀 Started LabDiscoveryService etcd watch (watching /workers/*/discover_labs)")

        if not self._settings.labs_refresh_enabled:
            logger.info("⏭️ Periodic lab discovery is disabled (LABS_REFRESH_ENABLED=false)")
            return

        logger.info(f"🚀 Starting LabDiscoveryService periodic scan (interval={self._settings.labs_refresh_interval}s)")
        self._task = asyncio.create_task(self._discovery_loop())

    async def stop_async(self) -> None:
        """Stop the lab discovery service."""
        logger.info("🛑 Stopping LabDiscoveryService...")
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._watch_task:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass

        logger.info(f"✅ LabDiscoveryService stopped (runs={self._discovery_runs}, discovered={self._total_labs_discovered}, synced={self._total_labs_synced})")

    # =========================================================================
    # Discovery loop
    # =========================================================================

    async def _discovery_loop(self) -> None:
        """Main discovery loop — runs at configured intervals."""
        # Initial delay to let the system stabilize
        await asyncio.sleep(15)

        while self._running:
            try:
                await self._run_discovery()
            except Exception as e:
                self._last_error = str(e)
                logger.error(f"❌ Lab discovery run failed: {e}", exc_info=True)

            # Wait for next interval
            await asyncio.sleep(self._settings.labs_refresh_interval)

    # =========================================================================
    # Targeted discovery via etcd watch (ADR-041 Phase 2)
    # =========================================================================

    async def _discovery_watch_loop(self) -> None:
        """Watch etcd for targeted lab discovery triggers.

        Watches /workers/*/discover_labs prefix. When worker-controller detects
        new lab_ids via WebSocket, CPA writes an etcd key here. This service
        reacts by executing _discover_worker_labs for the specific worker, then
        deletes the etcd key via CPA.

        Reconnects with exponential backoff on watch failures.
        """
        reconnect_delay = 1.0
        max_delay = 30.0

        # Initial delay to let the system stabilize
        await asyncio.sleep(10)

        while self._running:
            try:
                prefix = self._get_discover_labs_prefix()
                logger.info(f"LabDiscoveryService: Watching etcd prefix: {prefix}")

                async for event in self._etcd.watch_prefix(prefix):
                    if not self._running:
                        break

                    await self._handle_discover_labs_event(event)

                    # Reset delay on successful event processing
                    reconnect_delay = 1.0

            except asyncio.CancelledError:
                logger.info("LabDiscoveryService: Discovery watch cancelled")
                break
            except Exception as e:
                if not self._running:
                    break
                logger.error(f"LabDiscoveryService: Discovery watch error: {e}", exc_info=True)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_delay)

    def _get_discover_labs_prefix(self) -> str:
        """Get the etcd key prefix for targeted lab discovery watches."""
        base = getattr(self._settings, "etcd_key_prefix", "/lcm").rstrip("/")
        return f"{base}/workers/"

    async def _handle_discover_labs_event(self, event: EtcdEvent) -> None:
        """Process a targeted lab discovery event from etcd.

        Only handles PUT events on discover_labs keys.

        Args:
            event: etcd watch event.
        """
        # Only react to PUT events (new triggers)
        if event.type != "PUT":
            return

        # Only process discover_labs keys (ignore other /workers/ keys)
        if not event.key.endswith("/discover_labs"):
            return

        # Extract worker_id from key: /lcm/workers/{worker_id}/discover_labs
        worker_id = self._extract_worker_id_from_discover_key(event.key)
        if not worker_id:
            logger.warning(f"LabDiscoveryService: Could not parse worker_id from key: {event.key}")
            return

        # Parse payload
        try:
            payload = json.loads(event.value) if event.value else None
        except (json.JSONDecodeError, TypeError):
            logger.error(f"LabDiscoveryService: Invalid JSON in discover_labs value for {event.key}")
            return

        lab_ids = payload.get("lab_ids", []) if payload else []
        source = payload.get("source", "unknown") if payload else "unknown"

        logger.info(f"🎯 Targeted lab discovery triggered for worker {worker_id}: " f"lab_ids={lab_ids}, source={source}")

        # Execute targeted discovery for this worker
        try:
            # Fetch worker details from CPA
            worker = await self._api.get_worker(worker_id)
            if not worker:
                logger.warning(f"LabDiscoveryService: Worker {worker_id} not found in CPA, skipping targeted discovery")
                return

            result = await self._discover_worker_labs(worker)
            logger.info(f"✅ Targeted discovery for worker {worker_id} complete: " f"synced={result.synced}, discovered={result.discovered}, " f"updated={result.updated}")

            # Update totals
            self._total_labs_synced += result.synced
            self._total_labs_discovered += result.discovered
            self._total_labs_updated += result.updated
            self._total_labs_orphaned += result.orphaned

        except Exception as e:
            logger.error(f"LabDiscoveryService: Targeted discovery failed for worker {worker_id}: {e}", exc_info=True)
        finally:
            # Always delete the etcd key (cleanup) — idempotent
            try:
                await self._api.complete_lab_discovery(worker_id)
            except Exception as e:
                logger.debug(f"LabDiscoveryService: Failed to clear discover_labs key for {worker_id}: {e}")

    @staticmethod
    def _extract_worker_id_from_discover_key(key: str) -> str | None:
        """Extract worker_id from etcd key path.

        Key format: /lcm/workers/{worker_id}/discover_labs
        """
        match = re.search(r"/workers/([^/]+)/discover_labs$", key)
        return match.group(1) if match else None

    async def _run_discovery(self) -> None:
        """Execute a single discovery run across all running workers."""
        self._discovery_runs += 1
        self._last_run_at = datetime.now(timezone.utc)

        logger.info(f"🔄 Starting lab discovery run #{self._discovery_runs}")

        # Get running workers from Control Plane API
        try:
            workers = await self._api.get_workers(status="RUNNING")
        except Exception as e:
            logger.error(f"Failed to fetch running workers: {e}")
            return

        if not workers:
            logger.debug("No running workers for lab discovery")
            return

        run_stats = DiscoveryRunStats()

        # Process workers with concurrency limit
        semaphore = asyncio.Semaphore(5)

        async def process_worker(worker: dict) -> DiscoveryWorkerResult:
            async with semaphore:
                return await self._discover_worker_labs(worker)

        results = await asyncio.gather(
            *[process_worker(w) for w in workers],
            return_exceptions=True,
        )

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Lab discovery failed for worker {workers[i].get('id')}: {result}")
                run_stats.errors += 1
            elif isinstance(result, DiscoveryWorkerResult):
                run_stats.accumulate(result)

        # Update totals
        self._total_labs_synced += run_stats.synced
        self._total_labs_discovered += run_stats.discovered
        self._total_labs_updated += run_stats.updated
        self._total_labs_orphaned += run_stats.orphaned
        self._total_revisions_created += run_stats.revisions_created

        logger.info(
            f"✅ Lab discovery run #{self._discovery_runs} complete: "
            f"synced={run_stats.synced}, discovered={run_stats.discovered}, "
            f"updated={run_stats.updated}, orphaned={run_stats.orphaned}, "
            f"revisions={run_stats.revisions_created}, errors={run_stats.errors}"
        )

    # =========================================================================
    # Per-worker discovery
    # =========================================================================

    async def _discover_worker_labs(self, worker: dict) -> "DiscoveryWorkerResult":
        """Discover labs for a single worker.

        Scans CML for labs and posts to CPA discover_lab_records() which
        handles typed status, topology checksums, and orphan detection.

        Args:
            worker: Worker data from Control Plane API.

        Returns:
            DiscoveryWorkerResult with counts.
        """
        worker_id = worker.get("id", "")
        host = self._resolve_worker_host(worker)

        if not host:
            logger.warning(f"⏭️ Skipping worker {worker_id} — no endpoint available")
            return DiscoveryWorkerResult()

        logger.debug(f"Discovering labs for worker {worker_id} at {host}")

        try:
            # Fetch labs from CML
            labs = await self._cml_labs.list_labs(host)
            result = await self._discover(worker_id, host, labs)

            # Phase 5 (ADR-031): Register ports and sync tags for BOOTED labs.
            # After discovery sync, ensure BOOTED labs have ports allocated on
            # their LabRecord (via CPA) and CML node tags match allocated ports.
            port_result = await self._register_ports_and_sync_tags(worker_id, host, labs)
            self._total_ports_registered += port_result.ports_registered
            self._total_tags_synced += port_result.tags_synced

            return result

        except Exception as e:
            error_detail = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            logger.error(f"Failed to discover labs for worker {worker_id} at {host}: {error_detail}")
            return DiscoveryWorkerResult()

    async def _discover(
        self,
        worker_id: str,
        host: str,
        labs: list[LabInfo],
    ) -> "DiscoveryWorkerResult":
        """Discover labs: typed statuses, topology checksums, orphan detection.

        1. Build lab data with topology checksums for change detection.
        2. POST to CPA discover_lab_records() which handles:
           - Creating new LabRecords (status=DISCOVERED)
           - Updating existing LabRecords (status mapped from CML state)
           - Detecting topology changes (SHA-256 checksum → new LabRevision)
           - Marking orphaned labs (DB labs not in CML scan → ORPHANED)
           - Emitting SSE events

        Args:
            worker_id: Worker aggregate ID.
            host: CML worker host/IP (for topology download if needed).
            labs: List of LabInfo from CML scan.

        Returns:
            DiscoveryWorkerResult with counts.
        """
        # Build lab data with topology checksums
        lab_data = []
        for lab in labs:
            # Map CML state to LabRecordStatus
            status = self._map_cml_state_to_status(lab.state.value if hasattr(lab.state, "value") else str(lab.state))

            entry: dict[str, Any] = {
                "id": lab.id,
                "title": lab.title,
                "description": lab.description,
                "notes": lab.notes,
                "state": lab.state.value if hasattr(lab.state, "value") else str(lab.state),
                "status": status,
                "owner": lab.owner,
                "owner_username": lab.owner_username,
                "node_count": lab.node_count,
                "link_count": lab.link_count,
                "created_at": lab.created_at.isoformat() if lab.created_at else None,
                "modified_at": lab.modified_at.isoformat() if lab.modified_at else None,
                "worker_ip": host,
            }

            # Compute topology checksum for change detection
            checksum = self._compute_topology_checksum(lab)
            entry["topology_checksum"] = checksum

            # Detect topology change (compare with cached checksum)
            cache_key = (worker_id, lab.id)
            if cache_key in self._topology_checksums:
                if self._topology_checksums[cache_key] != checksum:
                    entry["topology_changed"] = True
                    logger.info(f"Topology change detected for lab {lab.id} on worker {worker_id}")

            # Update cache
            self._topology_checksums[cache_key] = checksum

            # Collect node and link summaries (hybrid topology approach)
            try:
                nodes = await self._cml_labs.get_lab_nodes(host, lab.id)
                entry["nodes"] = [
                    {
                        "id": n.id,
                        "label": n.label,
                        "node_definition": n.node_definition,
                        "state": n.state,
                        "tags": n.tags or [],
                        "cpu_limit": n.cpu_limit,
                        "ram": n.ram,
                        "x": n.x,
                        "y": n.y,
                    }
                    for n in nodes
                ]
            except Exception as e:
                logger.warning(f"Failed to collect nodes for lab {lab.id}: {e}")
                entry["nodes"] = []

            try:
                links = await self._cml_labs.get_lab_links(host, lab.id)
                entry["links"] = [
                    {
                        "id": lnk.id,
                        "label": lnk.label,
                        "state": lnk.state,
                        "node_a": lnk.node_a,
                        "node_b": lnk.node_b,
                        "interface_a": lnk.interface_a,
                        "interface_b": lnk.interface_b,
                    }
                    for lnk in links
                ]
            except Exception as e:
                logger.warning(f"Failed to collect links for lab {lab.id}: {e}")
                entry["links"] = []

            lab_data.append(entry)

        # Post to CPA discover endpoint
        result = await self._api.discover_lab_records(
            worker_id=worker_id,
            labs=lab_data,
            source="lab-discovery-service",
        )

        worker_result = DiscoveryWorkerResult(
            synced=result.get("synced", len(lab_data)),
            discovered=result.get("discovered", 0),
            updated=result.get("updated", 0),
            orphaned=result.get("orphaned", 0),
            revisions_created=result.get("revisions_created", 0),
            errors=len(result.get("errors", [])) if isinstance(result.get("errors"), list) else result.get("errors", 0),
        )

        if worker_result.discovered > 0 or worker_result.updated > 0 or worker_result.orphaned > 0:
            logger.info(
                f"🔍 Worker {worker_id}: discovered={worker_result.discovered}, updated={worker_result.updated}, orphaned={worker_result.orphaned}, revisions={worker_result.revisions_created}"
            )

        return worker_result

    # =========================================================================
    # Port registration & tag sync (ADR-031 Phase 5)
    # =========================================================================

    async def _register_ports_and_sync_tags(
        self,
        worker_id: str,
        host: str,
        labs: list[LabInfo],
    ) -> "PortRegistrationResult":
        """Register ports and sync tags for BOOTED/STARTED labs.

        ADR-031 Phase 5 / AD-PORT-001:
        After discovery sync, ensure BOOTED labs backed by a LabletDefinition
        have their ports allocated on the LabRecord (via CPA
        ``AllocateLabRecordPortsCommand``) and CML node tags are in sync.

        Port allocation is idempotent — already-allocated labs return their
        existing port mapping without re-allocating.

        Tag sync is non-fatal (AD-TAGS-001) — errors are logged as warnings.

        Args:
            worker_id: Worker aggregate ID.
            host: CML worker host/IP.
            labs: Labs from the CML scan.

        Returns:
            PortRegistrationResult with counts.
        """
        booted_labs = [lab for lab in labs if lab.state in (LabState.BOOTED, LabState.STARTED)]

        if not booted_labs:
            return PortRegistrationResult()

        result = PortRegistrationResult()

        # Fetch lab records for this worker to resolve lab_record_ids
        try:
            lab_records = await self._api.get_lab_records_for_worker(worker_id=worker_id)
        except Exception as e:
            logger.warning(f"Failed to fetch lab records for port registration on worker {worker_id}: {e}")
            return result

        records_by_lab_id: dict[str, dict[str, Any]] = {lr.get("lab_id", ""): lr for lr in lab_records}

        for lab in booted_labs:
            lr = records_by_lab_id.get(lab.id)
            if not lr:
                continue

            lab_record_id = lr.get("id")
            if not lab_record_id:
                continue

            # Skip labs without a definition (unmanaged/ad-hoc labs)
            if not lr.get("based_on_definition_id"):
                continue

            # 1. Allocate ports (idempotent — returns existing if already allocated)
            try:
                alloc_result = await self._api.allocate_lab_record_ports(
                    lab_record_id=lab_record_id,
                    worker_id=worker_id,
                )
            except Exception as e:
                logger.warning(f"Port allocation failed for lab_record {lab_record_id}: {e}")
                result.errors += 1
                continue

            allocated_ports = alloc_result.get("allocated_ports", {})
            if not allocated_ports:
                # No ports needed (no port template, empty template, or skipped)
                continue

            result.ports_registered += 1

            # 2. Sync CML node tags if missing (AD-TAGS-001: non-fatal)
            try:
                tags_synced = await self._sync_tags_if_missing(
                    host=host,
                    lab_id=lab.id,
                    allocated_ports=allocated_ports,
                )
                result.tags_synced += tags_synced
            except Exception as e:
                logger.warning(f"Tag sync failed for lab {lab.id} on worker {worker_id}: {e}")

        if result.ports_registered > 0 or result.tags_synced > 0:
            logger.info(f"🔌 Worker {worker_id}: ports_registered={result.ports_registered}, tags_synced={result.tags_synced}")

        return result

    async def _sync_tags_if_missing(
        self,
        host: str,
        lab_id: str,
        allocated_ports: dict[str, int],
    ) -> int:
        """Sync CML node tags for nodes with allocated ports but missing tags.

        Checks each node's existing tags against expected port tags derived
        from ``allocated_ports``.  Only patches nodes whose tags are missing
        or incomplete.

        Port name convention: ``{safe_node_label}_{protocol}`` (from
        ``PortTemplate.from_cml_nodes``).  Tag format: ``protocol:port``.

        AD-TAGS-001: Individual node patch failures are non-fatal — logged
        as warnings and skipped.

        Args:
            host: CML worker host/IP.
            lab_id: CML lab ID.
            allocated_ports: Port name → port number mapping.

        Returns:
            Number of nodes whose tags were synced.
        """
        # Build expected tags per node from allocated_ports
        expected_node_tags: dict[str, list[str]] = {}
        for port_name, port_number in allocated_ports.items():
            parts = port_name.rsplit("_", 1)
            if len(parts) != 2:
                continue
            node_label, protocol = parts
            tag = f"{protocol}:{port_number}"
            expected_node_tags.setdefault(node_label, []).append(tag)

        if not expected_node_tags:
            return 0

        # Get current nodes from CML
        nodes = await self._cml_labs.get_lab_nodes(host, lab_id)

        synced_count = 0
        for node in nodes:
            safe_label = re.sub(r"[^a-zA-Z0-9_-]", "_", node.label)

            if safe_label not in expected_node_tags:
                continue

            expected_tags = set(expected_node_tags[safe_label])
            current_tags = set(node.tags or [])

            # All expected port tags already present — nothing to sync
            if expected_tags.issubset(current_tags):
                continue

            # Merge: keep existing tags, add missing port tags
            merged_tags = sorted(current_tags | expected_tags)

            try:
                await self._cml_labs.patch_node_tags(
                    host=host,
                    lab_id=lab_id,
                    node_id=node.id,
                    tags=merged_tags,
                )
                synced_count += 1
                logger.debug(f"Synced tags for node {node.label} in lab {lab_id}: {merged_tags}")
            except Exception as e:
                # AD-TAGS-001: Non-fatal
                logger.warning(f"Failed to sync tags for node {node.label} in lab {lab_id}: {e}")

        return synced_count

    # =========================================================================
    # Topology change detection
    # =========================================================================

    @staticmethod
    def _compute_topology_checksum(lab: LabInfo) -> str:
        """Compute SHA-256 checksum of a lab's topology-identifying fields.

        Uses a canonical JSON representation (sorted keys) to avoid
        false positives from field ordering changes.

        Args:
            lab: Lab information from CML.

        Returns:
            Hex-encoded SHA-256 digest.
        """
        # Canonical representation: stable fields that define the topology
        canonical = {
            "title": lab.title or "",
            "node_count": lab.node_count,
            "link_count": lab.link_count,
            "owner": lab.owner or "",
        }

        # Sort keys for deterministic ordering
        canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    @staticmethod
    def _map_cml_state_to_status(cml_state: str) -> str:
        """Map CML native state string to LabRecordStatus value.

        Uses the same mapping as LabRecordStatus CML_STATE_TO_LAB_RECORD_STATUS
        but returns lowercase string for API transport.

        Args:
            cml_state: CML native state (e.g., "DEFINED_ON_CORE", "BOOTED").

        Returns:
            LabRecordStatus value string (lowercase).
        """
        mapping = {
            "DEFINED_ON_CORE": LabRecordStatus.DEFINED.value,
            "STARTED": LabRecordStatus.BOOTED.value,
            "BOOTED": LabRecordStatus.BOOTED.value,
            "STOPPED": LabRecordStatus.STOPPED.value,
            "QUEUED": LabRecordStatus.QUEUED.value,
        }
        return mapping.get(cml_state, LabRecordStatus.DISCOVERED.value)

    # =========================================================================
    # Helpers
    # =========================================================================

    def _resolve_worker_host(self, worker: dict) -> str | None:
        """Resolve the host address to use for CML API calls.

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
    # Observability
    # =========================================================================

    def get_stats(self) -> dict:
        """Get discovery service statistics.

        Returns:
            Dictionary with service statistics.
        """
        return {
            "enabled": self._settings.labs_refresh_enabled,
            "running": self._running,
            "discovery_runs": self._discovery_runs,
            "total_labs_synced": self._total_labs_synced,
            "total_labs_discovered": self._total_labs_discovered,
            "total_labs_updated": self._total_labs_updated,
            "total_labs_orphaned": self._total_labs_orphaned,
            "total_revisions_created": self._total_revisions_created,
            "total_ports_registered": self._total_ports_registered,
            "total_tags_synced": self._total_tags_synced,
            "last_run_at": self._last_run_at.isoformat() if self._last_run_at else None,
            "last_error": self._last_error,
            "interval_seconds": self._settings.labs_refresh_interval,
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

        Registers LabDiscoveryService as a concrete singleton only.
        The service is NOT registered as a HostedService because its lifecycle
        is managed by LabletReconciler — started in _become_leader() and
        stopped in _step_down(). This ensures only the elected leader runs
        discovery, preventing duplicate CML API calls across replicas.

        Args:
            services: Neuroglia service collection.
        """

        def factory(sp: "ServiceProviderBase") -> LabDiscoveryService:
            return cls(
                api_client=sp.get_required_service(ControlPlaneApiClient),
                cml_labs_client=sp.get_required_service(CmlLabsSpiClient),
                etcd_client=sp.get_required_service(EtcdClient),
                settings=sp.get_required_service(Settings),
            )

        # NOTE: implementation_type=cls ensures Neuroglia resolves the actual class,
        # not a string from inspect.signature().return_annotation.
        services.add_singleton(cls, implementation_type=cls, implementation_factory=factory)
        logger.info("✅ LabDiscoveryService registered (lifecycle managed by LabletReconciler)")


# =========================================================================
# Data classes for result tracking
# =========================================================================


class DiscoveryWorkerResult:
    """Result counts from discovering labs on a single worker."""

    __slots__ = ("synced", "discovered", "updated", "orphaned", "revisions_created", "errors")

    def __init__(
        self,
        synced: int = 0,
        discovered: int = 0,
        updated: int = 0,
        orphaned: int = 0,
        revisions_created: int = 0,
        errors: int = 0,
    ) -> None:
        self.synced = synced
        self.discovered = discovered
        self.updated = updated
        self.orphaned = orphaned
        self.revisions_created = revisions_created
        self.errors = errors


class DiscoveryRunStats:
    """Aggregate statistics for a full discovery run across all workers."""

    __slots__ = ("synced", "discovered", "updated", "orphaned", "revisions_created", "errors")

    def __init__(self) -> None:
        self.synced = 0
        self.discovered = 0
        self.updated = 0
        self.orphaned = 0
        self.revisions_created = 0
        self.errors = 0

    def accumulate(self, result: DiscoveryWorkerResult) -> None:
        """Add worker result counts to the run totals."""
        self.synced += result.synced
        self.discovered += result.discovered
        self.updated += result.updated
        self.orphaned += result.orphaned
        self.revisions_created += result.revisions_created
        self.errors += result.errors


class PortRegistrationResult:
    """Result of port registration and tag sync for a single worker (Phase 5)."""

    __slots__ = ("ports_registered", "tags_synced", "errors")

    def __init__(
        self,
        ports_registered: int = 0,
        tags_synced: int = 0,
        errors: int = 0,
    ) -> None:
        self.ports_registered = ports_registered
        self.tags_synced = tags_synced
        self.errors = errors
