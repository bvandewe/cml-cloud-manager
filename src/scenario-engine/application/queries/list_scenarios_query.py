"""ListScenariosQuery — List all registered scenarios.

Self-contained CQRS query: request class + handler in same file.
"""

import logging
from dataclasses import dataclass
from typing import Any

from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

from application.services.scenario_registry import get_all_scenarios

logger = logging.getLogger(__name__)


@dataclass
class ListScenariosQuery(Query[OperationResult[list[dict[str, Any]]]]):
    """Query to list all available scenarios.

    Attributes:
        name_filter: Optional filter by scenario name prefix.
    """

    name_filter: str | None = None


class ListScenariosQueryHandler(QueryHandler[ListScenariosQuery, OperationResult[list[dict[str, Any]]]]):
    """Handler for ListScenariosQuery.

    Returns all registered scenarios from the in-memory registry.
    """

    async def handle_async(self, request: ListScenariosQuery) -> OperationResult[list[dict[str, Any]]]:
        """Handle list scenarios query."""
        all_scenarios = get_all_scenarios()

        results = []
        for key, meta in all_scenarios.items():
            if request.name_filter and not meta["name"].startswith(request.name_filter):
                continue
            results.append(
                {
                    "name": meta["name"],
                    "version": meta["version"],
                    "description": meta.get("description", ""),
                }
            )

        return self.ok(results)
