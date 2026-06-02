"""Start Lab Record Command — sets pending_action=start for reconciliation (ADR-017).

Phase 8 (P8-2): Refactored from ControlLabCommand into a dedicated typed command.
Uses LabRecordStatus-aware pending action flow:
1. Control-plane-api sets pending_action=start on LabRecord (DB-only)
2. Lablet-controller watches etcd, sees pending start action
3. Lablet-controller starts the lab via CML API
4. Lablet-controller reports success/failure via internal API
"""

import logging
from dataclasses import dataclass

from domain.entities.lab_record import LabRecord
from domain.repositories.lab_record_repository import LabRecordRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler
from opentelemetry import trace

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class StartLabRecordCommand(Command[OperationResult[dict]]):
    """Command to start a lab (boot all nodes).

    ADR-017: Sets pending_action=start for reconciliation.
    The actual CML API call is performed by lablet-controller.

    Attributes:
        lab_record_id: LabRecord aggregate ID (not CML lab_id).
        started_by: Who requested the start (e.g., "user:admin", "reconciler").
    """

    lab_record_id: str
    started_by: str = "user"


class StartLabRecordCommandHandler(
    CommandHandlerBase,
    CommandHandler[StartLabRecordCommand, OperationResult[dict]],
):
    """Handler for StartLabRecordCommand — queues lab start for reconciliation."""

    def __init__(self, lab_record_repository: LabRecordRepository):
        self._lab_repository = lab_record_repository

    async def handle_async(self, request: StartLabRecordCommand) -> OperationResult[dict]:
        """Queue lab start for reconciliation.

        ADR-017: Sets pending_action=start on LabRecord, returns 202 Accepted.
        Lablet-controller will reconcile the actual start operation.
        """
        with tracer.start_as_current_span("start_lab_record_command") as span:
            span.set_attribute("lab_record.id", request.lab_record_id)
            span.set_attribute("lab.started_by", request.started_by)
            span.set_attribute("adr", "ADR-017")

            try:
                # 1. Get lab record
                lab = await self._lab_repository.get_by_id_async(request.lab_record_id)
                if not lab:
                    return self.not_found(LabRecord, request.lab_record_id)

                # 2. Check for pending action conflict
                if lab.state.pending_action:
                    return self.conflict(f"Lab already has pending action: {lab.state.pending_action}. Wait for it to complete or clear it first.")

                # 3. Check terminal state
                if lab.is_terminal:
                    return self.bad_request(f"Cannot start lab in terminal state: {lab.state.status.value}")

                # 4. Set pending start action (DB-only, no CML call!)
                lab.request_start()

                # 5. Persist
                await self._lab_repository.update_async(lab)

                log.info(
                    "Lab start queued for lab_record_id=%s (lab_id=%s). Lablet-controller will reconcile.",
                    request.lab_record_id,
                    lab.state.lab_id,
                )

                return self.accepted(
                    {
                        "lab_record_id": request.lab_record_id,
                        "lab_id": lab.state.lab_id,
                        "worker_id": lab.state.worker_id,
                        "action": "start",
                        "status": "pending",
                        "message": "Start queued for reconciliation",
                    }
                )

            except Exception as e:
                error_msg = f"Error queuing start for lab {request.lab_record_id}: {e}"
                log.error(error_msg, exc_info=True)
                return self.internal_server_error(error_msg)
