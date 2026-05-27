"""Command for triggering targeted lab discovery on a worker (ADR-041 Phase 2).

When worker-controller detects new lab_ids in WebSocket lab_stats that CPA doesn't
recognize, it calls this command. The handler emits a domain event on the CMLWorker
aggregate, which is projected to etcd for lablet-controller to react to.

Signal chain: worker-controller → CPA command → domain event → etcd projector →
lablet-controller watch → targeted REST discovery → report back → CPA deletes key.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.cml_worker import CMLWorker
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

log = logging.getLogger(__name__)


@dataclass
class TriggerLabDiscoveryCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to trigger targeted lab discovery for a worker.

    Called by worker-controller when new lab_ids are detected in WebSocket
    lab_stats events that don't match any known LabRecord.

    Attributes:
        worker_id: Worker identifier where new labs were detected
        lab_ids: Optional list of new CML lab IDs (informational)
        source: Source of the trigger (e.g., "websocket-lab-stats")
    """

    worker_id: str
    lab_ids: list[str] = field(default_factory=list)
    source: str = "websocket"


class TriggerLabDiscoveryCommandHandler(
    CommandHandlerBase,
    CommandHandler[TriggerLabDiscoveryCommand, OperationResult[dict[str, Any]]],
):
    """Handle lab discovery trigger — emit domain event → etcd projection → 202 Accepted.

    The handler loads the CMLWorker aggregate, calls trigger_lab_discovery() which
    emits CMLWorkerLabDiscoveryTriggeredDomainEvent, persists the aggregate (publishing
    the event), and returns 202 Accepted. The LabDiscoveryTriggeredEtcdProjector then
    writes the etcd key, and lablet-controller picks it up via watch.
    """

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        cml_worker_repository: CMLWorkerRepository,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._worker_repository = cml_worker_repository

    async def handle_async(self, command: TriggerLabDiscoveryCommand) -> OperationResult[dict[str, Any]]:
        """Execute the command."""
        if not command.worker_id:
            return self.bad_request("worker_id is required")

        # Load the aggregate
        worker: CMLWorker | None = await self._worker_repository.get_by_id_async(command.worker_id)
        if not worker:
            return self.not_found(CMLWorker, command.worker_id)

        triggered_at = datetime.now(timezone.utc).isoformat()

        # Emit domain event (no state change, notification only → etcd projection)
        worker.trigger_lab_discovery(
            lab_ids=command.lab_ids,
            source=command.source,
            triggered_at=triggered_at,
        )

        # Persist aggregate (publishes domain events → etcd projector fires)
        await self._worker_repository.update_async(worker)

        log.info(f"Lab discovery triggered for worker {command.worker_id}: " f"lab_ids={command.lab_ids}, source={command.source}")

        return self.accepted(
            {
                "worker_id": command.worker_id,
                "lab_ids": command.lab_ids,
                "source": command.source,
                "triggered_at": triggered_at,
            }
        )
