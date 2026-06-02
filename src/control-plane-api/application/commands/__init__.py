"""Application commands package.

ADR-015: All commands in this package are DB-only operations.
External calls (EC2, CloudWatch, CML API) are handled by controllers.
"""

# Base class - stays at root level
from .command_handler_base import CommandHandlerBase

# GradingSession commands (Phase 7D — ADR-021 child entity)
from .grading_session import (
    CreateGradingSessionCommand,
    CreateGradingSessionCommandHandler,
    UpdateGradingSessionStatusCommand,
    UpdateGradingSessionStatusCommandHandler,
)

# Lab commands
from .lab import (
    ControlLabCommand,
    ControlLabCommandHandler,
    DeleteLabCommand,
    DeleteLabCommandHandler,
    DownloadLabCommand,
    DownloadLabCommandHandler,
    ImportLabCommand,
    ImportLabCommandHandler,
    LabAction,
)

# LabletDefinition commands
from .lablet_definition import (
    CreateLabletDefinitionCommand,
    CreateLabletDefinitionCommandHandler,
    SyncLabletDefinitionCommand,
    SyncLabletDefinitionCommandHandler,
    UpdateLabletDefinitionCommand,  # noqa: F401
    UpdateLabletDefinitionCommandHandler,  # noqa: F401
)

# LabletSession commands (Phase 7D — replaces LabletInstance commands)
from .lablet_session import (
    CreateLabletSessionCommand,
    CreateLabletSessionCommandHandler,
    RecordResourceObservationCommand,
    RecordResourceObservationCommandHandler,
    TerminateLabletSessionCommand,
    TerminateLabletSessionCommandHandler,
)

# ScoreReport commands (Phase 7D — ADR-021 child entity)
from .score_report import (
    CreateScoreReportCommand,
    CreateScoreReportCommandHandler,
)

# Settings commands
from .settings import UpdateSystemSettingsCommand, UpdateSystemSettingsCommandHandler

# UserSession commands (Phase 7D — ADR-021 child entity)
from .user_session import (
    CreateUserSessionCommand,
    CreateUserSessionCommandHandler,
    UpdateUserSessionStatusCommand,
    UpdateUserSessionStatusCommandHandler,
)

# Worker commands (DB-only per ADR-015)
from .worker import (
    CreateCMLWorkerCommand,
    CreateCMLWorkerCommandHandler,
    DeleteCMLWorkerCommand,
    DeleteCMLWorkerCommandHandler,
    DeregisterCMLWorkerLicenseCommand,
    DeregisterCMLWorkerLicenseCommandHandler,
    DetectWorkerIdleCommand,
    DetectWorkerIdleCommandHandler,
    DisableIdleDetectionCommand,
    DisableIdleDetectionCommandHandler,
    EnableIdleDetectionCommand,
    EnableIdleDetectionCommandHandler,
    EnableWorkerDetailedMonitoringCommand,
    EnableWorkerDetailedMonitoringCommandHandler,
    InternalBulkImportResult,
    InternalBulkImportWorkersCommand,
    InternalBulkImportWorkersCommandHandler,
    MarkWorkerTerminatedCommand,
    MarkWorkerTerminatedCommandHandler,
    PauseWorkerCommand,
    PauseWorkerCommandHandler,
    RegisterCMLWorkerLicenseCommand,
    RegisterCMLWorkerLicenseCommandHandler,
    RequestScaleUpCommand,
    RequestScaleUpCommandHandler,
    RequestWorkerRefreshCommand,
    RequestWorkerRefreshCommandHandler,
    RequestWorkerSyncCommand,
    RequestWorkerSyncCommandHandler,
    StartCMLWorkerCommand,
    StartCMLWorkerCommandHandler,
    StopCMLWorkerCommand,
    StopCMLWorkerCommandHandler,
    TerminateCMLWorkerCommand,
    TerminateCMLWorkerCommandHandler,
    TriggerLabDiscoveryCommand,
    TriggerLabDiscoveryCommandHandler,
    UpdateCMLWorkerMetricsCommand,
    UpdateCMLWorkerMetricsCommandHandler,
    UpdateCMLWorkerStatusCommand,
    UpdateCMLWorkerStatusCommandHandler,
    UpdateCMLWorkerTagsCommand,
    UpdateCMLWorkerTagsCommandHandler,
    UpdateWorkerActivityCommand,
    UpdateWorkerActivityCommandHandler,
    UpdateWorkerCmlDataCommand,
    UpdateWorkerCmlDataCommandHandler,
    UpdateWorkerEc2DetailsCommand,
    UpdateWorkerEc2DetailsCommandHandler,
)

# WorkerTemplate commands
from .worker_template import (
    CreateWorkerTemplateCommand,
    CreateWorkerTemplateCommandHandler,
    DeleteWorkerTemplateCommand,
    DeleteWorkerTemplateCommandHandler,
    DisableWorkerTemplateCommand,
    DisableWorkerTemplateCommandHandler,
    EnableWorkerTemplateCommand,
    EnableWorkerTemplateCommandHandler,
    UpdateWorkerTemplateCommand,
    UpdateWorkerTemplateCommandHandler,
)

