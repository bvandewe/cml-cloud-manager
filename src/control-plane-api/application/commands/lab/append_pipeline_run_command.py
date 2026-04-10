"""Append Pipeline Run Command — internal command to log a pipeline execution.

Sprint F (ADR-034): Called by lablet-controller when a lifecycle pipeline
completes (instantiate, teardown, collect_evidence, compute_grading).
Records a PipelineRunRecord value object on the LabRecord aggregate.

Architecture ref: ADR-034-next-steps.md §Sprint F.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator
from opentelemetry import trace

from domain.entities.lab_record import LabRecord
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.value_objects.pipeline_run_record import PipelineRunRecord

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class AppendPipelineRunCommand(Command[OperationResult[dict]]):
    """Internal command to record a pipeline execution on a LabRecord.

    Appends a PipelineRunRecord to the LabRecord's pipeline_run_history.

    Attributes:
        lab_record_id: LabRecord aggregate ID.
        pipeline_name: Name of the pipeline (e.g., "instantiate", "teardown").
        status: Terminal status ("completed", "failed", "partial").
        started_at: Pipeline start time (ISO format string or None).
        completed_at: Pipeline completion time (ISO format string or None).
        duration_seconds: Total pipeline duration in seconds.
        steps_completed: Number of successfully completed steps.
        steps_failed: Number of failed steps.
        steps_skipped: Number of skipped steps.
        step_results: Per-step outcome dict.
        error_message: Pipeline-level error message if status is "failed".
        triggered_by: Who triggered the pipeline (e.g., "lablet-controller").
        lablet_session_id: LabletSession ID that owns this pipeline run.
    """

    lab_record_id: str
    pipeline_name: str
    status: str = "completed"
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None
    steps_completed: int = 0
    steps_failed: int = 0
    steps_skipped: int = 0
    step_results: dict | None = None
    error_message: str | None = None
    triggered_by: str = "lablet-controller"
    lablet_session_id: str | None = None


class AppendPipelineRunCommandHandler(
    CommandHandlerBase,
    CommandHandler[AppendPipelineRunCommand, OperationResult[dict]],
):
    """Handler for AppendPipelineRunCommand — appends a pipeline run to the LabRecord."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        lab_record_repository: LabRecordRepository,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._lab_repository = lab_record_repository

    async def handle_async(self, request: AppendPipelineRunCommand) -> OperationResult[dict]:
        """Append a pipeline execution record to the LabRecord aggregate."""
        with tracer.start_as_current_span("append_pipeline_run_command") as span:
            span.set_attribute("lab_record.id", request.lab_record_id)
            span.set_attribute("pipeline.name", request.pipeline_name)
            span.set_attribute("pipeline.status", request.status)

            try:
                lab = await self._lab_repository.get_by_id_async(request.lab_record_id)
                if not lab:
                    return self.not_found(LabRecord, request.lab_record_id)

                # Parse timestamps
                started_at = self._parse_datetime(request.started_at) or datetime.now(timezone.utc)
                completed_at = self._parse_datetime(request.completed_at)

                # Generate unique run ID
                run_id = str(uuid.uuid4())

                # Create PipelineRunRecord VO
                pipeline_run = PipelineRunRecord(
                    run_id=run_id,
                    pipeline_name=request.pipeline_name,
                    started_at=started_at,
                    completed_at=completed_at,
                    status=request.status,
                    step_results=request.step_results,
                    error_message=request.error_message,
                    triggered_by=request.triggered_by,
                    lablet_session_id=request.lablet_session_id,
                    duration_seconds=request.duration_seconds,
                    steps_completed=request.steps_completed,
                    steps_failed=request.steps_failed,
                    steps_skipped=request.steps_skipped,
                )

                # Append on aggregate (emits domain event, bounded list)
                lab.append_pipeline_run(pipeline_run)
                await self._lab_repository.update_async(lab)

                log.info(
                    "Pipeline run recorded: run_id=%s, lab_record_id=%s, pipeline=%s, status=%s, duration=%.1fs",
                    run_id,
                    request.lab_record_id,
                    request.pipeline_name,
                    request.status,
                    request.duration_seconds or 0,
                )

                return self.created(
                    {
                        "run_id": run_id,
                        "lab_record_id": request.lab_record_id,
                        "pipeline_name": request.pipeline_name,
                        "status": request.status,
                        "started_at": started_at.isoformat(),
                        "completed_at": completed_at.isoformat() if completed_at else None,
                        "duration_seconds": request.duration_seconds,
                        "steps_completed": request.steps_completed,
                        "steps_failed": request.steps_failed,
                        "steps_skipped": request.steps_skipped,
                        "message": "Pipeline run recorded",
                    }
                )

            except Exception as e:
                error_msg = f"Error recording pipeline run for lab {request.lab_record_id}: {e}"
                log.error(error_msg, exc_info=True)
                return self.internal_server_error(error_msg)

    def _parse_datetime(self, value: str | None) -> datetime | None:
        """Parse an ISO format datetime string, returning None if empty."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None
