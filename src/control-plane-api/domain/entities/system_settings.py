"""System Settings aggregate definition.

This aggregate holds dynamic configuration for the application, allowing
admins to modify behavior without redeploying.
"""

from dataclasses import dataclass, field
from datetime import datetime

from neuroglia.data.abstractions import AggregateRoot, AggregateState

from integration.enums import Ec2InstanceType


@dataclass
class WorkerProvisioningSettings:
    """Settings related to CML worker provisioning."""

    ami_name_default: str = "my-cml2.7.0-lablet-v0.1.0"
    ami_ids: dict[str, str] = field(
        default_factory=lambda: {
            "us-east-1": "ami-0123456789abcdef0",
            "us-west-2": "ami-0123456789abcdef0",
        }
    )
    ami_names: dict[str, str] = field(
        default_factory=lambda: {
            "us-east-1": "CML-2.7.0-Ubuntu-22.04",
            "us-west-2": "CML-2.7.0-Ubuntu-22.04",
        }
    )
    instance_type: str = Ec2InstanceType.SMALL.value
    security_group_ids: list[str] = field(default_factory=lambda: ["sg-0123456789abcdef0"])
    subnet_id: str | None = None


@dataclass
class MonitoringSettings:
    """Settings related to monitoring."""

    worker_metrics_poll_interval_seconds: int = 300


@dataclass
class IdleDetectionSettings:
    """Settings related to idle detection."""

    enabled: bool = True
    timeout_minutes: int = 60


@dataclass
class DiscoverySettings:
    """Settings related to worker discovery (ADR-012).

    These settings control how worker-controller discovers EC2 instances
    matching CML worker AMI patterns. Can be configured at runtime via
    the admin UI.
    """

    enabled: bool = True
    regions: list[str] = field(default_factory=lambda: ["us-east-1"])
    ami_name_pattern: str = "cisco-cml2.9*"
    scan_interval_seconds: int = 300


class SystemSettingsState(AggregateState[str]):
    """Encapsulates the persisted state for the SystemSettings aggregate."""

    id: str
    worker_provisioning: WorkerProvisioningSettings
    monitoring: MonitoringSettings
    idle_detection: IdleDetectionSettings
    discovery: DiscoverySettings
    updated_at: datetime
    updated_by: str | None

    def __init__(self) -> None:
        super().__init__()
        self.id = "default"
        self.worker_provisioning = WorkerProvisioningSettings()
        self.monitoring = MonitoringSettings()
        self.idle_detection = IdleDetectionSettings()
        self.discovery = DiscoverySettings()
        self.updated_at = datetime.now()
        self.updated_by = "system"


class SystemSettings(AggregateRoot[SystemSettingsState, str]):
    """The SystemSettings aggregate root."""

    def __init__(self) -> None:
        super().__init__()

    @classmethod
    def create_default(cls) -> "SystemSettings":
        """Create a default SystemSettings instance."""
        return cls()

    def update(
        self,
        worker_provisioning: WorkerProvisioningSettings | None = None,
        monitoring: MonitoringSettings | None = None,
        idle_detection: IdleDetectionSettings | None = None,
        discovery: DiscoverySettings | None = None,
        updated_by: str | None = None,
    ) -> None:
        """Update the system settings."""
        if worker_provisioning:
            self.state.worker_provisioning = worker_provisioning
        if monitoring:
            self.state.monitoring = monitoring
        if idle_detection:
            self.state.idle_detection = idle_detection
        if discovery:
            self.state.discovery = discovery

        self.state.updated_at = datetime.now()
        self.state.updated_by = updated_by

        # In a real event-sourced system, we would emit an event here.
        # For simplicity in this task, we are just updating the state.
        # self.record_event(SystemSettingsUpdatedDomainEvent(...))
