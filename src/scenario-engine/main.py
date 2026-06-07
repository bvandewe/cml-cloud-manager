"""Scenario Engine Service - Main Entry Point.

Domain: Pod Automation (DSL execution, multi-adapter infrastructure calls)
SPI: CML/AWS, ROC/RADkit, Proxmox, VMWare adapters

This service manages pod automation execution:
- Job submission and lifecycle (fire-and-forget with progress tracking)
- PodDefinition content synchronization from BlobStorage
- Scenario registry (decorator-based, auto-discovered at boot)
- DSL runtime (ServerlessWorkflow-inspired, jq expression evaluator)
- Multi-adapter dispatch (CML-on-AWS, ROC/RADkit, Proxmox, VMWare)

Architecture:
- WebApplicationBuilder for DI and lifecycle management
- Fire-and-forget job API (submit → job_id → CloudEvents callback)
- Standard endpoints (/healthz, /ready, /info)

Communication Pattern:
    LCM (lablet-controller) → POST /api/v1/jobs → SE executes → CloudEvents callback

All content synced from BlobStorage on demand (ADR-044).
"""

import logging
from pathlib import Path

import scenarios  # noqa: F401 — triggers @scenario decorator registrations
import uvicorn
from application.services.job_execution_service import JobExecutionService
from application.settings import Settings, app_settings
from domain.entities.job import Job
from domain.entities.pod_definition import PodDefinition
from domain.repositories.job_repository import JobRepository
from domain.repositories.pod_definition_repository import PodDefinitionRepository
from fastapi import FastAPI
from integration.persistence.mongo_job_repository import MongoJobRepository
from integration.persistence.mongo_pod_definition_repository import MongoPodDefinitionRepository
from integration.services.cloud_event_client import CloudEventCallbackService
from lcm_core.infrastructure import configure_logging
from lcm_core.infrastructure.content_store.content_extractor import ContentExtractor
from lcm_core.infrastructure.content_store.pav1_validator import PAv1Validator
from lcm_core.infrastructure.content_store.pod_type_detector import PodTypeDetector
from lcm_core.infrastructure.content_store.s3_content_client import S3ContentClient
from lcm_core.infrastructure.mixins import ServiceInfo, StandardEndpointsMixin
from neuroglia.data.infrastructure.mongo import MotorRepository
from neuroglia.hosting.web import SubAppConfig, WebApplicationBuilder
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator
from neuroglia.serialization.json import JsonSerializer

# Configure logging
configure_logging(log_level=app_settings.log_level)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create the Scenario Engine FastAPI application.

    Uses Neuroglia WebApplicationBuilder with build_app_with_lifespan for
    proper HostedService lifecycle management.

    Returns:
        Configured FastAPI application.
    """
    # Load settings
    settings = Settings()

    # Load API description from markdown file
    description_path = Path(__file__).parent / "api" / "description.md"
    api_description = "Scenario Engine for Lablet Cloud Manager"
    if description_path.exists():
        api_description = description_path.read_text(encoding="utf-8")
        logger.debug(f"Loaded API description from {description_path}")
    else:
        logger.warning(f"API description file not found: {description_path}")

    # Build Neuroglia application
    builder = WebApplicationBuilder(app_settings=settings)

    # =========================================================================
    # CONFIGURE SERVICES (Dependency Injection)
    # =========================================================================

    # Configure settings as singleton
    builder.services.add_singleton(Settings, implementation_factory=lambda _: settings)

    # Configure JsonSerializer (required by Neuroglia exception middleware)
    JsonSerializer.configure(builder, ["domain.entities"])

    # Configure Mediator (CQRS handler discovery)
    Mediator.configure(builder, ["application.commands", "application.queries"])

    # Configure Mapper
    Mapper.configure(builder, ["application.commands", "application.queries"])

    # Configure Job MongoDB repository
    MotorRepository.configure(
        builder,
        entity_type=Job,
        key_type=str,
        database_name=settings.mongodb_database,
        collection_name="jobs",
        domain_repository_type=JobRepository,
        implementation_type=MongoJobRepository,
    )

    # Configure PodDefinition MongoDB repository
    MotorRepository.configure(
        builder,
        entity_type=PodDefinition,
        key_type=str,
        database_name=settings.mongodb_database,
        collection_name="pod_definitions",
        domain_repository_type=PodDefinitionRepository,
        implementation_type=MongoPodDefinitionRepository,
    )

    # Configure CloudEventCallbackService as singleton
    builder.services.add_singleton(
        CloudEventCallbackService,
        implementation_factory=lambda _: CloudEventCallbackService(settings),
    )

    # Configure Content Store singletons (Phase 1 G-01 — SyncContentCommand pipeline)
    builder.services.add_singleton(
        S3ContentClient,
        implementation_factory=lambda _: S3ContentClient(
            endpoint_url=settings.s3_endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            region=settings.s3_region,
            secure=settings.s3_secure,
        ),
    )
    builder.services.add_singleton(ContentExtractor)
    builder.services.add_singleton(PAv1Validator)
    builder.services.add_singleton(PodTypeDetector)

    # Configure JobExecutionService as singleton + HostedService
    JobExecutionService.configure(builder.services, settings)

    # Service info for standard endpoints
    service_info = ServiceInfo(
        name=settings.app_name,
        version=settings.app_version,
        description="Scenario Engine - Pod automation execution service",
        image_tag=settings.image_tag,
    )

    # Custom setup for API sub-app
    def api_setup(app: FastAPI, settings_arg: object) -> None:
        """Configure API sub-app with standard endpoints."""

        # Configure standard endpoints mixin
        class ScenarioEndpoints(StandardEndpointsMixin):  # type: ignore[misc]
            def __init__(self) -> None:
                super().__init__()
                self._service_info = service_info

            async def check_readiness(self) -> tuple[bool, str]:
                return True, "OK"

            def get_extra_info(self) -> dict[str, object]:
                return {}

        endpoints = ScenarioEndpoints()
        endpoints.configure_standard_endpoints(app, tags=["Operations"])

        logger.info("Scenario Engine API configured")

    # Get static directory path for UI SubApp
    static_dir = Path(__file__).parent / "static"

    # Add API SubApp with controllers (mounted at /api)
    builder.add_sub_app(
        SubAppConfig(
            path="/api",
            name="api",
            title=settings.app_name,
            description=api_description,
            version=settings.app_version,
            controllers=["api.controllers"],
            custom_setup=api_setup,
            docs_url="/docs",
        )
    )

    # Add UI SubApp at root path
    builder.add_sub_app(
        SubAppConfig(
            path="/",
            name="ui",
            title=f"{settings.app_name} UI",
            description="Scenario Engine Admin Interface",
            version=settings.app_version,
            controllers=["ui.controllers"],
            static_files={"/static": str(static_dir)},
            docs_url=None,
        )
    )

    # Build the application with lifespan
    app = builder.build_app_with_lifespan(
        title=settings.app_name,
        description=api_description,
        version=settings.app_version,
        debug=settings.debug,
    )

    logger.info(f"✅ Scenario Engine application created (version {settings.app_version})")

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
