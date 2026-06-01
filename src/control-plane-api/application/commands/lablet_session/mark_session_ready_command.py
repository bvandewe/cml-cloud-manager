"""Mark Session Ready command.

Phase 7D: Replaces MarkInstanceReadyCommand.
Atomically transitions a LabletSession from INSTANTIATING to READY
after lab deployment and UserSession provisioning are confirmed.

ADR-021: Now takes user_session_id + cml_lab_id (not lds_session_id/lds_login_url).
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
from domain.entities.lablet_session import LabletSession
from domain.repositories.lablet_session_repository import LabletSessionRepository

log = logging.getLogger(__name__)


@dataclass
class MarkSessionReadyCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to mark a lablet session as READY.

    Sets UserSession FK and CML lab ID, then transitions INSTANTIATING → READY.

    Attributes:
        session_id: The LabletSession aggregate ID.
        user_session_id: FK to the provisioned UserSession child entity.
        cml_lab_id: CML lab identifier on the worker.
    """

    session_id: str
    user_session_id: str
    cml_lab_id: str


class MarkSessionReadyCommandHandler(
    CommandHandlerBase,
    CommandHandler[MarkSessionReadyCommand, OperationResult[dict[str, Any]]],
):
    """Handle marking a lablet session as ready."""

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

    async def handle_async(self, request: MarkSessionReadyCommand) -> OperationResult[dict[str, Any]]:
        """Handle mark session ready command."""
        log.info(
            "Marking session %s as READY (user_session_id=%s, cml_lab_id=%s)",
            request.session_id,
            request.user_session_id,
            request.cml_lab_id,
        )

        session = await self._session_repository.get_by_id_async(request.session_id)
        if not session:
            return self.not_found(LabletSession, request.session_id)

        try:
            session.mark_ready(
                user_session_id=request.user_session_id,
                cml_lab_id=request.cml_lab_id,
            )
        except Exception as e:
            log.warning("Cannot mark session %s as ready: %s", request.session_id, e)
            return self.conflict(f"Invalid state transition: {e}")

        await self._session_repository.update_async(session)

        log.info(
            "Session %s marked READY (user_session_id=%s, cml_lab_id=%s)",
            request.session_id,
            request.user_session_id,
            request.cml_lab_id,
        )

        return self.ok(
            {
                "session_id": request.session_id,
                "status": "READY",
                "user_session_id": request.user_session_id,
                "cml_lab_id": request.cml_lab_id,
            }
        )
