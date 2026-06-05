"""Package evidence step handler — package_evidence.

Bundles all artifacts into a compressed evidence package (stub).
"""

from __future__ import annotations

import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


@step_handler("package_evidence")
async def step_package_evidence(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Bundle all artifacts into a compressed evidence package.

    Stub — will be implemented in Sprint F+.
    """
    logger.info(f"package_evidence not yet implemented for session {instance.id}")
    return StepResult.completed({"evidence_uri": None, "note": "stub — no evidence collected yet"})
