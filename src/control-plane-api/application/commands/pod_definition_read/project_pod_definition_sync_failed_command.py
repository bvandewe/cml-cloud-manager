"""ProjectPodDefinitionSyncFailed — project SE ``pod_definition.sync_failed.v1``.

ADR-044 / G-12 / AD-CSI-007 + AD-CSI-015. Records the failure in the read
model so the UI can surface it. Honors the same last-write-wins staleness
guard as :class:`ProjectPodDefinitionReadyCommand`.
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
class ProjectPodDefinitionSyncFailedCommand(Command[OperationResult[dict[str, Any]]]):
    """Project a ``pod_definition.sync_failed.v1`` CloudEvent.

    The failure event payload does not include ``content_hash`` (SE may have
    failed before computing it), so the read model captures an empty string
    in that case. ``name`` and ``pod_type`` may also be empty when SE could
    not classify the package — the projector still records the failure so
    operators can investigate.
    """

    pod_definition_id: str = ""
    reason: str = ""
    error_detail: str | None = None
    name: str = ""
    pod_type: str = ""
    version: str = "v1"
    content_hash: str = ""
    source_uri: str | None = None
    event_time: datetime | None = None
    raw_event: dict[str, Any] = field(default_factory=dict)


class ProjectPodDefinitionSyncFailedCommandHandler(
    CommandHandlerBase,
    CommandHandler[ProjectPodDefinitionSyncFailedCommand, OperationResult[dict[str, Any]]],
):
    """Handler for :class:`ProjectPodDefinitionSyncFailedCommand`."""

    def __init__(self, pod_definition_read_repository: PodDefinitionReadRepository) -> None:
        self._repository = pod_definition_read_repository

    async def handle_async(self, request: ProjectPodDefinitionSyncFailedCommand) -> OperationResult[dict[str, Any]]:
        if not request.pod_definition_id:
            return self.bad_request("pod_definition_id is required")

        event_time = request.event_time or datetime.now(timezone.utc)

        existing = await self._repository.get_async(request.pod_definition_id)
        if existing is not None and existing.last_event_at is not None and event_time < existing.last_event_at:
            logger.info(
                "Dropping stale pod_definition.sync_failed event for %s " "(event_time=%s < last_event_at=%s)",
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

        # Carry forward immutable identity fields from the prior projection
        # when the failure payload omits them (SE can fail before classifying).
        name = request.name or (existing.name if existing else "")
        pod_type = request.pod_type or (existing.pod_type if existing else "")
        version = request.version or (existing.version if existing else "v1")
        content_hash = request.content_hash or (existing.content_hash if existing else "")
        source_uri = request.source_uri or (existing.source_uri if existing else None)

        model = PodDefinitionReadModel(
            id=request.pod_definition_id,
            name=name,
            version=version,
            pod_type=pod_type,
            status="FAILED",
            content_hash=content_hash,
            source_uri=source_uri,
            error_message=request.reason or "sync failed",
            error_detail=request.error_detail,
            last_event_at=event_time,
            projected_at=datetime.now(timezone.utc),
            raw_event=request.raw_event,
        )
        await self._repository.upsert_async(model)

        logger.info(
            "Projected pod_definition.sync_failed: id=%s reason=%s",
            request.pod_definition_id,
            request.reason,
        )
        return self.ok(
            {
                "pod_definition_id": request.pod_definition_id,
                "status": "FAILED",
            }
        )
