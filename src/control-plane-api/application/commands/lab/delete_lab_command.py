"""Delete Lab Command - queues lab deletion for reconciliation (ADR-017).

ADR-017: Lab delete operations use the reconciliation pattern:
1. Control-plane-api sets pending_action=delete on LabRecord (DB-only)
2. Lablet-controller watches etcd, sees pending delete action
3. Lablet-controller deletes the lab via CML API
4. Lablet-controller removes the LabRecord via internal API
"""

import logging
from dataclasses import dataclass

from neuroglia.core.operation_result import OperationResult
from neuroglia.mediation import Command, CommandHandler, Mediator
from opentelemetry import trace

from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.lab_record_repository import LabRecordRepository

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class DeleteLabCommand(Command[OperationResult[dict]]):
    """Command to delete a lab from a CML worker.

    ADR-017: This command sets pending_action=delete for reconciliation.
    The actual CML API call is performed by lablet-controller.

    Attributes:
        worker_id: Worker ID hosting the lab
        lab_id: Lab identifier to delete
    """

    worker_id: str
    lab_id: str


class DeleteLabCommandHandler(CommandHandler[DeleteLabCommand, OperationResult[dict]]):
    """Handler for DeleteLabCommand - queues lab deletion for reconciliation.

    ADR-017: This handler only updates the database, setting pending_action=delete.
    Lablet-controller reconciles by deleting the lab via CML API.
    """

    def __init__(
        self,
        mediator: Mediator,
        worker_repository: CMLWorkerRepository,
        lab_record_repository: LabRecordRepository,
    ):
        """Initialize handler with repository dependencies.

        Args:
            mediator: Mediator for triggering other commands
            worker_repository: Repository for accessing CML worker data
            lab_record_repository: Repository for accessing lab records
        """
        self._mediator = mediator
        self._worker_repository = worker_repository
        self._lab_record_repository = lab_record_repository

    async def handle_async(self, request: DeleteLabCommand, cancellation_token=None) -> OperationResult[dict]:
        """Queue lab deletion for reconciliation.

        ADR-017: Sets pending_action=delete on LabRecord, returns 202 Accepted.
        Lablet-controller will reconcile the actual deletion.

        Args:
            request: Command containing worker_id and lab_id
            cancellation_token: Optional cancellation token

        Returns:
            OperationResult with accepted status (async processing)
        """
        with tracer.start_as_current_span("delete_lab_command") as span:
            span.set_attribute("worker.id", request.worker_id)
            span.set_attribute("lab.id", request.lab_id)
            span.set_attribute("adr", "ADR-017")
            span.set_attribute("pattern", "reconciliation")

            try:
                # 1. Validate worker exists
                worker = await self._worker_repository.get_by_id_async(request.worker_id)
                if not worker:
                    error_msg = f"Worker {request.worker_id} not found"
                    log.error(error_msg)
                    return self.not_found("Worker", error_msg)

                # 2. Get lab record from repository
                lab = await self._lab_record_repository.get_by_lab_id_async(
                    worker_id=request.worker_id,
                    lab_id=request.lab_id,
                )
                if not lab:
                    error_msg = f"Lab {request.lab_id} not found on worker {request.worker_id}"
                    log.error(error_msg)
                    return self.not_found("Lab", error_msg)

                # 3. Check if there's already a pending action
                if lab.state.pending_action:
                    error_msg = f"Lab {request.lab_id} already has pending action: {lab.state.pending_action}. Wait for it to complete or clear it first."
                    log.warning(error_msg)
                    return self.conflict(error_msg)

                # 4. Set pending delete action (DB-only, no CML call!)
                lab.request_delete()
                log.info(f"Set pending_action=delete for lab {request.lab_id}")

                # 5. Save lab record with pending action
                await self._lab_record_repository.update_async(lab)

                # 6. Return 202 Accepted - lablet-controller will reconcile
                log.info(f"Lab deletion queued for lab {request.lab_id}. Lablet-controller will reconcile.")
                return self.accepted(
                    {
                        "lab_id": request.lab_id,
                        "worker_id": request.worker_id,
                        "status": "pending_delete",
                        "message": "Delete queued for reconciliation",
                    }
                )

            except Exception as e:
                error_msg = f"Error queuing delete for lab {request.lab_id}: {str(e)}"
                log.error(error_msg, exc_info=True)
                return self.internal_server_error(error_msg)
