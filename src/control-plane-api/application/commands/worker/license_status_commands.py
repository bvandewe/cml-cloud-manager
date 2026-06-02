"""License status commands for internal API.

ADR-016: These commands are called by worker-controller to report
license operation progress back to control-plane-api.

Each command updates the worker's license state based on the operation phase:
- Start: Mark operation as in-progress
- Complete: Mark operation as successful, update license details
- Fail: Mark operation as failed with error details
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from application.commands.command_handler_base import CommandHandlerBase
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from neuroglia.core import OperationResult
from neuroglia.mediation.mediator import Command, CommandHandler

log = logging.getLogger(__name__)


# =============================================================================
# License Registration Status Commands
# =============================================================================


@dataclass
class StartLicenseRegistrationCommand(Command[OperationResult[dict]]):
    """Command to mark license registration as started.

    Called by worker-controller when it begins the CML API registration call.
    """

    worker_id: str
    initiated_by: str | None = None


class StartLicenseRegistrationCommandHandler(CommandHandlerBase, CommandHandler[StartLicenseRegistrationCommand, OperationResult[dict]]):
    """Handler for StartLicenseRegistrationCommand."""

    def __init__(self, worker_repository: CMLWorkerRepository):
        self._repository = worker_repository

    async def handle_async(self, request: StartLicenseRegistrationCommand) -> OperationResult[dict]:
        """Mark license registration as started."""
        worker = await self._repository.get_by_id_async(request.worker_id)
        if not worker:
            return self.not_found("Worker", f"Worker {request.worker_id} not found")

        try:
            worker.start_license_registration(
                started_at=datetime.now(timezone.utc).isoformat(),
                initiated_by=request.initiated_by,
            )
            await self._repository.update_async(worker)

            log.info(f"📝 License registration started for worker {request.worker_id}")
            return self.ok({"worker_id": request.worker_id, "status": "in_progress"})

        except Exception as e:
            log.error(f"Failed to start license registration for worker {request.worker_id}: {e}")
            return self.internal_server_error(str(e))


@dataclass
class CompleteLicenseRegistrationCommand(Command[OperationResult[dict]]):
    """Command to mark license registration as completed.

    Called by worker-controller after successful CML API registration.
    """

    worker_id: str
    registration_status: str
    smart_account: str | None = None
    virtual_account: str | None = None


class CompleteLicenseRegistrationCommandHandler(CommandHandlerBase, CommandHandler[CompleteLicenseRegistrationCommand, OperationResult[dict]]):
    """Handler for CompleteLicenseRegistrationCommand."""

    def __init__(self, worker_repository: CMLWorkerRepository):
        self._repository = worker_repository

    async def handle_async(self, request: CompleteLicenseRegistrationCommand) -> OperationResult[dict]:
        """Mark license registration as completed."""
        worker = await self._repository.get_by_id_async(request.worker_id)
        if not worker:
            return self.not_found("Worker", f"Worker {request.worker_id} not found")

        try:
            worker.complete_license_registration(
                registration_status=request.registration_status,
                smart_account=request.smart_account,
                virtual_account=request.virtual_account,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            await self._repository.update_async(worker)

            log.info(f"✅ License registration completed for worker {request.worker_id}")
            return self.ok(
                {
                    "worker_id": request.worker_id,
                    "status": "completed",
                    "registration_status": request.registration_status,
                }
            )

        except Exception as e:
            log.error(f"Failed to complete license registration for worker {request.worker_id}: {e}")
            return self.internal_server_error(str(e))


@dataclass
class FailLicenseRegistrationCommand(Command[OperationResult[dict]]):
    """Command to mark license registration as failed.

    Called by worker-controller when CML API registration fails.
    """

    worker_id: str
    error_message: str
    error_code: str | None = None


class FailLicenseRegistrationCommandHandler(CommandHandlerBase, CommandHandler[FailLicenseRegistrationCommand, OperationResult[dict]]):
    """Handler for FailLicenseRegistrationCommand."""

    def __init__(self, worker_repository: CMLWorkerRepository):
        self._repository = worker_repository

    async def handle_async(self, request: FailLicenseRegistrationCommand) -> OperationResult[dict]:
        """Mark license registration as failed."""
        worker = await self._repository.get_by_id_async(request.worker_id)
        if not worker:
            return self.not_found("Worker", f"Worker {request.worker_id} not found")

        try:
            worker.fail_license_registration(
                error_message=request.error_message,
                error_code=request.error_code,
                failed_at=datetime.now(timezone.utc).isoformat(),
            )
            await self._repository.update_async(worker)

            log.warning(f"❌ License registration failed for worker {request.worker_id}: {request.error_message}")
            return self.ok({"worker_id": request.worker_id, "status": "failed", "error": request.error_message})

        except Exception as e:
            log.error(f"Failed to record license registration failure for worker {request.worker_id}: {e}")
            return self.internal_server_error(str(e))


# =============================================================================
# License Deregistration Status Commands
# =============================================================================


@dataclass
class StartLicenseDeregistrationCommand(Command[OperationResult[dict]]):
    """Command to mark license deregistration as started.

    Called by worker-controller when it begins the CML API deregistration call.
    """

    worker_id: str
    initiated_by: str | None = None


class StartLicenseDeregistrationCommandHandler(CommandHandlerBase, CommandHandler[StartLicenseDeregistrationCommand, OperationResult[dict]]):
    """Handler for StartLicenseDeregistrationCommand."""

    def __init__(self, worker_repository: CMLWorkerRepository):
        self._repository = worker_repository

    async def handle_async(self, request: StartLicenseDeregistrationCommand) -> OperationResult[dict]:
        """Mark license deregistration as started."""
        worker = await self._repository.get_by_id_async(request.worker_id)
        if not worker:
            return self.not_found("Worker", f"Worker {request.worker_id} not found")

        try:
            worker.start_license_deregistration(
                started_at=datetime.now(timezone.utc).isoformat(),
                initiated_by=request.initiated_by,
            )
            await self._repository.update_async(worker)

            log.info(f"📝 License deregistration started for worker {request.worker_id}")
            return self.ok({"worker_id": request.worker_id, "status": "in_progress"})

        except Exception as e:
            log.error(f"Failed to start license deregistration for worker {request.worker_id}: {e}")
            return self.internal_server_error(str(e))


@dataclass
class CompleteLicenseDeregistrationCommand(Command[OperationResult[dict]]):
    """Command to mark license deregistration as completed.

    Called by worker-controller after successful CML API deregistration.
    """

    worker_id: str
    message: str = "License deregistered successfully"


class CompleteLicenseDeregistrationCommandHandler(CommandHandlerBase, CommandHandler[CompleteLicenseDeregistrationCommand, OperationResult[dict]]):
    """Handler for CompleteLicenseDeregistrationCommand."""

    def __init__(self, worker_repository: CMLWorkerRepository):
        self._repository = worker_repository

    async def handle_async(self, request: CompleteLicenseDeregistrationCommand) -> OperationResult[dict]:
        """Mark license deregistration as completed."""
        worker = await self._repository.get_by_id_async(request.worker_id)
        if not worker:
            return self.not_found("Worker", f"Worker {request.worker_id} not found")

        try:
            worker.complete_license_deregistration(
                message=request.message,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            await self._repository.update_async(worker)

            log.info(f"✅ License deregistration completed for worker {request.worker_id}")
            return self.ok({"worker_id": request.worker_id, "status": "completed", "message": request.message})

        except Exception as e:
            log.error(f"Failed to complete license deregistration for worker {request.worker_id}: {e}")
            return self.internal_server_error(str(e))


@dataclass
class FailLicenseDeregistrationCommand(Command[OperationResult[dict]]):
    """Command to mark license deregistration as failed.

    Called by worker-controller when CML API deregistration fails.
    """

    worker_id: str
    error_message: str


class FailLicenseDeregistrationCommandHandler(CommandHandlerBase, CommandHandler[FailLicenseDeregistrationCommand, OperationResult[dict]]):
    """Handler for FailLicenseDeregistrationCommand."""

    def __init__(self, worker_repository: CMLWorkerRepository):
        self._repository = worker_repository

    async def handle_async(self, request: FailLicenseDeregistrationCommand) -> OperationResult[dict]:
        """Mark license deregistration as failed."""
        worker = await self._repository.get_by_id_async(request.worker_id)
        if not worker:
            return self.not_found("Worker", f"Worker {request.worker_id} not found")

        try:
            worker.fail_license_deregistration(
                error_message=request.error_message,
                failed_at=datetime.now(timezone.utc).isoformat(),
            )
            await self._repository.update_async(worker)

            log.warning(f"❌ License deregistration failed for worker {request.worker_id}: {request.error_message}")
            return self.ok({"worker_id": request.worker_id, "status": "failed", "error": request.error_message})

        except Exception as e:
            log.error(f"Failed to record license deregistration failure for worker {request.worker_id}: {e}")
            return self.internal_server_error(str(e))
