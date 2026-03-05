"""Resource Scheduler Service - Main Entry Point.

This service handles LabletSession placement decisions using leader election
for high availability. Built on the Neuroglia framework for consistency with
other LCM services.

Architecture:
- WebApplicationBuilder for DI and lifecycle management
- LeaderElectedHostedService for reconciliation with leader election
- Standard endpoints (/health, /ready, /metrics, /info)
- Admin endpoints for operational control

Uses build_app_with_lifespan for proper lifecycle management - HostedServices
are automatically started/stopped by the Neuroglia framework.
"""

import logging
from pathlib import Path
from typing import Any

import uvicorn
from api.controllers import AdminController, SchedulingController
from api.services import DualAuthService
from application.hosted_services import CleanupHostedService, SchedulerHostedService
from application.services.placement_engine import PlacementEngine
from application.settings import Settings, app_settings
from fastapi import FastAPI
from lcm_core.infrastructure import configure_logging
from lcm_core.infrastructure.mixins import ServiceInfo, StandardEndpointsMixin
from lcm_core.integration.clients import ControlPlaneApiClient, EtcdClient
from neuroglia.hosting.abstractions import HostedService
from neuroglia.hosting.web import SubAppConfig, WebApplicationBuilder
from neuroglia.serialization.json import JsonSerializer

# Configure logging
configure_logging(log_level=app_settings.log_level)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create the Resource Scheduler FastAPI application.

    Uses Neuroglia WebApplicationBuilder with build_app_with_lifespan for
    proper HostedService lifecycle management (no deprecated on_event).

    Returns:
        Configured FastAPI application.
    """
    # Load settings
    settings = Settings()

    # Load API description from markdown file
    description_path = Path(__file__).parent / "api" / "description.md"
    api_description = "Resource Scheduler for Lablet Cloud Manager"
    if description_path.exists():
        api_description = description_path.read_text(encoding="utf-8")
        logger.debug(f"Loaded API description from {description_path}")
    else:
        logger.warning(f"API description file not found: {description_path}")

    # Build Neuroglia application
    builder = WebApplicationBuilder()

    # Configure settings as singleton
    builder.services.add_singleton(Settings, implementation_factory=lambda _: settings)

    # Configure JsonSerializer (required by Neuroglia exception middleware)
    JsonSerializer.configure(builder, [])

    # Configure integration clients (from lcm-core)
    ControlPlaneApiClient.configure(
        builder.services,
        base_url=settings.control_plane_api_url,
        api_key=settings.control_plane_api_key,
    )

    EtcdClient.configure(
        builder.services,
        endpoints=settings.etcd_endpoints,
        username=settings.etcd_username,
        password=settings.etcd_password,
    )

    # Configure application services
    builder.services.add_singleton(PlacementEngine)

    # Configure DualAuth service
    DualAuthService.configure(builder)

    # Configure scheduler hosted service (registers as both concrete type and HostedService)
    SchedulerHostedService.configure(builder.services, settings)

    # Register SchedulerHostedService as HostedService for automatic lifecycle management
    # Using a typed factory function instead of lambda to ensure proper type resolution
    def scheduler_factory(sp) -> HostedService:
        return sp.get_required_service(SchedulerHostedService)

    builder.services.add_singleton(
        HostedService,
        implementation_factory=scheduler_factory,
    )

    # Configure cleanup hosted service for terminated worker cleanup
    CleanupHostedService.configure(builder.services, settings)

    # Register CleanupHostedService as HostedService for automatic lifecycle management
    def cleanup_factory(sp) -> HostedService:
        return sp.get_required_service(CleanupHostedService)

    builder.services.add_singleton(
        HostedService,
        implementation_factory=cleanup_factory,
    )

    # Service info for standard endpoints
    service_info = ServiceInfo(
        name=settings.app_name,
        version=settings.app_version,
        description="Resource Scheduler for Lablet Cloud Manager - handles LabletSession placement",
        image_tag=settings.image_tag,
    )

    # Custom setup for API sub-app
    def api_setup(app: FastAPI, settings: Any) -> None:
        """Configure API sub-app with admin routes and standard endpoints."""
        from api.services.openapi_config import configure_openapi_security

        # app.state.services is set by neuroglia before custom_setup is called
        scheduler = app.state.services.get_required_service(SchedulerHostedService)

        # Create and include admin controller
        admin_controller = AdminController(scheduler)
        app.include_router(admin_controller.router)

        # Create and include scheduling controller (AD-SCHED-001: dry-run preview)
        placement_engine = app.state.services.get_required_service(PlacementEngine)
        api_client = app.state.services.get_required_service(ControlPlaneApiClient)
        etcd_client = app.state.services.get_required_service(EtcdClient)
        scheduling_controller = SchedulingController(placement_engine, api_client, etcd_client)
        app.include_router(scheduling_controller.router)

        # Configure OAuth2 security for Swagger UI
        configure_openapi_security(app)

        # Configure standard endpoints mixin
        class SchedulerEndpoints(StandardEndpointsMixin):  # type: ignore[misc]
            def __init__(self) -> None:
                super().__init__()  # Initialize _readiness_checks
                self._service_info = service_info
                self._scheduler = scheduler

            async def check_readiness(self) -> tuple[bool, str]:
                if self._scheduler:
                    result: tuple[bool, str] = await self._scheduler.check_readiness()
                    return result
                return True, "OK"

            def get_extra_info(self) -> dict[str, Any]:
                if self._scheduler:
                    info: dict[str, Any] = self._scheduler.get_extra_info()
                    return info
                return {}

        endpoints = SchedulerEndpoints()
        endpoints.configure_standard_endpoints(app, tags=["Operations"])

    # Get static directory path for UI SubApp
    static_dir = Path(__file__).parent / "static"

    # Add API SubApp with controllers (mounted at /api)
    builder.add_sub_app(
        SubAppConfig(
            path="/api",  # API mounted at /api, docs at /api/docs
            name="api",
            title=settings.app_name,
            description=api_description,
            version=settings.app_version,
            controllers=["api.controllers"],
            custom_setup=api_setup,
            docs_url="/docs",  # Results in /api/docs
        )
    )

    # Add UI SubApp at root path
    builder.add_sub_app(
        SubAppConfig(
            path="/",  # UI at root
            name="ui",
            title=f"{settings.app_name} UI",
            description="Resource Scheduler Admin Interface",
            version=settings.app_version,
            controllers=["ui.controllers"],
            static_files={"/static": str(static_dir)},
            docs_url=None,  # No OpenAPI docs for UI SubApp
        )
    )

    # Build the application with lifespan (handles HostedService start/stop automatically)
    app = builder.build_app_with_lifespan(
        title=settings.app_name,
        description=api_description,
        version=settings.app_version,
        debug=settings.debug,
    )

    # Configure authentication middleware
    DualAuthService.configure_middleware(app)

    logger.info(f"✅ Resource Scheduler application created (version {settings.app_version})")

    return app


def main() -> None:
    """Main entry point for running directly."""
    settings = Settings()
    uvicorn.run(
        "main:create_app",
        factory=True,
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
        reload_excludes=["logs", "static", "data", "*.log"] if settings.debug else None,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
