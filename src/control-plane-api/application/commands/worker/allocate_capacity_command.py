"""Allocate worker capacity command with handler.

Wraps CMLWorker.assign_lablet_session() and allocate_ports() aggregate methods
into a CQRS command for capacity tracking during lablet scheduling.

Phase 1: Worker Foundation - Capacity Tracking
ADR-015: Control-plane-api is DB-only. No AWS EC2 calls.
"""

import logging
from dataclasses import dataclass
from typing import Any

from domain.entities.cml_worker import CMLWorker
from domain.enums import CMLWorkerStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.value_objects.worker_capacity import WorkerCapacity
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler
from neuroglia.observability.tracing import add_span_attributes
from opentelemetry import trace

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class AllocateCapacityCommand(Command[OperationResult[dict[str, Any]]]):
    """Allocate capacity on a worker for a lablet session.

    Reserves compute resources and optional ports on a CMLWorker for
    a scheduled LabletSession. Emits LabletSessionAssignedDomainEvent
    and optionally CMLWorkerPortsAllocatedDomainEvent.

    Args:
        worker_id: ID of the target CMLWorker
        session_id: ID of the LabletSession being assigned
        cpu_cores: CPU cores required by the session
        memory_gb: Memory in GB required by the session
        storage_gb: Storage in GB required by the session
        node_count: Number of CML nodes required (optional)
        port_requirements: Mapping of logical port names to allocate
                          e.g., {"console": 0, "api": 0} where 0 means auto-assign
    """

    worker_id: str
    session_id: str
    cpu_cores: int
    memory_gb: int
    storage_gb: int
    node_count: int | None = None
    port_requirements: dict[str, int] | None = None


class AllocateCapacityCommandHandler(
    CommandHandlerBase,
    CommandHandler[AllocateCapacityCommand, OperationResult[dict[str, Any]]],
):
    """Handle capacity allocation on a CMLWorker.

    Validates worker status and available capacity, then assigns
    the lablet session and allocates ports.
    """

    def __init__(self, cml_worker_repository: CMLWorkerRepository):
        self._repository = cml_worker_repository

    async def handle_async(self, request: AllocateCapacityCommand) -> OperationResult[dict[str, Any]]:
        """Handle allocate capacity command.

        Args:
            request: Command with worker ID, session ID, and resource requirements

        Returns:
            OperationResult with allocated capacity details or error
        """
        command = request

        add_span_attributes(
            {
                "cml_worker.id": command.worker_id,
                "lablet_session.id": command.session_id,
                "capacity.cpu_cores": command.cpu_cores,
                "capacity.memory_gb": command.memory_gb,
                "capacity.storage_gb": command.storage_gb,
            }
        )

        try:
            # Fetch worker
            with tracer.start_as_current_span("retrieve_worker") as span:
                worker = await self._repository.get_by_id_async(command.worker_id)
                if not worker:
                    log.warning(f"Worker not found: {command.worker_id}")
                    return self.not_found(CMLWorker, command.worker_id)

                span.set_attribute("cml_worker.status", worker.state.status.value)
                span.set_attribute("cml_worker.name", worker.state.name)

            # Validate worker is RUNNING
            if worker.state.status != CMLWorkerStatus.RUNNING:
                log.warning(f"Cannot allocate capacity on worker {command.worker_id}: status is {worker.state.status.value}, must be RUNNING")
                return self.conflict(f"Worker {command.worker_id} is {worker.state.status.value}, must be RUNNING")

            # Check if session is already assigned
            if worker.has_session(command.session_id):
                log.warning(f"Session {command.session_id} already assigned to worker {command.worker_id}")
                return self.conflict(f"Session {command.session_id} is already assigned to worker {command.worker_id}")

            # Check capacity
            with tracer.start_as_current_span("check_capacity") as span:
                requirements = WorkerCapacity(
                    cpu_cores=command.cpu_cores,
                    memory_gb=command.memory_gb,
                    storage_gb=command.storage_gb,
                    max_nodes=command.node_count,
                )

                if not worker.can_accommodate(requirements):
                    available = worker.available_capacity
                    log.warning(f"Insufficient capacity on worker {command.worker_id}: required={requirements}, available={available}")
                    return self.conflict(f"Insufficient capacity on worker {command.worker_id}. Required: {requirements}, Available: {available}")

                span.set_attribute("capacity.check_passed", True)

            # Assign lablet session (updates allocated_capacity)
            with tracer.start_as_current_span("assign_session") as span:
                worker.assign_lablet_session(
                    session_id=command.session_id,
                    cpu_cores=command.cpu_cores,
                    memory_gb=command.memory_gb,
                    storage_gb=command.storage_gb,
                    max_nodes=command.node_count,
                )
                span.set_attribute("session.assigned", True)

            # Allocate ports if requested
            allocated_ports: dict[str, int] = {}
            if command.port_requirements:
                with tracer.start_as_current_span("allocate_ports") as span:
                    port_count = len(command.port_requirements)
                    available_ports = worker.get_next_available_ports(port_count)

                    # Map logical port names to allocated port numbers
                    port_names = list(command.port_requirements.keys())
                    allocated_ports = dict(zip(port_names, available_ports))

                    worker.allocate_ports(
                        session_id=command.session_id,
                        ports=allocated_ports,
                    )
                    span.set_attribute("ports.allocated_count", port_count)

            # Persist
            await self._repository.update_async(worker)

            log.info(
                f"Allocated capacity on worker {command.worker_id} for session {command.session_id}: "
                f"cpu={command.cpu_cores}, mem={command.memory_gb}GB, "
                f"storage={command.storage_gb}GB, nodes={command.node_count}, "
                f"ports={allocated_ports or 'none'}"
            )

            return self.ok(
                {
                    "worker_id": command.worker_id,
                    "session_id": command.session_id,
                    "allocated_capacity": worker.state.allocated_capacity.to_dict(),
                    "available_capacity": worker.available_capacity.to_dict() if worker.available_capacity else None,
                    "allocated_ports": allocated_ports,
                    "assigned_session_count": len(worker.state.session_ids),
                }
            )

        except ValueError as e:
            log.warning(f"Validation error during capacity allocation: {e}")
            return self.bad_request(str(e))

        except Exception as e:
            log.error(f"Failed to allocate capacity on worker {command.worker_id}: {e}", exc_info=True)
            return self.internal_server_error(f"Failed to allocate capacity: {str(e)}")
