"""Record score step handler — record_score.

Creates ScoreReport aggregate and stores results (stub).
"""

from __future__ import annotations

import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


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
