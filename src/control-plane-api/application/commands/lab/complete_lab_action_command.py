"""Complete Lab Action Command — internal command to clear pending action on success.

Phase 8 (P8-13): Refactored from the existing CompletePendingLabActionCommand.
Called by lablet-controller (via internal API) when it has successfully completed
a pending action (start/stop/wipe/delete).

Also applies the corresponding typed status transition on the LabRecord,
and records run history entries (open on start, close on stop/wipe).

Architecture ref: §8.2 (internal endpoints), ADR-017 (reconciliation pattern).
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from domain.entities.lab_record import InvalidLabRecordTransitionError, LabRecord
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.value_objects.lab_run_record import LabRunRecord
from lcm_core.domain.enums import LabRecordStatus
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator
from opentelemetry import trace

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Map pending action names to LabRecordStatus transitions
_ACTION_TO_STATUS: dict[str, LabRecordStatus] = {
    "start": LabRecordStatus.BOOTED,
    "stop": LabRecordStatus.STOPPED,
    "wipe": LabRecordStatus.WIPED,
    "delete": LabRecordStatus.DELETED,
}


@dataclass
class CompleteLabActionCommand(Command[OperationResult[dict]]):
    """Internal command to mark a pending action as completed.

    Called by lablet-controller after it successfully executes a CML API operation.
    Clears the pending action and applies the corresponding status transition.

    Attributes:
        lab_record_id: LabRecord aggregate ID.
        action: The completed action (start/stop/wipe/delete).
        cml_state: Optional raw CML state string for legacy sync.
    """

    lab_record_id: str
    action: str | None = None
    cml_state: str | None = None


class CompleteLabActionCommandHandler(
    CommandHandlerBase,
    CommandHandler[CompleteLabActionCommand, OperationResult[dict]],
):
    """Handler for CompleteLabActionCommand — clears pending action and updates status."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        lab_record_repository: LabRecordRepository,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._lab_repository = lab_record_repository

    async def handle_async(self, request: CompleteLabActionCommand) -> OperationResult[dict]:
        """Complete a pending action and apply status transition."""
        with tracer.start_as_current_span("complete_lab_action_command") as span:
            span.set_attribute("lab_record.id", request.lab_record_id)
            span.set_attribute("action", request.action or "")
            span.set_attribute("adr", "ADR-017")

            try:
                lab = await self._lab_repository.get_by_id_async(request.lab_record_id)
                if not lab:
                    return self.not_found(LabRecord, request.lab_record_id)

                # Determine action to complete
                action = request.action or lab.state.pending_action
                if not action:
                    return self.bad_request(f"LabRecord {request.lab_record_id} has no pending action to complete")

                # Validate action matches pending action (if pending)
                if lab.state.pending_action and action != lab.state.pending_action:
                    log.warning(
                        "Action mismatch: completing '%s' but pending is '%s' for lab %s",
                        action,
                        lab.state.pending_action,
                        request.lab_record_id,
                    )

                # 1. Clear pending action
                lab.complete_pending_action()

                # 2. Apply corresponding status transition
                target_status = _ACTION_TO_STATUS.get(action)
                if target_status:
                    try:
                        self._apply_transition(lab, target_status)
                    except InvalidLabRecordTransitionError as e:
                        log.warning(
                            "Status transition failed after action complete: %s. Pending action cleared anyway.",
                            str(e),
                        )

                # 3. Record run history (best-effort — must not block the critical path)
                run_id = None
                try:
                    run_id = self._record_run(lab, action, target_status)
                except Exception as run_err:
                    log.error(
                        "Failed to record run history for lab %s action '%s': %s. Continuing with status transition and persistence.",
                        request.lab_record_id,
                        action,
                        run_err,
                        exc_info=True,
                    )

                # 4. Update legacy CML state if provided
                if request.cml_state:
                    lab.state.state = request.cml_state

                await self._lab_repository.update_async(lab)

                log.info(
                    "Lab action completed: lab_record_id=%s, action=%s, new_status=%s, run_id=%s",
                    request.lab_record_id,
                    action,
                    lab.state.status.value,
                    run_id,
                )

                return self.ok(
                    {
                        "lab_record_id": request.lab_record_id,
                        "action": action,
                        "status": lab.state.status.value,
                        "run_id": run_id,
                        "message": f"Action '{action}' completed",
                    }
                )

            except Exception as e:
                error_msg = f"Error completing action for lab {request.lab_record_id}: {e}"
                log.error(error_msg, exc_info=True)
                return self.internal_server_error(error_msg)

    def _apply_transition(self, lab, target_status: LabRecordStatus) -> None:
        """Apply the appropriate domain method for the target status."""
        if target_status == LabRecordStatus.BOOTED:
            lab.mark_started()
        elif target_status == LabRecordStatus.STOPPED:
            lab.mark_stopped()
        elif target_status == LabRecordStatus.WIPED:
            lab.mark_wiped()
        elif target_status == LabRecordStatus.DELETED:
            lab.mark_deleted()

    def _record_run(self, lab: LabRecord, action: str, target_status: LabRecordStatus | None) -> str | None:
        """Record run history based on the completed action.

        - start → opens a new run (started_at=now, no stopped_at)
        - stop/wipe → closes the most recent open run with stopped_at, duration, final_state
        - delete → closes any open run (terminal action)

        Returns the run_id if a run was created or closed, None otherwise.
        """
        now = datetime.now(timezone.utc)

        if action == "start":
            # Guard: do not open a new run if the last run is still active (no stopped_at)
            if lab.state.run_history_v2:
                last_run = lab.state.run_history_v2[-1]
                if last_run.get("stopped_at") is None:
                    log.warning(
                        "Skipping duplicate run for lab %s — previous run %s is still active",
                        lab.id(),
                        last_run.get("run_id", "?"),
                    )
                    return last_run.get("run_id")

            # Open a new run
            run_id = str(uuid.uuid4())
            run_record = LabRunRecord(
                run_id=run_id,
                started_at=now,
                stopped_at=None,
                duration_seconds=None,
                started_by="user",
                stop_reason=None,
                lablet_session_id=None,
                final_state=None,
            )
            lab.record_run(run_record)
            log.debug("Opened run %s for lab %s", run_id, lab.id())
            return run_id

        elif action in ("stop", "wipe", "delete"):
            # Close the most recent open run
            final_state = target_status.value if target_status else action
            return self._close_active_run(lab, now, action, final_state)

        return None

    def _close_active_run(self, lab: LabRecord, stopped_at: datetime, stop_reason: str, final_state: str) -> str | None:
        """Find and close the most recent open run (stopped_at is None).

        Because LabRunRecord is frozen, we replace the open entry in-place
        with a new completed LabRunRecord.

        Returns the closed run_id, or None if no open run was found.
        """
        for i in range(len(lab.state.run_history_v2) - 1, -1, -1):
            entry = lab.state.run_history_v2[i]
            if entry.get("stopped_at") is None:
                # Found the open run — close it
                open_run = LabRunRecord.from_dict(entry)
                # Normalize to UTC-aware (MongoDB may return naive datetimes)
                started_at = open_run.started_at if open_run.started_at.tzinfo else open_run.started_at.replace(tzinfo=timezone.utc)
                duration = int((stopped_at - started_at).total_seconds())
                closed_run = LabRunRecord(
                    run_id=open_run.run_id,
                    started_at=started_at,
                    stopped_at=stopped_at,
                    duration_seconds=duration,
                    started_by=open_run.started_by,
                    stop_reason=stop_reason,
                    lablet_session_id=open_run.lablet_session_id,
                    final_state=final_state,
                )
                lab.state.run_history_v2[i] = closed_run.to_dict()
                log.debug(
                    "Closed run %s for lab %s (duration=%ds, reason=%s)",
                    open_run.run_id,
                    lab.id(),
                    duration,
                    stop_reason,
                )
                return open_run.run_id

        log.debug(
            "No open run found for lab %s on action '%s' — no run to close",
            lab.id(),
            stop_reason,
        )
        return None
