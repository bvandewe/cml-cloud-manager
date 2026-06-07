"""UI controller for serving HTML pages.

This controller serves the Scenario Engine admin interface.
"""

from pathlib import Path

from application.settings import Settings
from classy_fastapi.decorators import get
from classy_fastapi.routable import Routable
from fastapi import Request
from fastapi.responses import HTMLResponse
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator
from neuroglia.mvc import ControllerBase
from neuroglia.mvc.controller_base import generate_unique_id_function


class UIController(ControllerBase):
    """Controller for UI pages."""

    def __init__(
        self,
        service_provider: ServiceProviderBase,
        mapper: Mapper,
        mediator: Mediator,
    ):
        self.service_provider = service_provider
        self.mapper = mapper
        self.mediator = mediator
        self.name = "UI"

        self._settings = service_provider.get_required_service(Settings)
        self.static_dir = Path(__file__).parent.parent.parent / "static"

        Routable.__init__(
            self,
            prefix="",
            tags=["UI"],
            generate_unique_id_function=generate_unique_id_function,
        )

    @get("/", response_class=HTMLResponse)
    async def index(self, request: Request) -> HTMLResponse:
        """Serve the main application page."""
        index_path = self.static_dir / "index.html"

        if not index_path.exists():
            return HTMLResponse(
                content=self._get_placeholder_html(),
                status_code=200,
            )

        return HTMLResponse(content=index_path.read_text(encoding="utf-8"), status_code=200)

    def _get_placeholder_html(self) -> str:
        """Return a placeholder HTML page when UI hasn't been built."""
        return """<!DOCTYPE html>
<html>
<head><title>Scenario Engine</title></head>
<body>
<h1>Scenario Engine</h1>
<p>UI not built. Run <code>make build-ui</code> to build the frontend.</p>
</body>
</html>"""
