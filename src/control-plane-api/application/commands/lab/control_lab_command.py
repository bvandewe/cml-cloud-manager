"""Lab Control Commands - Start, Stop, Wipe operations (ADR-017 Reconciliation Pattern).

ADR-017: Lab control operations use the reconciliation pattern:
1. Control-plane-api sets pending_action on LabRecord (DB-only)
2. Lablet-controller watches etcd, sees pending action
3. Lablet-controller executes the action via CML API
4. Lablet-controller reports success/failure via internal API
"""

import logging
from dataclasses import dataclass
from enum import Enum

from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.lab_record_repository import LabRecordRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler
from opentelemetry import trace

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class LabAction(str, Enum):
    """Supported lab actions."""

    START = "start"
    STOP = "stop"
    WIPE = "wipe"


@dataclass
class ControlLabCommand(Command[OperationResult[dict]]):
    """Command to control a lab (start/stop/wipe).

    ADR-017: This command sets a pending action for reconciliation.
    The actual CML API call is performed by lablet-controller.

    Attributes:
        worker_id: Worker ID hosting the lab
        lab_id: Lab identifier (CML lab ID)
        action: Action to perform (start/stop/wipe)
    """

    worker_id: str
    lab_id: str
    action: LabAction


class ControlLabCommandHandler(
    CommandHandlerBase,
    CommandHandler[ControlLabCommand, OperationResult[dict]],
):
    """Handler for lab control operations.

    ADR-017: This handler only updates the database, setting pending_action.
    Lablet-controller reconciles by watching etcd and executing CML API calls.
    """

    def __init__(self, cml_worker_repository: CMLWorkerRepository, lab_record_repository: LabRecordRepository):
        self._worker_repository = cml_worker_repository
        self._lab_repository = lab_record_repository

    async def handle_async(self, request: ControlLabCommand) -> OperationResult[dict]:
        """Handle lab control command by setting pending action.

        ADR-017: Sets pending_action on LabRecord, returns 202 Accepted.
        Lablet-controller will reconcile the actual operation.

        Args:
            request: Control command with worker_id, lab_id, and action

        Returns:
            OperationResult with accepted status (async processing)
        """
        command = request

        with tracer.start_as_current_span("control_lab_command") as span:
            span.set_attribute("worker.id", command.worker_id)
            span.set_attribute("lab.id", command.lab_id)
            span.set_attribute("lab.action", command.action.value)
            span.set_attribute("adr", "ADR-017")
            span.set_attribute("pattern", "reconciliation")

            try:
                # 1. Validate worker exists
                worker = await self._worker_repository.get_by_id_async(command.worker_id)
                if not worker:
                    error_msg = f"Worker {command.worker_id} not found"
                    log.error(error_msg)
                    return self.not_found("Worker", error_msg)

                # 2. Get lab record from repository
                lab = await self._lab_repository.get_by_lab_id_async(
                    worker_id=command.worker_id,
                    lab_id=command.lab_id,
                )
                if not lab:
                    error_msg = f"Lab {command.lab_id} not found on worker {command.worker_id}"
                    log.error(error_msg)
                    return self.not_found("Lab", error_msg)

                # 3. Check if there's already a pending action
                if lab.state.pending_action:
                    error_msg = f"Lab {command.lab_id} already has pending action: {lab.state.pending_action}. Wait for it to complete or clear it first."
                    log.warning(error_msg)
                    return self.conflict(error_msg)

                # 4. Set pending action based on requested action (DB-only, no CML call!)
                if command.action == LabAction.START:
                    lab.request_start()
                    log.info(f"Set pending_action=start for lab {command.lab_id}")
                elif command.action == LabAction.STOP:
                    lab.request_stop()
                    log.info(f"Set pending_action=stop for lab {command.lab_id}")
                elif command.action == LabAction.WIPE:
                    lab.request_wipe()
                    log.info(f"Set pending_action=wipe for lab {command.lab_id}")
                else:
                    error_msg = f"Unknown action: {command.action}"
                    log.error(error_msg)
                    return self.bad_request(error_msg)

                # 5. Save lab record with pending action
                await self._lab_repository.update_async(lab)

                # 6. Return 202 Accepted - lablet-controller will reconcile
                log.info(f"Lab control {command.action.value} queued for lab {command.lab_id}. Lablet-controller will reconcile.")
                return self.accepted(
                    {
                        "lab_id": command.lab_id,
                        "worker_id": command.worker_id,
                        "action": command.action.value,
                        "status": "pending",
                        "message": f"Action '{command.action.value}' queued for reconciliation",
                    }
                )

            except Exception as e:
                error_msg = f"Error queuing {command.action.value} for lab {command.lab_id}: {str(e)}"
                log.error(error_msg, exc_info=True)
                return self.internal_server_error(error_msg)
