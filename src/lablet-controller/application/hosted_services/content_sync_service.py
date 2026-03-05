"""Content Synchronization Service for LabletDefinition content packages.

Lifecycle managed by LabletReconciler (leader-only, like LabRecordReconciler).

PRIMARY trigger (AD-CS-001): Watches etcd /definitions/ prefix for content_sync
PUT events. When the CPA emits a LabletDefinitionSyncRequestedDomainEvent, the
ContentSyncRequestedEtcdProjector writes to /lcm/definitions/{id}/content_sync,
and this service reacts immediately.

FALLBACK trigger (opt-in): Polls CPA internal API for definitions with
sync_status=sync_requested at a configurable interval. Disabled by default.

Pipeline:
  1. Resolve Mosaic base URL via Environment Resolver
  2. Get latest publish records from Mosaic
  3. Download content package (zip archive)
  4. Compute SHA-256 hash of the package
  5. Extract metadata (mosaic_meta.json, cml.yaml, grade.xml, devices.json)
  6. Upload package to RustFS bucket
  7. Notify upstream services (LDS)
  8. Report results to CPA

All mutations go through Control Plane API (ADR-001).
"""

import asyncio
import hashlib
import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import yaml
from integration.services.environment_resolver_client import EnvironmentResolverClient
from integration.services.lds_spi import LdsSpiClient
from integration.services.mosaic_client import MosaicClient
from integration.services.s3_client import S3Client
from lcm_core.integration.clients import ControlPlaneApiClient
from lcm_core.integration.clients.etcd_client import EtcdClient, EtcdEvent

from application.settings import Settings

if TYPE_CHECKING:
    from neuroglia.dependency_injection import ServiceCollection
    from neuroglia.dependency_injection.service_provider import ServiceProviderBase

logger = logging.getLogger(__name__)


