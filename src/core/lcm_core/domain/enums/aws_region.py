"""AWS region enum — shared across all services.

Defines the AWS regions where CML workers can be deployed.
"""

from lcm_core.domain.enums.case_insensitive_enum import CaseInsensitiveStrEnum


class AwsRegion(CaseInsensitiveStrEnum):
    """AWS regions for CML worker deployment."""

    US_EAST_1 = "us-east-1"  # Virginia
    US_WEST_2 = "us-west-2"  # Oregon
