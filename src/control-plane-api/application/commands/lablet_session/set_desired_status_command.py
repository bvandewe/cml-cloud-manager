"""Set Desired Status command for LabletSession.

ADR-034 Sprint E / ADR-015 pattern: Sets the desired lifecycle state (spec)
on a LabletSession. Controllers watch etcd for desired_status changes and
reconcile actual state towards the desired state.

Unlike CMLWorker which uses verb-based commands (Start/Stop/Terminate),
LabletSession uses a single generic command since the reconciliation
target can be any valid lifecycle state.
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

# Valid desired_status targets for sessions
VALID_DESIRED_STATUSES = (
    LabletSessionStatus.RUNNING,
    LabletSessionStatus.STOPPED,
    LabletSessionStatus.TERMINATED,
)


@dataclass
class SetDesiredStatusCommand(Command[OperationResult[dict[str, Any]]]):
    """Set the desired lifecycle state for a LabletSession.

    ADR-034 Sprint E: Generic desired_status update — the reconciliation
    target for the lablet-controller.

    Attributes:
        session_id: The LabletSession ID.
        desired_status: Target lifecycle state ("running", "stopped", "terminated").
        requested_by: User or system identifier requesting the change.
        reason: Optional reason for the change.
    """

    session_id: str
    desired_status: str
    requested_by: str | None = None
    reason: str | None = None


class SetDesiredStatusCommandHandler(
    CommandHandlerBase,
    CommandHandler[SetDesiredStatusCommand, OperationResult[dict[str, Any]]],
):
    """Handle desired status updates for LabletSession.

    ADR-034 Sprint E / ADR-015: Validates the target status, loads the
    session aggregate, and calls update_desired_status() which emits a
    domain event. The etcd projector writes the desired_status to etcd,
    and controllers watch for the change to begin reconciliation.

    Workflow:
    1. Validate desired_status is a valid target
    2. Load LabletSession
    3. Call session.update_desired_status() (no-op if already at target)
    4. Persist if changed
    """

    def __init__(self, lablet_session_repository: LabletSessionRepository):
        self._session_repo = lablet_session_repository

    async def handle_async(self, request: SetDesiredStatusCommand) -> OperationResult[dict[str, Any]]:
        """Handle desired status update."""
        log.info(
            "Setting desired_status for session %s → %s (requested_by=%s, reason=%s)",
            request.session_id,
            request.desired_status,
            request.requested_by,
            request.reason,
        )

        # Validate desired_status
        try:
            target = LabletSessionStatus(request.desired_status)
        except ValueError:
            return self.bad_request(f"Invalid desired_status '{request.desired_status}'. Must be one of: {', '.join(s.value for s in VALID_DESIRED_STATUSES)}")

        if target not in VALID_DESIRED_STATUSES:
            return self.bad_request(f"Cannot set desired_status to '{target.value}'. Valid targets: {', '.join(s.value for s in VALID_DESIRED_STATUSES)}")

        # Load session
        session = await self._session_repo.get_by_id_async(request.session_id)
        if not session:
            return self.not_found(LabletSession, request.session_id)

        # Apply desired_status (no-op if already at target)
        changed = session.update_desired_status(
            new_desired_status=target,
            requested_by=request.requested_by,
            reason=request.reason,
        )

        if not changed:
            log.info(
                "Session %s desired_status already at '%s' — no change",
                request.session_id,
                target.value,
            )
            return self.ok(
                {
                    "session_id": request.session_id,
                    "desired_status": target.value,
                    "changed": False,
                }
            )

        # Persist
        await self._session_repo.update_async(session)

        log.info(
            "Session %s desired_status updated → %s",
            request.session_id,
            target.value,
        )
        return self.ok(
            {
                "session_id": request.session_id,
                "desired_status": target.value,
                "changed": True,
            }
        )
