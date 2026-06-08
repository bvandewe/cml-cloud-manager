"""ProjectPodDefinitionReady — project SE ``pod_definition.ready.v1`` event.

ADR-044 / G-12 / AD-CSI-007 + AD-CSI-015.

Idempotent last-write-wins projection. Staleness guard: events with a
``last_event_at`` strictly older than the existing projection are dropped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from application.commands.command_handler_base import CommandHandlerBase
from domain.read_models.pod_definition_read_model import PodDefinitionReadModel
from domain.repositories.pod_definition_read_repository import PodDefinitionReadRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

logger = logging.getLogger(__name__)


@dataclass
class ProjectPodDefinitionReadyCommand(Command[OperationResult[dict[str, Any]]]):
    """Project a ``pod_definition.ready.v1`` CloudEvent.

    Attributes:
        pod_definition_id: SE aggregate id (becomes the read-model primary
            key).
        name: PodDefinition name.
        version: Content version.
        pod_type: Detected pod type string.
        content_hash: SHA-256 of the source package.
        source_uri: Optional BlobStorage URI of the source package.
        superseded_ids: Optional list of PodDefinition ids SE marked
            SUPERSEDED as a result of this sync. May be empty — SE's current
            ``emit_content_synced`` does not carry this field; the projector
            tolerates absence (Q-09).
        event_time: Wall-clock time of the originating event (CloudEvent
            ``time`` attribute or current time). Used as staleness guard.
        raw_event: Full event payload for audit / replay.
    """

    pod_definition_id: str = ""
    name: str = ""
    version: str = "v1"
    pod_type: str = ""
    content_hash: str = ""
    source_uri: str | None = None
    superseded_ids: list[str] = field(default_factory=list)
    event_time: datetime | None = None
    raw_event: dict[str, Any] = field(default_factory=dict)


class ProjectPodDefinitionReadyCommandHandler(
    CommandHandlerBase,
    CommandHandler[ProjectPodDefinitionReadyCommand, OperationResult[dict[str, Any]]],
):
    """Handler for :class:`ProjectPodDefinitionReadyCommand`."""

    def __init__(self, pod_definition_read_repository: PodDefinitionReadRepository) -> None:
        self._repository = pod_definition_read_repository

    async def handle_async(self, request: ProjectPodDefinitionReadyCommand) -> OperationResult[dict[str, Any]]:
        if not request.pod_definition_id:
            return self.bad_request("pod_definition_id is required")
        if not request.name:
            return self.bad_request("name is required")
        if not request.pod_type:
            return self.bad_request("pod_type is required")
        if not request.content_hash:
            return self.bad_request("content_hash is required")

        event_time = request.event_time or datetime.now(timezone.utc)

        existing = await self._repository.get_async(request.pod_definition_id)
        if existing is not None and existing.last_event_at is not None and event_time < existing.last_event_at:
            # AD-CSI-015 — drop stale out-of-order events.
            logger.info(
                "Dropping stale pod_definition.ready event for %s " "(event_time=%s < last_event_at=%s)",
                request.pod_definition_id,
                event_time.isoformat(),
                existing.last_event_at.isoformat(),
            )
            return self.ok(
                {
                    "pod_definition_id": request.pod_definition_id,
                    "skipped": True,
                    "reason": "stale_event",
                }
            )

        model = PodDefinitionReadModel(
            id=request.pod_definition_id,
            name=request.name,
            version=request.version,
            pod_type=request.pod_type,
            status="READY",
            content_hash=request.content_hash,
            source_uri=request.source_uri,
            error_message=None,
            error_detail=None,
            last_event_at=event_time,
            projected_at=datetime.now(timezone.utc),
            raw_event=request.raw_event,
        )
        await self._repository.upsert_async(model)

        superseded_count = 0
        if request.superseded_ids:
            superseded_count = await self._repository.mark_superseded_async(
                request.superseded_ids,
                superseded_at=event_time.isoformat(),
            )
            logger.info(
                "Projected pod_definition.ready: id=%s name=%s pod_type=%s; " "marked %d ids superseded",
                request.pod_definition_id,
                request.name,
                request.pod_type,
                superseded_count,
            )
        else:
            logger.info(
                "Projected pod_definition.ready: id=%s name=%s pod_type=%s " "(no superseded_ids in payload)",
                request.pod_definition_id,
                request.name,
                request.pod_type,
            )

        return self.ok(
            {
                "pod_definition_id": request.pod_definition_id,
                "status": "READY",
                "superseded_count": superseded_count,
            }
        )
