"""Command for reporting lab state changes from WebSocket events (ADR-041)."""

import logging
from dataclasses import dataclass, field
from typing import Any

from application.services.sse_event_relay import SSEEventRelay
from domain.repositories.lab_record_repository import LabRecordRepository
from infrastructure.observability.cqrs_instrumentation import instrumented
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

log = logging.getLogger(__name__)


@dataclass
class ReportLabStateChangeCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to report a lab/node/interface state change from WebSocket.

    Reported by worker-controller when the CmlWebSocketMonitor receives
    state_change or lab_event messages from a CML worker's /ws/ui endpoint (ADR-041).

    Attributes:
        worker_id: Worker identifier
        lab_id: CML lab ID (if available)
        event: Event name (QUEUED, STARTED, BOOTED, STOPPED, etc.)
        element_type: Type of element ("node", "interface", "lab")
        element_id: ID of the element that changed state
        data: Additional event data from CML
    """

    worker_id: str
    lab_id: str | None = None
    event: str = ""
    element_type: str = ""
    element_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@instrumented
class ReportLabStateChangeCommandHandler(CommandHandler[ReportLabStateChangeCommand, OperationResult[dict[str, Any]]]):
    """Handler for ReportLabStateChangeCommand.

    Broadcasts state change as an SSE event for real-time frontend updates.
    If the event implies a lab-level state change, optionally updates LabRecord.
    """

    def __init__(
        self,
        lab_record_repository: LabRecordRepository,
        sse_relay: SSEEventRelay,
    ):
        self._lab_repository = lab_record_repository
        self._sse_relay = sse_relay

    async def handle_async(self, command: ReportLabStateChangeCommand) -> OperationResult[dict[str, Any]]:
        """Execute the command."""
        # Broadcast SSE event for real-time frontend updates
        event_data: dict[str, Any] = {
            "worker_id": command.worker_id,
            "event": command.event,
            "element_type": command.element_type,
            "element_id": command.element_id,
            "data": command.data,
        }
        if command.lab_id:
            event_data["lab_id"] = command.lab_id

        await self._sse_relay.broadcast_event("worker.lab.state_change", event_data, source="worker-controller")

        # If this is a lab-level state change, update LabRecord status
        updated_lab_record = False
        if command.element_type == "lab" and command.lab_id:
            lab_record = await self._lab_repository.get_by_lab_id_async(command.worker_id, command.lab_id)
            if lab_record:
                # Map CML event names to LabRecord state if applicable
                cml_to_lab_state = {
                    "STARTED": "STARTED",
                    "STOPPED": "STOPPED",
                    "QUEUED": "QUEUED",
                    "BOOTED": "BOOTED",
                    "DEFINED_ON_CORE": "DEFINED_ON_CORE",
                }
                new_state = cml_to_lab_state.get(command.event)
                if new_state:
                    lab_record.state.state = new_state  # Legacy raw CML state string
                    await self._lab_repository.update_async(lab_record)
                    updated_lab_record = True
                    log.info(f"Updated LabRecord state for worker={command.worker_id}, lab_id={command.lab_id}: {new_state}")

        log.debug(f"Lab state change for worker={command.worker_id}: event={command.event}, element_type={command.element_type}, element_id={command.element_id}")

        return self.ok(
            {
                "worker_id": command.worker_id,
                "lab_id": command.lab_id,
                "event": command.event,
                "element_type": command.element_type,
                "broadcasted": True,
                "lab_record_updated": updated_lab_record,
            }
        )
