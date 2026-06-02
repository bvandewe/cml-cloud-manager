"""Record Lab Run Command — internal command to log a start→stop execution cycle.

Phase 8 (P8-12): Called by lablet-controller when it detects a lab execution
cycle (start → stop). Records a LabRunRecord value object on the LabRecord aggregate.

Architecture ref: §4.1 (LabRunRecord VO), §8.2 (internal endpoints).
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from domain.entities.lab_record import LabRecord
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.value_objects.lab_run_record import LabRunRecord
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler
from opentelemetry import trace

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class RecordLabRunCommand(Command[OperationResult[dict]]):
    """Internal command to record a lab execution cycle.

    Records a LabRunRecord on the LabRecord aggregate for run history tracking.

    Attributes:
        lab_record_id: LabRecord aggregate ID.
        started_at: When the lab was started (ISO format string or datetime).
        stopped_at: When the lab was stopped (None if still running).
        started_by: Who started the lab (e.g., "reconciler", "user:admin").
        stop_reason: Why the lab was stopped (e.g., "timeslot_end", "user_request").
        lablet_session_id: Optional LabletSession that triggered this run.
        final_state: Lab state at end of run (e.g., "stopped", "wiped").
    """

    lab_record_id: str
    started_at: str | None = None
    stopped_at: str | None = None
    started_by: str = "system"
    stop_reason: str | None = None
    lablet_session_id: str | None = None
    final_state: str | None = None


class RecordLabRunCommandHandler(
    CommandHandlerBase,
    CommandHandler[RecordLabRunCommand, OperationResult[dict]],
):
    """Handler for RecordLabRunCommand — records a run cycle on the LabRecord."""

    def __init__(self, lab_record_repository: LabRecordRepository):
        self._lab_repository = lab_record_repository

    async def handle_async(self, request: RecordLabRunCommand) -> OperationResult[dict]:
        """Record a lab execution cycle on the LabRecord aggregate."""
        with tracer.start_as_current_span("record_lab_run_command") as span:
            span.set_attribute("lab_record.id", request.lab_record_id)

            try:
                lab = await self._lab_repository.get_by_id_async(request.lab_record_id)
                if not lab:
                    return self.not_found(LabRecord, request.lab_record_id)

                # Parse timestamps
                started_at = self._parse_datetime(request.started_at) or datetime.now(timezone.utc)
                stopped_at = self._parse_datetime(request.stopped_at)

                # Calculate duration
                duration_seconds = None
                if stopped_at:
                    duration_seconds = int((stopped_at - started_at).total_seconds())

                # Create run record VO
                run_id = str(uuid.uuid4())
                run_record = LabRunRecord(
                    run_id=run_id,
                    started_at=started_at,
                    stopped_at=stopped_at,
                    duration_seconds=duration_seconds,
                    started_by=request.started_by,
                    stop_reason=request.stop_reason,
                    lablet_session_id=request.lablet_session_id,
                    final_state=request.final_state,
                )

                # Record on aggregate (bounded list)
                lab.record_run(run_record)
                await self._lab_repository.update_async(lab)

                log.info(
                    "Lab run recorded: run_id=%s, lab_record_id=%s, duration=%ss, started_by=%s",
                    run_id,
                    request.lab_record_id,
                    duration_seconds,
                    request.started_by,
                )

                return self.created(
                    {
                        "run_id": run_id,
                        "lab_record_id": request.lab_record_id,
                        "started_at": started_at.isoformat(),
                        "stopped_at": stopped_at.isoformat() if stopped_at else None,
                        "duration_seconds": duration_seconds,
                        "started_by": request.started_by,
                        "message": "Run recorded",
                    }
                )

            except Exception as e:
                error_msg = f"Error recording run for lab {request.lab_record_id}: {e}"
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
