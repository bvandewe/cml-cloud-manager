"""Main application entry point with SubApp mounting."""

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Generic Database Seeding Infrastructure (lcm-core)
from lcm_core.infrastructure import configure_logging
from lcm_core.infrastructure.seeding import DatabaseSeederService
from neuroglia.data.infrastructure.mongo import MotorRepository
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_ingestor import CloudEventIngestor
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_middleware import CloudEventMiddleware
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublisher
from neuroglia.hosting.web import SubAppConfig, WebApplicationBuilder
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator
from neuroglia.observability import Observability
from neuroglia.serialization.json import JsonSerializer

from api.services import DualAuthService
from api.services.openapi_config import configure_api_openapi, configure_mounted_apps_openapi_prefix
from application.services.event_deduplication_service import EventDeduplicationService
from application.services.port_allocation_service import PortAllocationService
from application.services.port_mapping_resolution_service import PortMappingResolutionService
from application.services.sse_event_relay import SSEEventRelayHostedService
from application.services.system_configuration_service import SystemConfigurationService
from application.services.system_health_service import SystemHealthService
from application.services.worker_template_service import WorkerTemplateService
from application.settings import app_settings
from domain.entities.cml_worker import CMLWorker
from domain.entities.lab_record import LabRecord
from domain.entities.lablet_definition import LabletDefinition
from domain.entities.lablet_session import LabletSession
from domain.entities.system_settings import SystemSettings
from domain.entities.worker_template import WorkerTemplate
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.grading_session_repository import GradingSessionRepository
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from domain.repositories.score_report_repository import ScoreReportRepository
from domain.repositories.system_settings_repository import SystemSettingsRepository
from domain.repositories.user_session_repository import UserSessionRepository
from domain.repositories.worker_template_repository import WorkerTemplateRepository
from domain.services.idle_detection_service import IdleDetectionService

# Entity-specific seeders for this service
from infrastructure.seeding import LabletDefinitionSeeder, SystemSettingsSeeder, WorkerTemplateSeeder
from infrastructure.services.worker_refresh_throttle import WorkerRefreshThrottle
from integration.repositories.mongo_worker_template_repository import MongoWorkerTemplateRepository
from integration.repositories.motor_cml_worker_repository import MongoCMLWorkerRepository
from integration.repositories.motor_grading_session_repository import MongoGradingSessionRepository
from integration.repositories.motor_lab_record_repository import MongoLabRecordRepository
from integration.repositories.motor_lablet_definition_repository import MongoLabletDefinitionRepository
from integration.repositories.motor_lablet_session_repository import MongoLabletSessionRepository
from integration.repositories.motor_score_report_repository import MongoScoreReportRepository
from integration.repositories.motor_system_settings_repository import MongoSystemSettingsRepository
from integration.repositories.motor_user_session_repository import MongoUserSessionRepository

# ADR-015: AwsEc2Client and CMLApiClientFactory removed - external calls delegated to controllers
from integration.services.etcd_client import EtcdClient
from integration.services.etcd_state_store import EtcdStateStore
from integration.services.lds_adapter import LdsAdapter

# Configure logging using centralized lcm_core function
# LOG_TO_FILE, LOG_FILE, LOG_FILE_TRUNCATE_ON_START are read from environment
configure_logging(log_level=app_settings.log_level)
log = logging.getLogger(__name__)


def _mask_env_value(key: str, value: str) -> str:
    """Mask sensitive environment variable values.

    Any key containing common secret indicators will be masked to avoid leaking credentials.
    """
    sensitive_markers = ["SECRET", "PASSWORD", "TOKEN", "KEY", "ACCESS_KEY"]
    upper_key = key.upper()
    if any(marker in upper_key for marker in sensitive_markers):
        # Preserve length for debugging without exposing content
        return f"***MASKED(len={len(value)})***" if value else "***MASKED***"
    return value


