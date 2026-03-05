"""License-related enums — shared across all services.

Used for CML license registration status and license type affinity matching.
"""

from lcm_core.domain.enums.case_insensitive_enum import CaseInsensitiveStrEnum


class LicenseStatus(CaseInsensitiveStrEnum):
    """CML license registration status."""

    UNREGISTERED = "unregistered"
    REGISTERED = "registered"
    EVALUATION = "evaluation"
    EXPIRED = "expired"
    INVALID = "invalid"


class LicenseType(CaseInsensitiveStrEnum):
    """CML license types for LabletDefinition affinity matching.

    Used to specify which type of CML worker license is required
    or preferred for running a lablet.
    """

    PERSONAL = "personal"  # Personal license (limited nodes)
    ENTERPRISE = "enterprise"  # Enterprise license (unlimited nodes)
    EVALUATION = "evaluation"  # Evaluation/trial license
