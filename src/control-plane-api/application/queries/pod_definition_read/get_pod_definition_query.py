"""GetPodDefinitionQuery — fetch a single PodDefinition read-model entry.

ADR-044 / G-12 — read-only access to the CPA-side projection of SE state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from application.queries.query_handler_base import QueryHandlerBase
from domain.read_models.pod_definition_read_model import PodDefinitionReadModel
from domain.repositories.pod_definition_read_repository import PodDefinitionReadRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

logger = logging.getLogger(__name__)


@dataclass
class PodDefinitionReadDto:
    """DTO for the read-model projection of a SE PodDefinition."""

    id: str
    name: str
    version: str
    pod_type: str
    status: str
    content_hash: str
    source_uri: str | None = None
    error_message: str | None = None
    error_detail: str | None = None
    last_event_at: str | None = None
    projected_at: str | None = None
    raw_event: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_model(cls, model: PodDefinitionReadModel) -> PodDefinitionReadDto:
        return cls(
            id=model.id,
            name=model.name,
            version=model.version,
            pod_type=model.pod_type,
            status=model.status,
            content_hash=model.content_hash,
            source_uri=model.source_uri,
            error_message=model.error_message,
            error_detail=model.error_detail,
            last_event_at=_iso(model.last_event_at),
            projected_at=_iso(model.projected_at),
            raw_event=dict(model.raw_event or {}),
        )


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


@dataclass
class GetPodDefinitionQuery(Query[OperationResult[PodDefinitionReadDto]]):
    """Fetch a PodDefinition read model by its SE id."""

    pod_definition_id: str = ""


class GetPodDefinitionQueryHandler(
    QueryHandlerBase,
    QueryHandler[GetPodDefinitionQuery, OperationResult[PodDefinitionReadDto]],
):
    """Handler for :class:`GetPodDefinitionQuery`."""

    def __init__(self, pod_definition_read_repository: PodDefinitionReadRepository) -> None:
        super().__init__()
        self._repository = pod_definition_read_repository

    async def handle_async(self, request: GetPodDefinitionQuery) -> OperationResult[PodDefinitionReadDto]:
        if not request.pod_definition_id:
            return self.bad_request("pod_definition_id is required")

        model = await self._repository.get_async(request.pod_definition_id)
        if model is None:
            return self.not_found(PodDefinitionReadModel, request.pod_definition_id)

        return self.ok(PodDefinitionReadDto.from_model(model))
