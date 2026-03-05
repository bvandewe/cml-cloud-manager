"""Mixins for Lablet Cloud Manager services.

Provides reusable mixins for common functionality.
"""

from lcm_core.infrastructure.mixins.standard_endpoints import (
    ServiceInfo,
    StandardEndpointsMixin,
)

__all__ = [
    "ServiceInfo",
    "StandardEndpointsMixin",
]
