"""Shared value objects for Lablet Cloud Manager.

Value objects are immutable objects that represent a descriptive aspect
of the domain with no conceptual identity.
"""

# Value objects will be added incrementally during migration
# from lcm_core.domain.value_objects.resource_requirements import ResourceRequirements
# from lcm_core.domain.value_objects.port_template import PortTemplate

# ADR-030: Resource & Port Observation — "Learn from Live"
from lcm_core.domain.value_objects.interface_observation import InterfaceObservation

# ADR-036: Resource Management Abstraction Layer (Phase 2)
from lcm_core.domain.value_objects.managed_lifecycle import LifecyclePhase, ManagedLifecycle
from lcm_core.domain.value_objects.node_observation import NodeObservation

# ADR-044: ScenarioEngine — Pod Automation
from lcm_core.domain.value_objects.pod_definition_ref import PodDefinitionRef
from lcm_core.domain.value_objects.resource_observation import ResourceObservation
from lcm_core.domain.value_objects.state_transition import StateTransition
from lcm_core.domain.value_objects.timeslot import Timeslot

__all__: list[str] = [
    "InterfaceObservation",
    "LifecyclePhase",
    "ManagedLifecycle",
    "NodeObservation",
    "PodDefinitionRef",
    "ResourceObservation",
    "StateTransition",
    "Timeslot",
]
