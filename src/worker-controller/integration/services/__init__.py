"""Worker Controller Integration Services.

SPI clients for external infrastructure:
- AWS EC2 (instance lifecycle)
- AWS CloudWatch (metrics)
- CML System API (system stats, health, license)
"""

from .aws_cloudwatch_spi import AwsCloudWatchSpiClient, Ec2Metrics
from .aws_ec2_spi import AwsEc2SpiClient, Ec2InstanceState
from .cml_system_spi import (
    CmlComputeHealth,
    CmlComputeNode,
    CmlControllerHealth,
    CmlLicenseInfo,
    CmlSystemHealth,
    CmlSystemInfo,
    CmlSystemSpiClient,
    CmlSystemStats,
)

__all__ = [
    "AwsEc2SpiClient",
    "Ec2InstanceState",
    "AwsCloudWatchSpiClient",
    "Ec2Metrics",
    "CmlSystemSpiClient",
    "CmlSystemInfo",
    "CmlSystemStats",
    "CmlSystemHealth",
    "CmlComputeNode",
    "CmlComputeHealth",
    "CmlControllerHealth",
    "CmlLicenseInfo",
]
