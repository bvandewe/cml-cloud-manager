"""Binding role for lab-lablet relationships.

Defines the role a LabRecord plays within a LabletSession binding.
"""

from lcm_core.domain.enums.case_insensitive_enum import CaseInsensitiveStrEnum


class BindingRole(CaseInsensitiveStrEnum):
    """Role of a LabRecord within a LabletSession."""

    PRIMARY = "primary"  # Main lab topology
    SECONDARY = "secondary"  # Additional lab (multi-lab setup)
    AUXILIARY = "auxiliary"  # Support lab (e.g., management network)
