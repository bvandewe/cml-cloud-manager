"""Delete Lab Record Command — sets pending_action=delete for reconciliation (ADR-017).

Phase 8 (P8-5): Refactored from DeleteLabCommand with typed LabRecordStatus.
Uses LabRecord aggregate ID instead of worker_id + lab_id pair.
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
class DeleteLabRecordCommand(Command[OperationResult[dict]]):
    """Command to delete a lab from its runtime (CML worker).

    ADR-017: Sets pending_action=delete for reconciliation.
    The actual CML API call is performed by lablet-controller.

    Attributes:
        lab_record_id: LabRecord aggregate ID.
        deleted_by: Who requested the deletion.
    """

    lab_record_id: str
    deleted_by: str = "user"


class DeleteLabRecordCommandHandler(
    CommandHandlerBase,
    CommandHandler[DeleteLabRecordCommand, OperationResult[dict]],
):
    """Handler for DeleteLabRecordCommand — queues lab deletion for reconciliation."""

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

    async def handle_async(self, request: DeleteLabRecordCommand) -> OperationResult[dict]:
        """Queue lab deletion for reconciliation.

        ADR-017: Sets pending_action=delete on LabRecord, returns 202 Accepted.
        """
        with tracer.start_as_current_span("delete_lab_record_command") as span:
            span.set_attribute("lab_record.id", request.lab_record_id)
            span.set_attribute("lab.deleted_by", request.deleted_by)
            span.set_attribute("adr", "ADR-017")

            try:
                lab = await self._lab_repository.get_by_id_async(request.lab_record_id)
                if not lab:
                    return self.not_found(LabRecord, request.lab_record_id)

                if lab.state.pending_action:
                    return self.conflict(f"Lab already has pending action: {lab.state.pending_action}. Wait for it to complete or clear it first.")

                if lab.is_terminal:
                    return self.bad_request(f"Lab is already in terminal state: {lab.state.status.value}")

                lab.request_delete()
                await self._lab_repository.update_async(lab)

                log.info(
                    "Lab deletion queued for lab_record_id=%s (lab_id=%s, by=%s).",
                    request.lab_record_id,
                    lab.state.lab_id,
                    request.deleted_by,
                )

                return self.accepted(
                    {
                        "lab_record_id": request.lab_record_id,
                        "lab_id": lab.state.lab_id,
                        "worker_id": lab.state.worker_id,
                        "action": "delete",
                        "status": "pending",
                        "message": "Delete queued for stop-wipe-delete reconciliation",
                    }
                )

            except Exception as e:
                error_msg = f"Error queuing delete for lab {request.lab_record_id}: {e}"
                log.error(error_msg, exc_info=True)
                return self.internal_server_error(error_msg)
