"""Mark ready step handler — mark_ready.

ADR-038: Extracted from binding_steps.py (one step per file refactor).

Atomic transition to READY status after pipeline completion.
"""

from __future__ import annotations

import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_handlers._helpers import get_step_result_data
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


@step_handler("mark_ready")
async def step_mark_ready(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Atomic transition to READY status.

    Calls ``mark_session_ready()`` with the resolved CML lab ID
    and user session ID.

    ADR-038 Task 1 parity: Cleans up shared tracking state
    (resolved_lab_ids, freshly_imported_sessions) after successful
    mark_ready — the lab ID is now persisted in CPA.
    """
    resolve_data = get_step_result_data(progress, "lab_resolve")
    cml_lab_id = resolve_data.get("cml_lab_id") if resolve_data else None
    if not cml_lab_id:
        return StepResult.failed("No cml_lab_id from lab_resolve")

    # Get user_session_id from lds_provision (if it ran)
    lds_data = get_step_result_data(progress, "lds_provision")
    user_session_id = (lds_data.get("user_session_id") if lds_data else None) or ""

    try:
        await context.api.mark_session_ready(
            session_id=instance.id,
            user_session_id=user_session_id,
            cml_lab_id=cml_lab_id,
        )

        # Clean up local lab ID tracking (now persisted in CPA)
        if context.resolved_lab_ids is not None:
            context.resolved_lab_ids.pop(instance.id, None)
        if context.freshly_imported_sessions is not None:
            context.freshly_imported_sessions.discard(instance.id)

        logger.info(f"✅ Session {instance.id} marked READY (pipeline complete)")
        return StepResult.completed(
            {
                "cml_lab_id": cml_lab_id,
                "user_session_id": user_session_id,
            }
        )
    except Exception as e:
        return StepResult.failed(str(e))
