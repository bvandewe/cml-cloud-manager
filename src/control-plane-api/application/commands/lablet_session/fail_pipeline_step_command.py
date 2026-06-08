"""Fail Pipeline Step command (Phase 3 / AD-CSI-009).

Mirror of ``ResumePipelineStepCommand`` for the SE ``job.failed`` /
``job.cancelled`` CloudEvent paths. Flips a suspended pipeline step to
``"failed"`` and records the error message + optional details payload.

The downstream ``LifecyclePhaseHandler.fail_after_external_completion`` will
re-invoke the executor with the refreshed progress; the pipeline's
``pipeline_failure_strategy`` determines whether to retry, partial-complete,
or terminate.
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
class FailPipelineStepCommand(Command[OperationResult[dict[str, Any]]]):
    """Flip a suspended pipeline step to failed.

    Attributes:
        session_id: The LabletSession ID.
        pipeline_name: Pipeline holding the suspended step.
        step_correlation_id: Correlation token issued when suspended.
        error: Human-readable failure message.
        details: Optional structured error payload from the external job.
        failed_at: ISO 8601 timestamp of external failure.
    """

    session_id: str
    pipeline_name: str
    step_correlation_id: str
    error: str
    details: dict[str, Any] | None = field(default=None)
    failed_at: str | None = field(default=None)


class FailPipelineStepCommandHandler(
    CommandHandlerBase,
    CommandHandler[FailPipelineStepCommand, OperationResult[dict[str, Any]]],
):
    """Handle FailPipelineStepCommand."""

    def __init__(self, lablet_session_repository: LabletSessionRepository) -> None:
        self._session_repo = lablet_session_repository

    async def handle_async(self, request: FailPipelineStepCommand) -> OperationResult[dict[str, Any]]:
        log.info(
            "Failing suspended pipeline step for session=%s pipeline=%s correlation=%s",
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
        if target_step.get("status") not in ("suspended", "failed"):
            # Idempotency: if step is already in a non-failure terminal state
            # (e.g. completed), do not silently overwrite. Return conflict so
            # the caller surfaces the inconsistency.
            return self.conflict(f"Cannot fail step {target_step_name} in status '{target_step.get('status')}'")

        target_step["status"] = "failed"
        target_step["error"] = request.error
        if request.details is not None:
            target_step["error_details"] = request.details
        target_step["failed_at"] = request.failed_at or datetime.now(timezone.utc).isoformat()
        current_progress[target_step_name] = target_step

        session.update_pipeline_progress(
            pipeline_name=request.pipeline_name,
            step_name=target_step_name,
            step_status="failed",
            progress_data=current_progress,
        )
        await self._session_repo.update_async(session)

        log.info(
            "Pipeline step failed: session=%s pipeline=%s step=%s error=%s",
            request.session_id,
            request.pipeline_name,
            target_step_name,
            request.error,
        )

        return self.ok(
            {
                "session_id": request.session_id,
                "pipeline_name": request.pipeline_name,
                "step_name": target_step_name,
                "pipeline_progress": current_progress,
            }
        )
