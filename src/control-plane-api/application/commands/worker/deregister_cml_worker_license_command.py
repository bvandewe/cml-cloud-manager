"""Deregister CML Worker license command and handler.

ADR-016: This command is DB-only. It stores the license deregistration intent
in the database. The WorkerReconciler in worker-controller will observe this
and execute the actual CML API call.
"""

import logging
from dataclasses import dataclass

from domain.enums import CMLWorkerStatus, LicenseStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from infrastructure.observability.cqrs_instrumentation import instrumented
from neuroglia.core import OperationResult
from neuroglia.mediation.mediator import Command, CommandHandler

log = logging.getLogger(__name__)


@dataclass
class DeregisterCMLWorkerLicenseCommand(Command[OperationResult[dict]]):
    """Command to request CML Worker license deregistration.

    ADR-016: This command stores the intent in the database.
    Worker-controller reconciles by calling the CML API.
    """

    worker_id: str
    initiated_by: str | None = None


@instrumented
class DeregisterCMLWorkerLicenseCommandHandler(CommandHandler[DeregisterCMLWorkerLicenseCommand, OperationResult[dict]]):
    """Handler for DeregisterCMLWorkerLicenseCommand.

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
        request: DeregisterCMLWorkerLicenseCommand,
    ) -> OperationResult[dict]:
        """Handle license deregistration command.

        ADR-016: Stores intent only. Does NOT call CML API.

        Steps:
        1. Validate worker exists and has a registered license
        2. Store license deregistration intent (pending_operation="deregister")
        3. Return 202 Accepted
        4. WorkerReconciler will observe and execute the CML API call
        """
        # Get worker
        worker = await self._repository.get_by_id_async(request.worker_id)
        if not worker:
            return self.not_found("Worker", f"Worker {request.worker_id} not found")

        # Check worker is running or ready
        if worker.state.status not in [CMLWorkerStatus.RUNNING, CMLWorkerStatus.READY]:
            return self.bad_request(f"Worker must be running to deregister license (current: {worker.state.status.value})")

        # Check if license is registered
        if worker.state.license.status != LicenseStatus.REGISTERED:
            return self.bad_request("Worker does not have a registered license")

        # Check if license operation is already in progress
        if worker.state.license.operation_in_progress:
            return self.conflict("License operation already in progress")

        # Check if deregistration is already pending
        if worker.state.license.pending_operation == "deregister":
            return self.conflict("License deregistration already pending")

        try:
            # Store intent - worker-controller will reconcile
            worker.request_license_deregistration(
                initiated_by=request.initiated_by,
            )
            await self._repository.update_async(worker)

            log.info(f"📝 License deregistration requested for worker {request.worker_id} (ADR-016: DB-only)")
            return self.accepted(
                {
                    "message": "License deregistration queued",
                    "worker_id": request.worker_id,
                    "status": "pending",
                    "note": "Worker-controller will execute deregistration. Monitor worker status for completion.",
                }
            )

        except Exception as e:
            log.error(f"Failed to request license deregistration for worker {request.worker_id}: {e}")
            return self.internal_server_error(f"License deregistration request failed: {e}")
