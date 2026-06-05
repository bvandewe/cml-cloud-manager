"""Wipe lab step handler — wipe_lab.

Wipes the CML lab (resets to DEFINED_ON_CORE) preserving topology for reuse.
"""

from __future__ import annotations

import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


@step_handler("wipe_lab")
async def step_wipe_lab(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Wipe the CML lab (reset to DEFINED_ON_CORE).

    Preserves topology for reuse — does NOT delete the lab.
    CML Labs SPI: PUT /api/v0/labs/{id}/wipe

    Updates LabRecord status to WIPED via
    ``context.update_lab_record_status`` after successful wipe.
    """
    if not instance.cml_lab_id:
        return StepResult.completed({"lab_wiped": False})

    try:
        await context.cml.wipe_lab(
            host=context.worker_ip,
            lab_id=instance.cml_lab_id,
            username=context.worker_cml_username,
            password=context.worker_cml_password,
        )
        # Update LabRecord status to WIPED (best-effort)
        if instance.worker_id and context.update_lab_record_status:
            try:
                await context.update_lab_record_status(instance.cml_lab_id, instance.worker_id, "wiped")
            except Exception as e:
                logger.warning(f"Failed to update lab record status to WIPED for {instance.cml_lab_id}: {e}")
        logger.info(f"Lab {instance.cml_lab_id} wiped for session {instance.id}")
        return StepResult.completed({"lab_wiped": True})
    except Exception as e:
        return StepResult.failed(f"Failed to wipe lab: {e}")
