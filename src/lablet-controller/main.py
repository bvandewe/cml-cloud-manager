"""Lablet Controller Service - Main Entry Point.

Domain: Application Layer (Workloads)
SPI: CML Labs API (Labs, Nodes, Interfaces, Links)

This service manages LabletSession lifecycle:
- Reconcile LabletSession spec vs actual CML lab state
- Lab lifecycle management (import, start, stop, wipe, delete)
- Port allocation and mapping
- Node configuration extraction

Architecture:
- WebApplicationBuilder for DI and lifecycle management
- LeaderElectedHostedService for reconciliation with leader election
- Standard endpoints (/health, /ready, /metrics, /info)
- Admin endpoints for operational control

Reconciliation Pattern:
    SPEC (LabletSession from Control Plane API) ←→ OBSERVE (CML Lab state) → ACT (reconcile)

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
from application.hosted_services import LabletReconciler
from application.settings import Settings, app_settings
from fastapi import FastAPI
from integration.services.cml_labs_spi import CmlLabsSpiClient
from integration.services.environment_resolver_client import EnvironmentResolverClient
from integration.services.lds_spi import LdsSpiClient
from integration.services.mosaic_client import MosaicClient
from integration.services.oauth2_token_manager import TokenConfig
from integration.services.s3_client import S3Client
from integration.services.scenario_engine_client import ScenarioEngineClient
from lcm_core.infrastructure import configure_logging
from lcm_core.infrastructure.mixins import ServiceInfo, StandardEndpointsMixin
from lcm_core.integration.clients import ControlPlaneApiClient, EtcdClient
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_ingestor import CloudEventIngestor
from neuroglia.hosting.web import SubAppConfig, WebApplicationBuilder
from neuroglia.mediation.mediator import Mediator
from neuroglia.serialization.json import JsonSerializer

# Configure logging
configure_logging(log_level=app_settings.log_level)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create the Lablet Controller FastAPI application.

    Uses Neuroglia WebApplicationBuilder with build_app_with_lifespan for
    proper HostedService lifecycle management (no deprecated on_event).

    Returns:
        Configured FastAPI application.
    """
    # Load settings
    settings = Settings()

    # Load API description from markdown file
    description_path = Path(__file__).parent / "api" / "description.md"
    api_description = "Lablet Controller for Lablet Cloud Manager"
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

    # Configure JsonSerializer (required by Neuroglia exception middleware and
    # by CloudEventMiddleware for envelope deserialisation).
    JsonSerializer.configure(builder, [])

    # Configure Mediator + CloudEventIngestor so SE CloudEvent callbacks
    # delivered via CloudEventMiddleware (registered on the outer app below)
    # are routed to the IntegrationEventHandlers in
    # ``application.events.integration``. Mirrors the pattern used by
    # ``control-plane-api`` and ``knowledge-manager``.
    Mediator.configure(builder, ["application.events.integration"])
    CloudEventIngestor.configure(builder, ["application.events.integration"])

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

    # Configure CML Labs SPI client
    CmlLabsSpiClient.configure(
        builder.services,
        default_username=settings.cml_worker_api_username,
        default_password=settings.cml_worker_api_password,
    )

    # Configure LDS (Lab Delivery System) SPI client
    LdsSpiClient.configure(
        builder.services,
        config_path=settings.lds_deployments_config_path,
        verify_ssl=settings.lds_verify_ssl,
    )

    # Configure S3 client (RustFS/MinIO for content packages)
    S3Client.configure(
        builder.services,
        endpoint_url=settings.s3_endpoint,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        region=settings.s3_region,
        secure=settings.s3_secure,
    )

    # Configure Environment Resolver client
    env_resolver_token_config = None
    if settings.environment_resolver_token_url:
        env_resolver_token_config = TokenConfig(
            token_url=settings.environment_resolver_token_url,
            client_id=settings.environment_resolver_client_id or "",
            client_secret=settings.environment_resolver_client_secret or "",
            scopes=settings.environment_resolver_scopes,
        )
    EnvironmentResolverClient.configure(
        builder.services,
        base_url=settings.environment_resolver_url,
        default_environment=settings.environment_resolver_environment,
        token_config=env_resolver_token_config,
    )

    # Configure Mosaic client (content package downloads)
    mosaic_token_config = None
    if settings.mosaic_token_url:
        mosaic_token_config = TokenConfig(
            token_url=settings.mosaic_token_url,
            client_id=settings.mosaic_client_id or "",
            client_secret=settings.mosaic_client_secret or "",
            scopes=settings.mosaic_scopes,
        )
    MosaicClient.configure(
        builder.services,
        token_config=mosaic_token_config,
    )

    # Configure Scenario Engine client (ADR-044 / G-02, Phase 2).
    # Always registered so call sites can depend on it; the integration is
    # gated by settings.scenario_engine_integration_enabled at the call site
    # (best-effort, AD-CSI-014).
    ScenarioEngineClient.configure(
        builder.services,
        base_url=settings.scenario_engine_url,
        callback_url=settings.scenario_engine_callback_url,
    )

    # Configure DualAuth service
    DualAuthService.configure(builder)

    # Configure lablet reconciler hosted service
    # Registers as both concrete singleton and HostedService for automatic lifecycle.
    # Also registers LabDiscoveryService (started by leader in _become_leader).
    LabletReconciler.configure(builder.services, settings)

    # Service info for standard endpoints
    service_info = ServiceInfo(
        name=settings.app_name,
        version=settings.app_version,
        description="Lablet Controller for Lablet Cloud Manager - manages CML lab lifecycle",
        image_tag=settings.image_tag,
    )

    # Custom setup for API sub-app!
    def api_setup(app: FastAPI, settings: Any) -> None:
        """Configure API sub-app with admin routes and standard endpoints."""
        from api.services.openapi_config import configure_openapi_security

        # app.state.services is set by neuroglia before custom_setup is called
        reconciler = app.state.services.get_required_service(LabletReconciler)

        # Create and include admin controller
        admin_controller = AdminController(reconciler)
        app.include_router(admin_controller.router)

        # Phase 3 / AD-CSI-009: Scenario Engine CloudEvent callbacks are
        # ingested by Neuroglia's CloudEventMiddleware (registered on the
        # outer app below) and dispatched via the Mediator to the
        # IntegrationEventHandlers in ``application.events.integration``.
        # No explicit controller / route is required — the middleware
        # intercepts every request whose Content-Type is
        # ``application/cloudevents+json``.

        # Configure OAuth2 security for Swagger UI
        configure_openapi_security(app)

        # Configure standard endpoints mixin
        class LabletEndpoints(StandardEndpointsMixin):  # type: ignore[misc]
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

        endpoints = LabletEndpoints()
        endpoints.configure_standard_endpoints(app, tags=["Operations"])

        logger.info(f"Lablet Controller configured (leader={reconciler.is_leader})")

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
            description="Lablet Controller Admin Interface",
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

    # Note: CloudEventMiddleware is automatically added to the outer app by
    # neuroglia.hosting.web.WebApplicationBuilder.build_app_with_lifespan()
    # because CloudEventIngestor is configured above. It intercepts any
    # request with Content-Type: application/cloudevents+json on any path
    # (including the SE callback URL) and routes the envelope through the
    # CloudEventBus → CloudEventIngestor → Mediator pipeline.

    logger.info(f"✅ Lablet Controller application created (version {settings.app_version})")

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
        reload_dirs=["/app", "/core"] if settings.debug else None,
        reload_excludes=["logs", "static", "data", "*.log"] if settings.debug else None,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
