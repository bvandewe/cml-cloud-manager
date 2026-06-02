"""Create LabletSession command with handler.

Phase 7D: Replaces CreateLabletInstanceCommand.
Creates a new LabletSession reservation in PENDING state.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from application.commands.command_handler_base import CommandHandlerBase
from application.dtos.lablet_session_dto import LabletSessionCreatedDto
from domain.entities.lablet_definition import LabletDefinition
from domain.entities.lablet_session import LabletSession
from domain.enums import LabletDefinitionStatus
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

logger = logging.getLogger(__name__)


@dataclass
class CreateLabletSessionCommand(Command[OperationResult[LabletSessionCreatedDto]]):
    """Command to create a new LabletSession (reservation request).

    A LabletSession represents a runtime lab session that will be scheduled
    and executed on a CML worker. Upon creation, it enters PENDING status
    awaiting scheduling by the resource-scheduler service.
    """

    definition_id: str
    owner_id: str
    timeslot_start: str  # ISO 8601 datetime string
    timeslot_end: str  # ISO 8601 datetime string
    reservation_id: str | None = None


class CreateLabletSessionCommandHandler(
    CommandHandlerBase,
    CommandHandler[CreateLabletSessionCommand, OperationResult[LabletSessionCreatedDto]],
):
    """Handle LabletSession creation (reservation request)."""

    def __init__(self, lablet_session_repository: LabletSessionRepository, lablet_definition_repository: LabletDefinitionRepository):
        self._session_repository = lablet_session_repository
        self._definition_repository = lablet_definition_repository

    async def handle_async(self, request: CreateLabletSessionCommand) -> OperationResult[LabletSessionCreatedDto]:
        """Handle create LabletSession command."""
        # Validate required fields
        if not request.definition_id or not request.definition_id.strip():
            return self.bad_request("Definition ID is required")

        if not request.owner_id or not request.owner_id.strip():
            return self.bad_request("Owner ID is required")

        if not request.timeslot_start or not request.timeslot_start.strip():
            return self.bad_request("Timeslot start is required")

        if not request.timeslot_end or not request.timeslot_end.strip():
            return self.bad_request("Timeslot end is required")

        try:
            # Parse timeslot dates
            try:
                timeslot_start = datetime.fromisoformat(request.timeslot_start.replace("Z", "+00:00"))
            except ValueError:
                return self.bad_request(f"Invalid timeslot_start format: {request.timeslot_start}")

            try:
                timeslot_end = datetime.fromisoformat(request.timeslot_end.replace("Z", "+00:00"))
            except ValueError:
                return self.bad_request(f"Invalid timeslot_end format: {request.timeslot_end}")

            if timeslot_end <= timeslot_start:
                return self.bad_request("timeslot_end must be after timeslot_start")

            now = datetime.now(timezone.utc)
            if timeslot_start < now:
                return self.bad_request("timeslot_start cannot be in the past")

            # Verify definition exists and is active
            definition = await self._definition_repository.get_by_id_async(request.definition_id.strip())
            if not definition:
                return self.not_found(LabletDefinition, request.definition_id)

            if definition.state.status != LabletDefinitionStatus.ACTIVE:
                return self.bad_request(f"LabletDefinition '{definition.state.name}' is not active (status: {definition.state.status.value})")

            # Check if reservation_id already exists
            if request.reservation_id:
                existing = await self._session_repository.get_by_reservation_id_async(request.reservation_id)
                if existing:
                    return self.conflict(f"LabletSession with reservation_id '{request.reservation_id}' already exists")

            # Create the aggregate
            session = LabletSession.create(
                definition_id=definition.id(),
                definition_name=definition.state.name,
                definition_version=definition.state.version,
                owner_id=request.owner_id.strip(),
                timeslot_start=timeslot_start,
                timeslot_end=timeslot_end,
                reservation_id=request.reservation_id,
            )

            await self._session_repository.add_async(session)

            logger.info(
                "Created LabletSession: %s (definition=%s v%s, owner=%s, timeslot=%s to %s)",
                session.id(),
                definition.state.name,
                definition.state.version,
                request.owner_id,
                timeslot_start.isoformat(),
                timeslot_end.isoformat(),
            )

            dto = LabletSessionCreatedDto(
                id=session.id(),
                definition_id=session.state.definition_id,
                definition_name=session.state.definition_name,
                definition_version=session.state.definition_version,
                owner_id=session.state.owner_id,
                status=session.state.status.value,
                timeslot_start=session.state.timeslot_start.isoformat(),
                timeslot_end=session.state.timeslot_end.isoformat(),
                reservation_id=session.state.reservation_id,
                created_at=session.state.created_at.isoformat(),
            )

            return self.created(dto)

        except ValueError as e:
            logger.warning("Validation error creating LabletSession: %s", e)
            return self.bad_request(str(e))

        except Exception as e:
            logger.error("Error creating LabletSession: %s", e, exc_info=True)
            return self.internal_server_error(str(e))
