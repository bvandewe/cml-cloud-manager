"""Schedule LabletSession command.

Phase 7D: Replaces ScheduleLabletInstanceCommand.
Assigns a worker, port allocation, and lab record to a session.

Called by resource-scheduler after placement decision.
Per ADR-001: All state mutations go through Control Plane API.
"""

import logging
from dataclasses import dataclass
from typing import Any

from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

from application.commands.command_handler_base import CommandHandlerBase
from application.commands.worker.allocate_capacity_command import AllocateCapacityCommand
from domain.entities.cml_worker import CMLWorker
from domain.entities.lablet_definition import LabletDefinition
from domain.entities.lablet_session import LabletSession
from domain.enums import CMLWorkerStatus, LabletSessionStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from domain.value_objects.worker_capacity import WorkerCapacity

log = logging.getLogger(__name__)


@dataclass
class ScheduleLabletSessionCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to schedule a lablet session on a worker.

    Transitions session from PENDING to SCHEDULED and assigns worker,
    port allocation, and lab record binding.

    ADR-020: lab_record_id is now a direct 1:1 FK on the session
    (absorbed from the deleted LabletLabBinding entity).
    """

    session_id: str
    worker_id: str
    allocated_ports: dict[str, int]
    lab_record_id: str
    scheduled_by: str = "resource-scheduler"


class ScheduleLabletSessionCommandHandler(
    CommandHandlerBase,
    CommandHandler[ScheduleLabletSessionCommand, OperationResult[dict[str, Any]]],
):
    """Handle scheduling a lablet session on a worker.

    Validates worker status (must be RUNNING), checks capacity
    against LabletDefinition resource_requirements, and allocates
    capacity on the worker via AllocateCapacityCommand.
    """

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        lablet_session_repository: LabletSessionRepository,
        lablet_definition_repository: LabletDefinitionRepository,
        cml_worker_repository: CMLWorkerRepository,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._session_repository = lablet_session_repository
        self._definition_repository = lablet_definition_repository
        self._worker_repository = cml_worker_repository

    async def handle_async(self, request: ScheduleLabletSessionCommand) -> OperationResult[dict[str, Any]]:
        """Handle schedule lablet session command."""
        log.info("Scheduling session %s on worker %s", request.session_id, request.worker_id)

        session = await self._session_repository.get_by_id_async(request.session_id)
        if not session:
            return self.not_found(LabletSession, request.session_id)

        if session.state.status != LabletSessionStatus.PENDING:
            return self.conflict(f"Cannot schedule session in {session.state.status.value} status (expected PENDING)")

        worker = await self._worker_repository.get_by_id_async(request.worker_id)
        if not worker:
            return self.not_found(CMLWorker, request.worker_id)

        if worker.state.status != CMLWorkerStatus.RUNNING:
            log.warning("Worker %s is %s, cannot schedule", request.worker_id, worker.state.status.value)
            return self.conflict(f"Worker {request.worker_id} is {worker.state.status.value}, must be RUNNING")

        definition = await self._definition_repository.get_by_id_async(session.state.definition_id)
        if not definition:
            log.error("LabletDefinition %s not found for session %s", session.state.definition_id, request.session_id)
            return self.not_found(LabletDefinition, session.state.definition_id)

        resource_reqs = definition.state.resource_requirements
        requirements = WorkerCapacity(
            cpu_cores=resource_reqs.cpu_cores,
            memory_gb=resource_reqs.memory_gb,
            storage_gb=resource_reqs.storage_gb,
        )
        if not worker.can_accommodate(requirements):
            available = worker.available_capacity
            log.warning(
                "Insufficient capacity on worker %s: required=%s, available=%s",
                request.worker_id,
                requirements,
                available,
            )
            return self.conflict(f"Insufficient capacity on worker {request.worker_id}. Required: {requirements}, Available: {available}")

        session.schedule(
            worker_id=request.worker_id,
            allocated_ports=request.allocated_ports,
            lab_record_id=request.lab_record_id,
            scheduled_by=request.scheduled_by,
        )

        await self._session_repository.update_async(session)

        # Allocate capacity on the worker (best-effort side effect)
        capacity_allocated = False
        try:
            allocate_result = await self.mediator.execute_async(
                AllocateCapacityCommand(
                    worker_id=request.worker_id,
                    session_id=request.session_id,
                    cpu_cores=resource_reqs.cpu_cores,
                    memory_gb=resource_reqs.memory_gb,
                    storage_gb=resource_reqs.storage_gb,
                )
            )
            capacity_allocated = allocate_result.is_success
            if not capacity_allocated:
                log.error(
                    "Failed to allocate capacity for session %s on worker %s: %s. Session remains SCHEDULED but capacity tracking may be inconsistent.",
                    request.session_id,
                    request.worker_id,
                    allocate_result.error_message,
                )
        except Exception as e:
            log.error("Error allocating capacity for session %s: %s", request.session_id, e)

        return self.ok(
            {
                "session_id": request.session_id,
                "worker_id": request.worker_id,
                "lab_record_id": request.lab_record_id,
                "status": session.state.status.value,
                "scheduled_at": session.state.scheduled_at.isoformat() if session.state.scheduled_at else None,
                "capacity_allocated": capacity_allocated,
            }
        )
