"""Integration clients for Lablet Cloud Manager services.

This module provides shared clients for external services:
- Control Plane API client
- etcd client for leader election and state management
"""

from lcm_core.integration.clients.control_plane_client import ControlPlaneApiClient
from lcm_core.integration.clients.etcd_client import EtcdClient, EtcdEvent

__all__ = [
    "ControlPlaneApiClient",
    "EtcdClient",
    "EtcdEvent",
]