__all__ = [
    # Base class
    "CommandHandlerBase",
    # Lab commands
    "ControlLabCommand",
    "ControlLabCommandHandler",
    "DeleteLabCommand",
    "DeleteLabCommandHandler",
    "DownloadLabCommand",
    "DownloadLabCommandHandler",
    "ImportLabCommand",
    "ImportLabCommandHandler",
    "LabAction",
    # LabletDefinition commands
    "CreateLabletDefinitionCommand",
    "CreateLabletDefinitionCommandHandler",
    "SyncLabletDefinitionCommand",
    "SyncLabletDefinitionCommandHandler",
    # WorkerTemplate commands
    "CreateWorkerTemplateCommand",
    "CreateWorkerTemplateCommandHandler",
    "DeleteWorkerTemplateCommand",
    "DeleteWorkerTemplateCommandHandler",
    "DisableWorkerTemplateCommand",
    "DisableWorkerTemplateCommandHandler",
    "EnableWorkerTemplateCommand",
    "EnableWorkerTemplateCommandHandler",
    "UpdateWorkerTemplateCommand",
    "UpdateWorkerTemplateCommandHandler",
    # LabletSession commands (Phase 7D)
    "CreateLabletSessionCommand",
    "CreateLabletSessionCommandHandler",
    "RecordResourceObservationCommand",
    "RecordResourceObservationCommandHandler",
    "TerminateLabletSessionCommand",
    "TerminateLabletSessionCommandHandler",
    # Settings commands
    "UpdateSystemSettingsCommand",
    "UpdateSystemSettingsCommandHandler",
    # Worker commands (DB-only per ADR-015)
    "CreateCMLWorkerCommand",
    "CreateCMLWorkerCommandHandler",
    "DeleteCMLWorkerCommand",
    "DeleteCMLWorkerCommandHandler",
    "DeregisterCMLWorkerLicenseCommand",
    "DeregisterCMLWorkerLicenseCommandHandler",
    "DetectWorkerIdleCommand",
    "DetectWorkerIdleCommandHandler",
    "DisableIdleDetectionCommand",
    "DisableIdleDetectionCommandHandler",
    "EnableIdleDetectionCommand",
    "EnableIdleDetectionCommandHandler",
    "EnableWorkerDetailedMonitoringCommand",
    "EnableWorkerDetailedMonitoringCommandHandler",
    "InternalBulkImportResult",
    "InternalBulkImportWorkersCommand",
    "InternalBulkImportWorkersCommandHandler",
    "MarkWorkerTerminatedCommand",
    "MarkWorkerTerminatedCommandHandler",
    "PauseWorkerCommand",
    "PauseWorkerCommandHandler",
    "RegisterCMLWorkerLicenseCommand",
    "RegisterCMLWorkerLicenseCommandHandler",
    "RequestScaleUpCommand",
    "RequestScaleUpCommandHandler",
    "RequestWorkerRefreshCommand",
    "RequestWorkerRefreshCommandHandler",
    "RequestWorkerSyncCommand",
    "RequestWorkerSyncCommandHandler",
    "StartCMLWorkerCommand",
    "StartCMLWorkerCommandHandler",
    "StopCMLWorkerCommand",
    "StopCMLWorkerCommandHandler",
    "TerminateCMLWorkerCommand",
    "TerminateCMLWorkerCommandHandler",
    "TriggerLabDiscoveryCommand",
    "TriggerLabDiscoveryCommandHandler",
    "UpdateCMLWorkerMetricsCommand",
    "UpdateCMLWorkerMetricsCommandHandler",
    "UpdateCMLWorkerStatusCommand",
    "UpdateCMLWorkerStatusCommandHandler",
    "UpdateCMLWorkerTagsCommand",
    "UpdateCMLWorkerTagsCommandHandler",
    "UpdateWorkerActivityCommand",
    "UpdateWorkerActivityCommandHandler",
    "UpdateWorkerCmlDataCommand",
    "UpdateWorkerCmlDataCommandHandler",
    "UpdateWorkerEc2DetailsCommand",
    "UpdateWorkerEc2DetailsCommandHandler",
    # UserSession commands (Phase 7D — ADR-021 child entity)
    "CreateUserSessionCommand",
    "CreateUserSessionCommandHandler",
    "UpdateUserSessionStatusCommand",
    "UpdateUserSessionStatusCommandHandler",
    # GradingSession commands (Phase 7D — ADR-021 child entity)
    "CreateGradingSessionCommand",
    "CreateGradingSessionCommandHandler",
    "UpdateGradingSessionStatusCommand",
    "UpdateGradingSessionStatusCommandHandler",
    # ScoreReport commands (Phase 7D — ADR-021 child entity)
    "CreateScoreReportCommand",
    "CreateScoreReportCommandHandler",
]
