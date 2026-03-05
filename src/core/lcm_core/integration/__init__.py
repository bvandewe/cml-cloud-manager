"""Integration layer - shared integration utilities for Lablet Cloud Manager.

This module provides shared clients and utilities for:
- Control Plane API communication
- etcd key-value operations and leader election
- SSE subscription handling
"""

from lcm_core.integration.clients import (
    ControlPlaneApiClient,
    EtcdClient,
    EtcdEvent,
)

__all__ = [
    "ControlPlaneApiClient",
    "EtcdClient",
    "EtcdEvent",
]
