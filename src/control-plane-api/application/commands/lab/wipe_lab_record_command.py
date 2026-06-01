"""Wipe Lab Record Command — sets pending_action=wipe for reconciliation (ADR-017).

Phase 8 (P8-4): Dedicated typed command for wiping a lab (reset node configs).
Uses LabRecordStatus-aware pending action flow.
"""

import logging
from dataclasses import dataclass

from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator
from opentelemetry import trace

from domain.entities.lab_record import LabRecord
from domain.repositories.lab_record_repository import LabRecordRepository

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class WipeLabRecordCommand(Command[OperationResult[dict]]):
    """Command to wipe a lab (reset all node configurations).

    ADR-017: Sets pending_action=wipe for reconciliation.

    Attributes:
        lab_record_id: LabRecord aggregate ID.
    """

    lab_record_id: str


class WipeLabRecordCommandHandler(
    CommandHandlerBase,
    CommandHandler[WipeLabRecordCommand, OperationResult[dict]],
):
    """Handler for WipeLabRecordCommand — queues lab wipe for reconciliation."""

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

    async def handle_async(self, request: WipeLabRecordCommand) -> OperationResult[dict]:
        """Queue lab wipe for reconciliation.

        ADR-017: Sets pending_action=wipe on LabRecord, returns 202 Accepted.
        """
        with tracer.start_as_current_span("wipe_lab_record_command") as span:
            span.set_attribute("lab_record.id", request.lab_record_id)
            span.set_attribute("adr", "ADR-017")

            try:
                lab = await self._lab_repository.get_by_id_async(request.lab_record_id)
                if not lab:
                    return self.not_found(LabRecord, request.lab_record_id)

                if lab.state.pending_action:
                    return self.conflict(f"Lab already has pending action: {lab.state.pending_action}. Wait for it to complete or clear it first.")

                if lab.is_terminal:
                    return self.bad_request(f"Cannot wipe lab in terminal state: {lab.state.status.value}")

                lab.request_wipe()
                await self._lab_repository.update_async(lab)

                log.info(
                    "Lab wipe queued for lab_record_id=%s (lab_id=%s).",
                    request.lab_record_id,
                    lab.state.lab_id,
                )

                return self.accepted(
                    {
                        "lab_record_id": request.lab_record_id,
                        "lab_id": lab.state.lab_id,
                        "worker_id": lab.state.worker_id,
                        "action": "wipe",
                        "status": "pending",
                        "message": "Wipe queued for reconciliation",
                    }
                )

            except Exception as e:
                error_msg = f"Error queuing wipe for lab {request.lab_record_id}: {e}"
                log.error(error_msg, exc_info=True)
                return self.internal_server_error(error_msg)
