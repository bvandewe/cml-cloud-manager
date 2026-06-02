"""Worker-related commands package.

ADR-015: All commands in this package are DB-only operations.
External calls (EC2, CloudWatch, CML API) are handled by controllers.
"""

from .allocate_capacity_command import AllocateCapacityCommand, AllocateCapacityCommandHandler
from .cleanup_terminated_workers_command import (
    CleanupTerminatedWorkersCommand,
    CleanupTerminatedWorkersCommandHandler,
)
from .create_cml_worker_command import CreateCMLWorkerCommand, CreateCMLWorkerCommandHandler
from .delete_cml_worker_command import DeleteCMLWorkerCommand, DeleteCMLWorkerCommandHandler
from .deregister_cml_worker_license_command import (
    DeregisterCMLWorkerLicenseCommand,
    DeregisterCMLWorkerLicenseCommandHandler,
)
from .detect_worker_idle_command import DetectWorkerIdleCommand, DetectWorkerIdleCommandHandler
from .disable_idle_detection_command import DisableIdleDetectionCommand, DisableIdleDetectionCommandHandler
from .drain_worker_command import DrainWorkerCommand, DrainWorkerCommandHandler
from .enable_idle_detection_command import EnableIdleDetectionCommand, EnableIdleDetectionCommandHandler
from .enable_worker_detailed_monitoring_command import (
    EnableWorkerDetailedMonitoringCommand,
    EnableWorkerDetailedMonitoringCommandHandler,
)
from .internal_bulk_import_workers_command import (
    InternalBulkImportResult,
    InternalBulkImportWorkersCommand,
    InternalBulkImportWorkersCommandHandler,
)
from .license_status_commands import (
    CompleteLicenseDeregistrationCommand,
    CompleteLicenseDeregistrationCommandHandler,
    CompleteLicenseRegistrationCommand,
    CompleteLicenseRegistrationCommandHandler,
    FailLicenseDeregistrationCommand,
    FailLicenseDeregistrationCommandHandler,
    FailLicenseRegistrationCommand,
    FailLicenseRegistrationCommandHandler,
    StartLicenseDeregistrationCommand,
    StartLicenseDeregistrationCommandHandler,
    StartLicenseRegistrationCommand,
    StartLicenseRegistrationCommandHandler,
)
from .mark_worker_terminated_command import MarkWorkerTerminatedCommand, MarkWorkerTerminatedCommandHandler
from .pause_worker_command import PauseWorkerCommand, PauseWorkerCommandHandler
from .recalculate_worker_capacity_command import (
    RecalculateWorkerCapacityCommand,
    RecalculateWorkerCapacityCommandHandler,
)
from .register_cml_worker_license_command import RegisterCMLWorkerLicenseCommand, RegisterCMLWorkerLicenseCommandHandler
from .release_capacity_command import ReleaseCapacityCommand, ReleaseCapacityCommandHandler
from .report_activity_events_command import ReportActivityEventsCommand, ReportActivityEventsCommandHandler
from .report_lab_state_change_command import ReportLabStateChangeCommand, ReportLabStateChangeCommandHandler
from .request_scale_up_command import RequestScaleUpCommand, RequestScaleUpCommandHandler
from .request_worker_refresh_command import RequestWorkerRefreshCommand, RequestWorkerRefreshCommandHandler
from .request_worker_sync_command import RequestWorkerSyncCommand, RequestWorkerSyncCommandHandler
from .start_cml_worker_command import StartCMLWorkerCommand, StartCMLWorkerCommandHandler
from .stop_cml_worker_command import StopCMLWorkerCommand, StopCMLWorkerCommandHandler
from .terminate_cml_worker_command import TerminateCMLWorkerCommand, TerminateCMLWorkerCommandHandler
from .trigger_lab_discovery_command import TriggerLabDiscoveryCommand, TriggerLabDiscoveryCommandHandler
from .update_cml_worker_metrics_command import UpdateCMLWorkerMetricsCommand, UpdateCMLWorkerMetricsCommandHandler
from .update_cml_worker_status_command import UpdateCMLWorkerStatusCommand, UpdateCMLWorkerStatusCommandHandler
from .update_cml_worker_tags_command import UpdateCMLWorkerTagsCommand, UpdateCMLWorkerTagsCommandHandler
from .update_worker_activity_command import UpdateWorkerActivityCommand, UpdateWorkerActivityCommandHandler
from .update_worker_cml_data_command import UpdateWorkerCmlDataCommand, UpdateWorkerCmlDataCommandHandler
from .update_worker_ec2_details_command import UpdateWorkerEc2DetailsCommand, UpdateWorkerEc2DetailsCommandHandler
from .update_worker_lab_stats_command import UpdateWorkerLabStatsCommand, UpdateWorkerLabStatsCommandHandler
from .update_worker_ws_status_command import UpdateWorkerWsStatusCommand, UpdateWorkerWsStatusCommandHandler

