"""Command for updating worker WebSocket connection status (ADR-041)."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

from application.services.sse_event_relay import SSEEventRelay
from domain.repositories.cml_worker_repository import CMLWorkerRepository

log = logging.getLogger(__name__)


@dataclass
class UpdateWorkerWsStatusCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to update worker WebSocket connection status.

    Reported by worker-controller when the CmlWebSocketMonitor connects
    or disconnects from a CML worker's /ws/ui endpoint (ADR-041).

    Attributes:
        worker_id: Worker identifier
        connected: Whether WebSocket is currently connected
        reason: Disconnect reason (if disconnected)
        connected_at: Connection timestamp (ISO 8601)
        disconnected_at: Disconnection timestamp (ISO 8601)
    """

    worker_id: str
    connected: bool
    reason: str | None = None
    connected_at: str | None = None
    disconnected_at: str | None = None


class UpdateWorkerWsStatusCommandHandler(CommandHandler[UpdateWorkerWsStatusCommand, OperationResult[dict[str, Any]]]):
    """Handler for UpdateWorkerWsStatusCommand.

    Updates worker aggregate with WebSocket connection state and
    broadcasts SSE event for real-time frontend updates.
    """

    def __init__(
        self,
        worker_repository: CMLWorkerRepository,
        sse_relay: SSEEventRelay,
    ):
        self._repository = worker_repository
        self._sse_relay = sse_relay

    async def handle_async(self, command: UpdateWorkerWsStatusCommand) -> OperationResult[dict[str, Any]]:
        """Execute the command."""
        worker = await self._repository.get_by_id_async(command.worker_id)

        if not worker:
            log.warning(f"Worker {command.worker_id} not found for WS status update")
            return self.not_found(
                f"Worker {command.worker_id}",
                f"Worker {command.worker_id} not found",
            )

        # Update ws_connected on the worker state directly
        worker.state.ws_connected = command.connected
        worker.state.updated_at = datetime.now(timezone.utc)

        # Persist changes
        await self._repository.update_async(worker)

        # Broadcast SSE event
        event_type = "worker.ws.connected" if command.connected else "worker.ws.disconnected"
        event_data: dict[str, Any] = {
            "worker_id": command.worker_id,
            "connected": command.connected,
        }
        if command.reason:
            event_data["reason"] = command.reason
        if command.connected_at:
            event_data["connected_at"] = command.connected_at
        if command.disconnected_at:
            event_data["disconnected_at"] = command.disconnected_at

        await self._sse_relay.broadcast_event(event_type, event_data, source="worker-controller")

        log.info(f"Updated WS status for worker {command.worker_id}: connected={command.connected}")

        return self.ok(
            {
                "worker_id": command.worker_id,
                "ws_connected": command.connected,
                "event_type": event_type,
            }
        )
