"""Read model for WorkerTemplate entities."""

from dataclasses import dataclass
from typing import Any


@dataclass
class WorkerTemplateReadModel:
    """Read model for a WorkerTemplate from the Control Plane API.

    Defines EC2 instance configuration for worker provisioning.
    """

    id: str
    name: str
    instance_type: str
    ami_id: str | None = None
    aws_region: str | None = None
    security_group_id: str | None = None
    subnet_id: str | None = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkerTemplateReadModel":
        """Create from API response dictionary."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            instance_type=data.get("instance_type", "m5zn.metal"),
            ami_id=data.get("ami_id"),
            aws_region=data.get("aws_region"),
            security_group_id=data.get("security_group_id"),
            subnet_id=data.get("subnet_id"),
            metadata=data.get("metadata"),
        )
