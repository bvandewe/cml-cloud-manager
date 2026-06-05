"""Export pcaps step handler — export_pcaps.

Exports packet capture files from bridge interfaces (stub).
"""

from __future__ import annotations

import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


@step_handler("export_pcaps")
async def step_export_pcaps(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Export packet capture files from bridge interfaces.

    Stub — will be implemented in Sprint F+.
    """
    logger.info(f"export_pcaps not yet implemented for session {instance.id}")
    return StepResult.completed({"pcaps": [], "note": "stub"})
