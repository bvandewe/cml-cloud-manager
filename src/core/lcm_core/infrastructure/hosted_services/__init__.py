"""Hosted services for Lablet Cloud Manager.

This module provides reusable HostedService base classes for
resource-oriented services with reconciliation loop patterns.
"""

from lcm_core.infrastructure.hosted_services.leader_elected_hosted_service import (
    LeaderElectedHostedService,
    LeaderElectionConfig,
)
from lcm_core.infrastructure.hosted_services.reconciliation_hosted_service import (
    ReconciliationConfig,
    ReconciliationHostedService,
    ReconciliationResult,
    ReconciliationStatus,
)
from lcm_core.infrastructure.hosted_services.watch_triggered_hosted_service import (
    WatchConfig,
    WatchTriggeredHostedService,
)

__all__ = [
    # Reconciliation
    "ReconciliationConfig",
    "ReconciliationHostedService",
    "ReconciliationResult",
    "ReconciliationStatus",
    # Leader Election
    "LeaderElectedHostedService",
    "LeaderElectionConfig",
    # Watch-Triggered Reconciliation
    "WatchConfig",
    "WatchTriggeredHostedService",
]
