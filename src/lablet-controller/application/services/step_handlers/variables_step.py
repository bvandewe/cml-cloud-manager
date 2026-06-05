"""Variables step handler — variables.

Resolves session variables from definition defaults.
Currently a placeholder for future variable resolution service.
"""

from __future__ import annotations

import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


@step_handler("variables")
async def step_variables(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Resolve session variables — placeholder (§5).

    Currently a no-op. Future: call variable resolution service.
    """
    definition = context.definition
    variables = getattr(definition, "variables", None) if definition else None
    if not variables:
        return StepResult.skipped("No variables defined")

    # Future: resolve variables from definition defaults
    resolved = {var.get("name"): var.get("default_value") for var in variables if var.get("default_value")}
    return StepResult.completed({"resolved_variables": resolved})
