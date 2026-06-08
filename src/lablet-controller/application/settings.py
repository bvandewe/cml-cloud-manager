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
    app_host: str = "0.0.0.0"  # nosec B104 — container requires all-interfaces binding
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
    lab_action_poll_interval_seconds: int = 5
    lab_action_timeout_seconds: int = 180

    # ============================================================================
    # LDS (Lab Delivery System) Integration
    # ============================================================================
    lds_deployments_config_path: str | None = None  # Path to lds_deployments.yaml
    lds_verify_ssl: bool = True
    # Protocol priority for resolving multi-port devices (AD-LDS-002).
    # When a CML node has multiple annotations (e.g., serial + vnc), the first
    # matching protocol in this list wins when sending to LDS.
    lds_protocol_priority: list[str] = ["vnc", "http", "https", "rdp", "ssh", "serial", "telnet"]

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
    # Scenario Engine Integration (ADR-044 / G-02, Phase 2)
    # ============================================================================
    # Base URL of the Scenario Engine REST API (jobs + content sync).
    scenario_engine_url: str = "http://localhost:8084"
    # CloudEvent callback URL SE uses to deliver job lifecycle events back
    # to this service (e.g. http://lablet-controller:8082/events).
    scenario_engine_callback_url: str | None = None
    # Master switch — when False, lablet-controller skips the SE.sync_content
    # call (best-effort path, AD-CSI-014). Default off until Phase 4.
    scenario_engine_integration_enabled: bool = False
    # Phase 3 / Q-10 (watchdog hook): default per-step timeout for SE-suspended
    # pipeline steps. When the controller restarts mid-suspension, the recovery
    # reconciler will use this to detect orphaned external jobs that never
    # received a CloudEvent callback (e.g. SE crash, network partition).
    # 1800 seconds = 30 minutes.
    pipeline_external_step_default_timeout_seconds: int = 1800
    # Phase 3 / Q-10 — SuspendedStepWatchdogService scan interval (seconds).
    # Watchdog runs leader-only and lists active sessions, flagging any
    # pipeline step in status="suspended" whose suspended_at exceeded the
    # per-step timeout. Setting to 0 disables the scan loop entirely.
    suspended_step_watchdog_enabled: bool = True
    suspended_step_watchdog_interval_seconds: int = 60
    # Phase 3 / Q-11 — CloudEvent ingest source allow-list. EventsController
    # rejects CloudEvents whose ``source`` (structured mode) or ``ce-source``
    # header (binary mode) is not in this list. Empty list disables the check
    # (NOT recommended in production). Lower-cased for comparison.
    scenario_engine_allowed_sources: list[str] = ["scenario-engine"]

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
