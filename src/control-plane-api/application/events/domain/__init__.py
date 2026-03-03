from .cml_worker_data_refresh_events import (
    WorkerDataRefreshCompletedEventHandler,
    WorkerDataRefreshRequestedEventHandler,
    WorkerDataRefreshSkippedEventHandler,
)
from .cml_worker_events import (
    CMLMetricsUpdatedDomainEventHandler,
    CMLWorkerCreatedDomainEventHandler,
    CMLWorkerEndpointUpdatedDomainEventHandler,
    CMLWorkerImportedDomainEventHandler,
    CMLWorkerStatusUpdatedDomainEventHandler,
    CMLWorkerTelemetryUpdatedDomainEventHandler,
    CMLWorkerTerminatedDomainEventHandler,
    EC2InstanceDetailsUpdatedDomainEventHandler,
)
from .cml_worker_license_events import (
    CMLWorkerLicenseDeregisteredEventHandler,
    CMLWorkerLicenseRegistrationCompletedEventHandler,
    CMLWorkerLicenseRegistrationFailedEventHandler,
    CMLWorkerLicenseRegistrationStartedEventHandler,
)
from .etcd_state_projector import (
    CMLWorkerCreatedEtcdProjector,
    CMLWorkerDesiredStatusUpdatedEtcdProjector,
    CMLWorkerLicenseDeregistrationCompletedEtcdProjector,
    CMLWorkerLicenseDeregistrationRequestedEtcdProjector,
    CMLWorkerLicenseRegistrationCompletedEtcdProjector,
    CMLWorkerLicenseRegistrationRequestedEtcdProjector,
    CMLWorkerStatusUpdatedEtcdProjector,
    CMLWorkerTerminatedEtcdProjector,
    LabletSessionCollectingEtcdProjector,
    LabletSessionCreatedEtcdProjector,
    LabletSessionGradingEtcdProjector,
    LabletSessionInstantiatingEtcdProjector,
    LabletSessionRequeuedEtcdProjector,
    LabletSessionRunningEtcdProjector,
    LabletSessionScheduledEtcdProjector,
    LabletSessionStoppedEtcdProjector,
    LabletSessionStoppingEtcdProjector,
    LabletSessionTerminatedEtcdProjector,
)
from .lab_record_events import (
    LabRecordCreatedDomainEventHandler,
    LabRecordUpdatedDomainEventHandler,
    LabStateChangedDomainEventHandler,
)
from .lablet_definition_events import (
    LabletDefinitionActivatedDomainEventHandler,
    LabletDefinitionContentSyncedDomainEventHandler,
    LabletDefinitionCreatedDomainEventHandler,
    LabletDefinitionDeactivatedDomainEventHandler,
    LabletDefinitionDeletedDomainEventHandler,
    LabletDefinitionDeprecatedDomainEventHandler,
    LabletDefinitionSyncRequestedDomainEventHandler,
    LabletDefinitionUpdatedDomainEventHandler,
)
from .lablet_session_sse_handlers import (
    LabletSessionArchivedDomainEventHandler,
    LabletSessionCollectingDomainEventHandler,
    LabletSessionCreatedDomainEventHandler,
    LabletSessionGradingDomainEventHandler,
    LabletSessionInstantiatingDomainEventHandler,
    LabletSessionPortsReleasedDomainEventHandler,
    LabletSessionReadyDomainEventHandler,
    LabletSessionRunningDomainEventHandler,
    LabletSessionScheduledDomainEventHandler,
    LabletSessionScoreRecordedDomainEventHandler,
    LabletSessionStoppedDomainEventHandler,
    LabletSessionStoppingDomainEventHandler,
    LabletSessionTerminatedDomainEventHandler,
    LabletSessionTimeslotExtendedDomainEventHandler,
)
from .user_auth_events_handler import UserLoggedInDomainEventHandler
from .worker_activity_events_handler import (
    IdleDetectionToggledDomainEventHandler,
    WorkerActivityUpdatedDomainEventHandler,
    WorkerPausedDomainEventHandler,
    WorkerResumedDomainEventHandler,
)
from .worker_template_events import (
    WorkerTemplateCreatedDomainEventHandler,
    WorkerTemplateDeletedDomainEventHandler,
    WorkerTemplateUpdatedDomainEventHandler,
)

