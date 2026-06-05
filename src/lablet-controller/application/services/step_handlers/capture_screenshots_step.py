"""Capture screenshots step handler — capture_screenshots.

Captures VNC screenshots of graphical nodes (stub).
"""

from __future__ import annotations

import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


@step_handler("capture_screenshots")
async def step_capture_screenshots(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Capture VNC screenshots of graphical nodes.

    Stub — will be implemented in Sprint F+.
    """
    logger.info(f"capture_screenshots not yet implemented for session {instance.id}")
    return StepResult.completed({"screenshots": [], "note": "stub"})
