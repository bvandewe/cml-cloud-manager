"""Runtime environment type enum — shared across all services.

Represents the type of runtime environment hosting a lab.
Used by RuntimeBinding value object to enable polymorphic
runtime support (CML today, K8s/Pod/BareMetal in future).
"""

from lcm_core.domain.enums.case_insensitive_enum import CaseInsensitiveStrEnum


class RuntimeEnvironmentType(CaseInsensitiveStrEnum):
    """Types of runtime environments that can host a lab."""

    CML = "cml"  # Cisco Modeling Lab on EC2 (current default)
    POD = "pod"  # Pod-based lab environment
    K8S = "k8s"  # Kubernetes-based lab environment (Phase 14)
    BARE_METAL = "bare_metal"  # Bare-metal lab host