def debug_log_environment(prefix_only: tuple[str, ...] = ("AUTO_IMPORT_",)) -> None:
    """Dump environment variables at DEBUG level for diagnostic purposes.

    Sensitive values are masked. Optionally highlight certain prefixes (e.g. AUTO_IMPORT_).
    """
    if not log.isEnabledFor(logging.DEBUG):
        return
    try:
        log.debug("🔍 Dumping environment variables for startup diagnostics (masked)")
        highlighted = {}
        for k, v in sorted(os.environ.items()):
            masked = _mask_env_value(k, v)
            # Log all variables
            log.debug("ENV %s=%s", k, masked)
            if prefix_only and any(k.startswith(p) for p in prefix_only):
                highlighted[k] = v
        if highlighted:
            log.debug("✅ Highlighted AUTO_IMPORT settings: %s", highlighted)
        # Also log resolved settings object values of interest
        log.debug(
            "🧪 Resolved auto-import settings: enabled=%s interval=%s region=%s ami_name=%s",
            app_settings.auto_import_workers_enabled,
            app_settings.auto_import_workers_interval,
            app_settings.auto_import_workers_region,
            app_settings.auto_import_workers_ami_name,
        )
    except Exception as ex:
        log.warning("Failed to dump environment variables: %s", ex)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Creates separate apps for:
    - API backend (/api prefix) - REST API for task management
    - UI frontend (/ prefix) - Web interface

    Returns:
        Configured FastAPI application with multiple mounted apps
    """
    log.debug("🚀 Creating Cml Cloud Manager application...")

    # Early environment diagnostics before service configuration & scheduler startup
    debug_log_environment()

    builder = WebApplicationBuilder(app_settings=app_settings)

    # Configure core services
    Mediator.configure(
        builder,
        [
            "application.commands",
            "application.queries",
            "application.events.domain",
            "application.events.integration",
        ],
    )
    Mapper.configure(
        builder,
        [
            "application.commands",
            "application.queries",
            "application.mapping",
            "integration.models",
        ],
    )
    JsonSerializer.configure(
        builder,
        [
            "domain.entities",
            "domain.models",
            "integration.models",
        ],
    )
    CloudEventPublisher.configure(builder)
    CloudEventIngestor.configure(builder, ["application.events.integration"])
    Observability.configure(builder)

    # Configure CML Worker MongoDB repository
    MotorRepository.configure(
        builder,
        entity_type=CMLWorker,
        key_type=str,
        database_name="lablet_cloud_manager",
        collection_name="cml_workers",
        domain_repository_type=CMLWorkerRepository,
        implementation_type=MongoCMLWorkerRepository,
    )

    # Configure Lab Record Repository
    MotorRepository.configure(
        builder,
        entity_type=LabRecord,
        key_type=str,
        database_name="lablet_cloud_manager",
        collection_name="lab_records",
        domain_repository_type=LabRecordRepository,
        implementation_type=MongoLabRecordRepository,
    )

    # Configure System Settings Repository
    MotorRepository.configure(
        builder,
        entity_type=SystemSettings,
        key_type=str,
        database_name="lablet_cloud_manager",
        collection_name="system_settings",
        domain_repository_type=SystemSettingsRepository,
        implementation_type=MongoSystemSettingsRepository,
    )

    # Configure Worker Template Repository
    MotorRepository.configure(
        builder,
        entity_type=WorkerTemplate,
        key_type=str,
        database_name="lablet_cloud_manager",
        collection_name="worker_templates",
        domain_repository_type=WorkerTemplateRepository,
        implementation_type=MongoWorkerTemplateRepository,
    )

    # Configure LabletSession Repository (Phase 7E: replaces LabletInstance)
    MotorRepository.configure(
        builder,
        entity_type=LabletSession,
        key_type=str,
        database_name="lablet_cloud_manager",
        collection_name="lablet_sessions",
        domain_repository_type=LabletSessionRepository,
        implementation_type=MongoLabletSessionRepository,
    )

    # Configure LabletDefinition Repository (for lab definition templates)
    MotorRepository.configure(
        builder,
        entity_type=LabletDefinition,
        key_type=str,
        database_name="lablet_cloud_manager",
        collection_name="lablet_definitions",
        domain_repository_type=LabletDefinitionRepository,
        implementation_type=MongoLabletDefinitionRepository,
    )

    # Configure child entity repositories (Phase 7E — ADR-021)
    # These use plain Motor collections, not MotorRepository.configure(),
    # because they are Entity[str] not AggregateRoot.
    def _register_child_repos(b: WebApplicationBuilder) -> None:
        """Register child entity repositories with manual Motor collection wiring."""
        from motor.motor_asyncio import AsyncIOMotorClient

        def user_session_factory(sp: Any) -> MongoUserSessionRepository:
            client = sp.get_required_service(AsyncIOMotorClient)
            serializer = sp.get_required_service(JsonSerializer)
            return MongoUserSessionRepository(client, "lablet_cloud_manager", "user_sessions", serializer)

        def grading_session_factory(sp: Any) -> MongoGradingSessionRepository:
            client = sp.get_required_service(AsyncIOMotorClient)
            serializer = sp.get_required_service(JsonSerializer)
            return MongoGradingSessionRepository(client, "lablet_cloud_manager", "grading_sessions", serializer)

        def score_report_factory(sp: Any) -> MongoScoreReportRepository:
            client = sp.get_required_service(AsyncIOMotorClient)
            serializer = sp.get_required_service(JsonSerializer)
            return MongoScoreReportRepository(client, "lablet_cloud_manager", "score_reports", serializer)

        b.services.add_scoped(UserSessionRepository, implementation_factory=user_session_factory)
        b.services.add_scoped(GradingSessionRepository, implementation_factory=grading_session_factory)
        b.services.add_scoped(ScoreReportRepository, implementation_factory=score_report_factory)

    _register_child_repos(builder)

    # NOTE: APScheduler has been removed per ADR-011.
    # Background jobs are now handled by dedicated controllers:
    # - worker-controller: WorkerReconciler (includes discovery loop)
    # - lablet-controller: LabletReconciler
    # - resource-scheduler: ResourceScheduler
    # See docs/architecture/adr/ADR-011-apscheduler-removal.md

    # Configure Application Services
    DualAuthService.configure(builder)
    SSEEventRelayHostedService.configure(builder)
    # ADR-015: AwsEc2Client and CMLApiClientFactory removed
    # External AWS/CML calls are now delegated to worker-controller and lablet-controller
    SystemHealthService.configure(builder)
    SystemConfigurationService.configure(builder)
    IdleDetectionService.configure(builder)
    WorkerRefreshThrottle.configure(builder)

    # Configure etcd services (for state coordination - Lablet Resource Manager)
    EtcdClient.configure(builder)
    EtcdStateStore.configure(builder)

    # Configure Event Deduplication Service (for idempotent CloudEvent processing)
    builder.services.add_scoped(EventDeduplicationService)

    # Configure Port Allocation Service (depends on EtcdStateStore)
    PortAllocationService.configure(builder)

    # Configure Port Mapping Resolution Service (Phase 11 — resolves ports for LabletRecordRun)
    builder.services.add_scoped(PortMappingResolutionService)

    # Configure LDS Adapter (Phase 12 — LDS session operations for LabletRecordRun)
    LdsAdapter.configure(
        builder.services,
        base_url=app_settings.lds_base_url,
        username=app_settings.lds_username,
        password=app_settings.lds_password,
        verify_ssl=app_settings.lds_verify_ssl,
        timeout=app_settings.lds_timeout,
    )

    # Configure Worker Template Service (query/update operations)
    WorkerTemplateService.configure(builder)

    # Configure Database Seeder (seeds aggregates from YAML on startup)
    # Seeds: SystemSettings, WorkerTemplates, LabletDefinitions (in dependency order)
    seeds_dir = Path(__file__).parent / "data" / "seeds"
    DatabaseSeederService.configure(
        builder,
        seeds_dir=seeds_dir,
        entity_seeders=[
            SystemSettingsSeeder(),  # Order 5: Seed settings first
            WorkerTemplateSeeder(),  # Order 10: Seed templates second
            LabletDefinitionSeeder(),  # Order 20: Seed lablet definitions third
        ],
    )

    # Add SubApp for API with controllers
    builder.add_sub_app(
        SubAppConfig(
            path="/api",
            name="api",
            title=f"{app_settings.app_name} API",
            version=app_settings.app_version,
            controllers=["api.controllers"],
            custom_setup=lambda app, service_provider: configure_api_openapi(app, app_settings),
            docs_url="/docs",
        )
    )

    # UI sub-app: Web interface serving static files built by Parcel
    # Static files are always in ./static relative to this file (both local and Docker)
    static_dir = Path(__file__).parent / "static"

    # Add SubApp for UI at root path
    builder.add_sub_app(
        SubAppConfig(
            path="/",
            name="ui",
            title=app_settings.app_name,
            controllers=["ui.controllers"],
            static_files={"/static": str(static_dir)},
            docs_url=None,  # Disable docs for UI
        )
    )

    # Build the application
    app = builder.build_app_with_lifespan(
        title="Lablet Cloud Manager",
        description="Task management application with multi-app architecture",
        version="1.0.0",
        debug=True,
    )

    # Configure OpenAPI path prefixes for all mounted sub-apps
    configure_mounted_apps_openapi_prefix(app)

    # Configure middlewares
    DualAuthService.configure_middleware(app)
    app.add_middleware(CloudEventMiddleware, service_provider=app.state.services)

    if app_settings.enable_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    log.info("✅ Application created successfully!")
    log.info("📊 Access points:")
    log.info(f"   - UI: http://localhost:{app_settings.app_port}/")
    log.info(f"   - API Docs: http://localhost:{app_settings.app_port}/api/docs")
    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:create_app",
        factory=True,
        host=app_settings.app_host,
        port=app_settings.app_port,
        reload=app_settings.debug,
        reload_dirs=["/app", "/core"] if app_settings.debug else None,
        reload_excludes=["logs", "static", "data", "*.log"] if app_settings.debug else None,
        log_level=app_settings.log_level.lower(),
    )
