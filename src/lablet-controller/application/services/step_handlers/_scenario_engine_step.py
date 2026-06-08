"""Tier-B step adapter: submits an SE Job and returns SUSPENDED.

AD-CSI-008 / Phase 3 (G-05): any step that operates on an *external system*
(CML, RADkit, ...) delegates to the Scenario Engine instead of executing
in-process adapters. This module provides the canonical helper used by
``lab_resolve_step`` and ``lab_start_step`` (and, later, ``lab_stop`` /
``lab_wipe`` / ``collect_grade`` / ``score_report``).

Workflow:

1. Resolve the SE PodDefinition id from ``context.definition.pod_definition_ref``
   (LCM-side ``definition_id`` is *not* the SE-side aggregate id \u2014 AD-CSI-010).
2. Build a per-suspension correlation token (``step_correlation_id``) so the
   subsequent CloudEvent can be routed back to this specific step (AD-CSI-016).
3. Submit the SE Job via :class:`ScenarioEngineClient.submit_job`, passing
   metadata so SE can echo it onto the emitted CloudEvent payload
   (AD-CSI-017).
4. Return :py:meth:`StepResult.suspended` \u2014 the
   :class:`PipelineExecutor` (Phase 3 Step 4) persists progress and halts
   downstream dispatch until the matching CloudEvent arrives.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScenarioBinding:
    """Maps a pipeline step to the SE scenario that should execute it.

    Attributes:
        scenario_name: Registered scenario key in SE (e.g. ``"lab_resolve"``).
        scenario_version: Scenario version (defaults to ``"v1"``).
    """

    scenario_name: str
    scenario_version: str = "v1"


async def submit_scenario_engine_job(
    *,
    binding: ScenarioBinding,
    step_name: str,
    instance: LabletSessionReadModel,
    context: PipelineContext,
    input_data: dict[str, Any],
) -> StepResult:
    """Submit a Job to the Scenario Engine and return :py:class:`StepResult.suspended`.

    The CloudEvent emitted by SE on completion will carry ``subject = job_id``
    plus ``data.metadata.step_correlation_id``, which the lablet-controller's
    ``events_controller`` (Phase 3 Step 6) uses to find this suspended step.

    Returns ``StepResult.failed(...)`` on any precondition failure
    (missing client, missing ``pod_definition_ref``, SE call raises). Per
    AD-CSI-005 the executor will record this failure via the standard
    progress path; no out-of-band side effects are performed here.

    Args:
        binding: SE scenario coordinates.
        step_name: Pipeline step name (also used in the correlation token).
        instance: Session being reconciled.
        context: Pipeline execution context. Must carry a populated
            ``scenario_engine_client`` and a ``definition`` with a
            ``pod_definition_ref``.
        input_data: Free-form input dict passed verbatim to the SE scenario.

    Returns:
        :py:class:`StepResult.suspended` on successful job submission;
        :py:class:`StepResult.failed` otherwise.
    """
    if context.scenario_engine_client is None:
        return StepResult.failed(f"{step_name}: ScenarioEngineClient not available on PipelineContext")

    pod_definition_ref = context.definition.pod_definition_ref if context.definition else None
    pod_definition_id: str | None = None
    if isinstance(pod_definition_ref, dict):
        pod_definition_id = pod_definition_ref.get("definition_id")
    elif pod_definition_ref is not None:
        # Defensive: accept a VO-like object too.
        pod_definition_id = getattr(pod_definition_ref, "definition_id", None)

    if not pod_definition_id:
        return StepResult.failed(f"{step_name}: LabletDefinition {getattr(context.definition, 'id', '?')} " f"has no pod_definition_ref \u2014 cannot submit SE job")

    step_correlation_id = f"{instance.id}:{step_name}:{uuid.uuid4().hex[:8]}"

    metadata = {
        "lablet_session_id": instance.id,
        "step_name": step_name,
        "step_correlation_id": step_correlation_id,
    }

    try:
        result = await context.scenario_engine_client.submit_job(
            scenario_name=binding.scenario_name,
            scenario_version=binding.scenario_version,
            input_data=input_data,
            pod_definition_id=pod_definition_id,
            callback_url=context.cloud_event_callback_url,
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001 \u2014 SE downtime must fail the step
        logger.exception(
            "Failed to submit SE job for step=%s scenario=%s@%s session=%s: %s",
            step_name,
            binding.scenario_name,
            binding.scenario_version,
            instance.id,
            exc,
        )
        return StepResult.failed(f"{step_name}: SE submit_job failed: {exc}")

    logger.info(
        "SE job submitted: scenario=%s@%s job_id=%s step=%s session=%s correlation=%s",
        binding.scenario_name,
        binding.scenario_version,
        result.job_id,
        step_name,
        instance.id,
        step_correlation_id,
    )

    return StepResult.suspended(
        external_job_id=result.job_id,
        step_correlation_id=step_correlation_id,
        reason=(f"awaiting SE job {result.job_id} " f"(scenario={binding.scenario_name}@{binding.scenario_version})"),
    )