class ContentSyncService:
    """Orchestrates content synchronization for LabletDefinitions.

    Pattern: etcd watch loop (same as LabRecordReconciler — AD-023).
    Leader-only: started by LabletReconciler._become_leader().

    Configuration:
        CONTENT_SYNC_ENABLED: Master switch (default: true)
        CONTENT_SYNC_WATCH_ENABLED: PRIMARY etcd watch trigger (default: true)
        CONTENT_SYNC_POLL_ENABLED: FALLBACK polling trigger (default: false)
        CONTENT_SYNC_POLL_INTERVAL: Poll interval in seconds (default: 300)

    Statistics:
        Sync requests received, successes, failures tracked for observability.
    """

    def __init__(
        self,
        api_client: ControlPlaneApiClient,
        etcd_client: EtcdClient,
        environment_resolver: EnvironmentResolverClient,
        mosaic_client: MosaicClient,
        s3_client: S3Client,
        lds_client: LdsSpiClient,
        settings: Settings,
    ) -> None:
        """Initialize the content sync service.

        Args:
            api_client: Client for Control Plane API.
            etcd_client: Client for etcd watch.
            environment_resolver: Client for resolving FQN to service URLs.
            mosaic_client: Client for downloading content from Mosaic.
            s3_client: Client for uploading packages to RustFS.
            lds_client: Client for notifying LDS of content updates.
            settings: Application settings.
        """
        self._api = api_client
        self._etcd = etcd_client
        self._env_resolver = environment_resolver
        self._mosaic = mosaic_client
        self._s3 = s3_client
        self._lds = lds_client
        self._settings = settings

        self._watch_task: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None
        self._running = False

        # Statistics
        self._syncs_received = 0
        self._syncs_succeeded = 0
        self._syncs_failed = 0
        self._last_sync_at: str | None = None
        self._last_error: str | None = None

    # =========================================================================
    # Lifecycle (managed by LabletReconciler leader election)
    # =========================================================================

    async def start_async(self) -> None:
        """Start the watch loop (and optional poll loop).

        Only starts if CONTENT_SYNC_ENABLED is true.
        """
        if not self._settings.content_sync_enabled:
            logger.info("⏭️ ContentSyncService is disabled (CONTENT_SYNC_ENABLED=false)")
            return

        if self._running:
            return
        self._running = True

        # PRIMARY: etcd watch loop (always enabled when content_sync_watch_enabled)
        if self._settings.content_sync_watch_enabled:
            self._watch_task = asyncio.create_task(self._watch_loop())
            logger.info("🚀 ContentSyncService: started etcd watch loop (primary trigger)")
        else:
            logger.warning("⚠️ ContentSyncService: etcd watch DISABLED by configuration")

        # FALLBACK: optional polling loop (opt-in, disabled by default)
        if self._settings.content_sync_poll_enabled:
            self._poll_task = asyncio.create_task(self._poll_loop())
            logger.info(f"🚀 ContentSyncService: started poll loop (interval={self._settings.content_sync_poll_interval}s)")
        else:
            logger.info("ℹ️ ContentSyncService: polling DISABLED (opt-in only)")

    async def stop_async(self) -> None:
        """Stop all loops."""
        self._running = False

        for task in [self._watch_task, self._poll_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._watch_task = None
        self._poll_task = None
        logger.info(f"✅ ContentSyncService stopped (received={self._syncs_received}, succeeded={self._syncs_succeeded}, failed={self._syncs_failed})")

    # =========================================================================
    # PRIMARY: etcd watch loop (AD-CS-001, follows LabRecordReconciler pattern)
    # =========================================================================

    def _get_watch_prefix(self) -> str:
        """Return the etcd key prefix to watch for content sync requests.

        Convention: {etcd_key_prefix}/definitions/
        e.g., /lcm/definitions/
        """
        base = getattr(self._settings, "etcd_key_prefix", "/lcm").rstrip("/")
        return f"{base}/definitions/"

    async def _watch_loop(self) -> None:
        """Watch etcd for definition content sync requests.

        Reconnects with exponential backoff on failure.
        Pattern: identical to LabRecordReconciler._watch_loop() (AD-023).
        """
        reconnect_delay = 1.0
        max_delay = 30.0

        while self._running:
            try:
                prefix = self._get_watch_prefix()
                logger.info(f"ContentSyncService: Watching etcd prefix: {prefix}")

                async for event in self._etcd.watch_prefix(prefix):
                    if not self._running:
                        break

                    await self._handle_watch_event(event)

                    # Reset delay on successful event processing
                    reconnect_delay = 1.0

            except asyncio.CancelledError:
                logger.info("ContentSyncService: Watch cancelled")
                break
            except Exception as e:
                if not self._running:
                    break
                logger.error(f"ContentSyncService: Watch error: {e}", exc_info=True)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_delay)

    async def _handle_watch_event(self, event: EtcdEvent) -> None:
        """Process a single watch event.

        Only handles PUT events (new sync requests). DELETE events are
        ignored (they indicate cleanup after sync completion).

        Args:
            event: etcd watch event.
        """
        # Only react to PUT events (new sync requests)
        if event.type != "PUT":
            return

        # Parse key: /lcm/definitions/{definition_id}/content_sync
        definition_id = self._extract_definition_id(event.key)
        if not definition_id:
            logger.warning(f"ContentSyncService: Could not parse definition_id from key: {event.key}")
            return

        # Parse the sync request payload
        try:
            payload = json.loads(event.value) if event.value else None
        except (json.JSONDecodeError, TypeError):
            logger.error(f"ContentSyncService: Invalid JSON in etcd value for {event.key}: {event.value}")
            return

        if not payload:
            return

        fqn = payload.get("form_qualified_name", "")

        logger.info(f"ContentSyncService: Received sync request via etcd watch: definition={definition_id}, fqn='{fqn}'")
        self._syncs_received += 1

        # Fetch full definition from CPA (need all fields for sync pipeline)
        try:
            defn = await self._api.get_lablet_definition(definition_id)
        except Exception as e:
            logger.error(f"ContentSyncService: Failed to fetch definition {definition_id}: {e}")
            self._syncs_failed += 1
            self._last_error = str(e)
            return

        if not defn:
            logger.error(f"ContentSyncService: Definition {definition_id} not found in CPA")
            self._syncs_failed += 1
            return

        # Execute the sync pipeline
        await self._sync_definition(defn)

    def _extract_definition_id(self, key: str) -> str | None:
        """Extract definition_id from etcd key.

        Key format: /lcm/definitions/{definition_id}/content_sync

        Args:
            key: The etcd key string.

        Returns:
            The definition_id, or None if parsing fails.
        """
        parts = key.rstrip("/").split("/")
        # Expected: ['', 'lcm', 'definitions', '{definition_id}', 'content_sync']
        if len(parts) >= 4 and parts[-1] == "content_sync":
            return parts[-2]
        return None

    # =========================================================================
    # FALLBACK: opt-in polling loop (consistency catch-up)
    # =========================================================================

    async def _poll_loop(self) -> None:
        """Polling loop — fetch definitions needing sync, process each.

        Opt-in fallback (CONTENT_SYNC_POLL_ENABLED=true). Catches definitions
        that may have been missed during etcd watch reconnection gaps.
        """
        while self._running:
            try:
                definitions = await self._api.get_definitions_needing_sync()
                if definitions:
                    logger.info(f"ContentSyncService poll: found {len(definitions)} definitions needing sync")
                    for defn in definitions:
                        if not self._running:
                            break
                        await self._sync_definition(defn)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"ContentSyncService poll error: {e}", exc_info=True)

            await asyncio.sleep(self._settings.content_sync_poll_interval)

    # =========================================================================
    # Sync pipeline (shared by watch + poll paths)
    # =========================================================================

    async def _sync_definition(self, defn: dict[str, Any]) -> None:
        """Execute the full sync pipeline for one definition.

        Steps:
          1. Resolve Mosaic base URL via Environment Resolver
          2. Get latest publish records from Mosaic
          3. Download content package (zip archive)
          4. Compute SHA-256 hash of the package
          5. Extract metadata from zip
          6. Upload package to RustFS bucket
          7. Notify upstream services (LDS)
          8. Report results to CPA

        Args:
            defn: Definition dict from CPA API.
        """
        definition_id = defn.get("id", "unknown")
        fqn = defn.get("form_qualified_name", "")
        bucket_name = defn.get("bucket_name", "")
        package_name = defn.get("user_session_package_name", "SVN.zip")

        logger.info(f"Syncing definition {definition_id}: FQN='{fqn}', bucket='{bucket_name}'")

        # Initialize per-service upstream sync status tracking
        upstream_status: dict[str, Any] = {}

        try:
            # Step 1: Resolve Mosaic base URL
            env_resolver_logs: list[str] = []
            try:
                env_resolver_logs.append(f"Resolving FQN '{fqn}' via Environment Resolver...")
                resolved = await self._env_resolver.resolve(fqn)
                mosaic_url = resolved.mosaic_base_url
                env_resolver_logs.append(f"Resolved to mosaic_base_url: {mosaic_url}")
                upstream_status["environment_resolver"] = {
                    "status": "success",
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                    "mosaic_base_url": mosaic_url,
                    "logs": env_resolver_logs,
                }
            except Exception as env_err:
                env_resolver_logs.append(f"ERROR: {env_err}")
                upstream_status["environment_resolver"] = {
                    "status": "failed",
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                    "error": str(env_err),
                    "logs": env_resolver_logs,
                }
                raise  # Fatal — cannot continue without Mosaic URL

            # Step 2: Get latest publish records
            records = await self._mosaic.get_latest_publish_records(mosaic_url, fqn)
            if not records:
                raise ValueError(f"No publish records found for FQN '{fqn}'")

            # Find the LDSv3 layout record (preferred) or first available
            target_record = next((rec for rec in records if rec.layout == "LDSv3"), records[0])
            logger.info(f"Using publish record: id={target_record.id}, form={target_record.form_name}, version={target_record.version}")

            # Build Mosaic source URL from publish record metadata
            mosaic_source_url = self._build_mosaic_source_url(target_record, mosaic_url)

            # Step 3: Download the package
            package_bytes = await self._mosaic.download_package(mosaic_url, target_record.id)

            # Step 4: Compute SHA-256 hash of the entire package
            content_package_hash = hashlib.sha256(package_bytes).hexdigest()

            # Step 5: Extract metadata from the zip
            metadata = self._extract_metadata(package_bytes)

            # Step 6: Upload to RustFS — track as object_storage service
            object_storage_logs: list[str] = []
            try:
                object_storage_logs.append(f"Ensuring bucket '{bucket_name}' exists...")
                await self._s3.ensure_bucket_exists(bucket_name)
                object_storage_logs.append(f"Bucket '{bucket_name}' ready.")

                object_storage_logs.append(f"Uploading '{package_name}' ({len(package_bytes)} bytes)...")
                await self._s3.upload_bytes(
                    bucket_name=bucket_name,
                    object_key=package_name,
                    data=package_bytes,
                    content_type="application/zip",
                )
                object_storage_logs.append(f"Upload complete: {package_name}")

                # Build console URL for UI link
                console_url = self._build_object_storage_console_url(bucket_name)

                upstream_status["object_storage"] = {
                    "status": "success",
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                    "bucket_name": bucket_name,
                    "object_key": package_name,
                    "size_bytes": len(package_bytes),
                    "content_hash": content_package_hash,
                    "console_url": console_url,
                    "logs": object_storage_logs,
                }
            except Exception as s3_err:
                object_storage_logs.append(f"ERROR: {s3_err}")
                upstream_status["object_storage"] = {
                    "status": "failed",
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                    "bucket_name": bucket_name,
                    "error": str(s3_err),
                    "logs": object_storage_logs,
                }
                raise  # Fatal — cannot continue without storage

            # Step 7: Notify upstream services (LDS, Grading Engine)
            service_statuses = await self._notify_upstream_services(defn, fqn)
            upstream_status.update(service_statuses)

            # Add mosaic source URL to upstream status for UI linking
            upstream_status["mosaic_source"] = {
                "status": "success",
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "source_url": mosaic_source_url,
                "instance_name": getattr(target_record, "instance_name", None) or metadata.get("upstream_instance_name"),
                "form_id": getattr(target_record, "form_id", None) or metadata.get("upstream_form_id"),
                "form_set_id": getattr(target_record, "form_set_id", None),
                "module_id": getattr(target_record, "module_id", None),
                "version": target_record.version,
                "form_name": target_record.form_name,
            }

            # Step 8: Report results to CPA
            sync_result: dict[str, Any] = {
                "sync_status": "success",
                "lab_yaml_hash": metadata.get("cml_yaml_hash", ""),
                "content_package_hash": content_package_hash,
                "upstream_version": metadata.get("upstream_version"),
                "upstream_date_published": metadata.get("upstream_date_published"),
                "upstream_instance_name": metadata.get("upstream_instance_name"),
                "upstream_form_id": metadata.get("upstream_form_id"),
                "grade_xml_path": metadata.get("grade_xml_path"),
                "cml_yaml_path": metadata.get("cml_yaml_path"),
                "cml_yaml_content": metadata.get("cml_yaml_content"),
                "devices_json": metadata.get("devices_json"),
                "port_template": metadata.get("port_template"),
                "upstream_sync_status": upstream_status,
            }

            await self._api.record_content_sync_result(definition_id, sync_result)

            self._syncs_succeeded += 1
            self._last_sync_at = datetime.now(timezone.utc).isoformat()
            logger.info(f"✅ Content sync SUCCESS for {definition_id} (hash={content_package_hash[:12]}...)")

        except Exception as e:
            self._syncs_failed += 1
            self._last_error = str(e)
            logger.error(f"❌ Content sync FAILED for {definition_id}: {e}", exc_info=True)

            # Report failure to CPA (include partial upstream_status for debugging)
            try:
                await self._api.record_content_sync_result(
                    definition_id,
                    {
                        "sync_status": "failed",
                        "error_message": str(e),
                        "lab_yaml_hash": defn.get("lab_yaml_hash", ""),
                        "upstream_sync_status": upstream_status if upstream_status else None,
                    },
                )
            except Exception as report_err:
                logger.error(f"Failed to report sync failure to CPA: {report_err}")

    # =========================================================================
    # URL construction helpers
    # =========================================================================

    def _build_object_storage_console_url(self, bucket_name: str) -> str:
        """Build a console URL for browsing a bucket in the object storage UI.

        Uses s3_console_url setting (defaults to RustFS/MinIO Console on port 9001).
        Format: {console_url}/rustfs/console/browser/{bucket_name}

        Args:
            bucket_name: The S3 bucket name.

        Returns:
            Full URL to the bucket browser in the storage console.
        """
        console_base = getattr(self._settings, "s3_console_url", "").rstrip("/")
        if not console_base:
            # Fallback: derive from s3_endpoint by changing port 9000 → 9001
            endpoint = self._settings.s3_endpoint.rstrip("/")
            console_base = endpoint.replace(":9000", ":9001")
        return f"{console_base}/rustfs/console/browser/{bucket_name}"

    def _build_mosaic_source_url(self, record: Any, mosaic_base_url: str) -> str:
        """Build a URL to the Mosaic authoring source for a publish record.

        Constructs: https://{instance}/app/module/{moduleId}/formset/{formSetId}/form/{formId}

        Args:
            record: A MosaicPublishRecord with module_id, form_set_id, form_id, instance_name.
            mosaic_base_url: Resolved Mosaic base URL (e.g., https://mosaic-test.certs.cloud).

        Returns:
            URL to the form in the Mosaic authoring UI, or empty string if IDs unavailable.
        """
        module_id = getattr(record, "module_id", None)
        form_set_id = getattr(record, "form_set_id", None)
        form_id = getattr(record, "form_id", None)

        if not all([module_id, form_set_id, form_id]):
            return ""

        # Use the Mosaic instance base URL (already includes scheme + host)
        base = mosaic_base_url.rstrip("/")
        return f"{base}/app/module/{module_id}/formset/{form_set_id}/form/{form_id}"

    # =========================================================================
    # Upstream service notification (AD-CS-004)
    # =========================================================================

    async def _notify_upstream_services(self, defn: dict[str, Any], fqn: str) -> dict[str, Any]:
        """Notify upstream services of content update.

        Currently notifies:
        - LDS: Trigger content refresh from MinIO
        - Grading Engine: (deferred — placeholder for extensibility)

        Args:
            defn: Definition dict from CPA API.
            fqn: Form qualified name.

        Returns:
            Per-service sync status dict.
        """
        upstream_status: dict[str, Any] = {}

        # LDS sync
        lds_logs: list[str] = []
        try:
            user_session_default_region = defn.get("user_session_default_region")
            lds_logs.append(f"Triggering LDS content sync for FQN '{fqn}'...")
            if user_session_default_region:
                lds_logs.append(f"Using region: {user_session_default_region}")
            lds_result = await self._lds.sync_content(fqn, region=user_session_default_region)
            lds_version = lds_result.get("Version", "")
            lds_logs.append(f"LDS sync completed — version: {lds_version}")
            upstream_status["lds"] = {
                "status": "success",
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "version": lds_version,
                "region": user_session_default_region,
                "logs": lds_logs,
            }
        except Exception as lds_err:
            lds_logs.append(f"ERROR: {lds_err}")
            logger.error(f"LDS sync failed for '{fqn}': {lds_err}")
            upstream_status["lds"] = {
                "status": "failed",
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "error": str(lds_err),
                "region": defn.get("user_session_default_region"),
                "logs": lds_logs,
            }

        # Grading Engine sync (deferred — AD-CS-004)
        upstream_status["grading_engine"] = {
            "status": "not_configured",
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "logs": ["Grading Engine sync is not yet implemented (deferred — AD-CS-004)."],
        }

        return upstream_status

    # =========================================================================
    # Metadata extraction
    # =========================================================================

    def _extract_metadata(self, package_bytes: bytes) -> dict[str, Any]:
        """Extract metadata from a downloaded content package (zip).

        Searches for:
        - mosaic_meta.json → DatePublished, Version, InstanceName, FormId
        - cml.yaml or cml.yml → full content + SHA-256 hash + port_template
        - grade.xml → relative path
        - devices.json → full content

        Args:
            package_bytes: Raw zip archive bytes.

        Returns:
            Dict with extracted metadata.
        """
        metadata: dict[str, Any] = {}

        with zipfile.ZipFile(io.BytesIO(package_bytes)) as zf:
            names = zf.namelist()

            # Find mosaic_meta.json (anywhere in the archive)
            meta_files = [n for n in names if n.endswith("mosaic_meta.json")]
            if meta_files:
                meta_content = zf.read(meta_files[0]).decode("utf-8")
                meta_data = json.loads(meta_content)
                metadata["upstream_version"] = meta_data.get("Version")
                metadata["upstream_date_published"] = meta_data.get("DatePublished")
                metadata["upstream_instance_name"] = meta_data.get("InstanceName")
                metadata["upstream_form_id"] = meta_data.get("FormId")

            # Find cml.yaml or cml.yml (anywhere in the archive)
            cml_files = [n for n in names if n.endswith(("cml.yaml", "cml.yml"))]
            if cml_files:
                cml_content = zf.read(cml_files[0]).decode("utf-8")
                metadata["cml_yaml_path"] = cml_files[0]
                metadata["cml_yaml_content"] = cml_content
                metadata["cml_yaml_hash"] = hashlib.sha256(cml_content.encode("utf-8")).hexdigest()

                # Extract port_template from CML topology nodes[].tags (ADR-029)
                metadata["port_template"] = self._extract_port_template(cml_content)

            # Find grade.xml (anywhere in the archive)
            grade_files = [n for n in names if n.endswith("grade.xml")]
            if grade_files:
                metadata["grade_xml_path"] = grade_files[0]

            # Find devices.json (anywhere in the archive)
            devices_files = [n for n in names if n.endswith("devices.json")]
            if devices_files:
                devices_content = zf.read(devices_files[0]).decode("utf-8")
                metadata["devices_json"] = devices_content

        logger.info(
            f"Extracted metadata: version={metadata.get('upstream_version')}, "
            f"cml={metadata.get('cml_yaml_path')}, grade={metadata.get('grade_xml_path')}, "
            f"devices={'yes' if metadata.get('devices_json') else 'no'}"
        )
        return metadata

    @staticmethod
    def _extract_port_template(cml_yaml_content: str) -> dict[str, Any] | None:
        """Extract port template from CML YAML topology nodes.

        Parses the CML YAML to find nodes with port-related tags and
        builds a port_template dict structure for CPA consumption.

        ADR-029: PortTemplate auto-extraction from CML nodes[].tags.

        Args:
            cml_yaml_content: Raw CML YAML content string.

        Returns:
            Port template dict, or None if no port info found.
        """
        try:
            parsed = yaml.safe_load(cml_yaml_content)
            if not isinstance(parsed, dict):
                return None

            nodes = parsed.get("nodes", [])
            if not isinstance(nodes, list):
                return None

            port_definitions: list[dict[str, Any]] = []
            for node in nodes:
                if not isinstance(node, dict):
                    continue

                node_label = node.get("label", "")
                tags = node.get("tags", [])
                if not isinstance(tags, list):
                    continue

                for tag in tags:
                    if not isinstance(tag, str):
                        continue
                    # Parse tags like "port:ssh:22", "port:telnet:23", "port:vnc:5900"
                    if tag.startswith("port:"):
                        parts = tag.split(":")
                        if len(parts) >= 3:
                            port_definitions.append(
                                {
                                    "device_label": node_label,
                                    "protocol": parts[1],
                                    "port": int(parts[2]) if parts[2].isdigit() else 0,
                                }
                            )

            if port_definitions:
                return {"port_definitions": port_definitions}
            return None

        except Exception as e:
            logger.warning(f"Failed to extract port_template from CML YAML: {e}")
            return None

    # =========================================================================
    # Observability
    # =========================================================================

    def get_stats(self) -> dict[str, Any]:
        """Get service stats for admin/metrics endpoints.

        Returns:
            Dictionary with service statistics.
        """
        return {
            "running": self._running,
            "watch_enabled": self._settings.content_sync_watch_enabled,
            "poll_enabled": self._settings.content_sync_poll_enabled,
            "syncs_received": self._syncs_received,
            "syncs_succeeded": self._syncs_succeeded,
            "syncs_failed": self._syncs_failed,
            "last_sync_at": self._last_sync_at,
            "last_error": self._last_error,
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

        Registers ContentSyncService as a concrete singleton only.
        The service is NOT registered as a HostedService because its lifecycle
        is managed by LabletReconciler — started in _become_leader() and
        stopped in _step_down(). This ensures only the elected leader runs
        the watch, preventing duplicate sync operations across replicas.

        Pattern: same as LabRecordReconciler.configure() (AD-023).

        Args:
            services: Neuroglia service collection.
        """

        def factory(sp: "ServiceProviderBase") -> "ContentSyncService":
            return cls(
                api_client=sp.get_required_service(ControlPlaneApiClient),
                etcd_client=sp.get_required_service(EtcdClient),
                environment_resolver=sp.get_required_service(EnvironmentResolverClient),
                mosaic_client=sp.get_required_service(MosaicClient),
                s3_client=sp.get_required_service(S3Client),
                lds_client=sp.get_required_service(LdsSpiClient),
                settings=sp.get_required_service(Settings),
            )

        # NOTE: implementation_type=cls ensures Neuroglia resolves the actual class,
        # not a string from inspect.signature().return_annotation.
        services.add_singleton(cls, implementation_type=cls, implementation_factory=factory)
        logger.info("✅ ContentSyncService registered (lifecycle managed by LabletReconciler)")
