"""Deregister LDS step handler — deregister_lds.

Closes the LDS session and releases the license during teardown.
"""

from __future__ import annotations

import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult, step_handler
from integration.services.lds_spi import LdsSpiError

logger = logging.getLogger(__name__)


@step_handler("deregister_lds")
async def step_deregister_lds(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Deregister/archive the LDS session.

    Marked optional in seed YAML, so failures won't block the pipeline.
    """
    if not instance.lds_session_id:
        return StepResult.completed({"lds_archived": False})

    if not context.lds:
        return StepResult.skipped("LDS client not configured")

    try:
        region = instance.worker_aws_region
        await context.lds.archive_session(
            session_id=instance.lds_session_id,
            region=region,
        )
        logger.info(f"LDS session {instance.lds_session_id} archived for session {instance.id}")
        return StepResult.completed({"lds_archived": True})
    except LdsSpiError as e:
        logger.warning(f"LDS archive failed for session {instance.id}: {e}")
        return StepResult.failed(f"LDS archive failed: {e}")
    except Exception as e:
        logger.warning(f"LDS archive failed for session {instance.id}: {e}")
        return StepResult.failed(str(e))
