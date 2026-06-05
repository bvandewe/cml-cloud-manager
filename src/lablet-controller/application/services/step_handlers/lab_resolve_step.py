"""Lab resolve step handler — lab_resolve.

Resolves a CML lab for the session: reuses existing or imports fresh.
Returns cml_lab_id and lab_record_id for downstream steps.
"""

from __future__ import annotations

import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


@step_handler("lab_resolve")
async def step_lab_resolve(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Resolve lab — reuse existing or import fresh (P9-4/5/8).

    Returns ``cml_lab_id`` and ``lab_record_id`` in result_data.

    Resolution chain:
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

    # Check if lab already resolved (from previous attempts, session state, or tracking dict)
    resolved_lab_ids = context.resolved_lab_ids or {}
    cml_lab_id = instance.cml_lab_id or resolved_lab_ids.get(instance.id)
    freshly_imported = False

    if not cml_lab_id:
        # Use reconciler's resolve_lab_for_instance if available (includes reuse logic)
        if context.resolve_lab_for_instance:
            resolution = await context.resolve_lab_for_instance(instance, topology_yaml)
        else:
            # Fallback: direct import (no reuse) — for tests or minimal context
            resolution = None
            try:
                lab_id = await context.cml.import_lab(
                    host=context.worker_ip,
                    topology_yaml=topology_yaml,
                    username=context.worker_cml_username,
                    password=context.worker_cml_password,
                )
                if lab_id:
                    from application.services.reconciler_helpers.lab_resolution import LabResolutionResult

                    resolution = LabResolutionResult(lab_id=lab_id, freshly_imported=True)
            except Exception as e:
                return StepResult.failed(f"Lab import failed: {e}")

        if not resolution:
            return StepResult.failed("Lab resolution failed: unable to import or reuse a lab")

        cml_lab_id = resolution.lab_id
        freshly_imported = resolution.freshly_imported

        # Track resolved lab ID in shared state
        if context.resolved_lab_ids is not None:
            context.resolved_lab_ids[instance.id] = cml_lab_id

        # Track freshly imported sessions for cleanup differentiation (AD-CLEANUP-001)
        if freshly_imported:
            if context.freshly_imported_sessions is not None:
                context.freshly_imported_sessions.add(instance.id)
            logger.info(f"📦 Imported lab {cml_lab_id} for session {instance.id}")
        else:
            logger.info(f"♻️ Reusing lab {cml_lab_id} for session {instance.id}")

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
