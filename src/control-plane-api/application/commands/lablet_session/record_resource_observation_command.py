"""Record resource observations from a live CML lab session.

Self-contained command + handler (established CQRS pattern).
Called by lablet-controller via internal API after CML runtime introspection.

ADR-030: Resource & Port Observation — "Learn from Live"
"""

import logging
from dataclasses import dataclass
from typing import Any

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.lablet_session import LabletSession
from domain.enums import LabletSessionStatus
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

log = logging.getLogger(__name__)


@dataclass
class RecordResourceObservationCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to record resource observations on a LabletSession.

    Sent by lablet-controller after CML runtime introspection.
    """

    session_id: str
    observed_resources: dict  # Serialized ResourceObservation
    observed_ports: dict[str, int]  # Actual CML port allocations


class RecordResourceObservationCommandHandler(
    CommandHandlerBase,
    CommandHandler[RecordResourceObservationCommand, OperationResult[dict[str, Any]]],
):
    """Handle recording resource observations on a LabletSession.

    Validates session state, delegates to aggregate method for drift detection,
    and persists the updated session.
    """

    def __init__(self, lablet_session_repository: LabletSessionRepository):
        self._session_repository = lablet_session_repository

    async def handle_async(self, request: RecordResourceObservationCommand) -> OperationResult[dict[str, Any]]:
        """Handle record resource observation command."""
        log.info("Recording resource observation for session %s", request.session_id)

        session = await self._session_repository.get_by_id_async(request.session_id)
        if not session:
            return self.not_found(LabletSession, request.session_id)

        # Validate session is in an observable state
        observable_states = {LabletSessionStatus.RUNNING, LabletSessionStatus.COLLECTING}
        if session.state.status not in observable_states:
            return self.bad_request(f"Cannot record observations for session in '{session.state.status.value}' state. Session must be in {[s.value for s in observable_states]}")

        # Record the observation (drift detection happens inside aggregate)
        session.record_resource_observation(
            observed_resources=request.observed_resources,
            observed_ports=request.observed_ports,
        )

        await self._session_repository.update_async(session)

        drift = session.state.port_drift_detected
        if drift:
            log.warning("Port drift detected for session %s", request.session_id)

        return self.ok(
            {
                "session_id": request.session_id,
                "observation_count": session.state.observation_count,
                "port_drift_detected": drift,
                "observed_at": session.state.observed_at.isoformat() if session.state.observed_at else None,
            }
        )
