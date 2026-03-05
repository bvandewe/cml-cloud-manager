"""CML service status enum — shared across all services.

Represents the HTTPS service availability of a CML instance.
"""

from lcm_core.domain.enums.case_insensitive_enum import CaseInsensitiveStrEnum


class CMLServiceStatus(CaseInsensitiveStrEnum):
    """CML HTTPS service availability status."""

    UNAVAILABLE = "unavailable"  # Service not accessible
    STARTING = "starting"  # Service is starting up
    AVAILABLE = "available"  # Service is accessible via HTTPS
    ERROR = "error"  # Service encountered an error
