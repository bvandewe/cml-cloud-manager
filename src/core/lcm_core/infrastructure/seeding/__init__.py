"""Database seeding infrastructure for Lablet Cloud Manager.

This module provides reusable infrastructure for seeding aggregates
from YAML files at application startup.

Components:
- DatabaseSeeder: Generic seeder that loads YAML files and creates aggregates
- DatabaseSeederService: HostedService for automatic seeding on startup
- SeedResult/SeedSummary: Result tracking for seeding operations
- EntitySeeder: Protocol for entity-specific seeding logic
"""

from lcm_core.infrastructure.seeding.database_seeder import (
    DatabaseSeeder,
    DatabaseSeederService,
    EntitySeeder,
    SeedResult,
    SeedSummary,
)

__all__ = [
    "DatabaseSeeder",
    "DatabaseSeederService",
    "EntitySeeder",
    "SeedResult",
    "SeedSummary",
]
