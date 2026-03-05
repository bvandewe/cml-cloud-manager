"""Lablet Controller Integration Services.

SPI clients for external infrastructure:
- CML Labs API (lab lifecycle)
- LDS Reservations API (session provisioning)
- S3/RustFS (content package storage)
- Environment Resolver (FQN-to-URL resolution)
- Mosaic (content authoring downloads)
- OAuth2 Token Manager (client credentials cache)
"""

from .cml_labs_spi import CmlLabsSpiClient, InterfaceInfo, LabInfo, LabState, LabTopology, NodeInfo
from .environment_resolver_client import EnvironmentResolverClient, ResolvedEnvironment
from .lds_spi import (
    DeviceAccessInfo,
    LdsDeploymentConfig,
    LdsDeploymentNotFoundError,
    LdsSessionInfo,
    LdsSessionNotFoundError,
    LdsSpiClient,
    LdsSpiError,
    SessionPartInfo,
    load_lds_deployment_configs,
)
from .mosaic_client import MosaicClient, PublishRecord
from .oauth2_token_manager import OAuth2TokenManager, TokenConfig
from .s3_client import S3Client

__all__ = [
    # CML Labs SPI
    "CmlLabsSpiClient",
    "LabInfo",
    "LabState",
    "NodeInfo",
    "InterfaceInfo",
    "LabTopology",
    # LDS SPI
    "LdsSpiClient",
    "LdsSessionInfo",
    "SessionPartInfo",
    "DeviceAccessInfo",
    "LdsDeploymentConfig",
    "LdsSpiError",
    "LdsSessionNotFoundError",
    "LdsDeploymentNotFoundError",
    "load_lds_deployment_configs",
    # S3/RustFS
    "S3Client",
    # Environment Resolver
    "EnvironmentResolverClient",
    "ResolvedEnvironment",
    # Mosaic
    "MosaicClient",
    "PublishRecord",
    # OAuth2
    "OAuth2TokenManager",
    "TokenConfig",
]
