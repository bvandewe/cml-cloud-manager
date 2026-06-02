"""Timeout stale pending actions command (R5 domain resilience hardening).

Finds LabRecord entities whose pending_action has been stuck longer than
a configurable threshold and auto-fails them.  This prevents actions that
were requested but never completed (e.g. due to a controller crash, network
partition, or CML API timeout) from blocking future operations indefinitely.

Designed to be invoked periodically by the lablet-controller reconciliation
loop or via an internal API endpoint.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from domain.repositories.lab_record_repository import LabRecordRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)

# Default timeout: 30 minutes — actions not completed within this window
# are considered stale and will be auto-failed.
DEFAULT_STALE_THRESHOLD_MINUTES = 30


@dataclass
class TimeoutStalePendingActionsResult:
    """Result of the stale pending actions timeout sweep."""

    scanned: int  # Total records with pending actions
    timed_out: int  # Records whose pending action was auto-failed
    skipped: int  # Records still within threshold
    errors: list[str] = field(default_factory=list)  # Per-record error messages


@dataclass
class TimeoutStalePendingActionsCommand(Command[OperationResult[TimeoutStalePendingActionsResult]]):
    """Command to auto-fail stale pending actions on LabRecord entities.

    Args:
        threshold_minutes: Minutes after which a pending action is considered
            stale.  Defaults to DEFAULT_STALE_THRESHOLD_MINUTES (30).
        worker_id: Optional — scope the sweep to a single worker's labs.
            When None, all lab records with pending actions are checked.
    """

    threshold_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES
    worker_id: str | None = None


class TimeoutStalePendingActionsCommandHandler(
    CommandHandlerBase,
    CommandHandler[TimeoutStalePendingActionsCommand, OperationResult[TimeoutStalePendingActionsResult]],
):
    """Sweep pending actions and auto-fail those exceeding the threshold."""

    def __init__(self, lab_record_repository: LabRecordRepository):
        self.lab_record_repository = lab_record_repository

    async def handle_async(
        self,
        request: TimeoutStalePendingActionsCommand,
        cancellation_token=None,
    ) -> OperationResult[TimeoutStalePendingActionsResult]:
        """Execute the stale pending action timeout sweep.

        For each LabRecord with a pending action whose ``pending_action_at``
        timestamp is older than ``now - threshold_minutes``, calls
        ``fail_pending_action()`` and persists the update.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=request.threshold_minutes)

        # Fetch records with pending actions (optionally scoped to one worker)
        if request.worker_id:
            records = await self.lab_record_repository.get_with_pending_actions_by_worker_async(
                request.worker_id,
            )
        else:
            records = await self.lab_record_repository.get_with_pending_actions_async()

        scanned = len(records)
        timed_out = 0
        skipped = 0
        errors: list[str] = []

        for record in records:
            try:
                # Guard: if pending_action_at is missing or still within threshold, skip
                if record.state.pending_action_at is None or record.state.pending_action_at > cutoff:
                    skipped += 1
                    continue

                stale_minutes = int((datetime.now(timezone.utc) - record.state.pending_action_at).total_seconds() / 60)
                log.warning(
                    "Lab %s (%s): pending action '%s' stale for %d min (threshold=%d min) — auto-failing",
                    record.id(),
                    record.state.lab_id,
                    record.state.pending_action,
                    stale_minutes,
                    request.threshold_minutes,
                )
                record.fail_pending_action(f"Timed out after {stale_minutes} minutes (threshold: {request.threshold_minutes} min)")
                await self.lab_record_repository.update_async(record, cancellation_token)
                timed_out += 1
            except Exception as exc:
                msg = f"Failed to timeout stale action for lab {record.state.lab_id}: {exc}"
                log.error(msg, exc_info=True)
                errors.append(msg)

        result = TimeoutStalePendingActionsResult(
            scanned=scanned,
            timed_out=timed_out,
            skipped=skipped,
            errors=errors,
        )

        if timed_out > 0:
            log.info(
                "Stale pending action sweep: scanned=%d, timed_out=%d, skipped=%d, errors=%d",
                scanned,
                timed_out,
                skipped,
                len(errors),
            )

        return self.ok(result)
