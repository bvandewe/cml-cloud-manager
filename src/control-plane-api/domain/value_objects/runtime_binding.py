"""RuntimeBinding value object for LabRecord aggregate.

Represents the binding of a LabRecord to a specific runtime environment.
Abstracts the runtime type (CML/K8s/Pod/BareMetal) so the LabRecord
aggregate doesn't need to know implementation details.

Architecture ref: §4.1 Value Objects.
"""

from dataclasses import dataclass, field
from typing import Any

from lcm_core.domain.enums import RuntimeEnvironmentType


@dataclass(frozen=True)
class RuntimeBinding:
    """Binding of a lab to a runtime environment.

    Attributes:
        runtime_type: Type of runtime (CML, K8S, POD, BARE_METAL).
        worker_id: The LCM worker aggregate ID hosting this lab.
        runtime_lab_id: The lab identifier within the runtime (e.g., CML lab UUID).
        endpoint: Base URL to reach the runtime API (e.g., https://<worker-ip>).
        extra: Runtime-specific metadata (e.g., CML credentials, K8s namespace).
    """

    runtime_type: RuntimeEnvironmentType
    worker_id: str
    runtime_lab_id: str
    endpoint: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.worker_id:
            raise ValueError("worker_id cannot be empty")
        if not self.runtime_lab_id:
            raise ValueError("runtime_lab_id cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "runtime_type": self.runtime_type.value,
            "worker_id": self.worker_id,
            "runtime_lab_id": self.runtime_lab_id,
            "endpoint": self.endpoint,
            "extra": dict(self.extra),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "RuntimeBinding":
        """Create from dictionary."""
        return RuntimeBinding(
            runtime_type=RuntimeEnvironmentType(data["runtime_type"]),
            worker_id=data["worker_id"],
            runtime_lab_id=data["runtime_lab_id"],
            endpoint=data.get("endpoint"),
            extra=dict(data.get("extra", {})),
        )

    @staticmethod
    def for_cml(worker_id: str, lab_id: str, endpoint: str | None = None) -> "RuntimeBinding":
        """Factory for CML runtime binding."""
        return RuntimeBinding(
            runtime_type=RuntimeEnvironmentType.CML,
            worker_id=worker_id,
            runtime_lab_id=lab_id,
            endpoint=endpoint,
        )

    def __str__(self) -> str:
        return f"RuntimeBinding({self.runtime_type.value}: worker={self.worker_id}, lab={self.runtime_lab_id})"
