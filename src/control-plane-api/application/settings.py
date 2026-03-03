"""Application settings configuration."""

from typing import Any

from neuroglia.hosting.abstractions import ApplicationSettings
from pydantic_settings import SettingsConfigDict

from integration.enums import Ec2InstanceType


class Settings(ApplicationSettings):
    """Application settings with Keycloak OAuth2/OIDC configuration and observability."""

    # ============================================================================
    # Core Application Configuration
    # ============================================================================
    app_name: str = "Cml Cloud Manager"
    app_version: str = "1.0.0"
    image_tag: str = "v0.1.0"
    environment: str = "production"  # Default to production for safety
    debug: bool = False
    log_level: str = "INFO"

    # Networking
    app_host: str = "127.0.0.1"  # Default to localhost for security (use 0.0.0.0 in Docker)
    app_port: int = 8080
    app_url: str = "http://localhost:8020"  # External URL for callbacks

    # Controller Service URLs (internal, for server-side health checks)
    worker_controller_url: str = "http://localhost:8083"
    lablet_controller_url: str = "http://localhost:8082"
    resource_scheduler_url: str = "http://localhost:8081"

    # ============================================================================
    # Security & Authentication
    # ============================================================================

    # CORS
    enable_cors: bool = True
    cors_origins: list[str] = ["http://localhost:8020", "http://localhost:3000"]

    # Keycloak OAuth2/OIDC
    keycloak_url: str = "http://localhost:8041"  # External URL (browser/Swagger accessible)
    keycloak_url_internal: str | None = None  # Internal Docker network URL (auto-populated if not set)
    keycloak_realm: str = "aix"

    # Clients
    keycloak_client_id: str = "lcm-backend"  # Confidential client for backend
    keycloak_client_secret: str = "lcm-backend-secret-change-in-production"
    keycloak_public_client_id: str = "lcm-public"  # Public client for Swagger/Frontend

    # Token Validation
    verify_issuer: bool = True
    expected_issuer: str = ""  # e.g. "http://localhost:8041/realms/aix"
    verify_audience: bool = True
    expected_audience: list[str] = ["lcm"]

    # Token Lifespans (aligned with Keycloak realm settings)
    # These should match the realm's accessTokenLifespan, ssoSessionIdleTimeout, ssoSessionMaxLifespan
    access_token_lifespan_seconds: int = 1500  # 25 minutes (Keycloak default)
    sso_session_idle_timeout_minutes: int = 30  # Keycloak ssoSessionIdleTimeout
    sso_session_max_lifespan_minutes: int = 600  # 10 hours (Keycloak ssoSessionMaxLifespan)

    # Auto-refresh: refresh tokens this many seconds before access token expires
    # Should be < access_token_lifespan_seconds to allow time for refresh
    refresh_auto_leeway_seconds: int = 300  # 5 minutes before expiry

    # Service-to-Service API Key
    # Used by controllers (resource-scheduler, lablet-controller, worker-controller)
    # to authenticate with internal endpoints (X-API-Key header)
    internal_api_key: str = "lcm-internal-api-key-change-in-production"

    # Session Management
    # session_max_duration_minutes should align with sso_session_max_lifespan_minutes
    session_secret_key: str = "change-me-in-production-use-secrets-token-urlsafe"
    session_max_duration_minutes: int = 600  # 10 hours (aligned with Keycloak ssoSessionMaxLifespan)
    session_expiration_warning_minutes: int = 10  # Warn user this many minutes before session expires

    # ============================================================================
    # Database & Persistence
    # ============================================================================

    # MongoDB
    connection_strings: dict[str, str] = {"mongo": "mongodb://root:pass@mongodb:27017/?authSource=admin"}

    # Redis (Session Store)
    redis_enabled: bool = False
    redis_url: str = "redis://redis:6379/0"
    redis_key_prefix: str = "session:"

    # Background Job Store (APScheduler)
    background_job_store: dict[str, Any] = {
        "redis_host": "redis",
        "redis_port": 6379,
        "redis_db": 1,
    }

    # etcd (State Coordination)
    etcd_host: str = "localhost"
    etcd_port: int = 2379
    etcd_timeout: int = 5  # Connection timeout in seconds
    etcd_retry_attempts: int = 3
    etcd_retry_delay: float = 1.0  # Delay between retries in seconds
    etcd_key_prefix: str = "/lcm"  # Base prefix for all keys
    etcd_lease_ttl: int = 30  # Default lease TTL in seconds

    # Port Allocation (for lablet instances)
    port_allocation_min: int = 2000  # Minimum port in allocation range
    port_allocation_max: int = 9999  # Maximum port in allocation range

    # Consumer Group
    consumer_group: str | None = "lablet-cloud-manager-consumer-group"

    # ============================================================================
    # AWS & CML Worker Configuration
    # ============================================================================

    # AWS Credentials
    aws_access_key_id: str = "YOUR_ACCESS_KEY_ID"
    aws_secret_access_key: str = "YOUR_SECRET_ACCESS_KEY"

    # Data Seeding Configuration
    # Base path for seed data (e.g., /app/data in container, ./config locally)
    # Seed data is loaded from {data_seed_base_path}/seeds/{entity_type}/ folders
    data_seed_base_path: str = "/app/data"

    # Worker Provisioning
    cml_worker_ami_name_default: str = "my-cml2.7.0-lablet-v0.1.0"
    cml_worker_ami_ids: dict[str, str] = {
        "us-east-1": "ami-0123456789abcdef0",
        "us-west-2": "ami-0123456789abcdef0",
    }
    cml_worker_ami_names: dict[str, str] = {
        "us-east-1": "CML-2.7.0-Ubuntu-22.04",
        "us-west-2": "CML-2.7.0-Ubuntu-22.04",
    }
    cml_worker_instance_type: Ec2InstanceType = Ec2InstanceType.SMALL
    cml_worker_security_group_ids: list[str] = ["sg-0123456789abcdef0"]
    cml_worker_security_group_names: list[str] = ["ec2_cml_worker_sg"]
    cml_worker_vpc_id: str = "vpc-0123456789abcdef0"
    cml_worker_subnet_id: str = "subnet-0123456789abcdef0"
    cml_worker_key_name: str = "cml_worker_key_pair"
    cml_worker_username: str = "sys-admin"
    cml_worker_default_tags: dict[str, str] = {
        "Environment": "dev",
        "ApplicationName": "CML-Cloud-Manager",
        "ManagedBy": "CML-Cloud-Manager",
        "Name": "cml-worker-{worker_id}",
    }
    use_private_ip_for_monitoring: bool = False

    # ============================================================================
    # Scaling Constraints (Phase 3 - Auto-Scaling)
    # ============================================================================
    max_workers_per_region: int = 10  # Maximum concurrent workers per AWS region
    min_workers: int = 0  # Minimum workers to keep running (0 = scale to zero allowed)
    scale_up_cooldown_seconds: int = 300  # Cooldown between scale-up operations (5 min)
    scale_down_cooldown_seconds: int = 600  # Cooldown between scale-down operations (10 min)

    # CML API Credentials
    cml_worker_api_username: str = "admin"
    cml_worker_api_password: str = "admin"  # pragma: allowlist secret
    cml_worker_api_verify_ssl: bool = False

    # ============================================================================
    # Monitoring & Background Jobs
    # ============================================================================

    # Worker Monitoring
    worker_monitoring_enabled: bool = True
    worker_metrics_poll_interval: int = 300
    metrics_change_threshold_percent: float = 5.0

    # Activity Detection & Auto-Pause
    worker_activity_detection_enabled: bool = True
    worker_activity_detection_interval: int = 1800
    worker_idle_timeout_minutes: int = 60
    worker_auto_pause_enabled: bool = True
    worker_auto_pause_snooze_minutes: int = 60
    worker_activity_events_max_stored: int = 10
    worker_activity_excluded_user_pattern: str = "^00000000-0000-.*"
    worker_activity_relevant_categories: list[str] = [
        "start_lab",
        "stop_lab",
        "wipe_lab",
        "import_lab",
        "export_lab",
        "start_node",
        "stop_node",
        "queue_node",
        "boot_node",
        "user_activity",
    ]

    # Notifications
    worker_notification_webhooks: list[str] = []

    # Labs Refresh
    labs_refresh_interval: int = 1800

    # Worker Refresh Rate Limiting
    worker_refresh_min_interval: int = 10
    worker_refresh_check_upcoming_job_threshold: int = 10

    # Auto-Import Workers
    auto_import_workers_enabled: bool = False
    auto_import_workers_interval: int = 3600
    auto_import_workers_region: str = "us-east-1"
    auto_import_workers_ami_name: str = ""

    # ============================================================================
    # Feature Flags (Phase 7 — LabRecord Architecture)
    # ============================================================================
    lab_discovery_v2_enabled: bool = False  # Use Phase 7 typed LabRecordStatus-based discovery

    # ============================================================================
    # LDS (Lab Delivery System) Integration (Phase 12)
    # ============================================================================
    lds_base_url: str = ""  # LDS Reservations API base URL (empty = disabled)
    lds_username: str = ""  # HTTP Basic Auth username for LDS API
    lds_password: str = ""  # HTTP Basic Auth password for LDS API  # pragma: allowlist secret
    lds_verify_ssl: bool = False  # Whether to verify SSL certificates for LDS API
    lds_timeout: float = 30.0  # HTTP request timeout in seconds for LDS API calls
    lds_direct_mode: bool = False  # If True, CPA calls LDS directly; if False, delegates to lablet-controller

    # ============================================================================
    # Observability (OpenTelemetry)
    # ============================================================================

    # General
    service_name: str = "lablet-cloud-manager"
    service_version: str = app_version
    deployment_environment: str = "development"
    observability_enabled: bool = True

    # Endpoints
    observability_metrics_enabled: bool = True
    observability_tracing_enabled: bool = True
    observability_logging_enabled: bool = True
    observability_health_endpoint: bool = True
    observability_metrics_endpoint: bool = True
    observability_ready_endpoint: bool = True
    observability_health_path: str = "/health"
    observability_metrics_path: str = "/metrics"
    observability_ready_path: str = "/ready"
    observability_health_checks: list[str] = []

    # External Observability URLs (for UI)
    grafana_url: str = "http://localhost:3000"  # Grafana URL for embedded panels
    minio_console_url: str = "http://localhost:9001"  # MinIO Console URL for content storage
    prometheus_enabled: bool = True  # Whether Prometheus/Grafana panels are shown in UI

    # OpenTelemetry Collector
    otel_enabled: bool = True
    otel_endpoint: str = "http://otel-collector:4317"
    otel_protocol: str = "grpc"
    otel_timeout: int = 10
    otel_console_export: bool = False
    otel_batch_max_queue_size: int = 2048
    otel_batch_schedule_delay_ms: int = 5000
    otel_batch_max_export_size: int = 512
    otel_metrics_interval_ms: int = 60000
    otel_metrics_timeout_ms: int = 30000

    # Instrumentation
    otel_instrument_fastapi: bool = True
    otel_instrument_httpx: bool = True
    otel_instrument_logging: bool = True
    otel_instrument_system_metrics: bool = True
    otel_resource_attributes: dict[str, str] = {}

    # ============================================================================
    # Cloud Events
    # ============================================================================
    cloud_event_sink: str | None = None
    cloud_event_source: str | None = None
    cloud_event_type_prefix: str = "io.system.lablet-cloud-manager"
    cloud_event_retry_attempts: int = 5
    cloud_event_retry_delay: float = 1.0

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    def __init__(self, **kwargs: Any) -> None:
        """Initialize settings."""
        super().__init__(**kwargs)
        # If keycloak_url_internal is not provided, use keycloak_url as fallback
        # This handles both Docker (with override) and Kubernetes (single URL) scenarios
        if not self.keycloak_url_internal:
            self.keycloak_url_internal = self.keycloak_url


# Instantiate application settings
app_settings = Settings()
