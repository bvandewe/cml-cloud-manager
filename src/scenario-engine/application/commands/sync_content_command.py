"""SyncContentCommand — End-to-end content sync from BlobStorage for a PodDefinition.

Self-contained CQRS command: request class + handler in same file.

Phase 1 G-01 orchestration (AD-CSI-011/012/013):

    1. Validate input
    2. Load or create the PodDefinition aggregate
    3. Transition to SYNCHRONIZING
    4. Download package from S3 to a temp dir
    5. Compute SHA-256 content hash
    6. Detect pod type (manifest > topology heuristics)
    7. Extract PAv1 payload to a final scratch directory
    8. Validate manifest / lifecycle / scenarios with PAv1Validator
    9. Mark READY and persist (records PodDefinitionReadyDomainEvent)
   10. Supersede stale READY definitions sharing (name, pod_type) but with a
       different content_hash; emit ``pod_definition.ready.v1`` CloudEvent

Failures along steps 4-8 transition the aggregate to FAILED, persist it
(records ``PodDefinitionSyncFailedDomainEvent``) and emit
``pod_definition.sync_failed.v1``.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from domain.entities.pod_definition import PodDefinition
from domain.repositories.pod_definition_repository import PodDefinitionRepository
from integration.services.cloud_event_client import CloudEventCallbackService
from lcm_core.domain.enums import PodDefinitionStatus, PodType
from lcm_core.infrastructure.content_store.content_extractor import ContentExtractor, ExtractedContent
from lcm_core.infrastructure.content_store.pav1_errors import PAv1ValidationError, PodTypeIndeterminate
from lcm_core.infrastructure.content_store.pav1_validator import PAv1Validator
from lcm_core.infrastructure.content_store.pod_type_detector import PodTypeDetector
from lcm_core.infrastructure.content_store.s3_content_client import S3ContentClient, S3ContentClientError
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

from application.settings import Settings

logger = logging.getLogger(__name__)


@dataclass
class SyncContentCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to trigger content synchronization from BlobStorage.

    Attributes:
        definition_id: The PodDefinition identifier to sync (looked up if set).
        name: Content package name (required when creating a new aggregate).
        version: Content version.
        source_uri: BlobStorage URI for the content package (``s3://...``).
        force: Force re-sync even if content is already READY.
        callback_url: Optional per-request CloudEvent sink URL (AD-CSI-013).
        pod_type_override: Optional explicit pod type bypassing detection.
    """

    definition_id: str = ""
    name: str = ""
    version: str = "v1"
    source_uri: str = ""
    force: bool = False
    callback_url: str | None = None
    pod_type_override: str | None = None


