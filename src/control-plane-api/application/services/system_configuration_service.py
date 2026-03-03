"""Service for retrieving effective system configuration."""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from application.settings import Settings
from domain.repositories.system_settings_repository import SystemSettingsRepository

if TYPE_CHECKING:
    from neuroglia.hosting.web import WebApplicationBuilder

log = logging.getLogger(__name__)


@dataclass
class EffectiveWorkerProvisioningSettings:
    """Effective settings for worker provisioning."""

    ami_name_default: str
    instance_type: str
    security_group_ids: list[str]
    subnet_id: str | None


@dataclass
class EffectiveIdleDetectionSettings:
    """Effective settings for idle detection."""

    enabled: bool
    timeout_minutes: int
    check_interval_seconds: int


@dataclass
class EffectiveMonitoringSettings:
    """Effective settings for monitoring."""

    poll_interval_seconds: int


class SystemConfigurationService:
    """Service that provides effective configuration by merging dynamic and static settings.

    Prioritizes dynamic settings from the database (SystemSettings aggregate).
    Falls back to static application settings (env vars/defaults) if dynamic settings
    are missing or not set.
    """

    def __init__(self, settings_repository: SystemSettingsRepository, static_settings: Settings):
        self._repository = settings_repository
        self._static_settings = static_settings

    @classmethod
    def configure(cls, builder: "WebApplicationBuilder") -> None:
        """Configure the SystemConfigurationService in the dependency injection container."""
        builder.services.add_singleton(cls)

    async def get_worker_provisioning_settings_async(self) -> EffectiveWorkerProvisioningSettings:
        """Get effective worker provisioning settings."""
        dynamic = await self._get_dynamic_settings()

        # Defaults from static settings
        ami_name = self._static_settings.cml_worker_ami_name_default
        instance_type = self._static_settings.cml_worker_instance_type.value
        security_groups = self._static_settings.cml_worker_security_group_ids
        subnet_id = self._static_settings.cml_worker_subnet_id

        # Override with dynamic if available
        if dynamic and dynamic.state.worker_provisioning:
            prov = dynamic.state.worker_provisioning
            if prov.ami_name_default:
                ami_name = prov.ami_name_default
            if prov.instance_type:
                instance_type = prov.instance_type
            if prov.security_group_ids:
                security_groups = prov.security_group_ids
            if prov.subnet_id:
                subnet_id = prov.subnet_id

        return EffectiveWorkerProvisioningSettings(
            ami_name_default=ami_name,
            instance_type=instance_type,
            security_group_ids=security_groups,
            subnet_id=subnet_id,
        )

    async def get_idle_detection_settings_async(self) -> EffectiveIdleDetectionSettings:
        """Get effective idle detection settings."""
        dynamic = await self._get_dynamic_settings()

        # Defaults
        enabled = self._static_settings.worker_auto_pause_enabled
        timeout = self._static_settings.worker_idle_timeout_minutes

        # Override
        if dynamic and dynamic.state.idle_detection:
            idle = dynamic.state.idle_detection
            enabled = idle.enabled
            if idle.timeout_minutes is not None:
                timeout = idle.timeout_minutes

        return EffectiveIdleDetectionSettings(enabled=enabled, timeout_minutes=timeout, check_interval_seconds=self._static_settings.worker_metrics_poll_interval)

    async def get_monitoring_settings_async(self) -> EffectiveMonitoringSettings:
        """Get effective monitoring settings."""
        dynamic = await self._get_dynamic_settings()

        # Defaults
        interval = self._static_settings.worker_metrics_poll_interval

        # Override
        if dynamic and dynamic.state.monitoring:
            mon = dynamic.state.monitoring
            if mon.worker_metrics_poll_interval_seconds:
                interval = mon.worker_metrics_poll_interval_seconds

        return EffectiveMonitoringSettings(poll_interval_seconds=interval)

    async def _get_dynamic_settings(self):
        """Helper to fetch the singleton settings aggregate."""
        try:
            # We use a constant ID for the singleton settings
            return await self._repository.get_default_async()
        except Exception as e:
            log.warning(f"Failed to fetch dynamic settings: {e}. Using defaults.")
            return None
