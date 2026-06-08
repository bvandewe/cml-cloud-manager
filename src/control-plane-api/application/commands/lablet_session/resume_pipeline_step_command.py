"""Resume Pipeline Step command (Phase 3 / AD-CSI-009).

Called by the lablet-controller's ``events_controller`` when a Scenario Engine
``job.completed`` CloudEvent arrives for a previously-suspended pipeline step.

Workflow:
1. Validate inputs.
2. Load LabletSession.
3. Locate the suspended step inside ``pipeline_progress[pipeline_name]`` by
   ``step_correlation_id``. If not found, return 404 (the controller will
   convert this to a 202 + WARN log for idempotency — duplicate CloudEvent
   deliveries are expected).
4. Flip the step's ``status`` from ``"suspended"`` → ``"completed"`` and merge
   the external job's ``output_data`` into ``result_data``.
5. Persist via the existing ``update_pipeline_progress`` domain event (reusing
   ``LabletSessionPipelineProgressUpdatedDomainEvent`` keeps the audit trail
   homogeneous and avoids event proliferation).
6. Return the refreshed pipeline_progress dict so the caller (events_controller)
   can hand it back to the in-process ``LifecyclePhaseHandler`` for resumption.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.lablet_session import LabletSession
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

log = logging.getLogger(__name__)


@dataclass
class ResumePipelineStepCommand(Command[OperationResult[dict[str, Any]]]):
    """Flip a suspended pipeline step to completed and merge external output.

    Attributes:
        session_id: The LabletSession ID.
        pipeline_name: Pipeline holding the suspended step
            (typically ``"instantiate"``).
        step_correlation_id: The opaque correlation token issued when the
            step was suspended (round-tripped via SE CloudEvent metadata).
        output_data: Output payload from the external job.
        completed_at: ISO 8601 timestamp of external completion (defaults
            to ``datetime.now(UTC)`` if omitted).
    """

    session_id: str
    pipeline_name: str
    step_correlation_id: str
    output_data: dict[str, Any] = field(default_factory=dict)
    completed_at: str | None = field(default=None)


class ResumePipelineStepCommandHandler(
    CommandHandlerBase,
    CommandHandler[ResumePipelineStepCommand, OperationResult[dict[str, Any]]],
):
    """Handle ResumePipelineStepCommand by completing a suspended step."""

    def __init__(self, lablet_session_repository: LabletSessionRepository) -> None:
        self._session_repo = lablet_session_repository

    async def handle_async(self, request: ResumePipelineStepCommand) -> OperationResult[dict[str, Any]]:
        log.info(
            "Resuming suspended pipeline step for session=%s pipeline=%s correlation=%s",
            request.session_id,
            request.pipeline_name,
            request.step_correlation_id,
        )

        session = await self._session_repo.get_by_id_async(request.session_id)
        if session is None:
            return self.not_found(LabletSession, request.session_id)

        pipeline_progress: dict[str, Any] = session.state.pipeline_progress or {}
        current_progress: dict[str, Any] | None = pipeline_progress.get(request.pipeline_name)
        if not current_progress:
            return self.not_found(LabletSession, f"{request.session_id}/{request.pipeline_name}")

        # Locate the suspended step by step_correlation_id
        target_step_name: str | None = None
        for step_name, step_data in current_progress.items():
            if not isinstance(step_data, dict):
                continue
            if step_data.get("step_correlation_id") == request.step_correlation_id:
                target_step_name = step_name
                break

        if target_step_name is None:
            return self.not_found(
                LabletSession,
                f"{request.session_id}/{request.pipeline_name}/correlation/{request.step_correlation_id}",
            )

        target_step = current_progress[target_step_name]
        if target_step.get("status") != "suspended":
            # Already resumed (or in another terminal state) — idempotent no-op.
            log.info(
                "Step %s/%s already in status=%s — treating resume as idempotent no-op",
                request.pipeline_name,
                target_step_name,
                target_step.get("status"),
            )
            return self.ok(
                {
                    "session_id": request.session_id,
                    "pipeline_name": request.pipeline_name,
                    "step_name": target_step_name,
                    "pipeline_progress": current_progress,
                    "idempotent": True,
                }
            )

        # Flip suspended → completed, merge external output_data into result_data
        merged_result_data: dict[str, Any] = dict(target_step.get("result_data") or {})
        merged_result_data.update(request.output_data)
        target_step["status"] = "completed"
        target_step["result_data"] = merged_result_data
        target_step["completed_at"] = request.completed_at or datetime.now(timezone.utc).isoformat()
        current_progress[target_step_name] = target_step

        # Persist via the existing generic event
        session.update_pipeline_progress(
            pipeline_name=request.pipeline_name,
            step_name=target_step_name,
            step_status="completed",
            progress_data=current_progress,
        )
        await self._session_repo.update_async(session)

        log.info(
            "Pipeline step resumed: session=%s pipeline=%s step=%s",
            request.session_id,
            request.pipeline_name,
            target_step_name,
        )

        return self.ok(
            {
                "session_id": request.session_id,
                "pipeline_name": request.pipeline_name,
                "step_name": target_step_name,
                "pipeline_progress": current_progress,
                "idempotent": False,
            }
        )
