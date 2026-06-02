"""Archive Lab Record Command — marks a LabRecord as archived (terminal state).

Phase 8 (P8-7): Archive exports the lab topology and marks the LabRecord
as archived. This is a terminal state — the lab cannot be started again.

Architecture ref: §8.3 (archive endpoint).
"""

import logging
from dataclasses import dataclass

from domain.entities.lab_record import InvalidLabRecordTransitionError, LabRecord
from domain.repositories.lab_record_repository import LabRecordRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler
from opentelemetry import trace

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class ArchiveLabRecordCommand(Command[OperationResult[dict]]):
    """Command to archive a lab record.

    Marks the LabRecord as ARCHIVED (terminal state).
    Archived labs are kept in the database for history but cannot be started.

    Attributes:
        lab_record_id: LabRecord aggregate ID.
        archived_by: Who requested the archive.
    """

    lab_record_id: str
    archived_by: str = "user"


class ArchiveLabRecordCommandHandler(
    CommandHandlerBase,
    CommandHandler[ArchiveLabRecordCommand, OperationResult[dict]],
):
    """Handler for ArchiveLabRecordCommand — marks lab as archived."""

    def __init__(self, lab_record_repository: LabRecordRepository):
        self._lab_repository = lab_record_repository

    async def handle_async(self, request: ArchiveLabRecordCommand) -> OperationResult[dict]:
        """Archive a lab record (transition to terminal ARCHIVED state)."""
        with tracer.start_as_current_span("archive_lab_record_command") as span:
            span.set_attribute("lab_record.id", request.lab_record_id)
            span.set_attribute("lab.archived_by", request.archived_by)

            try:
                lab = await self._lab_repository.get_by_id_async(request.lab_record_id)
                if not lab:
                    return self.not_found(LabRecord, request.lab_record_id)

                if lab.state.pending_action:
                    return self.conflict(f"Lab has pending action: {lab.state.pending_action}. Complete or clear the action before archiving.")

                if lab.is_terminal:
                    return self.bad_request(f"Lab is already in terminal state: {lab.state.status.value}")

                # Validate transition and apply
                try:
                    lab.mark_archived(archived_by=request.archived_by)
                except InvalidLabRecordTransitionError as e:
                    return self.bad_request(str(e))

                await self._lab_repository.update_async(lab)

                log.info(
                    "Lab archived: lab_record_id=%s (lab_id=%s, by=%s)",
                    request.lab_record_id,
                    lab.state.lab_id,
                    request.archived_by,
                )

                return self.ok(
                    {
                        "lab_record_id": request.lab_record_id,
                        "lab_id": lab.state.lab_id,
                        "worker_id": lab.state.worker_id,
                        "status": "archived",
                        "message": "Lab record archived",
                    }
                )

            except Exception as e:
                error_msg = f"Error archiving lab {request.lab_record_id}: {e}"
                log.error(error_msg, exc_info=True)
                return self.internal_server_error(error_msg)
