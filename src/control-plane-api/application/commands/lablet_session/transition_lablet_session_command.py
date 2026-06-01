"""Transition LabletSession command.

Phase 7D: Replaces TransitionLabletInstanceCommand.
Generic status transition for LabletSession states:
RUNNING, COLLECTING, STOPPING, STOPPED, ARCHIVED.

Per ADR-001: All state mutations go through Control Plane API.
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
from application.commands.worker.release_capacity_command import ReleaseCapacityCommand
from domain.entities.lablet_session import LabletSession
from domain.enums import LabletSessionStatus
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository

log = logging.getLogger(__name__)


@dataclass
class TransitionLabletSessionCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to transition a lablet session to a new status.

    Validates state transition and updates session.
    """

    session_id: str
    target_status: str
    reason: str | None = None


class TransitionLabletSessionCommandHandler(
    CommandHandlerBase,
    CommandHandler[TransitionLabletSessionCommand, OperationResult[dict[str, Any]]],
):
    """Handle transitioning a lablet session to a new status."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        lablet_session_repository: LabletSessionRepository,
        lablet_definition_repository: LabletDefinitionRepository,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._session_repository = lablet_session_repository
        self._definition_repository = lablet_definition_repository

    async def handle_async(self, request: TransitionLabletSessionCommand) -> OperationResult[dict[str, Any]]:
        """Handle transition lablet session command."""
        log.info("Transitioning session %s to %s", request.session_id, request.target_status)

        session = await self._session_repository.get_by_id_async(request.session_id)
        if not session:
            return self.not_found(LabletSession, request.session_id)

        try:
            target_status = LabletSessionStatus(request.target_status)
        except ValueError:
            return self.bad_request(f"Invalid target status: {request.target_status}. Valid values: {[s.value for s in LabletSessionStatus]}")

        current_status = session.state.status

        try:
            match target_status:
                case LabletSessionStatus.INSTANTIATING:
                    return self.bad_request("Use POST /internal/lablet-sessions/{id}/start-instantiation instead.")
                case LabletSessionStatus.READY:
                    return self.bad_request("Transition to READY requires user_session_id and cml_lab_id. Use POST /internal/lablet-sessions/{id}/mark-ready instead.")
                case LabletSessionStatus.RUNNING:
                    session.mark_running()
                case LabletSessionStatus.COLLECTING:
                    session.start_collection()
                case LabletSessionStatus.GRADING:
                    return self.bad_request("Transition to GRADING requires grading_session_id. Use POST /internal/lablet-sessions/{id}/start-grading instead.")
                case LabletSessionStatus.STOPPING:
                    session.start_stopping(reason=request.reason)
                case LabletSessionStatus.STOPPED:
                    session.mark_stopped()
                case LabletSessionStatus.ARCHIVED:
                    session.archive(archived_by="lablet-controller")
                case LabletSessionStatus.TERMINATED:
                    return self.bad_request("Use POST /internal/lablet-sessions/{id}/terminate instead.")
                case _:
                    return self.bad_request(f"Transition to {target_status.value} not supported via this endpoint")
        except Exception as e:
            log.error("State transition failed: %s", e)
            return self.conflict(f"Cannot transition from {current_status.value} to {target_status.value}: {e}")

        await self._session_repository.update_async(session)

        # Release worker capacity when transitioning to STOPPING.
        # This is the "normal completion" path (RUNNING → ... → STOPPING).
        # Without this, capacity leaks for sessions that complete normally
        # without going through expire or terminate.
        capacity_released = None
        if target_status == LabletSessionStatus.STOPPING and session.state.worker_id:
            try:
                cpu_cores = 0
                memory_gb = 0
                storage_gb = 0
                if session.state.definition_id:
                    definition = await self._definition_repository.get_by_id_async(session.state.definition_id)
                    if definition:
                        resource_reqs = definition.state.resource_requirements
                        cpu_cores = resource_reqs.cpu_cores
                        memory_gb = resource_reqs.memory_gb
                        storage_gb = resource_reqs.storage_gb
                    else:
                        log.warning(
                            "LabletDefinition %s not found for session %s — capacity release will use 0 values",
                            session.state.definition_id,
                            request.session_id,
                        )

                release_result = await self.mediator.execute_async(
                    ReleaseCapacityCommand(
                        worker_id=session.state.worker_id,
                        session_id=request.session_id,
                        cpu_cores=cpu_cores,
                        memory_gb=memory_gb,
                        storage_gb=storage_gb,
                    )
                )
                capacity_released = release_result.is_success
                if not capacity_released:
                    log.warning(
                        "Capacity release failed for session %s on STOPPING: %s",
                        request.session_id,
                        release_result.error_message,
                    )
            except Exception as e:
                log.error("Error releasing capacity for session %s on STOPPING: %s", request.session_id, e)
                capacity_released = False

        return self.ok(
            {
                "session_id": request.session_id,
                "previous_status": current_status.value,
                "current_status": session.state.status.value,
                "reason": request.reason,
                **(
                    {
                        "capacity_released": capacity_released,
                    }
                    if capacity_released is not None
                    else {}
                ),
            }
        )
