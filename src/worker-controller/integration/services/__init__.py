"""Worker Controller Integration Services.

SPI clients for external infrastructure:
- AWS EC2 (instance lifecycle)
- AWS CloudWatch (metrics)
- CML System API (system stats, health, license)
- CML WebSocket Monitor (real-time events, ADR-041)
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
from .cml_websocket_monitor import CmlWebSocketMonitor, ConnectionStatus
from .cml_websocket_registry import CmlWebSocketMonitorRegistry

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
    "CmlWebSocketMonitor",
    "CmlWebSocketMonitorRegistry",
    "ConnectionStatus",
]