class SyncContentCommandHandler(CommandHandler[SyncContentCommand, OperationResult[dict[str, Any]]]):
    """End-to-end orchestrator for content sync — see module docstring."""

    def __init__(
        self,
        pod_definition_repository: PodDefinitionRepository,
        s3_content_client: S3ContentClient,
        content_extractor: ContentExtractor,
        pav1_validator: PAv1Validator,
        pod_type_detector: PodTypeDetector,
        cloud_event_service: CloudEventCallbackService,
        settings: Settings,
    ) -> None:
        self._repository = pod_definition_repository
        self._s3 = s3_content_client
        self._extractor = content_extractor
        self._validator = pav1_validator
        self._detector = pod_type_detector
        self._events = cloud_event_service
        self._settings = settings

    async def handle_async(self, request: SyncContentCommand) -> OperationResult[dict[str, Any]]:
        # ------------------------------------------------------------------
        # Step 1 — Input validation
        # ------------------------------------------------------------------
        if not request.source_uri:
            return self.bad_request("source_uri is required")

        # ------------------------------------------------------------------
        # Step 2 — Load or create the aggregate
        # ------------------------------------------------------------------
        pod_def: PodDefinition | None = None
        if request.definition_id:
            pod_def = await self._repository.get_by_id_async(request.definition_id)

        if pod_def is None:
            if not request.name:
                return self.bad_request("name is required when creating a new PodDefinition")
            # When pod_type is unknown at create time we default to CML_ON_AWS
            # and let detection (Step 6) write the authoritative value into
            # the READY event payload. AD-CSI-002.
            initial_pod_type = self._resolve_initial_pod_type(request.pod_type_override)
            pod_def = PodDefinition.create(
                name=request.name,
                version=request.version,
                pod_type=initial_pod_type,
                source_uri=request.source_uri,
                definition_id=request.definition_id or None,
            )
            await self._repository.add_async(pod_def)
        else:
            if pod_def.state.status == PodDefinitionStatus.READY and not request.force:
                return self.conflict("PodDefinition is already READY. Use force=true to re-sync.")

        # ------------------------------------------------------------------
        # Step 3 — Transition to SYNCHRONIZING
        # ------------------------------------------------------------------
        pod_def.start_sync()
        await self._repository.update_async(pod_def)
        logger.info(
            "PodDefinition %s SYNCHRONIZING from %s (force=%s)",
            pod_def.id(),
            request.source_uri,
            request.force,
        )

        # ------------------------------------------------------------------
        # Steps 4-9 — Download, hash, detect, extract, validate, mark READY
        # ------------------------------------------------------------------
        try:
            with tempfile.TemporaryDirectory(prefix=f"sync-{pod_def.id()}-") as tmpdir_str:
                tmpdir = Path(tmpdir_str)
                package_path = tmpdir / "package.zip"
                extract_dir = tmpdir / "extracted"
                extract_dir.mkdir(parents=True, exist_ok=True)

                # Step 4 — Download
                await self._s3.download(request.source_uri, package_path)
                logger.info(
                    "PodDefinition %s downloaded package (%d bytes)",
                    pod_def.id(),
                    package_path.stat().st_size,
                )

                # Step 5 — SHA-256
                content_hash = await _sha256_of_file(package_path)
                logger.info("PodDefinition %s content_hash=%s", pod_def.id(), content_hash)

                # Step 6 — Detect pod type
                resolved_pod_type = self._resolve_pod_type(package_path, request.pod_type_override)
                logger.info("PodDefinition %s resolved pod_type=%s", pod_def.id(), resolved_pod_type.value)

                # Step 7 — Extract
                extracted: ExtractedContent = await self._extractor.extract(package_path, extract_dir)
                logger.info("PodDefinition %s extracted to %s", pod_def.id(), extract_dir)

                # Step 8 — Validate PAv1 documents
                self._validate_pav1(extracted)
                logger.info("PodDefinition %s PAv1 validation OK", pod_def.id())

                # Step 9 — Mark READY
                pod_def.mark_ready(
                    local_path=str(extract_dir),
                    manifest=extracted.manifest,
                    content_hash=content_hash,
                    topology=extracted.topology,
                    devices=extracted.devices,
                    lifecycle_phases=extracted.lifecycle_phases,
                    scenarios=extracted.scenarios,
                    grading_rules=extracted.grading_rules,
                    reports=extracted.reports,
                    restore_rules=extracted.restore_rules,
                )
                await self._repository.update_async(pod_def)
                logger.info("PodDefinition %s READY", pod_def.id())
        except Exception as exc:  # noqa: BLE001 — funnel ALL pipeline errors → FAILED
            return await self._handle_failure(pod_def, exc, request.callback_url)

        # ------------------------------------------------------------------
        # Step 10 — Supersede stale + emit ready CloudEvent
        # ------------------------------------------------------------------
        superseded_ids = await self._repository.expire_superseded_definitions_async(
            name=pod_def.state.name,
            pod_type=resolved_pod_type,
            current_definition_id=pod_def.id(),
            current_content_hash=content_hash,
        )
        if superseded_ids:
            logger.info(
                "PodDefinition %s superseded %d stale definitions",
                pod_def.id(),
                len(superseded_ids),
            )

        await self._events.emit_content_synced(
            pod_definition_id=pod_def.id(),
            name=pod_def.state.name,
            version=pod_def.state.version,
            pod_type=resolved_pod_type.value,
            content_hash=content_hash,
            callback_url=request.callback_url,
        )

        return self.accepted(
            {
                "definition_id": pod_def.id(),
                "status": "ready",
                "content_hash": content_hash,
                "pod_type": resolved_pod_type.value,
                "superseded_ids": superseded_ids,
            }
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_initial_pod_type(self, override: str | None) -> PodType:
        if not override:
            return PodType.CML_ON_AWS
        try:
            return PodType(override)
        except ValueError:
            logger.warning("Invalid pod_type_override=%s, defaulting to CML_ON_AWS", override)
            return PodType.CML_ON_AWS

    def _resolve_pod_type(self, package_path: Path, override: str | None) -> PodType:
        if override:
            try:
                return PodType(override)
            except ValueError as exc:
                raise PAv1ValidationError("manifest.yaml", [f"invalid pod_type_override='{override}'"]) from exc
        with ZipFile(package_path) as zf:
            pod_type, signals = self._detector.detect(zf)
        logger.debug("PodTypeDetector signals: %s", signals)
        return pod_type

    def _validate_pav1(self, extracted: ExtractedContent) -> None:
        self._validator.validate_manifest(extracted.manifest)
        if extracted.lifecycle_phases is not None:
            self._validator.validate_lifecycle({"phases": extracted.lifecycle_phases})
        if extracted.scenarios:
            for scenario in extracted.scenarios.values():
                self._validator.validate_scenario(scenario)

    async def _handle_failure(
        self,
        pod_def: PodDefinition,
        exc: Exception,
        callback_url: str | None,
    ) -> OperationResult[dict[str, Any]]:
        reason, detail = _classify_failure(exc)
        logger.error(
            "PodDefinition %s sync failed: %s\n%s",
            pod_def.id(),
            reason,
            traceback.format_exc(),
        )
        pod_def.mark_failed(reason=reason, error_detail=detail)
        try:
            await self._repository.update_async(pod_def)
        except Exception:  # noqa: BLE001 — persistence failure must not mask the original
            logger.exception("Failed to persist FAILED state for PodDefinition %s", pod_def.id())

        try:
            await self._events.emit_sync_failed(
                pod_definition_id=pod_def.id(),
                reason=reason,
                error_detail=detail,
                callback_url=callback_url,
            )
        except Exception:  # noqa: BLE001 — CloudEvent delivery is fire-and-forget
            logger.exception("Failed to emit sync_failed CloudEvent for PodDefinition %s", pod_def.id())

        return self.internal_server_error(reason)


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


async def _sha256_of_file(path: Path) -> str:
    """Compute the SHA-256 of ``path`` (sync I/O wrapped to keep handler async)."""

    def _hash() -> str:
        h = hashlib.sha256()
        with path.open("rb") as fp:
            for chunk in iter(lambda: fp.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    return await asyncio.to_thread(_hash)


def _classify_failure(exc: Exception) -> tuple[str, str | None]:
    """Map exception type to (reason, error_detail) for FAILED diagnostics."""
    if isinstance(exc, S3ContentClientError):
        return f"S3 download failed: {exc}", None
    if isinstance(exc, PodTypeIndeterminate):
        return "Pod type could not be determined", "; ".join(exc.signals)
    if isinstance(exc, PAv1ValidationError):
        return f"PAv1 validation failed at {exc.path}", "; ".join(exc.errors)
    return f"Unhandled sync error: {type(exc).__name__}: {exc}", None
