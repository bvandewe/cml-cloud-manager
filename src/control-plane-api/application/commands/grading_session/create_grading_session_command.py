"""Create GradingSession command.

Phase 7D: Creates a GradingSession child entity in PENDING state.
GradingSession tracks the assessment grading lifecycle.

ADR-021: GradingSession is Entity[str], not AggregateRoot — no domain events.
"""

import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.grading_session import GradingSession
from domain.repositories.grading_session_repository import GradingSessionRepository

log = logging.getLogger(__name__)


@dataclass
class CreateGradingSessionCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to create a GradingSession in PENDING state.

    Attributes:
        lablet_session_id: Parent LabletSession ID.
        external_grading_session_id: External Grading Engine session ID.
        grading_part_id: Optional grading part identifier.
        pod_id: Optional pod identifier.
        form_qualified_name: Optional form qualified name.
        grading_rules_uri: Optional URI to grading rules.
        devices: Optional device list for grading context.
    """

    lablet_session_id: str
    external_grading_session_id: str | None = None
    grading_part_id: str | None = None
    pod_id: str | None = None
    form_qualified_name: str | None = None
    grading_rules_uri: str | None = None
    devices: list[dict[str, Any]] | None = None


class CreateGradingSessionCommandHandler(
    CommandHandlerBase,
    CommandHandler[CreateGradingSessionCommand, OperationResult[dict[str, Any]]],
):
    """Handle GradingSession creation."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        grading_session_repository: GradingSessionRepository,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._repository = grading_session_repository

    async def handle_async(self, request: CreateGradingSessionCommand) -> OperationResult[dict[str, Any]]:
        """Handle create grading session command."""
        if not request.lablet_session_id or not request.lablet_session_id.strip():
            return self.bad_request("lablet_session_id is required")

        # Check for existing grading session for this lablet session
        existing = await self._repository.get_by_lablet_session_async(request.lablet_session_id)
        if existing:
            return self.conflict(f"GradingSession already exists for lablet_session_id '{request.lablet_session_id}'")

        grading_session = GradingSession.create(
            grading_session_id=str(uuid4()),
            lablet_session_id=request.lablet_session_id.strip(),
            external_grading_session_id=request.external_grading_session_id,
            grading_part_id=request.grading_part_id,
            pod_id=request.pod_id,
            form_qualified_name=request.form_qualified_name,
            grading_rules_uri=request.grading_rules_uri,
            devices=request.devices,
        )

        await self._repository.add_async(grading_session)

        log.info(
            "Created GradingSession %s for lablet_session %s",
            grading_session.id,
            request.lablet_session_id,
        )

        return self.created(
            {
                "grading_session_id": grading_session.id,
                "lablet_session_id": grading_session.lablet_session_id,
                "status": grading_session.status.value,
            }
        )
