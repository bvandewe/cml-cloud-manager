"""Stop lab step handler — stop_lab.

Stops the CML lab and polls until STOPPED state is reached.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult, step_handler
from integration.services.cml_labs_spi import LabState

logger = logging.getLogger(__name__)


@step_handler("stop_lab")
async def step_stop_lab(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Stop the CML lab and poll until STOPPED.

    CML Labs SPI: PUT /api/v0/labs/{id}/stop
    """
    if not instance.cml_lab_id:
        return StepResult.completed({"lab_state": "NO_LAB"})

    try:
        lab_state = await context.cml.get_lab_state(
            host=context.worker_ip,
            lab_id=instance.cml_lab_id,
            username=context.worker_cml_username,
            password=context.worker_cml_password,
        )
    except Exception as e:
        return StepResult.failed(f"Failed to get lab state: {e}")

    if lab_state in (LabState.STOPPED, LabState.DEFINED_ON_CORE):
        return StepResult.completed({"lab_state": str(lab_state)})

    if lab_state == LabState.STARTED:
        try:
            await context.cml.stop_lab(
                host=context.worker_ip,
                lab_id=instance.cml_lab_id,
                username=context.worker_cml_username,
                password=context.worker_cml_password,
            )
            logger.info(f"Lab {instance.cml_lab_id} stop initiated for session {instance.id}")
        except Exception as e:
            return StepResult.failed(f"Failed to stop lab: {e}")

    # Poll until STOPPED (bounded by executor's per-step timeout)
    while True:
        await asyncio.sleep(5)
        try:
            lab_state = await context.cml.get_lab_state(
                host=context.worker_ip,
                lab_id=instance.cml_lab_id,
                username=context.worker_cml_username,
                password=context.worker_cml_password,
            )
        except Exception as e:
            return StepResult.failed(f"Failed to poll lab state: {e}")

        if lab_state in (LabState.STOPPED, LabState.DEFINED_ON_CORE):
            logger.info(f"Lab {instance.cml_lab_id} stopped (state={lab_state}) for session {instance.id}")
            return StepResult.completed({"lab_state": str(lab_state)})
