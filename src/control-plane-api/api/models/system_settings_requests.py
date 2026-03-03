"""System Settings API request models."""

from typing import Any

from pydantic import BaseModel, Field


class UpdateSystemSettingsRequest(BaseModel):
    """Request model for updating system settings."""

    worker_provisioning: dict[str, Any] | None = None
    monitoring: dict[str, Any] | None = None
    idle_detection: dict[str, Any] | None = None
    discovery: dict[str, Any] | None = None


class DiscoverySettingsRequest(BaseModel):
    """Request model for updating discovery settings (ADR-012).

    Used by admin UI to configure worker discovery regions and patterns.
    """

    enabled: bool = Field(default=True, description="Enable/disable worker discovery")
    regions: list[str] = Field(default_factory=lambda: ["us-east-1"], description="AWS regions to scan for workers")
    ami_name_pattern: str = Field(default="cisco-cml2.9*", description="AMI name pattern to match (supports wildcards)")
    scan_interval_seconds: int = Field(default=300, ge=60, le=3600, description="Seconds between discovery scans")
