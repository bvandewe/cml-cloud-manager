"""Expire Lablet Session command.

Phase 1 (Instantiation Pipeline): Handles session expiry due to timeslot
exhaustion. Performs downstream cleanup:
1. Expire the LabletSession (status → EXPIRED)
2. Unbind the LabRecord (if bound) — clear active_lablet_session_id
3. Release worker capacity (via ReleaseCapacityCommand)

Per ADR-031 / ADR-032:
- Ports are NOT released at session expiry — they belong to the LabRecord
  (topology-level) and persist for lab reuse.
- CML node tags are NOT cleared — topology-level, persist across cycles.
- Lab stop/wipe is NOT triggered here — the lablet-controller reconciler
  handles physical teardown on the next cycle.

Per ADR-001: All state mutations go through Control Plane API.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from application.commands.command_handler_base import CommandHandlerBase
from application.commands.worker.release_capacity_command import ReleaseCapacityCommand
from domain.entities.lablet_session import LabletSession
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

log = logging.getLogger(__name__)


@dataclass
class ExpireLabletSessionCommand(Command[OperationResult[dict[str, Any]]]):
    """Handle session expiry: update status and trigger downstream cleanup.

    Attributes:
        session_id: The LabletSession ID to expire.
        reason: Expiry reason (default: "timeslot_expired").
    """

    session_id: str
    reason: str = field(default="timeslot_expired")


class ExpireLabletSessionCommandHandler(
    CommandHandlerBase,
    CommandHandler[ExpireLabletSessionCommand, OperationResult[dict[str, Any]]],
):
    """Handle session expiry and downstream cleanup.

    Workflow:
    1. Load LabletSession and expire it (EXPIRED status)
    2. Unbind LabRecord if bound (clear active binding, NOT ports)
    3. Release worker capacity (via ReleaseCapacityCommand)
    4. Persist all changes
    """

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        lablet_session_repository: LabletSessionRepository,
        lab_record_repository: LabRecordRepository,
        lablet_definition_repository: LabletDefinitionRepository,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._session_repo = lablet_session_repository
        self._lab_record_repo = lab_record_repository
        self._definition_repo = lablet_definition_repository

    async def handle_async(self, request: ExpireLabletSessionCommand) -> OperationResult[dict[str, Any]]:
        """Handle session expiry."""
        log.info("Expiring session %s (reason: %s)", request.session_id, request.reason)

        # 1. Load session
        session = await self._session_repo.get_by_id_async(request.session_id)
        if not session:
            return self.not_found(LabletSession, request.session_id)

        # Idempotency — if already expired or in terminal state, return ok
        from domain.enums import LabletSessionStatus

        if session.state.status == LabletSessionStatus.EXPIRED:
            log.info("Session %s already expired — returning ok", request.session_id)
            return self.ok({"session_id": request.session_id, "status": "expired", "already_expired": True})

        # 2. Expire the session
        try:
            session.expire(reason=request.reason)
        except Exception as e:
            log.warning("Cannot expire session %s: %s", request.session_id, e)
            return self.conflict(f"Cannot expire session: {e}")

        await self._session_repo.update_async(session)

        # 3. Unbind LabRecord (if bound) — DO NOT release ports
        lab_record_unbound = False
        if session.state.lab_record_id:
            lab_record = await self._lab_record_repo.get_by_id_async(session.state.lab_record_id)
            if lab_record and lab_record.state.active_lablet_session_id == request.session_id:
                binding_id = lab_record.state.active_binding_id or ""
                lab_record.unbind_from_lablet(
                    lablet_session_id=request.session_id,
                    binding_id=binding_id,
                )
                # NOTE: lab_record.allocated_ports is UNCHANGED — ports are
                # topology-level and persist for future sessions. CML node tags
                # are also unchanged. See §3.10 for port release lifecycle.
                await self._lab_record_repo.update_async(lab_record)
                lab_record_unbound = True
                log.info(
                    "Unbound lab_record %s from expired session %s",
                    session.state.lab_record_id,
                    request.session_id,
                )

        # 4. Release worker capacity (NOT ports)
        # Look up LabletDefinition to get the actual resource values that were
        # allocated. Passing 0s would remove the session_id from the worker's
        # session_ids but leave allocated_capacity inflated (capacity leak).
        capacity_released = False
        if session.state.worker_id:
            try:
                cpu_cores = 0
                memory_gb = 0
                storage_gb = 0
                if session.state.definition_id:
                    definition = await self._definition_repo.get_by_id_async(session.state.definition_id)
                    if definition:
                        resource_reqs = definition.state.resource_requirements
                        cpu_cores = resource_reqs.cpu_cores
                        memory_gb = resource_reqs.memory_gb
                        storage_gb = resource_reqs.storage_gb
                    else:
                        log.warning(
                            "LabletDefinition %s not found for session %s — capacity release will use 0 values",
                            session.state.definition_id,
                            request.session_id,
                        )

                release_result = await self.mediator.execute_async(
                    ReleaseCapacityCommand(
                        worker_id=session.state.worker_id,
                        session_id=request.session_id,
                        cpu_cores=cpu_cores,
                        memory_gb=memory_gb,
                        storage_gb=storage_gb,
                    )
                )
                capacity_released = release_result.is_success
                if not capacity_released:
                    log.warning(
                        "Capacity release failed for session %s: %s",
                        request.session_id,
                        release_result.error_message,
                    )
            except Exception as e:
                log.error("Error releasing capacity for session %s: %s", request.session_id, e)

        log.info(
            "Session %s expired (lab_record_unbound=%s, capacity_released=%s)",
            request.session_id,
            lab_record_unbound,
            capacity_released,
        )

        return self.ok(
            {
                "session_id": request.session_id,
                "status": "expired",
                "reason": request.reason,
                "lab_record_unbound": lab_record_unbound,
                "capacity_released": capacity_released,
            }
        )
