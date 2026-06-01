"""Get WorkerTemplate query with handler."""

import logging
from dataclasses import dataclass

from application.dtos.worker_template_dto import WorkerTemplateDto, map_worker_template_to_dto
from application.queries.query_handler_base import QueryHandlerBase
from domain.entities.worker_template import WorkerTemplate
from domain.repositories.worker_template_repository import WorkerTemplateRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

logger = logging.getLogger(__name__)


@dataclass
class GetWorkerTemplateQuery(Query[OperationResult[WorkerTemplateDto]]):
    """Query to retrieve a single WorkerTemplate.

    Supports lookup by ID or by name.
    """

    id: str | None = None
    name: str | None = None


class GetWorkerTemplateQueryHandler(QueryHandlerBase, QueryHandler[GetWorkerTemplateQuery, OperationResult[WorkerTemplateDto]]):
    """Handle retrieving a single WorkerTemplate."""

    def __init__(self, worker_template_repository: WorkerTemplateRepository):
        super().__init__()
        self._repository = worker_template_repository

    async def handle_async(self, request: GetWorkerTemplateQuery) -> OperationResult[WorkerTemplateDto]:
        """Handle get WorkerTemplate query."""
        if not request.id and not request.name:
            return self.bad_request("Must provide either 'id' or 'name'")

        try:
            template = None

            if request.id:
                template = await self._repository.get_by_id_async(request.id)
                if not template:
                    return self.not_found(WorkerTemplate, request.id)
            else:
                template = await self._repository.get_by_name_async(request.name)  # type: ignore[arg-type]
                if not template:
                    return self.not_found(WorkerTemplate, request.name)  # type: ignore[arg-type]

            dto = map_worker_template_to_dto(template)
            logger.info("Retrieved WorkerTemplate: %s (name=%s)", template.id(), template.state.name)
            return self.ok(dto)

        except Exception as e:
            logger.error("Error retrieving WorkerTemplate: %s", e, exc_info=True)
            return self.internal_server_error(str(e))
