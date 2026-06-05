"""Evaluate step handler — evaluate.

Runs grading engine against evidence and rubric (stub).
"""

from __future__ import annotations

import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


@step_handler("evaluate")
async def step_evaluate(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Run grading engine against evidence and rubric.

    Stub — will be implemented when the grading engine is built.
    """
    logger.info(f"evaluate not yet implemented for session {instance.id}")
    return StepResult.completed({"score": None, "note": "stub — grading engine not implemented"})
