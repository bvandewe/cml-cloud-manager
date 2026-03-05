"""Update UserSession Status command.

Phase 7D: Transitions UserSession through its lifecycle states.
Dispatches to appropriate lifecycle methods: mark_provisioned, activate,
pause, resume, end, expire, fault.

ADR-021: UserSession is Entity[str] — state transitions are direct method calls.
"""

import logging
from dataclasses import dataclass
from typing import Any

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.user_session import UserSession
from domain.enums import UserSessionStatus
from domain.repositories.user_session_repository import UserSessionRepository
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

log = logging.getLogger(__name__)


@dataclass
class UpdateUserSessionStatusCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to transition a UserSession to a new status.

    Attributes:
        user_session_id: The UserSession entity ID.
        target_status: Target status string.
        lds_login_url: Required for PROVISIONING → PROVISIONED transition.
        devices: Optional device list for PROVISIONED transition.
        error_message: Optional error message for FAULTED transition.
    """

    user_session_id: str
    target_status: str
    lds_login_url: str | None = None
    devices: list[dict[str, Any]] | None = None
    error_message: str | None = None


class UpdateUserSessionStatusCommandHandler(
    CommandHandlerBase,
    CommandHandler[UpdateUserSessionStatusCommand, OperationResult[dict[str, Any]]],
):
    """Handle UserSession status transitions."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        user_session_repository: UserSessionRepository,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._repository = user_session_repository

    async def handle_async(self, request: UpdateUserSessionStatusCommand) -> OperationResult[dict[str, Any]]:
        """Handle update user session status command."""
        log.info("Updating UserSession %s to %s", request.user_session_id, request.target_status)

        user_session = await self._repository.get_by_id_async(request.user_session_id)
        if not user_session:
            return self.not_found(UserSession, request.user_session_id)

        try:
            target = UserSessionStatus(request.target_status)
        except ValueError:
            return self.bad_request(f"Invalid target status: {request.target_status}. Valid values: {[s.value for s in UserSessionStatus]}")

        current_status = user_session.status

        try:
            match target:
                case UserSessionStatus.PROVISIONED:
                    if not request.lds_login_url:
                        return self.bad_request("lds_login_url is required for PROVISIONED transition")
                    user_session.mark_provisioned(
                        lds_login_url=request.lds_login_url,
                        devices=request.devices,
                    )
                case UserSessionStatus.ACTIVE:
                    user_session.activate()
                case UserSessionStatus.PAUSED:
                    user_session.pause()
                case UserSessionStatus.ENDED:
                    user_session.end()
                case UserSessionStatus.EXPIRED:
                    user_session.expire()
                case UserSessionStatus.FAULTED:
                    user_session.fault(error_message=request.error_message)
                case _:
                    return self.bad_request(f"Transition to {target.value} not supported via this endpoint")
        except Exception as e:
            log.warning("UserSession %s transition failed: %s", request.user_session_id, e)
            return self.conflict(f"Cannot transition from {current_status.value} to {target.value}: {e}")

        await self._repository.update_async(user_session)

        return self.ok(
            {
                "user_session_id": request.user_session_id,
                "previous_status": current_status.value,
                "current_status": user_session.status.value,
            }
        )
