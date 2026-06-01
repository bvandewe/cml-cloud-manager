"""Bind Lab to Lablet Command — binds a LabRecord to a LabletSession.

Phase 7F: Refactored to use LabletSession.lab_record_id (direct 1:1 FK)
instead of the deprecated LabletLabBinding entity (ADR-020 §2).

Architecture ref: §5.2 (binding lifecycle), §8.4 (binding endpoint).
"""

import logging
from dataclasses import dataclass

from lcm_core.domain.enums import BindingRole
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator
from opentelemetry import trace

from domain.entities.lab_record import LabRecord
from domain.entities.lablet_session import LabletSession
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class BindLabToLabletCommand(Command[OperationResult[dict]]):
    """Command to bind a LabRecord to a LabletSession.

    Sets lab_record_id on the LabletSession aggregate (ADR-020 §2)
    and records the binding event on LabRecord.

    Attributes:
        lab_record_id: LabRecord aggregate ID.
        lablet_session_id: LabletSession aggregate ID.
        role: Binding role (PRIMARY, SECONDARY, AUXILIARY). Defaults to PRIMARY.
        metadata: Optional extra context (e.g., port mappings).
    """

    lab_record_id: str
    lablet_session_id: str
    role: str = "primary"
    metadata: dict | None = None


class BindLabToLabletCommandHandler(
    CommandHandlerBase,
    CommandHandler[BindLabToLabletCommand, OperationResult[dict]],
):
    """Handler for BindLabToLabletCommand — sets lab_record_id on session and records event."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        lab_record_repository: LabRecordRepository,
        lablet_session_repository: LabletSessionRepository,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._lab_repository = lab_record_repository
        self._session_repository = lablet_session_repository

    async def handle_async(self, request: BindLabToLabletCommand) -> OperationResult[dict]:
        """Create a binding between LabRecord and LabletSession."""
        with tracer.start_as_current_span("bind_lab_to_lablet_command") as span:
            span.set_attribute("lab_record.id", request.lab_record_id)
            span.set_attribute("lablet_session.id", request.lablet_session_id)
            span.set_attribute("binding.role", request.role)

            try:
                # 1. Validate lab record exists
                lab = await self._lab_repository.get_by_id_async(request.lab_record_id)
                if not lab:
                    return self.not_found(LabRecord, request.lab_record_id)

                if lab.is_terminal:
                    return self.bad_request(f"Cannot bind lab in terminal state: {lab.state.status.value}")

                # 2. Validate session exists
                session = await self._session_repository.get_by_id_async(request.lablet_session_id)
                if not session:
                    return self.not_found(LabletSession, request.lablet_session_id)

                # 3. Check for existing binding on this session
                if session.state.lab_record_id == request.lab_record_id:
                    return self.conflict(f"Active binding already exists between LabRecord {request.lab_record_id} and LabletSession {request.lablet_session_id}")
                if session.state.lab_record_id and session.state.lab_record_id != request.lab_record_id:
                    return self.conflict(f"LabletSession {request.lablet_session_id} is already bound to LabRecord {session.state.lab_record_id}")

                # 4. Parse role enum
                try:
                    binding_role = BindingRole(request.role.lower())
                except ValueError:
                    return self.bad_request(f"Invalid binding role: {request.role}. Valid roles: {[r.value for r in BindingRole]}")

                # 5. Set lab_record_id on session (direct 1:1 FK, ADR-020 §2)
                session.state.lab_record_id = request.lab_record_id
                await self._session_repository.update_async(session)

                # 6. Record binding event on LabRecord aggregate
                lab.bind_to_lablet(
                    lablet_session_id=request.lablet_session_id,
                    binding_id=request.lablet_session_id,  # session ID serves as binding ID
                    binding_role=binding_role.value,
                )
                await self._lab_repository.update_async(lab)

                log.info(
                    "Lab bound to lablet session: lab_record_id=%s, lablet_session_id=%s, role=%s",
                    request.lab_record_id,
                    request.lablet_session_id,
                    binding_role.value,
                )

                return self.created(
                    {
                        "binding_id": request.lablet_session_id,
                        "lab_record_id": request.lab_record_id,
                        "lablet_session_id": request.lablet_session_id,
                        "role": binding_role.value,
                        "status": "active",
                        "message": "Lab bound to lablet session",
                    }
                )

            except Exception as e:
                error_msg = f"Error binding lab {request.lab_record_id} to session {request.lablet_session_id}: {e}"
                log.error(error_msg, exc_info=True)
                return self.internal_server_error(error_msg)
