"""Instantiation step handlers — content_sync, variables, lab_resolve.

ADR-038: Extracted from LabletReconciler._step_content_sync/variables/lab_resolve.

These steps handle the early phase of lab instantiation:
1. content_sync — verify definition content is available
2. variables — resolve session variables from definition defaults
3. lab_resolve — import or reuse a CML lab on the assigned worker

ADR-038 Task 1: Parity gaps closed — handlers now use enriched PipelineContext
callables (resolve_lab_for_instance, find_lab_record_id, register_lab_record,
request_content_sync) and shared tracking state (resolved_lab_ids,
freshly_imported_sessions).
"""

from __future__ import annotations

import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


@step_handler("content_sync")
async def step_content_sync(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Verify definition content is synced and available (§6).

    Fail-fast prerequisite — if content is not synced, there is no
    point importing a lab (LDS provisioning requires the form and content).

    ADR-038 Task 1 parity: If content is not synced, triggers a content
    sync request via ``context.request_content_sync`` (mirrors reconciler's
    ``_content_sync_service.request_sync()`` call).
    """
    definition = context.definition
    if not definition:
        return StepResult.failed("Definition not found")

    if not getattr(definition, "content_sync_enabled", False):
        return StepResult.skipped("Content sync not enabled")

    sync_status = getattr(definition, "sync_status", None)
    if sync_status == "synced":
        return StepResult.completed(
            {
                "sync_status": sync_status,
                "form_qualified_name": definition.form_qualified_name,
            }
        )

    # Not synced — optionally trigger sync and fail (will retry on next reconcile)
    if context.request_content_sync and sync_status in (None, "not_synced", "sync_failed"):
        try:
            await context.request_content_sync(definition.id)
        except Exception as e:
            logger.warning(f"Could not trigger content sync for {definition.id}: {e}")

    return StepResult.failed(f"Content not synced (status: {sync_status}). Waiting for sync.")


@step_handler("variables")
async def step_variables(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Resolve session variables — placeholder (§5).

    Currently a no-op. Future: call variable resolution service.
    """
    definition = context.definition
    variables = getattr(definition, "variables", None) if definition else None
    if not variables:
        return StepResult.skipped("No variables defined")

    # Future: resolve variables from definition defaults
    resolved = {var.get("name"): var.get("default_value") for var in variables if var.get("default_value")}
    return StepResult.completed({"resolved_variables": resolved})


@step_handler("lab_resolve")
async def step_lab_resolve(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Resolve lab — reuse existing or import fresh (P9-4/5/8).

    Returns ``cml_lab_id`` and ``lab_record_id`` in result_data.

    ADR-038 Task 1 parity:
    - Uses ``context.resolve_lab_for_instance`` for lab resolution (includes
      lab reuse via ``_try_reuse_existing_lab``).
    - Tracks resolved labs in ``context.resolved_lab_ids`` (shared dict).
    - Tracks freshly imported sessions in ``context.freshly_imported_sessions``.
    - Uses ``context.find_lab_record_id`` and ``context.register_lab_record``
      for LabRecord resolution/creation (full fallback chain).
    """
    # Resolve topology YAML from definition
    topology_yaml = instance.topology_yaml
    if not topology_yaml:
        definition = context.definition
        if definition:
            topology_yaml = getattr(definition, "cml_yaml_content", None) or definition.topology_yaml
        if not topology_yaml:
            return StepResult.failed(f"No topology YAML found for definition {instance.definition_id}")

    # Check if lab already resolved (from previous attempts, session state, or tracking dict
    resolved_lab_ids = context.resolved_lab_ids or {}
    cml_lab_id = instance.cml_lab_id or resolved_lab_ids.get(instance.id)
    freshly_imported = False

    if not cml_lab_id:
        # Use reconciler's resolve_lab_for_instance if available (includes reuse logic)
        if context.resolve_lab_for_instance:
            lab_id = await context.resolve_lab_for_instance(instance, topology_yaml)
        else:
            # Fallback: direct import (no reuse) — for tests or minimal context
            try:
                lab_id = await context.cml.import_lab(
                    host=context.worker_ip,
                    topology_yaml=topology_yaml,
                    username=context.worker_cml_username,
                    password=context.worker_cml_password,
                )
            except Exception as e:
                return StepResult.failed(f"Lab import failed: {e}")

        if not lab_id:
            return StepResult.failed("Lab resolution failed: unable to import or reuse a lab")

        cml_lab_id = lab_id

        # Track resolved lab ID in shared state
        if context.resolved_lab_ids is not None:
            context.resolved_lab_ids[instance.id] = lab_id

        # Determine if freshly imported (not reused)
        # If resolve_lab_for_instance returned a lab that wasn't already known,
        # check if it's a reuse by looking at the session's previous cml_lab_id
        if not instance.cml_lab_id:
            # New lab assignment — mark as freshly imported
            freshly_imported = True
            if context.freshly_imported_sessions is not None:
                context.freshly_imported_sessions.add(instance.id)
            logger.info(f"📦 Imported lab {lab_id} for session {instance.id}")
        else:
            logger.info(f"♻️ Reusing lab {lab_id} for session {instance.id}")

    # Resolve lab_record_id via helper chain: find → register
    lab_record_id: str | None = None

    if context.find_lab_record_id:
        lab_record_id = await context.find_lab_record_id(cml_lab_id, instance.worker_id or "")

    if not lab_record_id and context.register_lab_record:
        logger.info(f"No LabRecord found for lab {cml_lab_id} on worker {instance.worker_id} — registering via discover_lab_records (freshly_imported={freshly_imported})")
        lab_record_id = await context.register_lab_record(cml_lab_id, instance)

    # Fallback: direct CPA query if context helpers not available
    if not lab_record_id:
        try:
            records = await context.api.get_lab_records_for_worker(worker_id=instance.worker_id or "")
            for lr in records:
                if lr.get("lab_id") == cml_lab_id:
                    lab_record_id = lr.get("id")
                    break
        except Exception as e:
            logger.warning(f"Failed to look up LabRecord for lab {cml_lab_id}: {e}")

    if not lab_record_id:
        return StepResult.failed(f"Failed to resolve or create LabRecord for lab {cml_lab_id} on worker {instance.worker_id}")

    # Fetch lab title for downstream binding
    cml_lab_title: str | None = None
    try:
        lab_info = await context.cml.get_lab(
            host=context.worker_ip,
            lab_id=cml_lab_id,
            username=context.worker_cml_username,
            password=context.worker_cml_password,
        )
        if lab_info:
            cml_lab_title = lab_info.title
    except Exception as e:
        logger.warning(f"Failed to fetch lab title for {cml_lab_id}: {e}")

    return StepResult.completed(
        {
            "cml_lab_id": cml_lab_id,
            "lab_record_id": lab_record_id,
            "cml_lab_title": cml_lab_title,
            "freshly_imported": freshly_imported,
        }
    )
