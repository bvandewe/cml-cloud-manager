"""List WorkerTemplates query with handler."""

import logging
from dataclasses import dataclass

from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

from application.dtos.worker_template_dto import WorkerTemplateSummaryDto, map_worker_template_to_summary_dto
from domain.repositories.worker_template_repository import WorkerTemplateRepository

logger = logging.getLogger(__name__)


@dataclass
class ListWorkerTemplatesQuery(Query[OperationResult[list[WorkerTemplateSummaryDto]]]):
    """Query to list WorkerTemplates with optional filtering.

    Supports filtering by:
    - enabled_only: Only return enabled templates (default False)
    - include_deleted: Include soft-deleted templates (default False)
    """

    enabled_only: bool = False
    include_deleted: bool = False


class ListWorkerTemplatesQueryHandler(QueryHandler[ListWorkerTemplatesQuery, OperationResult[list[WorkerTemplateSummaryDto]]]):
    """Handle listing WorkerTemplates."""

    def __init__(self, worker_template_repository: WorkerTemplateRepository):
        super().__init__()
        self._repository = worker_template_repository

    async def handle_async(self, request: ListWorkerTemplatesQuery) -> OperationResult[list[WorkerTemplateSummaryDto]]:
        """Handle list WorkerTemplates query."""
        try:
            if request.enabled_only:
                templates = await self._repository.list_enabled_async()
            else:
                templates = await self._repository.list_all_async()

            # Filter out soft-deleted unless requested
            if not request.include_deleted:
                templates = [t for t in templates if not t.state.deleted]

            # Map to DTOs
            result = [map_worker_template_to_summary_dto(t) for t in templates]

            logger.info(
                "Listed %d WorkerTemplates (enabled_only=%s, include_deleted=%s)",
                len(result),
                request.enabled_only,
                request.include_deleted,
            )
            return self.ok(result)

        except Exception as e:
            logger.error("Error listing WorkerTemplates: %s", e, exc_info=True)
            return self.internal_server_error(str(e))
