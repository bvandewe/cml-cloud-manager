"""Request resource observation for a live CML lab session.

Self-contained command + handler (established CQRS pattern).
Called by admin via external API to trigger on-demand observation.
The command emits a domain event that is projected to etcd,
which lablet-controller watches and reacts to.

ADR-030 / AD-OLR-007: Manual trigger via reactive etcd watch.
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
from domain.enums import LabletSessionStatus
from domain.repositories.lablet_session_repository import LabletSessionRepository

log = logging.getLogger(__name__)


@dataclass
class RequestResourceObservationCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to request resource observation on a LabletSession.

    Triggers lablet-controller to observe CML runtime resources
    and report back via the internal API.
    """

    session_id: str
    requested_by: str = ""


class RequestResourceObservationCommandHandler(
    CommandHandlerBase,
    CommandHandler[RequestResourceObservationCommand, OperationResult[dict[str, Any]]],
):
    """Handle requesting resource observation for a LabletSession.

    Validates session state, calls aggregate method to emit the
    ObserveResourcesRequested domain event, and persists.
    The event triggers an etcd projector for lablet-controller to react.
    """

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

    async def handle_async(self, request: RequestResourceObservationCommand) -> OperationResult[dict[str, Any]]:
        """Handle request resource observation command."""
        log.info("Requesting resource observation for session %s (by %s)", request.session_id, request.requested_by)

        session = await self._session_repository.get_by_id_async(request.session_id)
        if not session:
            return self.not_found(LabletSession, request.session_id)

        # Validate session is in an observable state
        observable_states = {LabletSessionStatus.RUNNING, LabletSessionStatus.COLLECTING}
        if session.state.status not in observable_states:
            return self.bad_request(f"Cannot request observation for session in '{session.state.status.value}' state. Session must be in {[s.value for s in observable_states]}")

        # Validate session has a CML lab and worker assigned
        if not session.state.cml_lab_id:
            return self.bad_request("Session does not have a CML lab assigned")
        if not session.state.worker_id:
            return self.bad_request("Session does not have a worker assigned")

        # Emit the observation request event (triggers etcd projector)
        session.request_resource_observation(requested_by=request.requested_by)

        await self._session_repository.update_async(session)

        return self.accepted(
            {
                "session_id": request.session_id,
                "message": "Resource observation requested. Results will be recorded asynchronously.",
            }
        )
