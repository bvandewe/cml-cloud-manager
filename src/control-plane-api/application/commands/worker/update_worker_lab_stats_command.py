"""Command for updating worker lab stats from WebSocket lab_stats events (ADR-041)."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

from application.services.sse_event_relay import SSEEventRelay
from domain.repositories.lab_record_repository import LabRecordRepository

log = logging.getLogger(__name__)


@dataclass
class UpdateWorkerLabStatsCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to update per-lab metrics from WebSocket lab_stats events.

    Reported by worker-controller when the CmlWebSocketMonitor receives
    lab_stats messages from a CML worker's /ws/ui endpoint (ADR-041).

    Attributes:
        worker_id: Worker identifier
        lab_id: CML lab ID
        nodes: Node-level resource metrics (node_id -> {cpu_usage, ram_usage, ...})
        links: Link-level throughput metrics (link_id -> {readbytes, writebytes, ...})
        collected_at: Timestamp when stats were collected (ISO 8601)
    """

    worker_id: str
    lab_id: str
    nodes: dict[str, Any] = field(default_factory=dict)
    links: dict[str, Any] = field(default_factory=dict)
    collected_at: str | None = None


class UpdateWorkerLabStatsCommandHandler(CommandHandler[UpdateWorkerLabStatsCommand, OperationResult[dict[str, Any]]]):
    """Handler for UpdateWorkerLabStatsCommand.

    Finds the LabRecord by cml_lab_id, updates it with node-level metrics,
    and broadcasts an SSE event for real-time frontend updates.
    """

    def __init__(
        self,
        lab_record_repository: LabRecordRepository,
        sse_relay: SSEEventRelay,
    ):
        self._lab_repository = lab_record_repository
        self._sse_relay = sse_relay

    async def handle_async(self, command: UpdateWorkerLabStatsCommand) -> OperationResult[dict[str, Any]]:
        """Execute the command."""
        # Find LabRecord by worker_id + cml_lab_id
        lab_record = await self._lab_repository.get_by_lab_id_async(command.worker_id, command.lab_id)

        if not lab_record:
            # Lab record might not exist yet (e.g., lab just created on CML)
            # This is not an error condition - just skip silently
            log.debug(f"No LabRecord found for worker={command.worker_id}, lab_id={command.lab_id} - skipping stats update")
            return self.ok(
                {
                    "worker_id": command.worker_id,
                    "lab_id": command.lab_id,
                    "updated": False,
                    "reason": "lab_record_not_found",
                }
            )

        # Determine collection timestamp
        collected_at = command.collected_at or datetime.now(timezone.utc).isoformat()

        # Update lab record with latest node/link metrics
        lab_record.state.node_stats = command.nodes
        lab_record.state.link_stats = command.links
        lab_record.state.stats_collected_at = collected_at
        lab_record.state.updated_at = datetime.now(timezone.utc)

        # Persist changes
        await self._lab_repository.update_async(lab_record)

        # Broadcast SSE event
        event_data: dict[str, Any] = {
            "worker_id": command.worker_id,
            "lab_id": command.lab_id,
            "lab_record_id": lab_record.id(),
            "nodes": command.nodes,
            "links": command.links,
            "collected_at": collected_at,
        }
        await self._sse_relay.broadcast_event("worker.lab.stats_updated", event_data, source="worker-controller")

        log.debug(f"Updated lab stats for worker={command.worker_id}, lab_id={command.lab_id}: nodes={len(command.nodes)}, links={len(command.links)}")

        return self.ok(
            {
                "worker_id": command.worker_id,
                "lab_id": command.lab_id,
                "lab_record_id": lab_record.id(),
                "updated": True,
                "collected_at": collected_at,
            }
        )
