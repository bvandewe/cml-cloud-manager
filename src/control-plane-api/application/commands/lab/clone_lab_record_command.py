"""Clone Lab Record Command — creates a new LabRecord as a clone of an existing one.

Phase 8 (P8-6): Lab clone creates a new LabRecord with source="clone" and sets
pending_action=clone for reconciliation. The lablet-controller will clone the lab
via CML API (POST /labs/{lab_id}/clone), creating a new CML lab on the same worker.

Architecture ref: §8.3 (clone endpoint).
"""

import logging
import uuid
from dataclasses import dataclass

from domain.entities.lab_record import LabRecord
from domain.repositories.lab_record_repository import LabRecordRepository
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator
from opentelemetry import trace

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class CloneLabRecordCommand(Command[OperationResult[dict]]):
    """Command to clone an existing lab to a new LabRecord.

    Creates a new LabRecord referencing the source, then queues a CML clone
    operation for reconciliation.

    Attributes:
        source_lab_record_id: LabRecord aggregate ID of the lab to clone.
        title: Optional title for the clone (defaults to "Clone of <source_title>").
        cloned_by: Who requested the clone.
    """

    source_lab_record_id: str
    title: str | None = None
    cloned_by: str = "user"


class CloneLabRecordCommandHandler(
    CommandHandlerBase,
    CommandHandler[CloneLabRecordCommand, OperationResult[dict]],
):
    """Handler for CloneLabRecordCommand — creates a clone LabRecord and queues CML clone."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        lab_record_repository: LabRecordRepository,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._lab_repository = lab_record_repository

    async def handle_async(self, request: CloneLabRecordCommand) -> OperationResult[dict]:
        """Create a clone LabRecord and queue CML clone for reconciliation.

        Flow:
        1. Validate source lab exists and is in a clonable state.
        2. Create a new LabRecord with source="clone" via factory method.
        3. Persist the new clone record.
        4. Return 201 Created with clone details.

        The lablet-controller will handle the actual CML API clone operation
        when it discovers the new record with status=DEFINED and source=clone.
        """
        with tracer.start_as_current_span("clone_lab_record_command") as span:
            span.set_attribute("source_lab_record.id", request.source_lab_record_id)
            span.set_attribute("lab.cloned_by", request.cloned_by)

            try:
                # 1. Get source lab record
                source_lab = await self._lab_repository.get_by_id_async(request.source_lab_record_id)
                if not source_lab:
                    return self.not_found(LabRecord, request.source_lab_record_id)

                # 2. Validate source is in a clonable state
                if source_lab.is_terminal:
                    return self.bad_request(f"Cannot clone lab in terminal state: {source_lab.state.status.value}")

                # 3. Create clone LabRecord
                clone_title = request.title or f"Clone of {source_lab.state.title or source_lab.state.lab_id}"
                clone_lab_id = f"clone-{uuid.uuid4().hex[:8]}"  # Placeholder until CML assigns real ID

                clone = LabRecord.discover(
                    lab_id=clone_lab_id,
                    worker_id=source_lab.state.worker_id,
                    title=clone_title,
                    description=source_lab.state.description,
                    state="DEFINED_ON_CORE",
                    owner_username=source_lab.state.owner_username,
                    node_count=source_lab.state.node_count,
                    link_count=source_lab.state.link_count,
                )

                # Apply the cloned event to set source and status
                from domain.events.lab_record_events import LabRecordClonedDomainEvent

                clone_event = LabRecordClonedDomainEvent(
                    aggregate_id=clone.id(),
                    lab_id=clone_lab_id,
                    source_lab_record_id=request.source_lab_record_id,
                    cloned_at=clone.state.first_seen_at,
                    cloned_by=request.cloned_by,
                )
                clone.state.on(clone.register_event(clone_event))  # type: ignore

                # Copy topology and external interfaces from source
                if source_lab.state.topology_spec:
                    clone.state.topology_spec = source_lab.state.topology_spec.copy()
                if source_lab.state.external_interfaces:
                    clone.state.external_interfaces = [ei.copy() for ei in source_lab.state.external_interfaces]

                clone.state.based_on_definition_id = source_lab.state.based_on_definition_id

                # 4. Persist clone
                await self._lab_repository.add_async(clone)

                log.info(
                    "Lab clone created: clone_id=%s from source_id=%s (worker=%s, by=%s)",
                    clone.id(),
                    request.source_lab_record_id,
                    source_lab.state.worker_id,
                    request.cloned_by,
                )

                return self.created(
                    {
                        "lab_record_id": clone.id(),
                        "source_lab_record_id": request.source_lab_record_id,
                        "lab_id": clone_lab_id,
                        "worker_id": source_lab.state.worker_id,
                        "title": clone_title,
                        "source": "clone",
                        "status": "defined",
                        "message": "Clone created, pending CML clone operation",
                    }
                )

            except Exception as e:
                error_msg = f"Error cloning lab {request.source_lab_record_id}: {e}"
                log.error(error_msg, exc_info=True)
                return self.internal_server_error(error_msg)
