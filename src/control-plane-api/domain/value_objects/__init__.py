"""Domain value objects package."""

from .cml_license import CMLLicense
from .external_interface import ExternalInterface
from .grading_score import GradingCheckResult, GradingScore
from .lab_revision import LabRevision
from .lab_run_record import LabRunRecord
from .lab_topology_spec import LabTopologySpec, TopologyAnnotation, TopologyLink, TopologyNode
from .port_allocation import PortAllocation
from .port_template import PortDefinition, PortTemplate
from .resource_requirements import AmiRequirement, ResourceRequirements
from .runtime_binding import RuntimeBinding
from .state_transition import StateTransition
from .worker_capacity import WorkerCapacity

__all__ = [
    "AmiRequirement",
    "CMLLicense",
    "ExternalInterface",
    "GradingCheckResult",
    "GradingScore",
    "LabRevision",
    "LabRunRecord",
    "LabTopologySpec",
    "PortAllocation",
    "PortDefinition",
    "PortTemplate",
    "ResourceRequirements",
    "RuntimeBinding",
    "StateTransition",
    "TopologyAnnotation",
    "TopologyLink",
    "TopologyNode",
    "WorkerCapacity",
]
