"""Extend Timeslot command.

Phase 7D: New command (was inline in old code).
Extends the timeslot end time for a LabletSession.

Per ADR-001: All state mutations go through Control Plane API.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.lablet_session import LabletSession
from domain.repositories.lablet_session_repository import LabletSessionRepository

log = logging.getLogger(__name__)


@dataclass
class ExtendTimeslotCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to extend the timeslot for a LabletSession.

    Attributes:
        session_id: The LabletSession aggregate ID.
        new_timeslot_end: New end time (ISO 8601, must be after current end).
        extended_by: User or system that requested the extension.
    """

    session_id: str
    new_timeslot_end: str  # ISO 8601 datetime string
    extended_by: str


class ExtendTimeslotCommandHandler(
    CommandHandlerBase,
    CommandHandler[ExtendTimeslotCommand, OperationResult[dict[str, Any]]],
):
    """Handle extending a session's timeslot."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        lablet_session_repository: LabletSessionRepository,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._session_repository = lablet_session_repository

    async def handle_async(self, request: ExtendTimeslotCommand) -> OperationResult[dict[str, Any]]:
        """Handle extend timeslot command."""
        log.info("Extending timeslot for session %s", request.session_id)

        session = await self._session_repository.get_by_id_async(request.session_id)
        if not session:
            return self.not_found(LabletSession, request.session_id)

        try:
            new_end = datetime.fromisoformat(request.new_timeslot_end.replace("Z", "+00:00"))
        except ValueError:
            return self.bad_request(f"Invalid new_timeslot_end format: {request.new_timeslot_end}")

        try:
            old_end = session.state.timeslot_end
            session.extend_timeslot(new_end=new_end, extended_by=request.extended_by)
        except ValueError as e:
            return self.bad_request(str(e))

        await self._session_repository.update_async(session)

        log.info(
            "Session %s timeslot extended from %s to %s by %s",
            request.session_id,
            old_end.isoformat(),
            new_end.isoformat(),
            request.extended_by,
        )

        return self.ok(
            {
                "session_id": request.session_id,
                "old_timeslot_end": old_end.isoformat(),
                "new_timeslot_end": new_end.isoformat(),
                "extended_by": request.extended_by,
            }
        )
