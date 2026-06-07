"""Scenarios Controller — list and inspect available scenarios.

Endpoints:
- GET /api/v1/scenarios — List all registered scenarios
- GET /api/v1/scenarios/{name}/{ver} — Get scenario details and schema
"""

import logging
from typing import Any

from application.queries.list_scenarios_query import ListScenariosQuery
from classy_fastapi.decorators import get
from classy_fastapi.routable import Routable
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator
from neuroglia.mvc import ControllerBase
from neuroglia.mvc.controller_base import generate_unique_id_function

logger = logging.getLogger(__name__)


class ScenariosController(ControllerBase):
    """Controller for scenario registry discovery.

    Routes mounted at /v1/scenarios under the API sub-app (/api/v1/scenarios/*).
    Provides introspection into the available scenario registry.
    """

    def __init__(self, service_provider: ServiceProviderBase, mapper: Mapper, mediator: Mediator):
        self.service_provider = service_provider
        self.mapper = mapper
        self.mediator = mediator
        self.name = "Scenarios"

        # Initialize ControllerBase (sets up json_serializer)
        ControllerBase.__init__(self, service_provider, mapper, mediator)

        # Override prefix with versioned path
        Routable.__init__(
            self,
            prefix="/v1/scenarios",
            tags=["Scenarios"],
            generate_unique_id_function=generate_unique_id_function,
        )

    @get("/", summary="List Scenarios")
    async def list_scenarios(self, name_filter: str | None = None) -> Any:
        """List all registered scenarios.

        Returns the scenario registry with name, version, and description
        for each available scenario.
        """
        query = ListScenariosQuery(name_filter=name_filter)
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @get("/{name}/{ver}", summary="Get Scenario")
    async def get_scenario(self, name: str, ver: str) -> Any:
        """Get scenario details and schema.

        Returns the full scenario definition including input/output JSON schemas
        for validation and documentation.
        """
        # TODO: Add GetScenarioQuery when detailed schema introspection is needed
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=501, content={"detail": "Not implemented — query pending"})