__all__ = [
    # User auth events
    "UserLoggedInDomainEventHandler",
    # CML Worker events
    "CMLWorkerCreatedDomainEventHandler",
    "CMLWorkerImportedDomainEventHandler",
    "CMLWorkerStatusUpdatedDomainEventHandler",
    "CMLWorkerTerminatedDomainEventHandler",
    "CMLWorkerTelemetryUpdatedDomainEventHandler",
    "CMLWorkerEndpointUpdatedDomainEventHandler",
    "CMLMetricsUpdatedDomainEventHandler",
    "EC2InstanceDetailsUpdatedDomainEventHandler",
    # CML Worker license events
    "CMLWorkerLicenseRegistrationStartedEventHandler",
    "CMLWorkerLicenseRegistrationCompletedEventHandler",
    "CMLWorkerLicenseRegistrationFailedEventHandler",
    "CMLWorkerLicenseDeregisteredEventHandler",
    # Worker data refresh events
    "WorkerDataRefreshRequestedEventHandler",
    "WorkerDataRefreshSkippedEventHandler",
    "WorkerDataRefreshCompletedEventHandler",
    # Worker activity events
    "IdleDetectionToggledDomainEventHandler",
    "WorkerActivityUpdatedDomainEventHandler",
    "WorkerPausedDomainEventHandler",
    "WorkerResumedDomainEventHandler",
    # Lab record events
    "LabRecordCreatedDomainEventHandler",
    "LabRecordUpdatedDomainEventHandler",
    "LabStateChangedDomainEventHandler",
    # etcd State Projectors (ADR-006: Watch-triggered reconciliation)
    "CMLWorkerCreatedEtcdProjector",
    "CMLWorkerDesiredStatusUpdatedEtcdProjector",
    "CMLWorkerStatusUpdatedEtcdProjector",
    "CMLWorkerTerminatedEtcdProjector",
    # etcd License Projectors (ADR-016: Reactive license operations)
    "CMLWorkerLicenseRegistrationRequestedEtcdProjector",
    "CMLWorkerLicenseRegistrationCompletedEtcdProjector",
    "CMLWorkerLicenseDeregistrationRequestedEtcdProjector",
    "CMLWorkerLicenseDeregistrationCompletedEtcdProjector",
    # etcd Session Projectors (Phase 7D)
    "LabletSessionCreatedEtcdProjector",
    "LabletSessionScheduledEtcdProjector",
    "LabletSessionInstantiatingEtcdProjector",
    "LabletSessionRunningEtcdProjector",
    "LabletSessionCollectingEtcdProjector",
    "LabletSessionGradingEtcdProjector",
    "LabletSessionStoppingEtcdProjector",
    "LabletSessionStoppedEtcdProjector",
    "LabletSessionRequeuedEtcdProjector",
    "LabletSessionTerminatedEtcdProjector",
    # SSE handlers - Worker Templates (ADR-013)
    "WorkerTemplateCreatedDomainEventHandler",
    "WorkerTemplateUpdatedDomainEventHandler",
    "WorkerTemplateDeletedDomainEventHandler",
    # SSE handlers - Lablet Definitions (ADR-013)
    "LabletDefinitionCreatedDomainEventHandler",
    "LabletDefinitionUpdatedDomainEventHandler",
    "LabletDefinitionActivatedDomainEventHandler",
    "LabletDefinitionDeactivatedDomainEventHandler",
    "LabletDefinitionDeletedDomainEventHandler",
    "LabletDefinitionContentSyncedDomainEventHandler",
    "LabletDefinitionDeprecatedDomainEventHandler",
    "LabletDefinitionSyncRequestedDomainEventHandler",
    # SSE handlers - Lablet Sessions (Phase 7D, ADR-013, ADR-020)
    "LabletSessionCreatedDomainEventHandler",
    "LabletSessionScheduledDomainEventHandler",
    "LabletSessionInstantiatingDomainEventHandler",
    "LabletSessionReadyDomainEventHandler",
    "LabletSessionRunningDomainEventHandler",
    "LabletSessionCollectingDomainEventHandler",
    "LabletSessionGradingDomainEventHandler",
    "LabletSessionScoreRecordedDomainEventHandler",
    "LabletSessionStoppingDomainEventHandler",
    "LabletSessionStoppedDomainEventHandler",
    "LabletSessionArchivedDomainEventHandler",
    "LabletSessionTerminatedDomainEventHandler",
    "LabletSessionPortsReleasedDomainEventHandler",
    "LabletSessionTimeslotExtendedDomainEventHandler",
]
