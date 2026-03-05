"""List LabletDefinitions query with handler."""

import logging
from dataclasses import dataclass

from application.dtos.lablet_definition_dto import LabletDefinitionSummaryDto, map_lablet_definition_to_summary_dto
from domain.enums import LabletDefinitionStatus
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

logger = logging.getLogger(__name__)


@dataclass
class ListLabletDefinitionsQuery(Query[OperationResult[list[LabletDefinitionSummaryDto]]]):
    """Query to list LabletDefinitions with filtering and pagination.

    Supports filtering by:
    - name: Filter by definition name (exact match)
    - status: Filter by status (active, deprecated, archived)
    - sync_status: Filter by sync_status (sync_requested, success, failed)
    - include_deprecated: Include deprecated definitions (default False)

    Supports pagination:
    - skip: Number of records to skip
    - limit: Maximum number of records to return
    """

    name: str | None = None
    status: str | None = None
    sync_status: str | None = None
    include_deprecated: bool = False
    skip: int = 0
    limit: int = 100


class ListLabletDefinitionsQueryHandler(QueryHandler[ListLabletDefinitionsQuery, OperationResult[list[LabletDefinitionSummaryDto]]]):
    """Handle listing LabletDefinitions with filtering and pagination."""

    def __init__(self, lablet_definition_repository: LabletDefinitionRepository):
        super().__init__()
        self._repository = lablet_definition_repository

    async def handle_async(self, request: ListLabletDefinitionsQuery) -> OperationResult[list[LabletDefinitionSummaryDto]]:
        """Handle list LabletDefinitions query.

        Args:
            request: Query with optional filters and pagination

        Returns:
            OperationResult with list of LabletDefinitionSummaryDto
        """
        try:
            definitions = []

            # Determine which repository method to use based on filters
            if request.sync_status:
                # Filter by sync_status (e.g., 'sync_requested' for lablet-controller discovery)
                valid_sync_statuses = ("sync_requested", "success", "failed")
                if request.sync_status not in valid_sync_statuses:
                    return self.bad_request(f"Invalid sync_status '{request.sync_status}'. Must be one of: {', '.join(valid_sync_statuses)}")
                definitions = await self._repository.list_by_sync_status_async(request.sync_status)
            elif request.name:
                # List all versions of a specific definition name
                definitions = await self._repository.list_by_name_async(request.name)
            elif request.status:
                # List by specific status
                try:
                    status_enum = LabletDefinitionStatus(request.status)
                    definitions = await self._repository.list_by_status_async(status_enum)
                except ValueError:
                    valid_statuses = ", ".join(s.value for s in LabletDefinitionStatus)
                    return self.bad_request(f"Invalid status '{request.status}'. Must be one of: {valid_statuses}")
            elif request.include_deprecated:
                # Include all statuses
                active = await self._repository.list_by_status_async(LabletDefinitionStatus.ACTIVE)
                pending = await self._repository.list_by_status_async(LabletDefinitionStatus.PENDING_SYNC)
                deprecated = await self._repository.list_by_status_async(LabletDefinitionStatus.DEPRECATED)
                archived = await self._repository.list_by_status_async(LabletDefinitionStatus.ARCHIVED)
                definitions = active + pending + deprecated + archived
            else:
                # Default: active + pending_sync definitions
                active = await self._repository.list_active_async()
                pending = await self._repository.list_by_status_async(LabletDefinitionStatus.PENDING_SYNC)
                definitions = active + pending

            # Apply pagination
            total_count = len(definitions)
            paginated = definitions[request.skip : request.skip + request.limit]

            # Map to DTOs
            result = [map_lablet_definition_to_summary_dto(d) for d in paginated]

            logger.info(f"Listed {len(result)} of {total_count} LabletDefinitions (skip={request.skip}, limit={request.limit}, filters: name={request.name}, status={request.status})")
            return self.ok(result)

        except Exception as e:
            logger.error(f"Error listing LabletDefinitions: {e}", exc_info=True)
            return self.internal_server_error(str(e))
