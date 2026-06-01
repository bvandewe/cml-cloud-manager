"""Get LabletDefinition query with handler."""

import logging
from dataclasses import dataclass

from application.dtos.lablet_definition_dto import LabletDefinitionDto, map_lablet_definition_to_dto
from application.queries.query_handler_base import QueryHandlerBase
from domain.entities.lablet_definition import LabletDefinition
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

logger = logging.getLogger(__name__)


@dataclass
class GetLabletDefinitionQuery(Query[OperationResult[LabletDefinitionDto]]):
    """Query to retrieve a single LabletDefinition.

    Supports lookup by ID or by name+version combination.
    """

    id: str | None = None
    name: str | None = None
    version: str | None = None


class GetLabletDefinitionQueryHandler(QueryHandlerBase, QueryHandler[GetLabletDefinitionQuery, OperationResult[LabletDefinitionDto]]):
    """Handle retrieving a single LabletDefinition."""

    def __init__(self, lablet_definition_repository: LabletDefinitionRepository):
        super().__init__()
        self._repository = lablet_definition_repository

    async def handle_async(self, request: GetLabletDefinitionQuery) -> OperationResult[LabletDefinitionDto]:
        """Handle get LabletDefinition query.

        Args:
            request: Query with id or name+version

        Returns:
            OperationResult with LabletDefinitionDto or error
        """
        # Validate: must provide either id or (name + version)
        if not request.id and not (request.name and request.version):
            return self.bad_request("Must provide either 'id' or both 'name' and 'version'")

        try:
            definition = None

            if request.id:
                # Lookup by ID
                definition = await self._repository.get_by_id_async(request.id)
                if not definition:
                    return self.not_found(LabletDefinition, request.id)
            else:
                # Lookup by name + version
                definition = await self._repository.get_by_name_and_version_async(
                    name=request.name,  # type: ignore
                    version=request.version,  # type: ignore
                )
                if not definition:
                    return self.not_found(LabletDefinition, f"{request.name}:{request.version}")

            # Map to DTO
            dto = map_lablet_definition_to_dto(definition)

            logger.info(f"Retrieved LabletDefinition: {definition.id()} ({definition.state.name} v{definition.state.version})")
            return self.ok(dto)

        except Exception as e:
            logger.error(f"Error retrieving LabletDefinition: {e}", exc_info=True)
            return self.internal_server_error(str(e))
