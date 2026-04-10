"""Create UserSession command.

Phase 7D: Creates a UserSession child entity in PROVISIONING state.
UserSession tracks the LDS (Lab Delivery System) session for a user.

ADR-021: UserSession is Entity[str], not AggregateRoot — no domain events.
"""

import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.user_session import UserSession
from domain.repositories.user_session_repository import UserSessionRepository
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

log = logging.getLogger(__name__)


@dataclass
class CreateUserSessionCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to create a UserSession in PROVISIONING state.

    If ``lds_login_url`` is supplied the entity is immediately transitioned
    to PROVISIONED (via ``mark_provisioned``) so that the login URL is
    persisted together with creation — matching the lablet-controller flow
    where the LDS session, launch URL and device list are all obtained
    before this command is dispatched.

    Attributes:
        lablet_session_id: Parent LabletSession ID.
        lds_session_id: LDS session identifier from provisioning.
        lds_login_url: Optional JWT-signed launch URL (triggers PROVISIONED).
        lds_part_id: Optional LDS part identifier.
        form_qualified_name: Optional form qualified name for assessment.
    """

    lablet_session_id: str
    lds_session_id: str
    lds_login_url: str | None = None
    lds_part_id: str | None = None
    form_qualified_name: str | None = None


class CreateUserSessionCommandHandler(
    CommandHandlerBase,
    CommandHandler[CreateUserSessionCommand, OperationResult[dict[str, Any]]],
):
    """Handle UserSession creation."""

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

    async def handle_async(self, request: CreateUserSessionCommand) -> OperationResult[dict[str, Any]]:
        """Handle create user session command."""
        if not request.lablet_session_id or not request.lablet_session_id.strip():
            return self.bad_request("lablet_session_id is required")

        if not request.lds_session_id or not request.lds_session_id.strip():
            return self.bad_request("lds_session_id is required")

        # Check if one already exists for this lablet session
        existing = await self._repository.get_by_lablet_session_async(request.lablet_session_id)
        if existing:
            return self.conflict(f"UserSession already exists for lablet_session_id '{request.lablet_session_id}'")

        user_session = UserSession.create(
            user_session_id=str(uuid4()),
            lablet_session_id=request.lablet_session_id.strip(),
            lds_session_id=request.lds_session_id.strip(),
            lds_part_id=request.lds_part_id,
            form_qualified_name=request.form_qualified_name,
        )

        # If a login URL was provided, immediately transition to PROVISIONED
        # so the URL is persisted on creation (lablet-controller flow).
        if request.lds_login_url:
            user_session.mark_provisioned(login_url=request.lds_login_url)

        await self._repository.add_async(user_session)

        log.info(
            "Created UserSession %s for lablet_session %s (lds_session_id=%s, status=%s)",
            user_session.id,
            request.lablet_session_id,
            request.lds_session_id,
            user_session.status.value,
        )

        return self.created(
            {
                "id": user_session.id,
                "user_session_id": user_session.id,
                "lablet_session_id": user_session.lablet_session_id,
                "lds_session_id": user_session.lds_session_id,
                "login_url": user_session.login_url,
                "status": user_session.status.value,
            }
        )
