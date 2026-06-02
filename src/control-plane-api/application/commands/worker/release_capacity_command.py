"""Release worker capacity command with handler.

Wraps CMLWorker.release_ports() and remove_lablet_session() aggregate methods
into a CQRS command for capacity release during lablet termination.

Phase 1: Worker Foundation - Capacity Tracking
ADR-015: Control-plane-api is DB-only. No AWS EC2 calls.
"""

import logging
from dataclasses import dataclass
from typing import Any

from domain.entities.cml_worker import CMLWorker
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler
from neuroglia.observability.tracing import add_span_attributes
from opentelemetry import trace

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class ReleaseCapacityCommand(Command[OperationResult[dict[str, Any]]]):
    """Release capacity on a worker when a lablet session is terminated.

    Frees compute resources and ports previously allocated to a
    LabletSession. Emits LabletSessionRemovedDomainEvent and
    optionally CMLWorkerPortsReleasedDomainEvent.

    Args:
        worker_id: ID of the CMLWorker to release capacity from
        session_id: ID of the LabletSession being removed
        cpu_cores: CPU cores to release (must match what was allocated)
        memory_gb: Memory in GB to release
        storage_gb: Storage in GB to release
        node_count: Number of CML nodes to release (optional)
    """

    worker_id: str
    session_id: str
    cpu_cores: int = 0
    memory_gb: int = 0
    storage_gb: int = 0
    node_count: int | None = None


class ReleaseCapacityCommandHandler(
    CommandHandlerBase,
    CommandHandler[ReleaseCapacityCommand, OperationResult[dict[str, Any]]],
):
    """Handle capacity release on a CMLWorker.

    Releases ports and removes the lablet session from the worker,
    freeing allocated resources.
    """

    def __init__(self, cml_worker_repository: CMLWorkerRepository):
        self._repository = cml_worker_repository

    async def handle_async(self, request: ReleaseCapacityCommand) -> OperationResult[dict[str, Any]]:
        """Handle release capacity command.

        Args:
            request: Command with worker ID, session ID, and resources to release

        Returns:
            OperationResult with updated capacity details or error
        """
        command = request

        add_span_attributes(
            {
                "cml_worker.id": command.worker_id,
                "lablet_session.id": command.session_id,
            }
        )

        try:
            # Fetch worker
            with tracer.start_as_current_span("retrieve_worker") as span:
                worker = await self._repository.get_by_id_async(command.worker_id)
                if not worker:
                    log.warning(f"Worker not found for capacity release: {command.worker_id}")
                    return self.not_found(CMLWorker, command.worker_id)

                span.set_attribute("cml_worker.status", worker.state.status.value)
                span.set_attribute("cml_worker.name", worker.state.name)

            # Verify session is assigned to this worker
            if not worker.has_session(command.session_id):
                log.info(f"Session {command.session_id} not assigned to worker {command.worker_id}, capacity release is a no-op")
                return self.ok(
                    {
                        "worker_id": command.worker_id,
                        "session_id": command.session_id,
                        "already_released": True,
                        "allocated_capacity": worker.state.allocated_capacity.to_dict(),
                        "available_capacity": worker.available_capacity.to_dict() if worker.available_capacity else None,
                    }
                )

            # Release ports first (if any allocated for this session)
            with tracer.start_as_current_span("release_ports") as span:
                port_allocation = worker.get_port_allocation(command.session_id)
                if port_allocation:
                    worker.release_ports(command.session_id)
                    span.set_attribute("ports.released_count", port_allocation.port_count())
                    log.info(f"Released {port_allocation.port_count()} ports for session {command.session_id}")
                else:
                    span.set_attribute("ports.released_count", 0)

            # Remove lablet session (releases allocated capacity)
            with tracer.start_as_current_span("remove_session") as span:
                worker.remove_lablet_session(
                    session_id=command.session_id,
                    cpu_cores=command.cpu_cores,
                    memory_gb=command.memory_gb,
                    storage_gb=command.storage_gb,
                    max_nodes=command.node_count,
                )
                span.set_attribute("session.removed", True)

            # Persist
            await self._repository.update_async(worker)

            log.info(
                f"Released capacity on worker {command.worker_id} for session {command.session_id}: "
                f"cpu={command.cpu_cores}, mem={command.memory_gb}GB, "
                f"storage={command.storage_gb}GB, nodes={command.node_count}"
            )

            return self.ok(
                {
                    "worker_id": command.worker_id,
                    "session_id": command.session_id,
                    "already_released": False,
                    "allocated_capacity": worker.state.allocated_capacity.to_dict(),
                    "available_capacity": worker.available_capacity.to_dict() if worker.available_capacity else None,
                    "assigned_session_count": len(worker.state.session_ids),
                }
            )

        except Exception as e:
            log.error(f"Failed to release capacity on worker {command.worker_id}: {e}", exc_info=True)
            return self.internal_server_error(f"Failed to release capacity: {str(e)}")
