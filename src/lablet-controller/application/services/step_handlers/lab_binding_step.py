"""Lab binding step handler — lab_binding.

ADR-038: Extracted from binding_steps.py (one step per file refactor).

Binds LabRecord to session and creates LabRunRecord.
"""

from __future__ import annotations

import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_handlers._helpers import get_step_result_data
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


@step_handler("lab_binding")
async def step_lab_binding(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Bind LabRecord to session and create LabRunRecord (§4.3).

    Calls CPA ``bind_lab_to_session()`` which:
    1. Creates a LabRunRecord (runtime tracking)
    2. Sets ``active_lablet_session_id`` on LabRecord
    3. Denormalizes ``LabRecord.allocated_ports`` onto LabletSession

    ADR-038 Task 1 parity: If ``lab_record_id`` is missing from lab_resolve
    result data, attempts full fallback chain: find → register → fail.
    Uses ``context.find_lab_record_id`` and ``context.register_lab_record``.
    """
    resolve_data = get_step_result_data(progress, "lab_resolve")
    cml_lab_id = resolve_data.get("cml_lab_id") if resolve_data else None
    lab_record_id = resolve_data.get("lab_record_id") if resolve_data else None

    if not cml_lab_id:
        return StepResult.failed("No cml_lab_id from lab_resolve")

    # Resilient fallback: resolve lab_record_id if missing from stale progress
    if not lab_record_id:
        logger.warning(f"lab_binding: lab_record_id missing from lab_resolve data for lab {cml_lab_id} — attempting to find or register LabRecord")
        # Step 1: Try to find existing LabRecord
        if context.find_lab_record_id:
            lab_record_id = await context.find_lab_record_id(cml_lab_id, instance.worker_id or "")

        # Step 2: Register if not found
        if not lab_record_id and context.register_lab_record:
            lab_record_id = await context.register_lab_record(cml_lab_id, instance)

        # Step 3: Direct CPA fallback
        if not lab_record_id:
            try:
                records = await context.api.get_lab_records_for_worker(worker_id=instance.worker_id or "")
                for lr in records:
                    if lr.get("lab_id") == cml_lab_id:
                        lab_record_id = lr.get("id")
                        break
            except Exception as e:
                logger.warning(f"lab_binding: fallback lookup failed: {e}")

        if not lab_record_id:
            return StepResult.failed(f"No lab_record_id for lab {cml_lab_id} — find and register both failed")
        logger.info(f"lab_binding: resolved lab_record_id={lab_record_id} via fallback")

    cml_lab_title = resolve_data.get("cml_lab_title") if resolve_data else None

    try:
        result = await context.api.bind_lab_to_session(
            session_id=instance.id,
            worker_id=instance.worker_id,
            lab_record_id=lab_record_id,
            cml_lab_id=cml_lab_id,
            cml_lab_title=cml_lab_title,
        )
        return StepResult.completed(result)
    except Exception as e:
        return StepResult.failed(str(e))
