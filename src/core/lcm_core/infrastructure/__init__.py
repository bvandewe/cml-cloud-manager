"""Infrastructure layer - shared infrastructure utilities for Lablet Cloud Manager.

This module provides shared infrastructure components:
- configure_logging: Centralized logging configuration for all services
- ReconciliationHostedService: Base for resource-oriented controllers
- LeaderElectedHostedService: Reconciliation with leader election
- StandardEndpointsMixin: /health, /ready, /metrics, /info endpoints
- DatabaseSeeder: YAML-based aggregate seeding infrastructure
"""

from lcm_core.infrastructure.hosted_services import (
    LeaderElectedHostedService,
    LeaderElectionConfig,
    ReconciliationConfig,
    ReconciliationHostedService,
    ReconciliationResult,
    ReconciliationStatus,
)
from lcm_core.infrastructure.logging import configure_logging
from lcm_core.infrastructure.mixins import ServiceInfo, StandardEndpointsMixin
from lcm_core.infrastructure.seeding import (
    DatabaseSeeder,
    DatabaseSeederService,
    EntitySeeder,
    SeedResult,
    SeedSummary,
)

__all__ = [
    # Logging
    "configure_logging",
    # Hosted Services
    "ReconciliationHostedService",
    "ReconciliationConfig",
    "ReconciliationResult",
    "ReconciliationStatus",
    "LeaderElectedHostedService",
    "LeaderElectionConfig",
    # Mixins
    "StandardEndpointsMixin",
    "ServiceInfo",
    # Seeding
    "DatabaseSeeder",
    "DatabaseSeederService",
    "EntitySeeder",
    "SeedResult",
    "SeedSummary",
]
