"""Domain entities package.

Phase 7C: LabletInstance/LabletLabBinding/LabletRecordRun replaced by
LabletSession (aggregate) + UserSession, GradingSession, ScoreReport
(child entities per ADR-020 / ADR-021).
"""

from .cml_worker import CMLWorker, CMLWorkerState
from .grading_session import GradingSession
from .lab_record import InvalidLabRecordTransitionError, LabRecord, LabRecordState
from .lablet_definition import LabletDefinition, LabletDefinitionState, NotificationConfig
from .lablet_session import InvalidStateTransitionError, LabletSession, LabletSessionState
from .pending_lab_import import PendingLabImport
from .score_report import ScoreReport, ScoreSection
from .user_session import UserSession
from .worker_template import (
    WorkerTemplate,
    WorkerTemplateCreatedDomainEvent,
    WorkerTemplateDisabledDomainEvent,
    WorkerTemplateState,
    WorkerTemplateUpdatedDomainEvent,
)

__all__ = [
    "CMLWorker",
    "CMLWorkerState",
    "GradingSession",
    "InvalidLabRecordTransitionError",
    "InvalidStateTransitionError",
    "LabletDefinition",
    "LabletDefinitionState",
    "LabletSession",
    "LabletSessionState",
    "LabRecord",
    "LabRecordState",
    "NotificationConfig",
    "PendingLabImport",
    "ScoreReport",
    "ScoreSection",
    "UserSession",
    "WorkerTemplate",
    "WorkerTemplateCreatedDomainEvent",
    "WorkerTemplateDisabledDomainEvent",
    "WorkerTemplateState",
    "WorkerTemplateUpdatedDomainEvent",
]
