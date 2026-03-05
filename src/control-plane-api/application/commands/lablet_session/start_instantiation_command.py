"""Start Instantiation command.

Phase 7D: Replaces transition_lablet_instance(INSTANTIATING).
Transitions a LabletSession from SCHEDULED to INSTANTIATING.

Called by lablet-controller when it begins lab import/startup.
Per ADR-001: All state mutations go through Control Plane API.
"""

import logging
from dataclasses import dataclass
from typing import Any

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.lablet_session import LabletSession
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

log = logging.getLogger(__name__)


@dataclass
class StartInstantiationCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to begin lab instantiation for a LabletSession.

    Transitions: SCHEDULED → INSTANTIATING
    """

    session_id: str


class StartInstantiationCommandHandler(
    CommandHandlerBase,
    CommandHandler[StartInstantiationCommand, OperationResult[dict[str, Any]]],
):
    """Handle starting lab instantiation."""

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

    async def handle_async(self, request: StartInstantiationCommand) -> OperationResult[dict[str, Any]]:
        """Handle start instantiation command."""
        log.info("Starting instantiation for session %s", request.session_id)

        session = await self._session_repository.get_by_id_async(request.session_id)
        if not session:
            return self.not_found(LabletSession, request.session_id)

        try:
            session.start_instantiation()
        except Exception as e:
            log.warning("Cannot start instantiation for session %s: %s", request.session_id, e)
            return self.conflict(f"Invalid state transition: {e}")

        await self._session_repository.update_async(session)

        log.info("Session %s transitioned to INSTANTIATING", request.session_id)

        return self.ok(
            {
                "session_id": request.session_id,
                "status": session.state.status.value,
            }
        )
