"""Command for reporting push-based activity events from WebSocket (ADR-041)."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

from domain.repositories.cml_worker_repository import CMLWorkerRepository

log = logging.getLogger(__name__)


@dataclass
class ReportActivityEventsCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to report push-based activity events from WebSocket stream.

    Reported by worker-controller when the CmlWebSocketMonitor classifies
    events as activity indicators (ADR-041).

    Unlike DetectWorkerIdleCommand (which polls on a schedule), this command
    receives continuous push-based activity events from the WebSocket stream.

    Attributes:
        worker_id: Worker identifier
        activity_events: List of classified activity events
        source: Event source identifier ("websocket" or "telemetry_poll")
    """

    worker_id: str
    activity_events: list[dict[str, Any]] = field(default_factory=list)
    source: str = "websocket"


class ReportActivityEventsCommandHandler(CommandHandler[ReportActivityEventsCommand, OperationResult[dict[str, Any]]]):
    """Handler for ReportActivityEventsCommand.

    Updates worker aggregate with the latest activity events from the
    WebSocket stream. Same pipeline as idle detection Step 2, but decoupled
    from idle evaluation (events arrive continuously, idle evaluation runs
    on its own schedule).
    """

    def __init__(self, worker_repository: CMLWorkerRepository):
        self._repository = worker_repository

    async def handle_async(self, command: ReportActivityEventsCommand) -> OperationResult[dict[str, Any]]:
        """Execute the command."""
        worker = await self._repository.get_by_id_async(command.worker_id)

        if not worker:
            log.warning(f"Worker {command.worker_id} not found for activity events report")
            return self.not_found(
                f"Worker {command.worker_id}",
                f"Worker {command.worker_id} not found",
            )

        if not command.activity_events:
            return self.ok(
                {
                    "worker_id": command.worker_id,
                    "events_processed": 0,
                    "source": command.source,
                }
            )

        # Determine the latest activity timestamp from events
        now = datetime.now(timezone.utc)
        last_activity_at = now  # If we have events, there IS activity

        # Look for explicit timestamps in events
        for event in command.activity_events:
            ts = event.get("timestamp") or event.get("collected_at")
            if ts:
                try:
                    parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    if parsed > last_activity_at:
                        last_activity_at = parsed
                except (ValueError, TypeError):
                    pass

        # Update worker activity (same method as idle detection Step 2)
        worker.update_activity(
            recent_events=command.activity_events,
            last_activity_at=last_activity_at,
            last_check_at=now,
            next_check_at=None,  # Don't override scheduled idle checks
            target_pause_at=None,  # Don't override idle detection's pause target
        )

        # Persist changes
        await self._repository.update_async(worker)

        log.info(f"Recorded {len(command.activity_events)} activity events for worker {command.worker_id} (source={command.source})")

        return self.ok(
            {
                "worker_id": command.worker_id,
                "events_processed": len(command.activity_events),
                "last_activity_at": last_activity_at.isoformat(),
                "source": command.source,
            }
        )
