"""Capture configs step handler — capture_configs.

Exports running-config from managed devices (stub).
"""

from __future__ import annotations

import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


@step_handler("capture_configs")
async def step_capture_configs(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Export running-config from all managed devices.

    Stub — will be implemented in Sprint F+.
    """
    logger.info(f"capture_configs not yet implemented for session {instance.id}")
    return StepResult.completed({"configs": [], "note": "stub"})
