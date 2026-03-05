"""Update Lab Record Status Command — internal command for controller-driven status changes.

Phase 8 (P8-10): Called by lablet-controller (via internal API) when it observes
a CML lab state change that should update the LabRecord's typed status.

This handles typed LabRecordStatus updates from raw CML state string changes.

Architecture ref: §8.2 (internal endpoints).
"""

import logging
from dataclasses import dataclass

from domain.entities.lab_record import InvalidLabRecordTransitionError, LabRecord
from domain.repositories.lab_record_repository import LabRecordRepository
from lcm_core.domain.enums import CML_STATE_TO_LAB_RECORD_STATUS, LabRecordStatus
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
class UpdateLabRecordStatusCommand(Command[OperationResult[dict]]):
    """Internal command to update a LabRecord's status.

    Called by lablet-controller when it observes a CML state transition.
    Accepts either a typed LabRecordStatus value or a raw CML state string
    (which will be mapped via CML_STATE_TO_LAB_RECORD_STATUS).

    Attributes:
        lab_record_id: LabRecord aggregate ID.
        new_status: Target LabRecordStatus value (e.g., "booted", "stopped").
        cml_state: Optional raw CML state string for mapping fallback.
        error_message: Optional error message (when status=ERROR).
    """

    lab_record_id: str
    new_status: str | None = None
    cml_state: str | None = None
    error_message: str | None = None


class UpdateLabRecordStatusCommandHandler(
    CommandHandlerBase,
    CommandHandler[UpdateLabRecordStatusCommand, OperationResult[dict]],
):
    """Handler for UpdateLabRecordStatusCommand — applies typed status transitions."""

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

    async def handle_async(self, request: UpdateLabRecordStatusCommand) -> OperationResult[dict]:
        """Update lab record status via typed transition."""
        with tracer.start_as_current_span("update_lab_record_status_command") as span:
            span.set_attribute("lab_record.id", request.lab_record_id)
            span.set_attribute("target.status", request.new_status or "")
            span.set_attribute("target.cml_state", request.cml_state or "")

            try:
                lab = await self._lab_repository.get_by_id_async(request.lab_record_id)
                if not lab:
                    return self.not_found(LabRecord, request.lab_record_id)

                # Resolve target status
                target_status = self._resolve_status(request.new_status, request.cml_state)
                if target_status is None:
                    return self.bad_request(f"Either new_status or cml_state must be provided. new_status={request.new_status}, cml_state={request.cml_state}")

                # Skip if already in target status
                if lab.state.status == target_status:
                    return self.ok(
                        {
                            "lab_record_id": request.lab_record_id,
                            "status": target_status.value,
                            "message": "Already in target status, no change",
                        }
                    )

                # Apply the transition
                try:
                    self._apply_transition(lab, target_status, request.error_message)
                except InvalidLabRecordTransitionError as e:
                    return self.bad_request(str(e))

                # Update legacy raw state string if CML state provided
                if request.cml_state:
                    lab.state.state = request.cml_state

                await self._lab_repository.update_async(lab)

                log.info(
                    "Lab status updated: lab_record_id=%s, %s → %s",
                    request.lab_record_id,
                    lab.state.status.value,
                    target_status.value,
                )

                return self.ok(
                    {
                        "lab_record_id": request.lab_record_id,
                        "status": target_status.value,
                        "previous_status": lab.state.status.value,
                        "message": f"Status updated to {target_status.value}",
                    }
                )

            except Exception as e:
                error_msg = f"Error updating status for lab {request.lab_record_id}: {e}"
                log.error(error_msg, exc_info=True)
                return self.internal_server_error(error_msg)

    def _resolve_status(self, new_status: str | None, cml_state: str | None) -> LabRecordStatus | None:
        """Resolve target LabRecordStatus from typed value or CML state string."""
        if new_status:
            try:
                return LabRecordStatus(new_status.lower())
            except ValueError:
                return None
        if cml_state:
            return CML_STATE_TO_LAB_RECORD_STATUS.get(cml_state)
        return None

    def _apply_transition(
        self,
        lab,
        target_status: LabRecordStatus,
        error_message: str | None,
    ) -> None:
        """Apply the appropriate domain method for the target status."""
        transition_map = {
            LabRecordStatus.BOOTED: lambda: lab.mark_started(),
            LabRecordStatus.STOPPED: lambda: lab.mark_stopped(),
            LabRecordStatus.WIPED: lambda: lab.mark_wiped(),
            LabRecordStatus.DELETED: lambda: lab.mark_deleted(),
            LabRecordStatus.ARCHIVED: lambda: lab.mark_archived(),
            LabRecordStatus.ERROR: lambda: lab.mark_error(error_message or "Unknown error"),
            LabRecordStatus.ORPHANED: lambda: lab.mark_orphaned(),
        }
        handler = transition_map.get(target_status)
        if handler:
            handler()
        else:
            raise InvalidLabRecordTransitionError(
                lab.state.status,
                target_status,
                f"No handler for transition to {target_status.value}",
            )
