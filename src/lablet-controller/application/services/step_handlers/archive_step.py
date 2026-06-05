"""Archive step handler — archive.

Records lab run completion and archives the session after teardown.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel
from lcm_core.domain.enums import LabletSessionStatus

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


@step_handler("archive")
async def step_archive(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Record lab run completion and archive the session.

    Calls ``context.record_lab_run_completed`` (best-effort) before
    transitioning the session to ARCHIVED status.
    """
    # Record lab run completion (P9-7) — best-effort
    if context.record_lab_run_completed:
        try:
            await context.record_lab_run_completed(instance)
        except Exception as e:
            logger.warning(f"Failed to record lab run for session {instance.id}: {e}")

    try:
        await context.api.transition_session(
            session_id=instance.id,
            new_status=LabletSessionStatus.ARCHIVED,
            reason="Teardown pipeline completed",
        )
        logger.info(f"Session {instance.id} archived (teardown pipeline complete)")
        return StepResult.completed(
            {
                "archived_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as e:
        return StepResult.failed(f"Failed to archive session: {e}")
