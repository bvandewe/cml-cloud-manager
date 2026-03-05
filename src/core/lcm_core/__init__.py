"""LCM Core - Shared core package for Lablet Cloud Manager services.

This package provides shared domain models, enums, value objects,
and integration utilities used across all Lablet Cloud Manager services.

Usage:
    # Domain
    from lcm_core.domain.entities import CMLWorkerReadModel, LabletSessionReadModel
    from lcm_core.domain.enums import CMLWorkerStatus, LabletSessionStatus

    # Infrastructure
    from lcm_core.infrastructure import (
        configure_logging,
        ReconciliationHostedService,
        LeaderElectedHostedService,
        StandardEndpointsMixin,
        ServiceInfo,
    )

    # Integration
    from lcm_core.integration import ControlPlaneApiClient, EtcdClient
"""

__version__ = "0.1.0"

# Re-export commonly used classes
from lcm_core.domain.entities import (
    CMLWorkerReadModel,
    GradingSessionReadModel,
    LabletDefinitionReadModel,
    LabletSessionReadModel,
    ScoreReportReadModel,
    UserSessionReadModel,
    WorkerTemplateReadModel,
)
from lcm_core.infrastructure import (
    LeaderElectedHostedService,
    LeaderElectionConfig,
    ReconciliationConfig,
    ReconciliationHostedService,
    ReconciliationResult,
    ReconciliationStatus,
    ServiceInfo,
    StandardEndpointsMixin,
    configure_logging,
)
from lcm_core.integration import ControlPlaneApiClient, EtcdClient, EtcdEvent

__all__ = [
    "__version__",
    # Infrastructure - Logging
    "configure_logging",
    # Domain - Read Models
    "CMLWorkerReadModel",
    "GradingSessionReadModel",
    "LabletDefinitionReadModel",
    "LabletSessionReadModel",
    "ScoreReportReadModel",
    "UserSessionReadModel",
    "WorkerTemplateReadModel",
    # Infrastructure
    "ReconciliationHostedService",
    "ReconciliationConfig",
    "ReconciliationResult",
    "ReconciliationStatus",
    "LeaderElectedHostedService",
    "LeaderElectionConfig",
    "StandardEndpointsMixin",
    "ServiceInfo",
    # Integration
    "ControlPlaneApiClient",
    "EtcdClient",
    "EtcdEvent",
]
