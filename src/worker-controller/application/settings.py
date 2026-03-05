"""Worker Controller Service Settings.

Configuration for the Worker Controller service using Neuroglia ApplicationSettings.
Supports environment variable configuration with case-insensitive mapping.

Includes:
- Scaling constraints (max/min workers, cooldowns, timeouts)
- Per-region AWS infrastructure config loaded from YAML (ADR-018)
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from neuroglia.hosting.abstractions import ApplicationSettings
from pydantic_settings import SettingsConfigDict

log = logging.getLogger(__name__)


# ============================================================================
# Per-Region AWS Infrastructure Config (ADR-018)
# ============================================================================


@dataclass
class AwsRegionConfig:
    """Infrastructure configuration for a single AWS region.

    Loaded from config/aws_regions.yaml at startup.
    Used during EC2 provisioning to resolve VPC networking per region.
    """

    region: str
    security_group_ids: list[str] = field(default_factory=list)
    subnet_id: str = ""
    key_name: str | None = None
    default_tags: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, region: str, data: dict[str, Any]) -> "AwsRegionConfig":
        """Create from YAML dictionary."""
        return cls(
            region=region,
            security_group_ids=data.get("security_group_ids", []),
            subnet_id=data.get("subnet_id", ""),
            key_name=data.get("key_name"),
            default_tags=data.get("default_tags", {}),
        )


def load_aws_region_configs(config_path: str | None = None) -> dict[str, AwsRegionConfig]:
    """Load per-region AWS infrastructure configs from YAML file.

    ADR-018: Infrastructure config comes from YAML files per region,
    following the same pattern as control-plane-api's worker_templates.yaml.

    Args:
        config_path: Path to aws_regions.yaml. Defaults to ./config/aws_regions.yaml

    Returns:
        Dictionary mapping region name to AwsRegionConfig.
    """
    if not config_path:
        # Try standard locations
        candidates = [
            Path("config/aws_regions.yaml"),
            Path("/app/config/aws_regions.yaml"),
        ]
        for candidate in candidates:
            if candidate.exists():
                config_path = str(candidate)
                break

    if not config_path:
        log.warning("No aws_regions.yaml found. Per-region config will be empty.")
        return {}

    path = Path(config_path)
    if not path.exists():
        log.warning(f"AWS regions config not found at {config_path}. Per-region config will be empty.")
        return {}

    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        log.error(f"Failed to parse aws_regions.yaml: {e}")
        return {}

    if not data or "regions" not in data:
        log.warning("No 'regions' key found in aws_regions.yaml")
        return {}

    configs: dict[str, AwsRegionConfig] = {}
    for region_name, region_data in data["regions"].items():
        configs[region_name] = AwsRegionConfig.from_dict(region_name, region_data)
        log.info(f"Loaded AWS region config: {region_name} (subnet={configs[region_name].subnet_id})")

    return configs


class Settings(ApplicationSettings):
    """Configuration settings for the Worker Controller Service.

    Inherits from Neuroglia ApplicationSettings for framework compatibility.
    Uses lowercase field names with case-insensitive env var mapping.
    """

    # ============================================================================
    # Core Application Configuration
    # ============================================================================
    app_name: str = "worker-controller"
    app_version: str = "1.0.0"
    image_tag: str = "v0.1.0"
    environment: str = "production"
    debug: bool = False
    log_level: str = "INFO"

    # HTTP Server
    app_host: str = "0.0.0.0"
    app_port: int = 8083

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
    leader_key: str = "/lcm/worker-controller/leader"

    # ============================================================================
    # Reconciliation & Observation
    # ============================================================================
    reconcile_interval: int = 30
    reconcile_polling_enabled: bool = True  # Set False for watch-only mode (ADR-015)
    metrics_poll_interval: int = 60
    labs_sync_interval: int = 300  # 5 minutes
    idle_check_interval: int = 60
    idle_threshold_minutes: int = 30

    # ============================================================================
    # CML Worker API Credentials
    # ============================================================================
    cml_worker_api_username: str = "admin"
    cml_worker_api_password: str = ""

    # ============================================================================
    # AWS Configuration
    # ============================================================================
    aws_region: str = "us-east-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_regions_config_path: str | None = None  # Path to aws_regions.yaml (auto-discovered if None)

    # ============================================================================
    # Scaling Constraints (Phase 3 - Auto-Scaling)
    # ============================================================================
    scale_down_enabled: bool = False  # Enable automatic scale-down (drain idle workers)
    max_workers_per_region: int = 10  # Maximum concurrent workers per AWS region
    min_workers: int = 0  # Minimum workers to keep running (0 = scale to zero allowed)
    scale_up_cooldown_seconds: int = 300  # Cooldown between scale-up operations (5 min)
    scale_down_cooldown_seconds: int = 600  # Cooldown between scale-down operations (10 min)
    provisioning_timeout_seconds: int = 900  # Max time for PENDING→RUNNING transition (15 min)
    drain_timeout_seconds: int = 600  # Max time for DRAINING→STOPPED transition (10 min)

    # ============================================================================
    # Worker Discovery (auto-import)
    # ============================================================================
    worker_discovery_enabled: bool = True
    worker_discovery_interval: int = 300  # 5 minutes
    worker_discovery_ami_name: str | None = None  # e.g., "cisco-cml2.9*"
    worker_discovery_regions: str = ""  # Comma-separated, defaults to aws_region

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
    service_name: str = "worker-controller"
    otel_service_name: str = "worker-controller"
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
        # Load per-region AWS infrastructure configs from YAML (ADR-018)
        self._aws_region_configs: dict[str, AwsRegionConfig] = load_aws_region_configs(self.aws_regions_config_path)

    @property
    def aws_region_configs(self) -> dict[str, AwsRegionConfig]:
        """Get per-region AWS infrastructure configs.

        Returns:
            Dictionary mapping region name to AwsRegionConfig.
        """
        return self._aws_region_configs

    def get_region_config(self, region: str) -> AwsRegionConfig | None:
        """Get infrastructure config for a specific AWS region.

        Args:
            region: AWS region name (e.g., "us-east-1").

        Returns:
            AwsRegionConfig or None if region not configured.
        """
        return self._aws_region_configs.get(region)

    @property
    def etcd_endpoints(self) -> list[str]:
        """Get etcd endpoints list.

        Supports both single host:port and comma-separated list.
        """
        endpoints_str = os.getenv("ETCD_ENDPOINTS")
        if endpoints_str:
            return [ep.strip() for ep in endpoints_str.split(",")]
        return [f"{self.etcd_host}:{self.etcd_port}"]

    @property
    def discovery_regions(self) -> list[str]:
        """Get worker discovery regions list.

        Returns regions to scan for EC2 instances. Defaults to aws_region if not specified.
        """
        if self.worker_discovery_regions:
            return [r.strip() for r in self.worker_discovery_regions.split(",") if r.strip()]
        return [self.aws_region]


# Instantiate application settings
app_settings = Settings()
