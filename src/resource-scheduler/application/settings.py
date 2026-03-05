"""Resource Scheduler Service Settings.

Configuration for the Resource Scheduler service using Neuroglia ApplicationSettings.
Supports environment variable configuration with case-insensitive mapping.
"""

import os
from typing import Any

from neuroglia.hosting.abstractions import ApplicationSettings
from pydantic_settings import SettingsConfigDict


class Settings(ApplicationSettings):
    """Configuration settings for the Resource Scheduler Service.

    Inherits from Neuroglia ApplicationSettings for framework compatibility.
    Uses lowercase field names with case-insensitive env var mapping.
    """

    # ============================================================================
    # Core Application Configuration
    # ============================================================================
    app_name: str = "resource-scheduler"
    app_version: str = "1.0.0"
    image_tag: str = "v0.1.0"
    environment: str = "production"
    debug: bool = False
    log_level: str = "INFO"

    # HTTP Server
    app_host: str = "0.0.0.0"
    app_port: int = 8081

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
    leader_key: str = "/lcm/resource-scheduler/leader"

    # ============================================================================
    # Scheduling
    # ============================================================================
    reconcile_interval: int = 30
    reconcile_polling_enabled: bool = True  # Set False for watch-only mode (ADR-015)
    timeslot_lead_time_minutes: int = 35

    # ============================================================================
    # Cleanup Configuration
    # ============================================================================
    cleanup_enabled: bool = True
    cleanup_interval_seconds: int = 3600  # Run every hour
    cleanup_retention_days: int = 30  # Keep terminated workers for 30 days

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
    # Observability (OpenTelemetry)
    # ============================================================================
    service_name: str = "resource-scheduler"
    otel_service_name: str = "resource-scheduler"
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
        """Get etcd endpoints as a list."""
        endpoints_str = os.getenv("ETCD_ENDPOINTS")
        if endpoints_str:
            return [ep.strip() for ep in endpoints_str.split(",")]
        return [f"{self.etcd_host}:{self.etcd_port}"]


# Instantiate application settings
app_settings = Settings()
