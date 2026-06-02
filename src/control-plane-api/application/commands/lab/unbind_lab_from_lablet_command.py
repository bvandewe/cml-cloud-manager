"""Unbind Lab from Lablet Command — releases the binding between a LabRecord and LabletSession.

Phase 7F: Refactored to use LabletSession.lab_record_id (direct 1:1 FK)
instead of the deprecated LabletLabBinding entity (ADR-020 §2).

Architecture ref: §5.2 (binding lifecycle), §8.4 (unbind endpoint).
"""

import logging
from dataclasses import dataclass

from domain.entities.lab_record import LabRecord
from domain.entities.lablet_session import LabletSession
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler
from opentelemetry import trace

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class UnbindLabFromLabletCommand(Command[OperationResult[dict]]):
    """Command to release a binding between a LabRecord and LabletSession.

    Attributes:
        lab_record_id: LabRecord aggregate ID.
        lablet_session_id: LabletSession aggregate ID.
        reason: Why the binding is being released (e.g., "timeslot_end", "user_request").
    """

    lab_record_id: str
    lablet_session_id: str
    reason: str | None = None


class UnbindLabFromLabletCommandHandler(
    CommandHandlerBase,
    CommandHandler[UnbindLabFromLabletCommand, OperationResult[dict]],
):
    """Handler for UnbindLabFromLabletCommand — clears lab_record_id on session and records event."""

    def __init__(self, lab_record_repository: LabRecordRepository, lablet_session_repository: LabletSessionRepository):
        self._lab_repository = lab_record_repository
        self._session_repository = lablet_session_repository

    async def handle_async(self, request: UnbindLabFromLabletCommand) -> OperationResult[dict]:
        """Release a binding between LabRecord and LabletSession."""
        with tracer.start_as_current_span("unbind_lab_from_lablet_command") as span:
            span.set_attribute("lab_record.id", request.lab_record_id)
            span.set_attribute("lablet_session.id", request.lablet_session_id)

            try:
                # 1. Validate lab record exists
                lab = await self._lab_repository.get_by_id_async(request.lab_record_id)
                if not lab:
                    return self.not_found(LabRecord, request.lab_record_id)

                # 2. Validate session exists and is bound to this lab
                session = await self._session_repository.get_by_id_async(request.lablet_session_id)
                if not session:
                    return self.not_found(LabletSession, request.lablet_session_id)

                if session.state.lab_record_id != request.lab_record_id:
                    return self.not_found(
                        LabletSession,
                        f"No active binding between LabRecord {request.lab_record_id} and LabletSession {request.lablet_session_id}",
                    )

                # 3. Clear the binding on session (direct 1:1 FK, ADR-020 §2)
                session.state.lab_record_id = None
                await self._session_repository.update_async(session)

                # 4. Record unbinding event on LabRecord aggregate
                lab.unbind_from_lablet(
                    lablet_session_id=request.lablet_session_id,
                    binding_id=request.lablet_session_id,
                )
                await self._lab_repository.update_async(lab)

                log.info(
                    "Lab unbound from lablet session: lab_record_id=%s, lablet_session_id=%s, reason=%s",
                    request.lab_record_id,
                    request.lablet_session_id,
                    request.reason,
                )

                return self.ok(
                    {
                        "binding_id": request.lablet_session_id,
                        "lab_record_id": request.lab_record_id,
                        "lablet_session_id": request.lablet_session_id,
                        "status": "released",
                        "reason": request.reason,
                        "message": "Binding released",
                    }
                )

            except Exception as e:
                error_msg = f"Error unbinding lab {request.lab_record_id} from session {request.lablet_session_id}: {e}"
                log.error(error_msg, exc_info=True)
                return self.internal_server_error(error_msg)
