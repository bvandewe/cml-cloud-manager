"""Pod type enum — infrastructure platform type for pod automation.

Defines the supported infrastructure platforms that a PodDefinition
can target. Used for:
- Content declaration (PAv1/manifest.yaml declares required pod_type)
- Worker capability matching (resource-scheduler validates compatibility)
- Adapter selection (ScenarioEngine dispatches to correct adapter)

ADR-044 §2.7: Dual adapter selection — definition declares + worker matches.
"""

from lcm_core.domain.enums.case_insensitive_enum import CaseInsensitiveStrEnum


class PodType(CaseInsensitiveStrEnum):
    """Infrastructure platform type for pod automation.

    Each value corresponds to a ScenarioEngine adapter implementation
    that knows how to interact with that specific infrastructure.
    """

    CML_ON_AWS = "cml_on_aws"  # Cisco Modeling Lab on AWS EC2 (m5zn.metal)
    ROC_RADKIT = "roc_radkit"  # Real-On-Cloud via Cisco RADkit (CCIE DMZ)
    PROXMOX = "proxmox"  # Proxmox VE hypervisor (future)
    VMWARE = "vmware"  # VMWare vSphere (future)
