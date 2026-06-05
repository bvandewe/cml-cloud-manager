"""Load rubric step handler — load_rubric.

Loads grading rules from definition (stub).
"""

from __future__ import annotations

import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


@step_handler("load_rubric")
async def step_load_rubric(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Load grading rules from definition (grade.xml).

    Stub — will be implemented when the grading engine is built.
    """
    logger.info(f"load_rubric not yet implemented for session {instance.id}")
    return StepResult.completed({"rubric_loaded": False, "note": "stub"})
