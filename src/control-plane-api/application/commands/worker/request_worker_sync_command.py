"""Request Worker Sync command (AD-043).

This command triggers full state synchronization for a worker via etcd watch.
Unlike refresh (data collection only), sync forces the worker-controller to
re-evaluate actual EC2 + CML state, correct status mismatches, and optionally
trigger lab record reconciliation.

Signal chain: API → command → domain event → etcd projector →
/workers/{id}/sync → worker-controller watch → full reconciliation → clear key.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from domain.enums import CMLWorkerStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)


@dataclass
class RequestWorkerSyncCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to request full synchronization of a worker's state.

    This triggers reactive reconciliation via etcd watch, forcing the
    worker-controller to re-read actual EC2 + CML state and align it
    with desired state. Works for any non-terminal worker status.
    """

    worker_id: str
    scope: str = "full"  # "full" | "ec2_only" | "cml_only"
    include_labs: bool = True  # Trigger lab record reconciliation
    reason: str = "manual"  # Audit trail
    requested_by: str = "user"


class RequestWorkerSyncCommandHandler(
    CommandHandlerBase,
    CommandHandler[RequestWorkerSyncCommand, OperationResult[dict[str, Any]]],
):
    """Handle requesting full worker state synchronization."""

    def __init__(self, cml_worker_repository: CMLWorkerRepository):
        self.cml_worker_repository = cml_worker_repository

    async def handle_async(self, request: RequestWorkerSyncCommand) -> OperationResult[dict[str, Any]]:
        log.info(f"Requesting sync for worker {request.worker_id} (scope={request.scope}, include_labs={request.include_labs})")

        worker = await self.cml_worker_repository.get_by_id_async(request.worker_id)

        if not worker:
            return self.not_found("CMLWorker", f"Worker {request.worker_id} not found")

        if worker.state.status == CMLWorkerStatus.TERMINATED:
            return self.bad_request("Cannot sync a terminated worker — no resources to reconcile")

        requested_at = datetime.now(timezone.utc).isoformat()

        worker.request_sync(
            requested_at=requested_at,
            requested_by=request.requested_by,
            scope=request.scope,
            include_labs=request.include_labs,
            reason=request.reason,
        )
        await self.cml_worker_repository.update_async(worker)

        log.info(f"Sync requested for worker {request.worker_id}: scope={request.scope}, include_labs={request.include_labs}")

        return self.accepted(
            {
                "worker_id": request.worker_id,
                "sync_requested": True,
                "scope": request.scope,
                "include_labs": request.include_labs,
                "message": "Synchronization requested. Worker state will be reconciled immediately.",
            }
        )
