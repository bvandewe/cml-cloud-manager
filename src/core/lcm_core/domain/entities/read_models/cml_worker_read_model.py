"""Read model for CMLWorker entities."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CMLLicenseReadModel:
    """Read model for CML license state.

    ADR-016: Includes pending fields for license reconciliation.
    """

    status: str = "unregistered"
    token: str | None = None
    pending_token: str | None = None  # ADR-016: Token to register
    pending_operation: str | None = None  # ADR-016: "register" | "deregister" | None
    operation_in_progress: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CMLLicenseReadModel":
        """Create from API response dictionary."""
        if not data:
            return cls()
        return cls(
            status=data.get("status", "unregistered"),
            token=data.get("token"),
            pending_token=data.get("pending_token"),
            pending_operation=data.get("pending_operation"),
            operation_in_progress=data.get("operation_in_progress", False),
        )


@dataclass
class CMLWorkerReadModel:
    """Read model for a CMLWorker from the Control Plane API.

    Used by worker-controller for:
    - EC2 instance lifecycle management
    - Metrics collection (CloudWatch + CML System API)
    - Capacity tracking
    - Activity detection and auto-pause
    - License reconciliation (ADR-016)
    """

    id: str
    name: str
    status: str
    desired_status: str
    ec2_instance_id: str | None = None
    ip_address: str | None = None
    template_id: str | None = None
    template_name: str | None = None
    instance_type: str | None = None
    ami_name: str | None = None
    aws_region: str | None = None
    cml_username: str | None = None
    cml_password: str | None = None
    metadata: dict[str, Any] | None = None

    # Activity detection settings
    is_idle_detection_enabled: bool = True

    # On-demand refresh
    refresh_requested_at: str | None = None

    # Port allocation tracking (ADR-031 / AD-PORT-001)
    # These are populated by CPA from PortAllocationService (etcd) state.
    # Used by resource-scheduler for placement decisions and by the
    # frontend to show port utilization on the worker detail panel.
    allocated_port_count: int = 0  # Number of ports currently allocated on this worker
    available_port_count: int = 0  # Number of ports available for allocation
    port_utilization_pct: float = 0.0  # Percentage of port range in use (0.0–100.0)

    # License state (ADR-016)
    license: CMLLicenseReadModel = field(default_factory=CMLLicenseReadModel)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CMLWorkerReadModel":
        """Create from API response dictionary."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            status=data.get("status", ""),
            desired_status=data.get("desired_status", "running"),
            ec2_instance_id=data.get("ec2_instance_id") or data.get("aws_instance_id"),
            ip_address=data.get("ip_address") or data.get("public_ip") or data.get("private_ip"),
            template_id=data.get("template_id"),
            template_name=data.get("template_name"),
            instance_type=data.get("instance_type"),
            ami_name=data.get("ami_name"),
            aws_region=data.get("aws_region"),
            cml_username=data.get("cml_username"),
            cml_password=data.get("cml_password"),
            metadata=data.get("metadata"),
            is_idle_detection_enabled=data.get("is_idle_detection_enabled", True),
            refresh_requested_at=data.get("refresh_requested_at"),
            allocated_port_count=data.get("allocated_port_count", 0),
            available_port_count=data.get("available_port_count", 0),
            port_utilization_pct=data.get("port_utilization_pct", 0.0),
            license=CMLLicenseReadModel.from_dict(data.get("license")),
        )
