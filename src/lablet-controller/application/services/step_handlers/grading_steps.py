"""Grading step handlers — stubs.

ADR-038: Extracted from LabletReconciler grading step stubs.

G1. load_rubric — load grading rules from definition
G2. evaluate — run grading engine against evidence and rubric
G3. record_score — create ScoreReport aggregate and store results

All steps are stubs — real implementation when the grading engine is built.
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


@step_handler("record_score")
async def step_record_score(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Create ScoreReport aggregate and store results.

    Stub — will be implemented when the grading engine is built.
    """
    logger.info(f"record_score not yet implemented for session {instance.id}")
    return StepResult.completed({"score_report_id": None, "note": "stub"})
