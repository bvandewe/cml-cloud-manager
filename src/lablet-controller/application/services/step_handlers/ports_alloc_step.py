"""Ports allocation step handler — ports_alloc.

Allocates real ports from the worker pool via CPA for lab connectivity.
"""

from __future__ import annotations

import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_handlers._helpers import get_step_result_data
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


@step_handler("ports_alloc")
async def step_ports_alloc(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Allocate real ports from worker pool via CPA (§3.6).

    Ports are stored on the LabRecord, keyed by lab_record_id in etcd.
    """
    definition = context.definition
    if not definition or not getattr(definition, "port_template", None):
        return StepResult.skipped("No port template defined")

    resolve_data = get_step_result_data(progress, "lab_resolve")
    lab_record_id = resolve_data.get("lab_record_id") if resolve_data else None
    if not lab_record_id:
        return StepResult.failed("No lab_record_id from lab_resolve")

    try:
        result = await context.api.allocate_lab_record_ports(
            lab_record_id=lab_record_id,
            worker_id=instance.worker_id,
        )
        return StepResult.completed(result)
    except Exception as e:
        return StepResult.failed(str(e))
