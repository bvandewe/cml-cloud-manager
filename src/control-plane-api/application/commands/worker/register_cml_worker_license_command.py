"""Register CML Worker license command and handler.

ADR-016: This command is DB-only. It stores the license registration intent
in the database. The WorkerReconciler in worker-controller will observe this
and execute the actual CML API call.
"""

import logging
from dataclasses import dataclass

from domain.enums import CMLWorkerStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from infrastructure.observability.cqrs_instrumentation import instrumented
from neuroglia.core import OperationResult
from neuroglia.mediation.mediator import Command, CommandHandler

log = logging.getLogger(__name__)


@dataclass
class RegisterCMLWorkerLicenseCommand(Command[OperationResult[dict]]):
    """Command to request CML Worker license registration.

    ADR-016: This command stores the intent in the database.
    Worker-controller reconciles by calling the CML API.
    """

    worker_id: str
    license_token: str
    reregister: bool = False
    initiated_by: str | None = None


@instrumented
class RegisterCMLWorkerLicenseCommandHandler(CommandHandler[RegisterCMLWorkerLicenseCommand, OperationResult[dict]]):
    """Handler for RegisterCMLWorkerLicenseCommand.

    ADR-016: DB-only handler. Does NOT call CML API directly.
    """

    def __init__(
        self,
        worker_repository: CMLWorkerRepository,
    ):
        super().__init__()
        self._repository = worker_repository

    async def handle_async(
        self,
        request: RegisterCMLWorkerLicenseCommand,
    ) -> OperationResult[dict]:
        """Handle license registration command.

        ADR-016: Stores intent only. Does NOT call CML API.

        Steps:
        1. Validate worker exists and is in appropriate state
        2. Store license registration intent (pending_token, pending_operation)
        3. Return 202 Accepted
        4. WorkerReconciler will observe and execute the CML API call
        """
        # Validate worker exists
        worker = await self._repository.get_by_id_async(request.worker_id)
        if not worker:
            return self.not_found("Worker", f"Worker {request.worker_id} not found")

        # Check worker is running or ready
        if worker.state.status not in [CMLWorkerStatus.RUNNING, CMLWorkerStatus.READY]:
            return self.bad_request(f"Worker must be running to register license (current: {worker.state.status.value})")

        # Check if license operation is already in progress
        if worker.state.license.operation_in_progress:
            return self.conflict("License operation already in progress")

        # Check if registration is already pending
        if worker.state.license.pending_operation == "register":
            return self.conflict("License registration already pending")

        try:
            # Store intent - worker-controller will reconcile
            worker.request_license_registration(
                license_token=request.license_token,
                initiated_by=request.initiated_by,
                reregister=request.reregister,
            )
            await self._repository.update_async(worker)

            log.info(f"📝 License registration requested for worker {request.worker_id} (ADR-016: DB-only)")
            return self.accepted(
                {
                    "message": "License registration queued",
                    "worker_id": request.worker_id,
                    "status": "pending",
                    "note": "Worker-controller will execute registration. Monitor worker status for completion.",
                }
            )

        except Exception as e:
            log.error(f"Failed to request license registration for worker {request.worker_id}: {e}")
            return self.internal_server_error(f"License registration request failed: {e}")
