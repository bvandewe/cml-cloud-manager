"""Lab resolution helpers — resolve / reuse / import.

ADR-038 Task 3: Extracted from LabletReconciler._resolve_lab_for_instance(),
_try_reuse_existing_lab(), and _import_fresh_lab().
"""

import logging
from dataclasses import dataclass

from integration.services.cml_labs_spi import CmlLabsSpiClient
from lcm_core.domain.entities import LabletSessionReadModel
from lcm_core.domain.entities.read_models.lab_record_read_model import LabRecordReadModel
from lcm_core.domain.entities.read_models.lablet_definition_read_model import LabletDefinitionReadModel
from lcm_core.domain.enums.lab_record_status import LabRecordStatus
from lcm_core.integration.clients import ControlPlaneApiClient

from application.services.reconciler_helpers.definition_cache import get_definition
from application.services.reconciler_helpers.lab_record_helpers import update_lab_record_status

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LabResolutionResult:
    """Structured result from lab resolution indicating origin.

    Attributes:
        lab_id: CML lab ID (from reuse or import).
        freshly_imported: True if the lab was freshly imported from topology YAML;
                          False if an existing lab on the worker was reused.
    """

    lab_id: str
    freshly_imported: bool


async def resolve_lab_for_instance(
    instance: LabletSessionReadModel,
    api: ControlPlaneApiClient,
    cml_labs: CmlLabsSpiClient,
    definition_cache: dict[str, LabletDefinitionReadModel],
    topology_yaml: str | None = None,
) -> LabResolutionResult | None:
    """Resolve a lab for an instance: reuse existing or import fresh.

    Lab Resolution Strategy (Architecture §5.4):
    1. Fetch LabletDefinition to check lab_reuse_enabled flag (P9-8)
    2. If reuse enabled, query CPA for existing LabRecords on this worker
       matching the definition's topology:
       a. DEFINED lab → bind and start (fastest ~15s, already on runtime)
       b. WIPED lab → bind and start (~20s)
       c. STOPPED lab → wipe first, then start (~30s)
    3. If no reusable lab found or reuse disabled → fresh import (~90s)

    Args:
        instance: The LabletSession needing a lab.
        api: Control Plane API client.
        cml_labs: CML Labs SPI client.
        definition_cache: Mutable definition cache dict.
        topology_yaml: Resolved topology YAML (from definition or session).

    Returns:
        LabResolutionResult with lab_id and freshly_imported flag, or None on failure.
    """
    definition = await get_definition(instance.definition_id, api, definition_cache)

    # P9-8: Check if lab reuse is enabled for this definition
    if definition and definition.lab_reuse_enabled:
        reused_lab_id = await try_reuse_existing_lab(instance, definition, api, cml_labs)
        if reused_lab_id:
            return LabResolutionResult(lab_id=reused_lab_id, freshly_imported=False)

    # Fallback: fresh import
    imported_lab_id = await import_fresh_lab(instance, cml_labs, topology_yaml=topology_yaml)
    if imported_lab_id:
        return LabResolutionResult(lab_id=imported_lab_id, freshly_imported=True)
    return None


