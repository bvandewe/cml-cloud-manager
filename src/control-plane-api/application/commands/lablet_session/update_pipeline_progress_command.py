"""Update Pipeline Progress command.

ADR-034 Sprint E: Records per-step progress updates for all pipeline types
(instantiate, teardown, collect_evidence, compute_grading) from the
lablet-controller reconciler.

The CPA is the source of truth for pipeline state — the controller sends
step-level deltas, and this handler applies them to the full progress
stored per pipeline on the session.

Sprint G (G1): Also upserts a PipelineExecutionRecord for auditing.
Sprint G (G5): Emits granular per-step CloudEvents for SSE reactivity.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from application.commands.command_handler_base import CommandHandlerBase
from application.events.integration.pipeline_events import (
    PipelineCompletedEventV1,
    PipelineStepCompletedEventV1,
    PipelineStepFailedEventV1,
    PipelineStepStartedEventV1,
)
from domain.entities.lablet_session import LabletSession
from domain.entities.pipeline_execution_record import PipelineExecutionRecord
from domain.repositories.lablet_session_repository import LabletSessionRepository
from domain.repositories.pipeline_execution_repository import PipelineExecutionRepository
from integration.services.cloud_event_publisher import CloudEventPublisher
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

log = logging.getLogger(__name__)

VALID_STEP_STATUSES = ("pending", "completed", "failed", "skipped")
VALID_PIPELINE_NAMES = ("instantiate", "teardown", "collect_evidence", "compute_grading")


@dataclass
class UpdatePipelineProgressCommand(Command[OperationResult[dict[str, Any]]]):
    """Update a single pipeline step on a LabletSession's pipeline progress.

    ADR-034 Sprint E: Generic pipeline progress — supports all pipeline types.

    Attributes:
        session_id: The LabletSession ID.
        pipeline_name: Pipeline type ("instantiate", "teardown", etc.).
        step_name: Pipeline step name (e.g., "stop_lab", "wipe_lab").
        step_status: Step outcome — "completed", "failed", or "skipped".
        result_data: Optional result payload for completed steps.
        error: Optional error message for failed steps.
    """

    session_id: str
    pipeline_name: str
    step_name: str
    step_status: str
    result_data: dict[str, Any] | None = field(default=None)
    error: str | None = field(default=None)


class UpdatePipelineProgressCommandHandler(
    CommandHandlerBase,
    CommandHandler[UpdatePipelineProgressCommand, OperationResult[dict[str, Any]]],
):
    """Handle generic pipeline progress updates.

    ADR-034 Sprint E: Applies step-level deltas to pipeline_progress dict
    on the LabletSession aggregate, keyed by pipeline_name.

    Sprint G additions:
    - G1: Upserts PipelineExecutionRecord on pipeline start/completion
      for auditable execution history.
    - G5: Emits granular per-step CloudEvents (pipeline.step.started.v1,
      pipeline.step.completed.v1, pipeline.step.failed.v1,
      pipeline.completed.v1) for SSE reactivity.

    Workflow:
    1. Validate inputs (pipeline_name, step_status)
    2. Load LabletSession
    3. Load or initialize pipeline progress for the given pipeline
    4. Apply step-level delta (complete/fail/skip)
    5. Persist updated progress on session aggregate via domain event
    6. Emit per-step CloudEvent (G5 — fire-and-forget)
    7. Upsert PipelineExecutionRecord (G1 — fire-and-forget)
    """

    def __init__(
        self,
        cloud_event_publisher: CloudEventPublisher,
        lablet_session_repository: LabletSessionRepository,
        pipeline_execution_repository: PipelineExecutionRepository,
    ):
        self._cloud_event_publisher = cloud_event_publisher
        self._session_repo = lablet_session_repository
        self._execution_repo = pipeline_execution_repository

    async def handle_async(self, request: UpdatePipelineProgressCommand) -> OperationResult[dict[str, Any]]:
        """Handle generic pipeline progress update.

        Sprint G additions:
        - G5: Emits granular per-step CloudEvents for SSE reactivity.
        - G1: Upserts PipelineExecutionRecord on pipeline start/completion.
        """
        log.info(
            "Updating pipeline progress for session %s — pipeline=%s step=%s status=%s",
            request.session_id,
            request.pipeline_name,
            request.step_name,
            request.step_status,
        )

        # Validate pipeline_name
        if request.pipeline_name not in VALID_PIPELINE_NAMES:
            return self.bad_request(f"Invalid pipeline_name '{request.pipeline_name}'. Must be one of {VALID_PIPELINE_NAMES}")

        # Validate step_status
        if request.step_status not in VALID_STEP_STATUSES:
            return self.bad_request(f"Invalid step_status '{request.step_status}'. Must be one of {VALID_STEP_STATUSES}")

        # 1. Load session
        session = await self._session_repo.get_by_id_async(request.session_id)
        if not session:
            return self.not_found(LabletSession, request.session_id)

        # 2. Load or initialize pipeline progress for this pipeline
        pipeline_progress = session.state.pipeline_progress or {}
        current_progress = pipeline_progress.get(request.pipeline_name, {})

        # 3. Apply step-level delta
        if request.step_name not in current_progress:
            # Auto-initialize step if not present (e.g., teardown/evidence/grading
            # pipelines don't have pre-built progress like instantiation does)
            current_progress[request.step_name] = {"status": "pending", "order": len(current_progress)}

        step = current_progress[request.step_name]

        if request.step_status == "pending":
            step["status"] = "in_progress"
        elif request.step_status == "completed":
            step["status"] = "completed"
            if request.result_data:
                step["result_data"] = request.result_data
        elif request.step_status == "failed":
            step["status"] = "failed"
            step["error"] = request.error or "Unknown error"
        elif request.step_status == "skipped":
            step["status"] = "skipped"
            if request.error:
                step["skip_reason"] = request.error

        current_progress[request.step_name] = step

        # 4. Persist via domain event
        session.update_pipeline_progress(
            pipeline_name=request.pipeline_name,
            step_name=request.step_name,
            step_status=request.step_status,
            progress_data=current_progress,
        )
        await self._session_repo.update_async(session)

        # Check pipeline completion (all steps completed or skipped)
        all_done = all(s.get("status") in ("completed", "skipped") for s in current_progress.values())

        # =====================================================================
        # G5: Emit granular per-step CloudEvents for SSE reactivity
        # =====================================================================
        await self._emit_step_cloud_event(request, all_done, current_progress)

        # =====================================================================
        # G1: Upsert PipelineExecutionRecord on pipeline start / completion
        # =====================================================================
        await self._upsert_execution_record(request, current_progress, all_done)

        log.info(
            "Pipeline progress updated for session %s — pipeline=%s step=%s → %s (pipeline_complete=%s)",
            request.session_id,
            request.pipeline_name,
            request.step_name,
            request.step_status,
            all_done,
        )

        return self.ok(
            {
                "session_id": request.session_id,
                "pipeline_name": request.pipeline_name,
                "step_name": request.step_name,
                "step_status": request.step_status,
                "pipeline_complete": all_done,
            }
        )

    # =========================================================================
    # G5: Per-step CloudEvent emission
    # =========================================================================

    async def _emit_step_cloud_event(
        self,
        request: UpdatePipelineProgressCommand,
        all_done: bool,
        current_progress: dict[str, Any],
    ) -> None:
        """Emit a granular CloudEvent for the step transition.

        Fire-and-forget: errors are logged but never propagate to the
        caller so the main progress update is never blocked.
        """
        try:
            now = datetime.now(timezone.utc)

            if request.step_status == "pending":
                # Step is transitioning to in_progress
                await self._cloud_event_publisher.publish_async(
                    PipelineStepStartedEventV1(
                        aggregate_id=request.session_id,
                        session_id=request.session_id,
                        pipeline_name=request.pipeline_name,
                        step_name=request.step_name,
                        started_at=now,
                    )
                )
            elif request.step_status == "completed":
                await self._cloud_event_publisher.publish_async(
                    PipelineStepCompletedEventV1(
                        aggregate_id=request.session_id,
                        session_id=request.session_id,
                        pipeline_name=request.pipeline_name,
                        step_name=request.step_name,
                        result_data=request.result_data or {},
                        completed_at=now,
                    )
                )
            elif request.step_status == "failed":
                await self._cloud_event_publisher.publish_async(
                    PipelineStepFailedEventV1(
                        aggregate_id=request.session_id,
                        session_id=request.session_id,
                        pipeline_name=request.pipeline_name,
                        step_name=request.step_name,
                        error=request.error or "Unknown error",
                        failed_at=now,
                    )
                )
            # "skipped" does not emit a dedicated event — it's captured in
            # the pipeline-completed event below.

            # Pipeline-level completion event
            if all_done:
                steps_completed = sum(1 for s in current_progress.values() if s.get("status") == "completed")
                steps_failed = sum(1 for s in current_progress.values() if s.get("status") == "failed")
                steps_skipped = sum(1 for s in current_progress.values() if s.get("status") == "skipped")

                if steps_failed > 0:
                    terminal_status = "failed"
                elif steps_skipped > 0:
                    terminal_status = "partial"
                else:
                    terminal_status = "completed"

                await self._cloud_event_publisher.publish_async(
                    PipelineCompletedEventV1(
                        aggregate_id=request.session_id,
                        session_id=request.session_id,
                        pipeline_name=request.pipeline_name,
                        status=terminal_status,
                        steps_completed=steps_completed,
                        steps_failed=steps_failed,
                        steps_skipped=steps_skipped,
                        completed_at=now,
                    )
                )

        except Exception:
            log.exception(
                "G5: Failed to emit step CloudEvent for session=%s pipeline=%s step=%s",
                request.session_id,
                request.pipeline_name,
                request.step_name,
            )

    # =========================================================================
    # G1: PipelineExecutionRecord upsert
    # =========================================================================

    async def _upsert_execution_record(
        self,
        request: UpdatePipelineProgressCommand,
        current_progress: dict[str, Any],
        all_done: bool,
    ) -> None:
        """Create or update a PipelineExecutionRecord for auditing.

        - On first step transition (pending → in_progress): create a
          "running" record.
        - On pipeline completion (all_done=True): finalize the record
          with terminal status and duration.

        Fire-and-forget: errors are logged but never propagate.
        """
        try:
            is_first_step = request.step_status == "pending"

            if is_first_step:
                # Determine attempt number from existing records
                existing = await self._execution_repo.get_by_session_and_pipeline_async(request.session_id, request.pipeline_name)
                attempt = len(existing) + 1

                steps_snapshot = [{"name": name, "status": data.get("status", "pending"), "order": data.get("order", 0)} for name, data in current_progress.items()]

                record = PipelineExecutionRecord.create(
                    session_id=request.session_id,
                    pipeline_name=request.pipeline_name,
                    attempt=attempt,
                    steps=steps_snapshot,
                )
                await self._execution_repo.add_async(record)
                log.info(
                    "G1: Created PipelineExecutionRecord id=%s session=%s pipeline=%s attempt=%d",
                    record.id,
                    request.session_id,
                    request.pipeline_name,
                    attempt,
                )

            elif all_done:
                # Finalize the latest running record
                record = await self._execution_repo.get_latest_by_session_and_pipeline_async(request.session_id, request.pipeline_name)
                if record and record.status == "running":
                    steps_snapshot = [{"name": name, "status": data.get("status", "pending"), "order": data.get("order", 0)} for name, data in current_progress.items()]

                    steps_failed = sum(1 for s in current_progress.values() if s.get("status") == "failed")
                    steps_skipped = sum(1 for s in current_progress.values() if s.get("status") == "skipped")

                    duration = (datetime.now(timezone.utc) - record.started_at).total_seconds() if record.started_at else 0.0

                    if steps_failed > 0:
                        record.mark_failed(
                            error=request.error or "One or more steps failed",
                            steps=steps_snapshot,
                            duration_seconds=duration,
                        )
                    elif steps_skipped > 0:
                        record.mark_partial(
                            steps=steps_snapshot,
                            outputs=request.result_data or {},
                            duration_seconds=duration,
                        )
                    else:
                        record.mark_completed(
                            steps=steps_snapshot,
                            outputs=request.result_data or {},
                            duration_seconds=duration,
                        )

                    await self._execution_repo.update_async(record)
                    log.info(
                        "G1: Finalized PipelineExecutionRecord id=%s session=%s pipeline=%s → %s (%.1fs)",
                        record.id,
                        request.session_id,
                        request.pipeline_name,
                        record.status,
                        duration,
                    )

        except Exception:
            log.exception(
                "G1: Failed to upsert PipelineExecutionRecord for session=%s pipeline=%s",
                request.session_id,
                request.pipeline_name,
            )
