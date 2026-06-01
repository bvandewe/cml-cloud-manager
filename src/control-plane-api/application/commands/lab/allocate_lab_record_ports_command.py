"""Allocate Lab Record Ports command.

Phase 1 (Instantiation Pipeline): Allocates ports from worker pool
and stores them on the LabRecord aggregate.

Per ADR-032: Port allocation is a LabRecord topology concern — ports persist
across session lifecycles (bind/unbind cycles) and are released only when
the LabRecord is deleted.

The PortAllocationService (etcd) is keyed by lab_record_id, NOT session_id.
This ensures ports stay with the lab topology, not the session.

Called by lablet-controller during the `ports_alloc` pipeline step.
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
from application.services.port_allocation_service import PortAllocationService
from domain.entities.lab_record import LabRecord
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.value_objects.port_template import PortTemplate

log = logging.getLogger(__name__)


@dataclass
class AllocateLabRecordPortsCommand(Command[OperationResult[dict[str, Any]]]):
    """Allocate ports from worker pool and store on LabRecord.

    Ports are allocated via PortAllocationService (etcd) keyed by
    lab_record_id, then persisted on the LabRecord aggregate via
    LabRecord.allocate_ports().

    Attributes:
        lab_record_id: The LabRecord aggregate ID to allocate ports for.
        worker_id: The CMLWorker hosting this lab (etcd key scope).
    """

    lab_record_id: str
    worker_id: str


class AllocateLabRecordPortsCommandHandler(
    CommandHandlerBase,
    CommandHandler[AllocateLabRecordPortsCommand, OperationResult[dict[str, Any]]],
):
    """Handle port allocation for a LabRecord.

    Workflow:
    1. Load LabRecord by ID
    2. Idempotency check — skip if already allocated
    3. Resolve PortTemplate from the LabRecord's associated LabletDefinition
    4. Allocate ports via PortAllocationService (etcd atomic operation)
    5. Store allocated_ports on LabRecord aggregate
    6. Return allocated port mapping
    """

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        lab_record_repository: LabRecordRepository,
        lablet_definition_repository: LabletDefinitionRepository,
        port_allocation_service: PortAllocationService,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._lab_record_repo = lab_record_repository
        self._definition_repo = lablet_definition_repository
        self._port_service = port_allocation_service

    async def handle_async(self, request: AllocateLabRecordPortsCommand) -> OperationResult[dict[str, Any]]:
        """Handle port allocation for a LabRecord."""
        log.info(
            "Allocating ports for lab_record %s on worker %s",
            request.lab_record_id,
            request.worker_id,
        )

        # 1. Load LabRecord
        lab_record = await self._lab_record_repo.get_by_id_async(request.lab_record_id)
        if not lab_record:
            return self.not_found(LabRecord, request.lab_record_id)

        # 2. Idempotency — if ports are already allocated, return them
        if lab_record.state.allocated_ports:
            log.info(
                "Ports already allocated for lab_record %s: %s",
                request.lab_record_id,
                lab_record.state.allocated_ports,
            )
            return self.ok(
                {
                    "allocated_ports": lab_record.state.allocated_ports,
                    "already_allocated": True,
                }
            )

        # 3. Resolve PortTemplate from the associated LabletDefinition
        definition_id = lab_record.state.based_on_definition_id
        if not definition_id:
            log.info("Lab record %s has no associated definition — skipping port allocation", request.lab_record_id)
            return self.ok({"allocated_ports": {}, "skipped": True, "reason": "no_definition"})

        definition = await self._definition_repo.get_by_id_async(definition_id)
        if not definition:
            log.warning("Definition %s not found for lab_record %s", definition_id, request.lab_record_id)
            return self.ok({"allocated_ports": {}, "skipped": True, "reason": "definition_not_found"})

        # Resolve port_template — may be stored as dict (MongoDB) or PortTemplate (event replay)
        raw_template = definition.state.port_template
        if not raw_template:
            log.info("Definition %s has no port template — skipping port allocation", definition_id)
            return self.ok({"allocated_ports": {}, "skipped": True, "reason": "no_port_template"})

        if isinstance(raw_template, dict):
            port_template = PortTemplate.from_dict(raw_template)
        else:
            port_template = raw_template

        if port_template.port_count == 0:
            log.info("Definition %s has empty port template — skipping port allocation", definition_id)
            return self.ok({"allocated_ports": {}, "skipped": True, "reason": "empty_port_template"})

        # 4. Allocate ports via PortAllocationService (etcd)
        #    Key: lab_record_id (not session_id) — ports belong to topology, not session
        result = await self._port_service.allocate_ports(
            worker_id=request.worker_id,
            session_id=request.lab_record_id,  # etcd key = lab_record_id per ADR-032
            port_template=port_template,
        )

        if not result.success:
            log.warning(
                "Port allocation failed for lab_record %s: %s",
                request.lab_record_id,
                result.error,
            )
            return self.conflict(f"Port allocation failed: {result.error}")

        # 5. Store allocated_ports on LabRecord aggregate
        lab_record.allocate_ports(result.allocated_ports)
        await self._lab_record_repo.update_async(lab_record)

        log.info(
            "Ports allocated for lab_record %s: %s",
            request.lab_record_id,
            result.allocated_ports,
        )

        return self.ok({"allocated_ports": result.allocated_ports})
