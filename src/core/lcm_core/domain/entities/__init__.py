"""Entity models for Lablet Cloud Manager.

Read-only models: Immutable DTOs used by controllers and schedulers.
Base state classes: Abstract aggregate states for the resource hierarchy (ADR-036).

Important: Read models are NOT aggregates. Full aggregates with event sourcing
are owned by control-plane-api. Controllers use read models for decision making
and request state changes via the Control Plane API.
"""

# ADR-036: Resource Management Abstraction Layer — base state classes
# Read models — immutable DTOs from Control Plane API responses
from lcm_core.domain.entities.read_models import (
    CMLWorkerReadModel,
    GradingSessionReadModel,
    LabletDefinitionReadModel,
    LabletSessionReadModel,
    ScoreReportReadModel,
    ScoreSectionReadModel,
    TimedResourceReadModel,
    UserSessionReadModel,
    WorkerTemplateReadModel,
)
from lcm_core.domain.entities.resource import ResourceState
from lcm_core.domain.entities.timed_resource import TimedResourceState

__all__ = [
    # Base state classes (ADR-036)
    "ResourceState",
    "TimedResourceState",
    # Read models
    "CMLWorkerReadModel",
    "GradingSessionReadModel",
    "LabletDefinitionReadModel",
    "LabletSessionReadModel",
    "ScoreReportReadModel",
    "ScoreSectionReadModel",
    "TimedResourceReadModel",
    "UserSessionReadModel",
    "WorkerTemplateReadModel",
]
