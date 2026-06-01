"""Terminate LabletSession command with handler.

Phase 7D: Replaces TerminateLabletInstanceCommand.
Releases worker capacity on termination via ReleaseCapacityCommand.
Unbinds and queues wipe for the linked LabRecord (AD-WIPE-001).
"""

import logging
from dataclasses import dataclass

from application.commands.command_handler_base import CommandHandlerBase
from application.commands.lab.wipe_lab_record_command import WipeLabRecordCommand
from application.commands.worker.release_capacity_command import ReleaseCapacityCommand
from domain.entities.lablet_session import InvalidStateTransitionError, LabletSession
from domain.enums import LabletSessionStatus
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

logger = logging.getLogger(__name__)


@dataclass
class TerminateLabletSessionDto:
    """DTO returned after terminating a LabletSession."""

    id: str
    status: str
    terminated_at: str
    terminated_by: str
    reason: str | None


@dataclass
class TerminateLabletSessionCommand(Command[OperationResult[TerminateLabletSessionDto]]):
    """Command to terminate a LabletSession.

    Terminates the session from any valid state, performing cleanup
    and marking as TERMINATED.
    """

    session_id: str
    terminated_by: str
    reason: str | None = None


class TerminateLabletSessionCommandHandler(
    CommandHandlerBase,
    CommandHandler[TerminateLabletSessionCommand, OperationResult[TerminateLabletSessionDto]],
):
    """Handle LabletSession termination."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        lablet_session_repository: LabletSessionRepository,
        lablet_definition_repository: LabletDefinitionRepository,
        lab_record_repository: LabRecordRepository,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._repository = lablet_session_repository
        self._definition_repository = lablet_definition_repository
        self._lab_record_repository = lab_record_repository

    async def handle_async(self, request: TerminateLabletSessionCommand) -> OperationResult[TerminateLabletSessionDto]:
        """Handle terminate LabletSession command."""
        if not request.session_id or not request.session_id.strip():
            return self.bad_request("Session ID is required")

        if not request.terminated_by or not request.terminated_by.strip():
            return self.bad_request("Terminated by is required")

        try:
            session = await self._repository.get_by_id_async(request.session_id.strip())
            if not session:
                return self.not_found(LabletSession, request.session_id)

            if session.state.status == LabletSessionStatus.TERMINATED:
                return self.conflict(f"LabletSession '{request.session_id}' is already terminated")

            if not session.can_be_terminated:
                return self.conflict(f"LabletSession '{request.session_id}' cannot be terminated from current status '{session.state.status.value}'")

            # Release ports if allocated
            if session.state.allocated_ports:
                session.release_ports()

            session.terminate(
                terminated_by=request.terminated_by.strip(),
                reason=request.reason,
            )

            await self._repository.update_async(session)

            logger.info(
                "Terminated LabletSession: %s (by=%s, reason=%s)",
                session.id(),
                request.terminated_by,
                request.reason or "not specified",
            )

            # Release capacity on worker (best-effort)
            if session.state.worker_id:
                try:
                    definition = await self._definition_repository.get_by_id_async(session.state.definition_id)
                    cpu_cores = 0
                    memory_gb = 0
                    storage_gb = 0
                    if definition:
                        resource_reqs = definition.state.resource_requirements
                        cpu_cores = resource_reqs.cpu_cores
                        memory_gb = resource_reqs.memory_gb
                        storage_gb = resource_reqs.storage_gb

                    release_result = await self.mediator.execute_async(
                        ReleaseCapacityCommand(
                            worker_id=session.state.worker_id,
                            session_id=session.id(),
                            cpu_cores=cpu_cores,
                            memory_gb=memory_gb,
                            storage_gb=storage_gb,
                        )
                    )
                    if not release_result.is_success:
                        logger.warning(
                            "Failed to release capacity for session %s on worker %s: %s",
                            session.id(),
                            session.state.worker_id,
                            release_result.error_message,
                        )
                except Exception as e:
                    logger.warning(
                        "Error releasing capacity for session %s on worker %s: %s",
                        session.id(),
                        session.state.worker_id,
                        e,
                    )

            # Unbind LabRecord and queue wipe (best-effort, AD-WIPE-001)
            if session.state.lab_record_id:
                try:
                    lab_record = await self._lab_record_repository.get_by_id_async(session.state.lab_record_id)
                    if lab_record:
                        # Unbind if this session is the active binding
                        if lab_record.state.active_lablet_session_id == session.id():
                            binding_id = lab_record.state.active_binding_id or ""
                            lab_record.unbind_from_lablet(
                                lablet_session_id=session.id(),
                                binding_id=binding_id,
                            )
                            await self._lab_record_repository.update_async(lab_record)
                            logger.info(
                                "Unbound lab_record %s from terminated session %s",
                                session.state.lab_record_id,
                                session.id(),
                            )

                        # Queue wipe if lab is not terminal and has no pending action
                        if not lab_record.is_terminal and not lab_record.state.pending_action:
                            wipe_result = await self.mediator.execute_async(WipeLabRecordCommand(lab_record_id=session.state.lab_record_id))
                            if wipe_result.is_success:
                                logger.info(
                                    "Queued wipe for lab_record %s after session %s termination",
                                    session.state.lab_record_id,
                                    session.id(),
                                )
                            else:
                                logger.warning(
                                    "Failed to queue wipe for lab_record %s: %s",
                                    session.state.lab_record_id,
                                    wipe_result.error_message,
                                )
                except Exception as e:
                    logger.warning(
                        "Error during lab cleanup for terminated session %s: %s",
                        session.id(),
                        e,
                    )

            dto = TerminateLabletSessionDto(
                id=session.id(),
                status=session.state.status.value,
                terminated_at=session.state.terminated_at.isoformat() if session.state.terminated_at else "",
                terminated_by=request.terminated_by.strip(),
                reason=request.reason,
            )

            return self.ok(dto)

        except InvalidStateTransitionError as e:
            logger.warning("Invalid state transition for termination: %s", e)
            return self.conflict(str(e))

        except Exception as e:
            logger.error("Error terminating LabletSession: %s", e, exc_info=True)
            return self.internal_server_error(str(e))
