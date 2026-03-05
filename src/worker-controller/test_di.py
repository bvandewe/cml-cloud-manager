#!/usr/bin/env python3
"""Test script to debug HostedService registration."""

import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/core")

from neuroglia.dependency_injection import ServiceCollection, ServiceProvider
from neuroglia.hosting.abstractions import HostedService

# Create a minimal simulation
services = ServiceCollection()


class FakeReconciler:
    pass


class FakeDiscovery:
    pass


# Register like main.py
services.add_singleton(FakeReconciler, implementation_factory=lambda sp: FakeReconciler())
services.add_singleton(HostedService, implementation_factory=lambda sp: sp.get_required_service(FakeReconciler))

services.add_singleton(FakeDiscovery, implementation_factory=lambda sp: FakeDiscovery())
services.add_singleton(HostedService, implementation_factory=lambda sp: sp.get_required_service(FakeDiscovery))

print(f"Registered {sum(1 for d in services if d.service_type == HostedService)} HostedService descriptors")

# Build provider
provider = ServiceProvider(services)

# Get all HostedServices
hosted_services = provider.get_services(HostedService)
print(f"Resolved {len(hosted_services)} HostedService(s):")
for i, hs in enumerate(hosted_services):
    print(f"  {i}: {type(hs).__name__} - {id(hs)}")
