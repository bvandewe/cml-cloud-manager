"""Search LabletDefinitions query with handler.

Provides text-based search across definition names and descriptions
for use in autocomplete/typeahead UI components.
"""

import logging
from dataclasses import dataclass

from application.dtos.lablet_definition_dto import LabletDefinitionSummaryDto, map_lablet_definition_to_summary_dto
from application.queries.query_handler_base import QueryHandlerBase
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

logger = logging.getLogger(__name__)


@dataclass
class SearchLabletDefinitionsQuery(Query[OperationResult[list[LabletDefinitionSummaryDto]]]):
    """Query to search LabletDefinitions by name or description text.

    Used for autocomplete/typeahead functionality in UI.
    Searches are case-insensitive and match anywhere in the name or description.

    Args:
        q: Search query string (minimum 2 characters)
        limit: Maximum number of results (default 10, max 50)
        include_deprecated: Include deprecated definitions (default False)
    """

    q: str
    limit: int = 10
    include_deprecated: bool = False


class SearchLabletDefinitionsQueryHandler(QueryHandlerBase, QueryHandler[SearchLabletDefinitionsQuery, OperationResult[list[LabletDefinitionSummaryDto]]]):
    """Handle searching LabletDefinitions by name/description text."""

    def __init__(self, lablet_definition_repository: LabletDefinitionRepository):
        super().__init__()
        self._repository = lablet_definition_repository

    async def handle_async(self, request: SearchLabletDefinitionsQuery) -> OperationResult[list[LabletDefinitionSummaryDto]]:
        """Handle search LabletDefinitions query.

        Args:
            request: Query with search term and options

        Returns:
            OperationResult with list of matching LabletDefinitionSummaryDto
        """
        try:
            # Validate query length
            query = request.q.strip()
            if len(query) < 2:
                return self.ok([])  # Return empty for short queries

            # Limit must be between 1 and 50
            limit = max(1, min(request.limit, 50))

            # Search via repository
            definitions = await self._repository.search_async(
                query=query,
                include_deprecated=request.include_deprecated,
                limit=limit,
            )

            # Map to DTOs
            result = [map_lablet_definition_to_summary_dto(d) for d in definitions]

            logger.debug(f"Search '{query}' returned {len(result)} results")
            return self.ok(result)

        except Exception as e:
            logger.error(f"Error searching LabletDefinitions: {e}", exc_info=True)
            return self.internal_server_error(str(e))
