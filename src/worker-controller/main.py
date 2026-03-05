"""Worker Controller Service - Main Entry Point.

Domain: Infrastructure Layer (Compute Resources)
SPI: Cloud Provider (AWS EC2, CloudWatch) + CML System API (system_stats, license)

This service manages CMLWorker lifecycle and metrics:
- Worker lifecycle management (provision, start, stop, terminate EC2 instances)
- Capacity tracking and metrics collection (CloudWatch + CML system_stats)
- Auto-scaling execution (scale-up/scale-down based on Resource Scheduler signals)
- License management via CML System API
- Health monitoring and worker state synchronization

Architecture:
- WebApplicationBuilder for DI and lifecycle management
- LeaderElectedHostedService for reconciliation with leader election
- Standard endpoints (/health, /ready, /metrics, /info)
- Admin endpoints for operational control

Reconciliation Pattern:
    SPEC (Worker from Control Plane API) ←→ OBSERVE (EC2 + CML state) → ACT (reconcile)

All mutations go through Control Plane API (ADR-001).

Uses build_app_with_lifespan for proper lifecycle management - HostedServices
are automatically started/stopped by the Neuroglia framework.
"""

import logging
from pathlib import Path
from typing import Any

import uvicorn
from api.controllers import AdminController
from api.services import DualAuthService
from application.hosted_services import WorkerReconciler
from application.settings import Settings, app_settings
from fastapi import FastAPI
from integration.services.aws_cloudwatch_spi import AwsCloudWatchSpiClient
from integration.services.aws_ec2_spi import AwsEc2SpiClient
from integration.services.cml_system_spi import CmlSystemSpiClient
from lcm_core.infrastructure import configure_logging
from lcm_core.infrastructure.mixins import ServiceInfo, StandardEndpointsMixin
from lcm_core.integration.clients import ControlPlaneApiClient, EtcdClient
from neuroglia.hosting.web import SubAppConfig, WebApplicationBuilder
from neuroglia.serialization.json import JsonSerializer

# Configure logging
configure_logging(log_level=app_settings.log_level)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create the Worker Controller FastAPI application.

    Uses Neuroglia WebApplicationBuilder with build_app_with_lifespan for
    proper HostedService lifecycle management (no deprecated on_event).

    Returns:
        Configured FastAPI application.
    """
    # Load settings
    settings = Settings()

    # Load API description from markdown file
    description_path = Path(__file__).parent / "api" / "description.md"
    api_description = "Worker Controller for Lablet Cloud Manager"
    if description_path.exists():
        api_description = description_path.read_text(encoding="utf-8")
        logger.debug(f"Loaded API description from {description_path}")
    else:
        logger.warning(f"API description file not found: {description_path}")

    # Build Neuroglia application
    builder = WebApplicationBuilder()

    # =========================================================================
    # CONFIGURE SERVICES (Dependency Injection)
    # =========================================================================

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

    # Configure AWS SPI clients
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        AwsEc2SpiClient.configure(
            builder.services,
            access_key_id=settings.aws_access_key_id,
            secret_access_key=settings.aws_secret_access_key,
            region=settings.aws_region,
        )

        AwsCloudWatchSpiClient.configure(
            builder.services,
            access_key_id=settings.aws_access_key_id,
            secret_access_key=settings.aws_secret_access_key,
            region=settings.aws_region,
        )
    else:
        logger.warning("AWS credentials not configured - EC2/CloudWatch operations will fail")

    # Configure CML System SPI client
    CmlSystemSpiClient.configure(
        builder.services,
        default_username=settings.cml_worker_api_username,
        default_password=settings.cml_worker_api_password,
    )

    # Configure DualAuth service
    DualAuthService.configure(builder)

    # Configure worker reconciler hosted service
    # Registers as both concrete singleton and HostedService for automatic lifecycle
    WorkerReconciler.configure(builder.services, settings)

    # Service info for standard endpoints
    service_info = ServiceInfo(
        name=settings.app_name,
        version=settings.app_version,
        description="Worker Controller for Lablet Cloud Manager - manages CML worker lifecycle",
        image_tag=settings.image_tag,
    )

    # Custom setup for API sub-app
    def api_setup(app: FastAPI, settings: Any) -> None:
        """Configure API sub-app with admin routes and standard endpoints."""
        from api.services.openapi_config import configure_openapi_security

        # app.state.services is set by neuroglia before custom_setup is called
        reconciler = app.state.services.get_required_service(WorkerReconciler)

        # Create and include admin controller
        admin_controller = AdminController(reconciler)
        app.include_router(admin_controller.router)

        # Configure OAuth2 security for Swagger UI
        configure_openapi_security(app)

        # Configure standard endpoints mixin
        class WorkerEndpoints(StandardEndpointsMixin):  # type: ignore[misc]
            def __init__(self) -> None:
                super().__init__()  # Initialize _readiness_checks
                self._service_info = service_info
                self._reconciler = reconciler

            async def check_readiness(self) -> tuple[bool, str]:
                if self._reconciler:
                    result: tuple[bool, str] = await self._reconciler.check_readiness()
                    return result
                return True, "OK"

            def get_extra_info(self) -> dict[str, Any]:
                if self._reconciler:
                    info: dict[str, Any] = self._reconciler.get_extra_info()
                    return info
                return {}

        endpoints = WorkerEndpoints()
        endpoints.configure_standard_endpoints(app, tags=["Operations"])

        logger.info(f"Worker Controller configured (leader={reconciler.is_leader})")

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
            description="Worker Controller Admin Interface",
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

    # Configure DualAuth middleware
    DualAuthService.configure_middleware(app)

    logger.info(f"✅ Worker Controller application created (version {settings.app_version})")

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
