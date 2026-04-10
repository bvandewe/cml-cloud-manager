"""Read-only entity models for Lablet Cloud Manager.

These are immutable data transfer objects used by controllers and schedulers.
They represent the current state of entities as returned by the Control Plane API.

Important: These are NOT aggregates. Full aggregates with event sourcing
are owned by control-plane-api. Controllers use these read models for
decision making and request state changes via the Control Plane API.
"""

from lcm_core.domain.entities.read_models.cml_worker_read_model import CMLWorkerReadModel
from lcm_core.domain.entities.read_models.grading_session_read_model import GradingSessionReadModel
from lcm_core.domain.entities.read_models.lab_record_read_model import LabRecordReadModel
from lcm_core.domain.entities.read_models.lablet_definition_read_model import LabletDefinitionReadModel
from lcm_core.domain.entities.read_models.lablet_session_read_model import LabletSessionReadModel
from lcm_core.domain.entities.read_models.score_report_read_model import ScoreReportReadModel, ScoreSectionReadModel
from lcm_core.domain.entities.read_models.timed_resource_read_model import TimedResourceReadModel
from lcm_core.domain.entities.read_models.user_session_read_model import UserSessionReadModel
from lcm_core.domain.entities.read_models.worker_template_read_model import WorkerTemplateReadModel

__all__ = [
    "CMLWorkerReadModel",
    "GradingSessionReadModel",
    "LabRecordReadModel",
    "LabletDefinitionReadModel",
    "LabletSessionReadModel",
    "ScoreReportReadModel",
    "ScoreSectionReadModel",
    "TimedResourceReadModel",
    "UserSessionReadModel",
    "WorkerTemplateReadModel",
]
