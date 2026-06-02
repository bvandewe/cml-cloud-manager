"""Recalculate worker allocated capacity command with handler.

Repair mechanism for when allocated_capacity has drifted due to bugs in
session lifecycle handlers (e.g., expired/terminated sessions that failed
to release capacity — phantom allocations).

Iterates the worker's session_ids, validates each against the actual session
status, sums resource_requirements from LabletDefinitions for active sessions,
and replaces the current (possibly inflated) allocated_capacity.

Phase 1: Worker Foundation - Capacity Tracking (Repair)
ADR-015: Control-plane-api is DB-only. No AWS EC2 calls.
"""

import logging
from dataclasses import dataclass
from typing import Any

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.cml_worker import CMLWorker
from domain.enums import LabletSessionStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

log = logging.getLogger(__name__)

# Sessions in these statuses are actively consuming worker resources.
# Sessions in terminal states (TERMINATED, EXPIRED, ARCHIVED, STOPPED)
# should NOT hold capacity on a worker.
CAPACITY_HOLDING_STATUSES = frozenset(
    {
        LabletSessionStatus.PENDING,
        LabletSessionStatus.SCHEDULED,
        LabletSessionStatus.INSTANTIATING,
        LabletSessionStatus.READY,
        LabletSessionStatus.RUNNING,
        LabletSessionStatus.COLLECTING,
        LabletSessionStatus.GRADING,
        LabletSessionStatus.STOPPING,
    }
)


@dataclass
class RecalculateWorkerCapacityCommand(Command[OperationResult[dict[str, Any]]]):
    """Recalculate a worker's allocated capacity from its active sessions.

    Repair command: iterates session_ids, validates each session's status,
    sums resource_requirements for active sessions, and replaces
    allocated_capacity with the correct computed value.

    Args:
        worker_id: ID of the CMLWorker to recalculate
        requested_by: Who/what triggered the recalculation
    """

    worker_id: str
    requested_by: str = "system"


class RecalculateWorkerCapacityCommandHandler(
    CommandHandlerBase,
    CommandHandler[RecalculateWorkerCapacityCommand, OperationResult[dict[str, Any]]],
):
    """Handle worker capacity recalculation.

    Loads the worker, checks each tracked session against the session
    repository, classifies sessions as active or stale, sums resource
    requirements for active sessions, and replaces allocated_capacity.
    """

    def __init__(self, cml_worker_repository: CMLWorkerRepository, lablet_session_repository: LabletSessionRepository, lablet_definition_repository: LabletDefinitionRepository):
        self._worker_repository = cml_worker_repository
        self._session_repository = lablet_session_repository
        self._definition_repository = lablet_definition_repository

    async def handle_async(self, request: RecalculateWorkerCapacityCommand) -> OperationResult[dict[str, Any]]:
        """Handle recalculate worker capacity command."""
        log.info(
            "Recalculating capacity for worker %s (requested_by=%s)",
            request.worker_id,
            request.requested_by,
        )

        # 1. Load worker
        worker = await self._worker_repository.get_by_id_async(request.worker_id)
        if not worker:
            return self.not_found(CMLWorker, request.worker_id)

        old_allocated = worker.state.allocated_capacity.to_dict()
        old_session_ids = list(worker.state.session_ids)

        # 2. Iterate tracked session_ids and classify each
        active_session_ids: list[str] = []
        stale_session_ids: list[str] = []
        stale_reasons: dict[str, str] = {}

        total_cpu = 0
        total_memory = 0
        total_storage = 0
        total_nodes: int | None = None

        for session_id in old_session_ids:
            session = await self._session_repository.get_by_id_async(session_id)

            if not session:
                stale_session_ids.append(session_id)
                stale_reasons[session_id] = "session_not_found"
                log.warning("Session %s tracked on worker %s but not found in DB", session_id, request.worker_id)
                continue

            if session.state.status not in CAPACITY_HOLDING_STATUSES:
                stale_session_ids.append(session_id)
                stale_reasons[session_id] = f"terminal_status:{session.state.status.value}"
                log.info(
                    "Session %s on worker %s is in terminal status %s — removing from capacity tracking",
                    session_id,
                    request.worker_id,
                    session.state.status.value,
                )
                continue

            # Session is active — look up its definition for resource requirements
            active_session_ids.append(session_id)

            if session.state.definition_id:
                definition = await self._definition_repository.get_by_id_async(session.state.definition_id)
                if definition:
                    resource_reqs = definition.state.resource_requirements
                    total_cpu += resource_reqs.cpu_cores
                    total_memory += resource_reqs.memory_gb
                    total_storage += resource_reqs.storage_gb
                    if definition.state.node_count is not None:
                        total_nodes = (total_nodes or 0) + definition.state.node_count
                else:
                    log.warning(
                        "LabletDefinition %s not found for active session %s — capacity for this session not counted",
                        session.state.definition_id,
                        session_id,
                    )
            else:
                log.warning(
                    "Active session %s has no definition_id — capacity for this session not counted",
                    session_id,
                )

        # 3. Apply recalculation via domain event
        worker.recalculate_capacity(
            recalculated_cpu_cores=total_cpu,
            recalculated_memory_gb=total_memory,
            recalculated_storage_gb=total_storage,
            recalculated_max_nodes=total_nodes,
            active_session_ids=active_session_ids,
            stale_session_ids=stale_session_ids,
        )

        # 4. Persist
        await self._worker_repository.update_async(worker)

        new_allocated = worker.state.allocated_capacity.to_dict()

        log.info(
            "Recalculated capacity for worker %s: old_allocated=%s, new_allocated=%s, active_sessions=%d, stale_sessions_removed=%d",
            request.worker_id,
            old_allocated,
            new_allocated,
            len(active_session_ids),
            len(stale_session_ids),
        )

        return self.ok(
            {
                "worker_id": request.worker_id,
                "old_allocated_capacity": old_allocated,
                "new_allocated_capacity": new_allocated,
                "available_capacity": worker.available_capacity.to_dict() if worker.available_capacity else None,
                "active_session_ids": active_session_ids,
                "stale_sessions_removed": stale_session_ids,
                "stale_reasons": stale_reasons,
                "requested_by": request.requested_by,
            }
        )
