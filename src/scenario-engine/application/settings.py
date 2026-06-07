"""Scenario Engine Service Settings.

Configuration for the Scenario Engine service using Neuroglia ApplicationSettings.
Supports environment variable configuration with case-insensitive mapping.
"""

import logging

from neuroglia.hosting.abstractions import ApplicationSettings

log = logging.getLogger(__name__)


class Settings(ApplicationSettings):
    """Configuration settings for the Scenario Engine Service.

    Inherits from Neuroglia ApplicationSettings for framework compatibility.
    Uses lowercase field names with case-insensitive env var mapping.
    """

    # ============================================================================
    # Core Application Configuration
    # ============================================================================
    app_name: str = "scenario-engine"
    app_version: str = "0.1.0"
    image_tag: str = "v0.1.0"
    environment: str = "production"
    debug: bool = False
    log_level: str = "INFO"

    # HTTP Server
    app_host: str = "0.0.0.0"  # nosec B104: container bind to all interfaces
    app_port: int = 8084

    # ============================================================================
    # MongoDB Configuration
    # ============================================================================
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "scenario_engine"
    connection_strings: dict[str, str] = {"mongo": "mongodb://root:pass@mongodb:27017/?authSource=admin"}

    # ============================================================================
    # BlobStorage / S3 Configuration
    # ============================================================================
    s3_endpoint: str = ""
    s3_bucket: str = "lcm-content"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    s3_secure: bool = False  # Set true for HTTPS S3 endpoints (AD-CSI-013).

    # ============================================================================
    # CloudEvents Sink (for job completion callbacks)
    # ============================================================================
    cloud_event_sink: str = ""

    # ============================================================================
    # Control Plane API
    # ============================================================================
    control_plane_api_url: str = "http://localhost:8020"
    control_plane_api_key: str | None = None

    # ============================================================================
    # Job Execution Configuration
    # ============================================================================
    max_concurrent_jobs: int = 10
    job_default_timeout: int = 600  # 10 minutes
    job_progress_interval: int = 5  # seconds between progress events


# Module-level settings instance for early access (logging config etc.)
app_settings = Settings()
