"""Update GradingSession Status command.

Phase 7D: Transitions GradingSession through its lifecycle states.
Dispatches to lifecycle methods: start_collecting, start_grading,
start_reviewing, submit, fault.

ADR-021: GradingSession is Entity[str] — state transitions are direct method calls.
"""

import logging
from dataclasses import dataclass
from typing import Any

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.grading_session import GradingSession
from domain.enums import GradingSessionStatus
from domain.repositories.grading_session_repository import GradingSessionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

log = logging.getLogger(__name__)


@dataclass
class UpdateGradingSessionStatusCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to transition a GradingSession to a new status.

    Attributes:
        grading_session_id: The GradingSession entity ID.
        target_status: Target status string.
        error_message: Optional error message for FAULTED transition.
    """

    grading_session_id: str
    target_status: str
    error_message: str | None = None


class UpdateGradingSessionStatusCommandHandler(
    CommandHandlerBase,
    CommandHandler[UpdateGradingSessionStatusCommand, OperationResult[dict[str, Any]]],
):
    """Handle GradingSession status transitions."""

    def __init__(self, grading_session_repository: GradingSessionRepository):
        self._repository = grading_session_repository

    async def handle_async(self, request: UpdateGradingSessionStatusCommand) -> OperationResult[dict[str, Any]]:
        """Handle update grading session status command."""
        log.info("Updating GradingSession %s to %s", request.grading_session_id, request.target_status)

        grading_session = await self._repository.get_by_id_async(request.grading_session_id)
        if not grading_session:
            return self.not_found(GradingSession, request.grading_session_id)

        try:
            target = GradingSessionStatus(request.target_status)
        except ValueError:
            return self.bad_request(f"Invalid target status: {request.target_status}. Valid values: {[s.value for s in GradingSessionStatus]}")

        current_status = grading_session.status

        try:
            match target:
                case GradingSessionStatus.COLLECTING:
                    grading_session.start_collecting()
                case GradingSessionStatus.GRADING:
                    grading_session.start_grading()
                case GradingSessionStatus.REVIEWING:
                    grading_session.start_reviewing()
                case GradingSessionStatus.SUBMITTED:
                    grading_session.submit()
                case GradingSessionStatus.FAULTED:
                    grading_session.fault(error_message=request.error_message)
                case _:
                    return self.bad_request(f"Transition to {target.value} not supported via this endpoint")
        except Exception as e:
            log.warning("GradingSession %s transition failed: %s", request.grading_session_id, e)
            return self.conflict(f"Cannot transition from {current_status.value} to {target.value}: {e}")

        await self._repository.update_async(grading_session)

        return self.ok(
            {
                "grading_session_id": request.grading_session_id,
                "previous_status": current_status.value,
                "current_status": grading_session.status.value,
            }
        )
