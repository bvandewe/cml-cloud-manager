"""Lab-related commands package.

CQRS command surface for LabRecord lifecycle management.
Includes BFF commands (user-facing operations) and internal commands
(controller-to-CPA mutations per ADR-001).
"""

from .allocate_lab_record_ports_command import AllocateLabRecordPortsCommand, AllocateLabRecordPortsCommandHandler
from .append_pipeline_run_command import AppendPipelineRunCommand, AppendPipelineRunCommandHandler
from .archive_lab_record_command import ArchiveLabRecordCommand, ArchiveLabRecordCommandHandler
from .bind_lab_to_lablet_command import BindLabToLabletCommand, BindLabToLabletCommandHandler
from .clone_lab_record_command import CloneLabRecordCommand, CloneLabRecordCommandHandler
from .complete_lab_action_command import CompleteLabActionCommand, CompleteLabActionCommandHandler
from .control_lab_command import ControlLabCommand, ControlLabCommandHandler, LabAction
from .delete_lab_command import DeleteLabCommand, DeleteLabCommandHandler
from .delete_lab_record_command import DeleteLabRecordCommand, DeleteLabRecordCommandHandler
from .discover_lab_records_command import (
    DiscoverLabRecordsCommand,
    DiscoverLabRecordsCommandHandler,
    DiscoverLabRecordsResult,
)
from .download_lab_command import DownloadLabCommand, DownloadLabCommandHandler
from .fail_lab_action_command import FailLabActionCommand, FailLabActionCommandHandler
from .import_lab_command import ImportLabCommand, ImportLabCommandHandler
from .record_lab_run_command import RecordLabRunCommand, RecordLabRunCommandHandler
from .start_lab_record_command import StartLabRecordCommand, StartLabRecordCommandHandler
from .stop_lab_record_command import StopLabRecordCommand, StopLabRecordCommandHandler
from .timeout_stale_pending_actions_command import (
    TimeoutStalePendingActionsCommand,
    TimeoutStalePendingActionsCommandHandler,
    TimeoutStalePendingActionsResult,
)
from .unbind_lab_from_lablet_command import UnbindLabFromLabletCommand, UnbindLabFromLabletCommandHandler
from .update_lab_record_status_command import UpdateLabRecordStatusCommand, UpdateLabRecordStatusCommandHandler
from .update_lab_topology_command import UpdateLabTopologyCommand, UpdateLabTopologyCommandHandler
from .wipe_lab_record_command import WipeLabRecordCommand, WipeLabRecordCommandHandler

__all__ = [
    # BFF commands (user-facing operations)
    "ControlLabCommand",
    "ControlLabCommandHandler",
    "DeleteLabCommand",
    "DeleteLabCommandHandler",
    "DownloadLabCommand",
    "DownloadLabCommandHandler",
    "ImportLabCommand",
    "ImportLabCommandHandler",
    "LabAction",
    "TimeoutStalePendingActionsCommand",
    "TimeoutStalePendingActionsCommandHandler",
    "TimeoutStalePendingActionsResult",
    # Phase 8: BFF commands (P8-2 through P8-9)
    "ArchiveLabRecordCommand",
    "ArchiveLabRecordCommandHandler",
    "BindLabToLabletCommand",
    "BindLabToLabletCommandHandler",
    "CloneLabRecordCommand",
    "CloneLabRecordCommandHandler",
    "DeleteLabRecordCommand",
    "DeleteLabRecordCommandHandler",
    "StartLabRecordCommand",
    "StartLabRecordCommandHandler",
    "StopLabRecordCommand",
    "StopLabRecordCommandHandler",
    "UnbindLabFromLabletCommand",
    "UnbindLabFromLabletCommandHandler",
    "WipeLabRecordCommand",
    "WipeLabRecordCommandHandler",
    # Phase 8: Internal commands (P8-1, P8-10 through P8-14)
    "AllocateLabRecordPortsCommand",
    "AllocateLabRecordPortsCommandHandler",
    "AppendPipelineRunCommand",
    "AppendPipelineRunCommandHandler",
    "CompleteLabActionCommand",
    "CompleteLabActionCommandHandler",
    "DiscoverLabRecordsCommand",
    "DiscoverLabRecordsCommandHandler",
    "DiscoverLabRecordsResult",
    "FailLabActionCommand",
    "FailLabActionCommandHandler",
    "RecordLabRunCommand",
    "RecordLabRunCommandHandler",
    "UpdateLabRecordStatusCommand",
    "UpdateLabRecordStatusCommandHandler",
    "UpdateLabTopologyCommand",
    "UpdateLabTopologyCommandHandler",
]
