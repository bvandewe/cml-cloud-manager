"""Resource Requirements value object for LabletDefinition."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AmiRequirement:
    """AMI requirement specification for lab deployment.

    Specifies constraints on the AMI that can host this lablet.
    """

    cml_version_min: str | None = None  # Minimum CML version (e.g., "2.7.0")
    cml_version_max: str | None = None  # Maximum CML version (e.g., "2.9.0")
    node_definitions_required: tuple[str, ...] = ()  # Required node definitions

    def matches_version(self, version: str) -> bool:
        """Check if a CML version matches this requirement.

        Args:
            version: The CML version string to check (e.g., "2.8.1")

        Returns:
            True if the version is within the required range
        """
        if self.cml_version_min and version < self.cml_version_min:
            return False
        if self.cml_version_max and version > self.cml_version_max:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "cml_version_min": self.cml_version_min,
            "cml_version_max": self.cml_version_max,
            "node_definitions_required": list(self.node_definitions_required),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "AmiRequirement":
        """Create from dictionary."""
        return AmiRequirement(
            cml_version_min=data.get("cml_version_min"),
            cml_version_max=data.get("cml_version_max"),
            node_definitions_required=tuple(data.get("node_definitions_required", [])),
        )


@dataclass(frozen=True)
class ResourceRequirements:
    """Resource requirements specification for a LabletDefinition.

    Immutable value object that defines the compute resources needed
    to run a lablet on a CML worker.
    """

    cpu_cores: int  # Required CPU cores
    memory_gb: int  # Required memory in GB
    storage_gb: int  # Required storage in GB
    nested_virt: bool = True  # Whether nested virtualization is required
    ami_requirements: tuple[AmiRequirement, ...] = ()  # AMI constraints

    def __post_init__(self) -> None:
        """Validate resource requirements on creation."""
        if self.cpu_cores < 1:
            raise ValueError("cpu_cores must be at least 1")
        if self.memory_gb < 1:
            raise ValueError("memory_gb must be at least 1")
        if self.storage_gb < 1:
            raise ValueError("storage_gb must be at least 1")

    def fits_capacity(self, available_cpu: int, available_memory: int, available_storage: int) -> bool:
        """Check if these requirements fit within available capacity.

        Args:
            available_cpu: Available CPU cores
            available_memory: Available memory in GB
            available_storage: Available storage in GB

        Returns:
            True if requirements fit within available capacity
        """
        return self.cpu_cores <= available_cpu and self.memory_gb <= available_memory and self.storage_gb <= available_storage

    def with_node_definitions(self, node_definitions: tuple[str, ...]) -> "ResourceRequirements":
        """Create a copy with updated node_definitions_required.

        Updates the first AmiRequirement's node_definitions_required,
        or creates a new AmiRequirement if none exist.
        CPU/memory/storage/nested_virt are preserved unchanged.

        Used by content sync to update topology metadata from CML YAML
        without overwriting operator-configured resource limits.

        Args:
            node_definitions: Sorted tuple of unique node definition names.

        Returns:
            New ResourceRequirements instance with updated ami_requirements.
        """
        if self.ami_requirements:
            first = self.ami_requirements[0]
            updated_first = AmiRequirement(
                cml_version_min=first.cml_version_min,
                cml_version_max=first.cml_version_max,
                node_definitions_required=node_definitions,
            )
            new_ami_reqs = (updated_first, *self.ami_requirements[1:])
        else:
            new_ami_reqs = (AmiRequirement(node_definitions_required=node_definitions),)

        return ResourceRequirements(
            cpu_cores=self.cpu_cores,
            memory_gb=self.memory_gb,
            storage_gb=self.storage_gb,
            nested_virt=self.nested_virt,
            ami_requirements=new_ami_reqs,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "cpu_cores": self.cpu_cores,
            "memory_gb": self.memory_gb,
            "storage_gb": self.storage_gb,
            "nested_virt": self.nested_virt,
            "ami_requirements": [req.to_dict() for req in self.ami_requirements],
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ResourceRequirements":
        """Create from dictionary."""
        ami_reqs = [AmiRequirement.from_dict(req) for req in data.get("ami_requirements", [])]
        return ResourceRequirements(
            cpu_cores=data["cpu_cores"],
            memory_gb=data["memory_gb"],
            storage_gb=data["storage_gb"],
            nested_virt=data.get("nested_virt", True),
            ami_requirements=tuple(ami_reqs),
        )
