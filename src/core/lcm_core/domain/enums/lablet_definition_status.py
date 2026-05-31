"""Lablet definition status enum — shared across all services.

Represents the lifecycle status of a LabletDefinition (template).
"""

from lcm_core.domain.enums.case_insensitive_enum import CaseInsensitiveStrEnum


class LabletDefinitionStatus(CaseInsensitiveStrEnum):
    """Status of a LabletDefinition."""

    PENDING_SYNC = "pending_sync"  # Created but content not yet synchronized
    ACTIVE = "active"  # Definition is active and can be used
    INACTIVE = "inactive"  # Temporarily deactivated, not available for scheduling
    DEPRECATED = "deprecated"  # Definition is deprecated, no new instances
    ARCHIVED = "archived"  # Definition is archived, historical only
    DELETED = "deleted"  # Soft-deleted, excluded from all listings
