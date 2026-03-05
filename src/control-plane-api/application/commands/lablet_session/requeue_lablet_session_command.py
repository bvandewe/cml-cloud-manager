"""Requeue LabletSession command with handler.

Re-queues a stuck session for reconciliation by recording a requeue
event (bumps updated_at, records in state_history) without changing
the session status. This allows etcd watchers or change-detection
mechanisms to pick up the session for re-processing.

Supports both single and bulk requeue operations.
"""

import logging
from dataclasses import dataclass, field

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.lablet_session import InvalidStateTransitionError, LabletSession
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

logger = logging.getLogger(__name__)


@dataclass
class RequeueLabletSessionDto:
    """DTO returned after re-queuing a LabletSession."""

    id: str
    status: str
    requeued_by: str
    reason: str | None


@dataclass
class RequeueLabletSessionCommand(Command[OperationResult[RequeueLabletSessionDto]]):
    """Command to re-queue a single LabletSession for reconciliation.

    Does NOT change session status — only bumps updated_at and records
    the requeue in state_history for audit trail.
    """

    session_id: str
    requeued_by: str
    reason: str | None = None


class RequeueLabletSessionCommandHandler(
    CommandHandlerBase,
    CommandHandler[RequeueLabletSessionCommand, OperationResult[RequeueLabletSessionDto]],
):
    """Handle re-queuing a LabletSession for reconciliation."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        lablet_session_repository: LabletSessionRepository,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._repository = lablet_session_repository

    async def handle_async(self, request: RequeueLabletSessionCommand) -> OperationResult[RequeueLabletSessionDto]:
        """Handle requeue LabletSession command."""
        if not request.session_id or not request.session_id.strip():
            return self.bad_request("Session ID is required")

        if not request.requeued_by or not request.requeued_by.strip():
            return self.bad_request("Requeued by is required")

        try:
            session = await self._repository.get_by_id_async(request.session_id.strip())
            if not session:
                return self.not_found(LabletSession, request.session_id)

            session.requeue(
                requeued_by=request.requeued_by.strip(),
                reason=request.reason,
            )

            await self._repository.update_async(session)

            logger.info(
                "Requeued LabletSession: %s (status=%s, by=%s, reason=%s)",
                request.session_id,
                session.state.status.value,
                request.requeued_by,
                request.reason,
            )

            return self.ok(
                RequeueLabletSessionDto(
                    id=session.id(),
                    status=session.state.status.value,
                    requeued_by=request.requeued_by.strip(),
                    reason=request.reason,
                )
            )

        except InvalidStateTransitionError as e:
            return self.conflict(str(e))
        except Exception as e:
            logger.exception("Failed to requeue LabletSession %s: %s", request.session_id, e)
            return self.internal_server_error(f"Failed to requeue session: {e}")


@dataclass
class BulkRequeueLabletSessionsCommand(Command[OperationResult[dict]]):
    """Command to re-queue multiple LabletSessions for reconciliation."""

    session_ids: list[str] = field(default_factory=list)
    requeued_by: str = ""
    reason: str | None = None


class BulkRequeueLabletSessionsCommandHandler(
    CommandHandlerBase,
    CommandHandler[BulkRequeueLabletSessionsCommand, OperationResult[dict]],
):
    """Handle bulk re-queuing of LabletSessions."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        lablet_session_repository: LabletSessionRepository,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._repository = lablet_session_repository

    async def handle_async(self, request: BulkRequeueLabletSessionsCommand) -> OperationResult[dict]:
        """Handle bulk requeue LabletSessions command."""
        if not request.session_ids:
            return self.bad_request("At least one session ID is required")

        if not request.requeued_by or not request.requeued_by.strip():
            return self.bad_request("Requeued by is required")

        success_count = 0
        fail_count = 0
        errors: list[dict] = []

        for session_id in request.session_ids:
            try:
                session = await self._repository.get_by_id_async(session_id.strip())
                if not session:
                    fail_count += 1
                    errors.append({"session_id": session_id, "error": "Not found"})
                    continue

                session.requeue(
                    requeued_by=request.requeued_by.strip(),
                    reason=request.reason,
                )
                await self._repository.update_async(session)
                success_count += 1

            except InvalidStateTransitionError as e:
                fail_count += 1
                errors.append({"session_id": session_id, "error": str(e)})
            except Exception as e:
                fail_count += 1
                errors.append({"session_id": session_id, "error": str(e)})
                logger.exception("Failed to requeue session %s: %s", session_id, e)

        logger.info(
            "Bulk requeue completed: %d succeeded, %d failed (by=%s)",
            success_count,
            fail_count,
            request.requeued_by,
        )

        return self.ok(
            {
                "success_count": success_count,
                "fail_count": fail_count,
                "errors": errors,
            }
        )
