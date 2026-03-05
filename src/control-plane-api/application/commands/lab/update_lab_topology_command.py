"""Update Lab Topology Command — internal command for topology and revision updates.

Phase 8 (P8-11): Called by lablet-controller (via internal API) when it detects
a topology change via checksum comparison during discovery.

Updates the LabRecord's topology spec and creates a new revision if the
checksum has changed.

Architecture ref: §8.2 (internal endpoints), §4.1 (topology spec).
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from domain.entities.lab_record import LabRecord
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.value_objects.lab_topology_spec import LabTopologySpec
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
class UpdateLabTopologyCommand(Command[OperationResult[dict]]):
    """Internal command to update a LabRecord's topology specification.

    Creates a new revision if the topology checksum has changed.

    Attributes:
        lab_record_id: LabRecord aggregate ID.
        topology_data: Raw topology data (nodes, links, annotations, raw_yaml).
        change_summary: Optional human-readable summary of changes.
    """

    lab_record_id: str
    topology_data: dict[str, Any] = field(default_factory=dict)
    change_summary: str | None = None


class UpdateLabTopologyCommandHandler(
    CommandHandlerBase,
    CommandHandler[UpdateLabTopologyCommand, OperationResult[dict]],
):
    """Handler for UpdateLabTopologyCommand — updates topology and creates revisions."""

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

    async def handle_async(self, request: UpdateLabTopologyCommand) -> OperationResult[dict]:
        """Update lab topology specification and create revision if changed."""
        with tracer.start_as_current_span("update_lab_topology_command") as span:
            span.set_attribute("lab_record.id", request.lab_record_id)

            try:
                lab = await self._lab_repository.get_by_id_async(request.lab_record_id)
                if not lab:
                    return self.not_found(LabRecord, request.lab_record_id)

                if lab.is_terminal:
                    return self.bad_request(f"Cannot update topology for lab in terminal state: {lab.state.status.value}")

                # Parse topology data into LabTopologySpec VO
                try:
                    topology_spec = LabTopologySpec.from_dict(request.topology_data)
                except (KeyError, ValueError, TypeError) as e:
                    return self.bad_request(f"Invalid topology data: {e}")

                # Compute checksums for change detection
                new_checksum = topology_spec.checksum()
                previous_revision = lab.state.revision

                # Update topology (creates revision if checksum changed)
                lab.update_topology(topology_spec, change_summary=request.change_summary)

                revision_created = lab.state.revision > previous_revision

                await self._lab_repository.update_async(lab)

                log.info(
                    "Lab topology updated: lab_record_id=%s, revision=%d, " "new_revision_created=%s",
                    request.lab_record_id,
                    lab.state.revision,
                    revision_created,
                )

                return self.ok(
                    {
                        "lab_record_id": request.lab_record_id,
                        "revision": lab.state.revision,
                        "checksum": new_checksum,
                        "revision_created": revision_created,
                        "node_count": topology_spec.node_count,
                        "link_count": topology_spec.link_count,
                        "message": "Topology updated" + (" (new revision)" if revision_created else " (no change)"),
                    }
                )

            except Exception as e:
                error_msg = f"Error updating topology for lab {request.lab_record_id}: {e}"
                log.error(error_msg, exc_info=True)
                return self.internal_server_error(error_msg)