__all__ = [
    # Capacity Management (Phase 1 - Lablet Integration)
    "AllocateCapacityCommand",
    "AllocateCapacityCommandHandler",
    "ReleaseCapacityCommand",
    "ReleaseCapacityCommandHandler",
    "RecalculateWorkerCapacityCommand",
    "RecalculateWorkerCapacityCommandHandler",
    # Create/Delete lifecycle (DB-only, controllers reconcile)
    "CreateCMLWorkerCommand",
    "CreateCMLWorkerCommandHandler",
    "DeleteCMLWorkerCommand",
    "DeleteCMLWorkerCommandHandler",
    # Scale-Up (Phase 3 - Auto-Scaling)
    "RequestScaleUpCommand",
    "RequestScaleUpCommandHandler",
    # On-demand refresh (user-triggered data collection)
    "RequestWorkerRefreshCommand",
    "RequestWorkerRefreshCommandHandler",
    # Scale-Down / Drain (Phase 3 - Auto-Scaling)
    "DrainWorkerCommand",
    "DrainWorkerCommandHandler",
    # Cleanup/Maintenance (internal/admin)
    "CleanupTerminatedWorkersCommand",
    "CleanupTerminatedWorkersCommandHandler",
    # Start/Stop/Terminate lifecycle (DB-only, sets desired_status)
    "StartCMLWorkerCommand",
    "StartCMLWorkerCommandHandler",
    "StopCMLWorkerCommand",
    "StopCMLWorkerCommandHandler",
    "TerminateCMLWorkerCommand",
    "TerminateCMLWorkerCommandHandler",
    "MarkWorkerTerminatedCommand",
    "MarkWorkerTerminatedCommandHandler",
    "PauseWorkerCommand",
    "PauseWorkerCommandHandler",
    # Internal API for controllers
    "InternalBulkImportResult",
    "InternalBulkImportWorkersCommand",
    "InternalBulkImportWorkersCommandHandler",
    # Status and metrics (DB-only, returns cached data)
    "UpdateCMLWorkerStatusCommand",
    "UpdateCMLWorkerStatusCommandHandler",
    "UpdateCMLWorkerMetricsCommand",
    "UpdateCMLWorkerMetricsCommandHandler",
    "UpdateCMLWorkerTagsCommand",
    "UpdateCMLWorkerTagsCommandHandler",
    "UpdateWorkerActivityCommand",
    "UpdateWorkerActivityCommandHandler",
    # CML data (system_info, health, license - separate from utilization metrics)
    "UpdateWorkerCmlDataCommand",
    "UpdateWorkerCmlDataCommandHandler",
    # EC2 instance details (AMI, IPs, instance type)
    "UpdateWorkerEc2DetailsCommand",
    "UpdateWorkerEc2DetailsCommandHandler",
    # Idle detection (DB-only)
    "DetectWorkerIdleCommand",
    "DetectWorkerIdleCommandHandler",
    "DisableIdleDetectionCommand",
    "DisableIdleDetectionCommandHandler",
    "EnableIdleDetectionCommand",
    "EnableIdleDetectionCommandHandler",
    # Monitoring settings (DB-only, worker-controller applies)
    "EnableWorkerDetailedMonitoringCommand",
    "EnableWorkerDetailedMonitoringCommandHandler",
    # License (DB-only, lablet-controller handles lifecycle)
    "DeregisterCMLWorkerLicenseCommand",
    "DeregisterCMLWorkerLicenseCommandHandler",
    "RegisterCMLWorkerLicenseCommand",
    "RegisterCMLWorkerLicenseCommandHandler",
    # License status commands (internal API for worker-controller)
    "StartLicenseRegistrationCommand",
    "StartLicenseRegistrationCommandHandler",
    "CompleteLicenseRegistrationCommand",
    "CompleteLicenseRegistrationCommandHandler",
    "FailLicenseRegistrationCommand",
    "FailLicenseRegistrationCommandHandler",
    "StartLicenseDeregistrationCommand",
    "StartLicenseDeregistrationCommandHandler",
    "CompleteLicenseDeregistrationCommand",
    "CompleteLicenseDeregistrationCommandHandler",
    "FailLicenseDeregistrationCommand",
    "FailLicenseDeregistrationCommandHandler",
    # ADR-041: WebSocket-based real-time monitoring
    "ReportActivityEventsCommand",
    "ReportActivityEventsCommandHandler",
    "ReportLabStateChangeCommand",
    "ReportLabStateChangeCommandHandler",
    "UpdateWorkerLabStatsCommand",
    "UpdateWorkerLabStatsCommandHandler",
    "UpdateWorkerWsStatusCommand",
    "UpdateWorkerWsStatusCommandHandler",
    # ADR-041 Phase 2: Targeted lab discovery trigger
    "TriggerLabDiscoveryCommand",
    "TriggerLabDiscoveryCommandHandler",
    # AD-043: Full state sync (etcd-triggered reconciliation)
    "RequestWorkerSyncCommand",
    "RequestWorkerSyncCommandHandler",
]
