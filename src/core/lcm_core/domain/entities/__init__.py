"""Read-only entity models for Lablet Cloud Manager.

These are immutable data transfer objects used by controllers and schedulers.
They represent the current state of entities as returned by the Control Plane API.

Important: These are NOT aggregates. Full aggregates with event sourcing
are owned by control-plane-api. Controllers use these read models for
decision making and request state changes via the Control Plane API.
"""

from lcm_core.domain.entities.read_models import (
    CMLWorkerReadModel,
    GradingSessionReadModel,
    LabletDefinitionReadModel,
    LabletSessionReadModel,
    ScoreReportReadModel,
    ScoreSectionReadModel,
    UserSessionReadModel,
    WorkerTemplateReadModel,
)

__all__ = [
    "CMLWorkerReadModel",
    "GradingSessionReadModel",
    "LabletDefinitionReadModel",
    "LabletSessionReadModel",
    "ScoreReportReadModel",
    "ScoreSectionReadModel",
    "UserSessionReadModel",
    "WorkerTemplateReadModel",
]
