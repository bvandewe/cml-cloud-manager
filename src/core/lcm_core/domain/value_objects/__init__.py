"""Shared value objects for Lablet Cloud Manager.

Value objects are immutable objects that represent a descriptive aspect
of the domain with no conceptual identity.
"""

# Value objects will be added incrementally during migration
# from lcm_core.domain.value_objects.resource_requirements import ResourceRequirements
# from lcm_core.domain.value_objects.port_template import PortTemplate

# ADR-030: Resource & Port Observation — "Learn from Live"
from lcm_core.domain.value_objects.interface_observation import InterfaceObservation
from lcm_core.domain.value_objects.node_observation import NodeObservation
from lcm_core.domain.value_objects.resource_observation import ResourceObservation

__all__: list[str] = [
    "InterfaceObservation",
    "NodeObservation",
    "ResourceObservation",
]
