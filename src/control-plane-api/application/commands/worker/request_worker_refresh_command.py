"""Request Worker Refresh command.

This command triggers an on-demand data refresh for a worker.
Sets the refresh_requested_at flag which the worker-controller reconciler
checks during reconciliation to perform a full data collection.

Called by the public API when a user wants to refresh worker data.
"""

import logging
from dataclasses import dataclass
from typing import Any

from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

from domain.enums import CMLWorkerStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)


@dataclass
class RequestWorkerRefreshCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to request on-demand data refresh for a worker.

    Sets refresh_requested_at on the worker. The worker-controller
    will pick this up on next reconciliation and perform a full
    data collection (EC2 details + CML system data).
    """

    worker_id: str
    requested_by: str | None = None


class RequestWorkerRefreshCommandHandler(
    CommandHandlerBase,
    CommandHandler[RequestWorkerRefreshCommand, OperationResult[dict[str, Any]]],
):
    """Handle requesting a worker data refresh."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        cml_worker_repository: CMLWorkerRepository,
    ):
        super().__init__(
            mediator,
            mapper,
            cloud_event_bus,
            cloud_event_publishing_options,
        )
        self.cml_worker_repository = cml_worker_repository

    async def handle_async(self, request: RequestWorkerRefreshCommand) -> OperationResult[dict[str, Any]]:
        """Handle request worker refresh command.

        Sets refresh_requested_at flag on the worker. Worker-controller
        detects this during reconciliation and performs full data pull.

        Args:
            request: Command with worker ID.

        Returns:
            OperationResult with acknowledgment.
        """
        log.info(f"Requesting data refresh for worker {request.worker_id}")

        worker = await self.cml_worker_repository.get_by_id_async(request.worker_id)

        if not worker:
            return self.not_found("CMLWorker", f"Worker {request.worker_id} not found")

        # Only allow refresh for RUNNING workers
        if worker.state.status != CMLWorkerStatus.RUNNING:
            return self.bad_request(f"Cannot refresh worker in {worker.state.status.value} state. Worker must be RUNNING.")

        # Set the refresh request flag
        worker.request_refresh()

        # Persist changes
        await self.cml_worker_repository.update_async(worker)

        return self.accepted(
            {
                "worker_id": request.worker_id,
                "refresh_requested": True,
                "message": "Refresh requested. Data will be updated on next reconciliation cycle.",
            }
        )
