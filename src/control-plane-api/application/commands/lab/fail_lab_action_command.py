"""Fail Lab Action Command — internal command to mark a pending action as failed.

Phase 8 (P8-14): Called by lablet-controller (via internal API) when a CML API
operation fails. Stores the error message and optionally transitions the
LabRecord to ERROR state.

Architecture ref: §8.2 (internal endpoints), ADR-017 (reconciliation pattern).
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
class FailLabActionCommand(Command[OperationResult[dict]]):
    """Internal command to mark a pending action as failed.

    Called by lablet-controller when a CML API operation fails.

    Attributes:
        lab_record_id: LabRecord aggregate ID.
        error_message: Description of the failure.
        transition_to_error: Whether to transition the LabRecord to ERROR status.
            Default: False (keeps current status, just stores error on pending action).
    """

    lab_record_id: str
    error_message: str
    transition_to_error: bool = False


class FailLabActionCommandHandler(
    CommandHandlerBase,
    CommandHandler[FailLabActionCommand, OperationResult[dict]],
):
    """Handler for FailLabActionCommand — records failure on pending action."""

    def __init__(self, lab_record_repository: LabRecordRepository):
        self._lab_repository = lab_record_repository

    async def handle_async(self, request: FailLabActionCommand) -> OperationResult[dict]:
        """Record action failure on the LabRecord."""
        with tracer.start_as_current_span("fail_lab_action_command") as span:
            span.set_attribute("lab_record.id", request.lab_record_id)
            span.set_attribute("error.message", request.error_message)
            span.set_attribute("adr", "ADR-017")

            try:
                lab = await self._lab_repository.get_by_id_async(request.lab_record_id)
                if not lab:
                    return self.not_found(LabRecord, request.lab_record_id)

                if not lab.state.pending_action:
                    return self.bad_request(f"LabRecord {request.lab_record_id} has no pending action to fail")

                failed_action = lab.state.pending_action

                # 1. Record failure on pending action
                lab.fail_pending_action(request.error_message)

                # 2. Optionally transition to ERROR state
                if request.transition_to_error:
                    try:
                        lab.mark_error(f"Action '{failed_action}' failed: {request.error_message}")
                    except InvalidLabRecordTransitionError as e:
                        log.warning(
                            "Could not transition to ERROR after action failure: %s",
                            str(e),
                        )

                await self._lab_repository.update_async(lab)

                log.warning(
                    "Lab action failed: lab_record_id=%s, action=%s, error=%s, transitioned_to_error=%s",
                    request.lab_record_id,
                    failed_action,
                    request.error_message,
                    request.transition_to_error,
                )

                return self.ok(
                    {
                        "lab_record_id": request.lab_record_id,
                        "action": failed_action,
                        "error_message": request.error_message,
                        "status": lab.state.status.value,
                        "message": f"Action '{failed_action}' marked as failed",
                    }
                )

            except Exception as e:
                error_msg = f"Error failing action for lab {request.lab_record_id}: {e}"
                log.error(error_msg, exc_info=True)
                return self.internal_server_error(error_msg)