async def try_reuse_existing_lab(
    instance: LabletSessionReadModel,
    definition: LabletDefinitionReadModel,
    api: ControlPlaneApiClient,
    cml_labs: CmlLabsSpiClient,
) -> str | None:
    """Try to find and reuse an existing lab on the worker.

    Queries CPA for LabRecords on this worker that match the session's
    definition_id (via ``based_on_definition_id``).  Candidates are
    verified against the CML worker (``get_lab()``) before binding
    to prevent ghost-lab reuse.

    Candidate states in preference order (fastest-to-ready first):
      1. DEFINED — already on runtime, just start (~15 s)
      2. WIPED  — just start (~20 s)
      3. STOPPED — wipe first, then start (~30 s)
      4. WIPING — wait for wipe to finish, then start
      5. STOPPING — wait for stop, then wipe, then start

    Ghost handling: If ``get_lab()`` returns ``None`` (HTTP 404), the
    candidate is skipped and its LabRecord is marked ORPHANED via CPA.

    Args:
        instance: The LabletSession needing a lab.
        definition: The LabletDefinition with topology spec.
        api: Control Plane API client.
        cml_labs: CML Labs SPI client.

    Returns:
        Reused CML lab ID, or None if no reusable lab found.
    """
    if not instance.worker_id or not instance.worker_ip:
        return None

    try:
        # Query CPA for all labs on this worker
        lab_records = await api.get_lab_records_for_worker(
            worker_id=instance.worker_id,
        )

        if not lab_records:
            return None

        # Parse into read models for structured access
        candidates = [LabRecordReadModel.from_dict(lr) for lr in lab_records]

        # Filter to candidates matching the definition (by definition_id)
        # and bucket by reusable state.
        defined_candidates: list[LabRecordReadModel] = []
        wiped_candidates: list[LabRecordReadModel] = []
        stopped_candidates: list[LabRecordReadModel] = []
        wiping_candidates: list[LabRecordReadModel] = []
        stopping_candidates: list[LabRecordReadModel] = []

        for lr in candidates:
            # Must match the session's definition via provenance tracking
            if lr.based_on_definition_id != instance.definition_id:
                continue

            # Must not already be bound to an active session
            if lr.active_lablet_session_id:
                continue

            # Must not already have an active pending action
            if lr.has_pending_action:
                continue

            if lr.status == LabRecordStatus.DEFINED.value:
                defined_candidates.append(lr)
            elif lr.status == LabRecordStatus.WIPED.value:
                wiped_candidates.append(lr)
            elif lr.status == LabRecordStatus.STOPPED.value:
                stopped_candidates.append(lr)
            elif lr.status == LabRecordStatus.WIPING.value:
                wiping_candidates.append(lr)
            elif lr.status == LabRecordStatus.STOPPING.value:
                stopping_candidates.append(lr)

        # Walk candidates in preference order: defined → wiped → stopped → wiping → stopping
        ordered_candidates = defined_candidates + wiped_candidates + stopped_candidates + wiping_candidates + stopping_candidates

        for lab in ordered_candidates:
            # Verify the CML lab actually exists on the worker (prevents ghost binding)
            cml_lab = await cml_labs.get_lab(
                host=instance.worker_ip,
                lab_id=lab.lab_id,
                username=instance.worker_cml_username,
                password=instance.worker_cml_password,
            )
            if cml_lab is None:
                # Ghost lab — mark LabRecord as ORPHANED and skip
                logger.warning(f"👻 Ghost lab detected: LabRecord {lab.id} references lab {lab.lab_id} which does not exist on worker {instance.worker_ip} — marking ORPHANED")
                await update_lab_record_status(lab.lab_id, instance.worker_id, LabRecordStatus.ORPHANED.value, api)
                continue

            # Candidate verified — handle based on its current state
            if lab.status == LabRecordStatus.DEFINED.value:
                logger.info(f"♻️ Found DEFINED lab {lab.lab_id} on worker {instance.worker_id} for reuse (instance={instance.id})")
                return lab.lab_id

            if lab.status == LabRecordStatus.WIPED.value:
                logger.info(f"♻️ Found WIPED lab {lab.lab_id} on worker {instance.worker_id} for reuse (instance={instance.id})")
                return lab.lab_id

            if lab.status == LabRecordStatus.STOPPED.value:
                logger.info(f"♻️ Found STOPPED lab {lab.lab_id} on worker {instance.worker_id} — wiping for reuse (instance={instance.id})")
                await cml_labs.wipe_lab(
                    host=instance.worker_ip,
                    lab_id=lab.lab_id,
                    username=instance.worker_cml_username,
                    password=instance.worker_cml_password,
                )
                await update_lab_record_status(lab.lab_id, instance.worker_id, LabRecordStatus.WIPED.value, api)
                return lab.lab_id

            # WIPING / STOPPING — lab is in transition; log and skip for now
            logger.info(f"⏳ Lab {lab.lab_id} on worker {instance.worker_id} is in transitional state {lab.status} — skipping for now (instance={instance.id})")

        logger.debug(f"No reusable labs found on worker {instance.worker_id} for definition {instance.definition_id}")
        return None

    except Exception as e:
        logger.warning(f"Lab reuse lookup failed for instance {instance.id}: {e}")
        return None


async def import_fresh_lab(
    instance: LabletSessionReadModel,
    cml_labs: CmlLabsSpiClient,
    topology_yaml: str | None = None,
) -> str | None:
    """Import a fresh lab from topology YAML.

    Args:
        instance: The LabletSession needing a lab.
        cml_labs: CML Labs SPI client.
        topology_yaml: Resolved topology YAML (from definition or session fallback).

    Returns:
        New CML lab ID, or None on failure.
    """
    effective_yaml = topology_yaml or instance.topology_yaml
    if not effective_yaml:
        logger.error(f"No topology YAML available for session {instance.id}")
        return None

    try:
        lab_id = await cml_labs.import_lab(
            host=instance.worker_ip,
            topology_yaml=effective_yaml,
            title=instance.name,
            username=instance.worker_cml_username,
            password=instance.worker_cml_password,
        )
        return lab_id
    except Exception as e:
        logger.error(f"Failed to import lab for instance {instance.id}: {e}")
        return None
