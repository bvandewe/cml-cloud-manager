"""Lablet Controller Service Settings.

Configuration for the Lablet Controller service using Neuroglia ApplicationSettings.
Supports environment variable configuration with case-insensitive mapping.
"""

import os
from typing import Any

from neuroglia.hosting.abstractions import ApplicationSettings
from pydantic_settings import SettingsConfigDict


class Settings(ApplicationSettings):
    """Configuration settings for the Lablet Controller Service.

    Inherits from Neuroglia ApplicationSettings for framework compatibility.
    Uses lowercase field names with case-insensitive env var mapping.
    """

    # ============================================================================
    # Core Application Configuration
    # ============================================================================
    app_name: str = "lablet-controller"
    app_version: str = "1.0.0"
    image_tag: str = "v0.1.0"
    environment: str = "production"
    debug: bool = False
    log_level: str = "INFO"

    # HTTP Server
    app_host: str = "0.0.0.0"
    app_port: int = 8082

    # ============================================================================
    # etcd Configuration
    # ============================================================================
    etcd_host: str = "localhost"
    etcd_port: int = 2379
    etcd_username: str | None = None
    etcd_password: str | None = None
    etcd_watch_enabled: bool = True
    etcd_key_prefix: str = "/lcm"

    # ============================================================================
    # Control Plane API
    # ============================================================================
    control_plane_api_url: str = "http://localhost:8020"
    control_plane_api_key: str | None = None

    # ============================================================================
    # Leader Election
    # ============================================================================
    leader_lease_ttl: int = 15
    leader_key: str = "/lcm/lablet-controller/leader"

    # ============================================================================
    # Reconciliation & Scaling
    # ============================================================================
    reconcile_interval: int = 30
    reconcile_polling_enabled: bool = True  # Set False for watch-only mode (ADR-015)
    scale_down_grace_period_minutes: int = 30
    worker_bootup_delay_minutes: int = 20

    # ============================================================================
    # Timeslot Watcher (AD-TIMESLOT-001)
    # ============================================================================
    timeslot_check_enabled: bool = True  # Master switch for TimeslotWatcherService
    timeslot_check_interval: int = 10  # Seconds between deadline scans
    timeslot_boot_window_minutes: int = 35  # Look-ahead for SCHEDULED sessions (>= max boot lead time)

    # ============================================================================
    # CML Worker API Credentials
    # ============================================================================
    cml_worker_api_username: str = "admin"
    cml_worker_api_password: str = ""
    use_private_ip_for_monitoring: bool = False

    # ============================================================================
    # Labs Refresh / Lab Discovery V2
    # ============================================================================
    labs_refresh_enabled: bool = True
    labs_refresh_interval: int = 300  # 5 minutes

    # ============================================================================
    # Lab Record Reconciliation (AD-023)
    # ============================================================================
    lab_record_reconcile_enabled: bool = True  # Watch etcd for lab pending actions

    # ============================================================================
    # LDS (Lab Delivery System) Integration
    # ============================================================================
    lds_deployments_config_path: str | None = None  # Path to lds_deployments.yaml
    lds_verify_ssl: bool = True

    # ============================================================================
    # Security & Authentication (Keycloak)
    # ============================================================================
    keycloak_url: str = "http://localhost:8041"
    keycloak_url_internal: str | None = None
    keycloak_realm: str = "aix"
    keycloak_client_id: str = "lcm-public"
    keycloak_client_secret: str | None = None
    verify_issuer: bool = True
    expected_issuer: str = ""
    verify_audience: bool = True
    expected_audience: list[str] = ["lcm"]

    # Token Lifespans (aligned with Keycloak realm settings)
    access_token_lifespan_seconds: int = 1500  # 25 minutes (Keycloak default)
    sso_session_idle_timeout_minutes: int = 30  # Keycloak ssoSessionIdleTimeout
    sso_session_max_lifespan_minutes: int = 600  # 10 hours (Keycloak ssoSessionMaxLifespan)
    refresh_auto_leeway_seconds: int = 300  # 5 minutes before expiry

    # Session Management (for future UI expansion)
    session_secret_key: str = "change-me-in-production-use-secrets-token-urlsafe"
    session_max_duration_minutes: int = 600  # 10 hours (aligned with Keycloak)
    session_expiration_warning_minutes: int = 10

    # ============================================================================
    # S3 / RustFS Object Storage (Content Sync)
    # ============================================================================
    s3_endpoint: str = "http://localhost:9000"  # RustFS/MinIO S3 API endpoint
    s3_console_url: str = "http://localhost:9001"  # RustFS/MinIO Console URL (for UI links)
    s3_access_key: str = "admin"
    s3_secret_key: str = "admin123"
    s3_region: str = "us-east-1"  # Default region for S3 client
    s3_secure: bool = False  # Use HTTPS for S3

    # ============================================================================
    # Environment Resolver Service (Content Sync)
    # ============================================================================
    environment_resolver_url: str = "https://environment-resolver.expert.certs.cloud"
    environment_resolver_environment: str = "CERTS-DEV"  # Default resolver environment
    # OAuth2 client credentials for Environment Resolver (optional)
    environment_resolver_token_url: str | None = None
    environment_resolver_client_id: str | None = None
    environment_resolver_client_secret: str | None = None
    environment_resolver_scopes: str = ""  # Space-separated scopes

    # ============================================================================
    # Mosaic (Content Authoring Platform)
    # ============================================================================
    # Mosaic base URL is resolved dynamically via Environment Resolver
    # OAuth2 client credentials for Mosaic API
    mosaic_token_url: str | None = None  # Keycloak token endpoint
    mosaic_client_id: str | None = None
    mosaic_client_secret: str | None = None
    mosaic_scopes: str = ""  # Space-separated scopes

    # ============================================================================
    # Content Sync Service (AD-CS-001)
    # ============================================================================
    content_sync_enabled: bool = True  # Master switch
    content_sync_watch_enabled: bool = True  # PRIMARY: etcd watch for immediate reaction
    content_sync_poll_enabled: bool = False  # FALLBACK: opt-in polling (disabled by default)
    content_sync_poll_interval: int = 300  # Seconds between polls (only if poll_enabled)

    # ============================================================================
    # Resource Observation (ADR-030)
    # ============================================================================
    resource_observation_enabled: bool = True  # Enable automatic observation at COLLECTING
    resource_observation_timeout_seconds: int = 30  # Timeout for CML API observation calls

    # ============================================================================
    # Observability (OpenTelemetry)
    # ============================================================================
    service_name: str = "lablet-controller"
    otel_service_name: str = "lablet-controller"
    otel_exporter_otlp_endpoint: str | None = None
    otel_enabled: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    def __init__(self, **kwargs: Any) -> None:
        """Initialize settings."""
        super().__init__(**kwargs)
        if not self.keycloak_url_internal:
            self.keycloak_url_internal = self.keycloak_url

    @property
    def etcd_endpoints(self) -> list[str]:
        """Get etcd endpoints list.

        Supports both single host:port and comma-separated list.
        """
        endpoints_str = os.getenv("ETCD_ENDPOINTS")
        if endpoints_str:
            return [ep.strip() for ep in endpoints_str.split(",")]
        return [f"{self.etcd_host}:{self.etcd_port}"]


# Instantiate application settings
app_settings = Settings()
