"""UI controller for serving HTML pages.

This controller serves the Resource Scheduler admin interface.
The UI is a simple Bootstrap 5 dashboard showing scheduler status,
leader election info, and placement statistics.
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
        # Store DI services first
        self.service_provider = service_provider
        self.mapper = mapper
        self.mediator = mediator
        self.name = "UI"

        # Get settings for config injection
        self._settings = service_provider.get_required_service(Settings)

        # Get absolute path to static directory where UI assets are served from
        # From ui/controllers/ui_controller.py -> ../../static
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
        """Serve the main application page."""
        index_path = self.static_dir / "index.html"

        if not index_path.exists():
            # Return a basic placeholder page if UI hasn't been built
            return HTMLResponse(
                content=self._get_placeholder_html(),
                status_code=200,
                media_type="text/html",
            )

        # Read the file content
        content = index_path.read_text(encoding="utf-8")

        # Inject runtime configuration
        config_script = f"""
        <script>
            window.APP_CONFIG = {{
                serviceName: "{self._settings.app_name}",
                version: "{self._settings.app_version}",
                apiDocsUrl: "/api/docs",
            }};
        </script>
        """

        # Insert before closing head tag
        content = content.replace("</head>", f"{config_script}</head>")

        return HTMLResponse(content=content, media_type="text/html")

    def _get_placeholder_html(self) -> str:
        """Return placeholder HTML when static UI hasn't been built."""
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{self._settings.app_name}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; }}
        .card {{ border: none; box-shadow: 0 10px 40px rgba(0,0,0,0.2); }}
    </style>
</head>
<body class="d-flex align-items-center justify-content-center">
    <div class="container">
        <div class="row justify-content-center">
            <div class="col-md-8 col-lg-6">
                <div class="card">
                    <div class="card-body text-center p-5">
                        <h1 class="mb-3">📅 {self._settings.app_name}</h1>
                        <p class="text-muted mb-4">Version {self._settings.app_version} <span class="badge bg-secondary">{self._settings.image_tag}</span></p>
                        <p class="lead">Resource Scheduler manages LabletSession placement decisions using bin-packing algorithms.</p>
                        <hr class="my-4">
                        <div class="d-grid gap-2">
                            <a href="/api/docs" class="btn btn-primary btn-lg">
                                📚 API Documentation
                            </a>
                            <a href="/api/health" class="btn btn-outline-secondary">
                                ❤️ Health Check
                            </a>
                            <a href="/api/ready" class="btn btn-outline-secondary">
                                ✅ Readiness Check
                            </a>
                            <a href="/api/info" class="btn btn-outline-secondary">
                                ℹ️ Service Info
                            </a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>"""
