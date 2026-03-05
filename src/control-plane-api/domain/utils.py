"""Domain utility functions for Control Plane API.

Re-exports shared utilities from lcm-core for local convenience.
All CPA domain code should import utilities from this module:
    from domain.utils import slugify_fqn
"""

from lcm_core.domain.utils import slugify_fqn  # noqa: F401

__all__ = ["slugify_fqn"]
