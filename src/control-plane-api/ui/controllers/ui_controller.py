"""UI controller for serving HTML pages."""

from pathlib import Path

from classy_fastapi.decorators import get
from classy_fastapi.routable import Routable
from fastapi import Request
from fastapi.responses import HTMLResponse
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator
from neuroglia.mvc import ControllerBase
from neuroglia.mvc.controller_base import generate_unique_id_function

from application.settings import app_settings


class UIController(ControllerBase):
    """Controller for UI pages."""

    def __init__(
        self,
        service_provider: ServiceProviderBase,
        mapper: Mapper,
        mediator: Mediator,
    ):
        # Store DI services first
        self.service_provider = service_provider
        self.mapper = mapper
        self.mediator = mediator
        self.name = "UI"

        # Get absolute path to static directory where Parcel builds the HTML
        # From ui/controllers/ui_controller.py -> ../../../static (which is /app/static in Docker)
        self.static_dir = Path(__file__).parent.parent.parent / "static"

        # Call Routable.__init__ directly with empty prefix for root routes
        Routable.__init__(
            self,
            prefix="",  # Empty prefix for root routes
            tags=["UI"],
            generate_unique_id_function=generate_unique_id_function,
        )

    @get("/", response_class=HTMLResponse)
    async def index(self, request: Request) -> HTMLResponse:
        """Serve the main application page (built by Parcel)."""
        index_path = self.static_dir / "index.html"

        if not index_path.exists():
            return HTMLResponse("<h1>UI not built. Run 'make build-ui' first.</h1>", status_code=500)

        # Read the file content
        content = index_path.read_text(encoding="utf-8")

        # Inject runtime configuration
        config_script = f"""
        <script>
            window.APP_CONFIG = {{
                environment: "{app_settings.environment}",
                version: "{app_settings.app_version}",
                title: "{app_settings.app_name}",
                grafanaUrl: "{app_settings.grafana_url}",
                minioConsoleUrl: "{app_settings.minio_console_url}",
                prometheusEnabled: {str(app_settings.prometheus_enabled).lower()},
            }};
        </script>
        """

        # Insert before closing head tag
        content = content.replace("</head>", f"{config_script}</head>")

        return HTMLResponse(content=content, media_type="text/html")
