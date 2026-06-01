"""SystemSettings EntitySeeder implementation.

Seeds SystemSettings aggregate from YAML files in data/seeds/system_settings/.
"""

import logging
from typing import Any

from lcm_core.infrastructure.seeding import EntitySeeder
from neuroglia.data.infrastructure.abstractions import Repository

from domain.entities.system_settings import (
    DiscoverySettings,
    IdleDetectionSettings,
    MonitoringSettings,
    SystemSettings,
    WorkerProvisioningSettings,
)

logger = logging.getLogger(__name__)


class SystemSettingsSeeder(EntitySeeder[SystemSettings]):
    """Seeds SystemSettings aggregate from YAML configuration.

    Only one SystemSettings record should exist (id="default").
    This seeder ensures default configuration is present on startup.

    YAML Schema:
        id: default
        name: Default System Settings
        description: Default configuration for Lablet Cloud Manager

        worker_provisioning:
          ami_name_default: my-cml2.7.0-lablet-v0.1.0
          instance_type: small
          ...

        monitoring:
          worker_metrics_poll_interval_seconds: 300

        idle_detection:
          enabled: true
          timeout_minutes: 60

        discovery:
          enabled: true
          regions:
            - us-east-1
          ami_name_pattern: cisco-cml2.9*
          scan_interval_seconds: 300
    """

    @property
    def entity_type(self) -> str:
        return "system_settings"

    @property
    def folder_name(self) -> str:
        return "system_settings"

    @property
    def seeding_order(self) -> int:
        # Settings should be seeded very early
        return 5

    def get_repository(self, scoped_provider: Any) -> Repository[SystemSettings, str]:
        """Get the SystemSettings repository."""
        return scoped_provider.get_required_service(Repository[SystemSettings, str])

    def get_entity_id(self, data: dict[str, Any]) -> str | None:
        """Extract settings ID from YAML data.

        Uses 'id' field, defaults to 'default'.
        """
        return data.get("id", "default")

    def create_entity(self, data: dict[str, Any]) -> SystemSettings:
        """Create a SystemSettings aggregate from YAML data."""
        settings = SystemSettings.create_default()

        # Update worker provisioning settings if present
        wp_data = data.get("worker_provisioning", {})
        if wp_data:
            settings.state.worker_provisioning = WorkerProvisioningSettings(
                ami_name_default=wp_data.get("ami_name_default", "my-cml2.7.0-lablet-v0.1.0"),
                ami_ids=wp_data.get("ami_ids", {}),
                ami_names=wp_data.get("ami_names", {}),
                instance_type=wp_data.get("instance_type", "small"),
                security_group_ids=wp_data.get("security_group_ids", []),
                subnet_id=wp_data.get("subnet_id"),
            )

        # Update monitoring settings if present
        mon_data = data.get("monitoring", {})
        if mon_data:
            settings.state.monitoring = MonitoringSettings(
                worker_metrics_poll_interval_seconds=mon_data.get("worker_metrics_poll_interval_seconds", 300),
            )

        # Update idle detection settings if present
        idle_data = data.get("idle_detection", {})
        if idle_data:
            settings.state.idle_detection = IdleDetectionSettings(
                enabled=idle_data.get("enabled", True),
                timeout_minutes=idle_data.get("timeout_minutes", 60),
            )

        # Update discovery settings if present (ADR-012)
        discovery_data = data.get("discovery", {})
        if discovery_data:
            settings.state.discovery = DiscoverySettings(
                enabled=discovery_data.get("enabled", True),
                regions=discovery_data.get("regions", ["us-east-1"]),
                ami_name_pattern=discovery_data.get("ami_name_pattern", "cisco-cml2.9*"),
                scan_interval_seconds=discovery_data.get("scan_interval_seconds", 300),
            )

        # Set ID
        settings.state.id = self.get_entity_id(data)

        return settings
