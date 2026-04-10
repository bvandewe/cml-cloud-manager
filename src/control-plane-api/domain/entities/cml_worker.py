"""CML Worker aggregate definition using the AggregateState pattern.

The CML Worker represents an AWS EC2 instance running Cisco Modeling Lab.
It manages the lifecycle of the instance, monitors telemetry, and provides
access to CML labs hosted on the instance.
"""

from dataclasses import replace
from datetime import datetime, timezone
from typing import cast
from urllib.parse import urlparse
from uuid import uuid4

from domain.enums import CML_WORKER_VALID_TRANSITIONS, CMLServiceStatus, CMLWorkerStatus, LicenseStatus, WorkerOrigin
from domain.events.cloudwatch_monitoring_updated_domain_event import CloudWatchMonitoringUpdatedDomainEvent
from domain.events.cml_worker import (
    AllocatedCapacityRecalculatedDomainEvent,
    CMLServiceStatusUpdatedDomainEvent,
    CMLWorkerCapacityUpdatedDomainEvent,
    CMLWorkerCreatedDomainEvent,
    CMLWorkerDesiredStatusUpdatedDomainEvent,
    CMLWorkerEndpointUpdatedDomainEvent,
    CMLWorkerImportedDomainEvent,
    CMLWorkerInstanceAssignedDomainEvent,
    CMLWorkerLicenseDeregisteredDomainEvent,
    CMLWorkerLicenseDeregistrationCompletedDomainEvent,
    CMLWorkerLicenseDeregistrationFailedDomainEvent,
    CMLWorkerLicenseDeregistrationRequestedDomainEvent,
    CMLWorkerLicenseDeregistrationStartedDomainEvent,
    CMLWorkerLicenseRegistrationCompletedDomainEvent,
    CMLWorkerLicenseRegistrationFailedDomainEvent,
    CMLWorkerLicenseRegistrationRequestedDomainEvent,
    CMLWorkerLicenseRegistrationStartedDomainEvent,
    CMLWorkerLicenseUpdatedDomainEvent,
    CMLWorkerPortsAllocatedDomainEvent,
    CMLWorkerPortsReleasedDomainEvent,
    CMLWorkerStatusUpdatedDomainEvent,
    CMLWorkerTagsUpdatedDomainEvent,
    CMLWorkerTelemetryUpdatedDomainEvent,
    CMLWorkerTerminatedDomainEvent,
    LabletSessionAssignedDomainEvent,
    LabletSessionRemovedDomainEvent,
    WorkerDataRefreshCompletedDomainEvent,
    WorkerDataRefreshRequestedDomainEvent,
    WorkerDataRefreshSkippedDomainEvent,
)
from domain.events.worker_activity_events import (
    IdleDetectionToggledDomainEvent,
    WorkerActivityUpdatedDomainEvent,
    WorkerPausedDomainEvent,
    WorkerResumedDomainEvent,
)
from domain.events.worker_metrics_events import (
    CloudWatchMetricsUpdatedDomainEvent,
    CMLMetricsUpdatedDomainEvent,
    EC2InstanceDetailsUpdatedDomainEvent,
    EC2MetricsUpdatedDomainEvent,
)
from domain.lifecycles import CML_WORKER_LIFECYCLE
from domain.value_objects.cml_license import CMLLicense
from domain.value_objects.cml_metrics import (
    CMLMetrics,
    CMLSystemHealth,
    CMLSystemInfo,
    CMLSystemInfoCompute,
    CMLSystemInfoComputeStats,
    CpuStats,
    DiskStats,
    DomInfoStats,
    MemoryStats,
)
from domain.value_objects.port_allocation import PortAllocation
from domain.value_objects.worker_capacity import WorkerCapacity
from lcm_core.domain.entities.timed_resource import TimedResourceState
from lcm_core.domain.value_objects.managed_lifecycle import ManagedLifecycle
from lcm_core.domain.value_objects.state_transition import StateTransition
from multipledispatch import dispatch
from neuroglia.data.abstractions import AggregateRoot


class CMLWorkerState(TimedResourceState):
    """Encapsulates the persisted state for the CML Worker aggregate.

    Inheritance hierarchy (ADR-036 §2.1.4):
        AggregateState[str]  (Neuroglia)
            └── ResourceState  (Layer 1 — status, desired_status, state_history)
                    └── TimedResourceState  (Layer 2 — timeslot, lifecycle, timestamps)
                            └── CMLWorkerState  ← YOU ARE HERE

    Inherits from TimedResourceState:
        - resource_type, owner_id, pipeline_progress (from ResourceState)
        - timeslot, lifecycle (from TimedResourceState)
        - started_at, ended_at, duration_seconds, terminated_at (from TimedResourceState)

    Shadows parent fields with typed versions:
        - status: CMLWorkerStatus (parent: str)
        - desired_status: CMLWorkerStatus (parent: str | None)
        - state_history: list[dict] (parent: list)
    """

    id: str
    name: str
    aws_region: str
    aws_instance_id: str | None
    instance_type: str
    ami_id: str | None
    ami_name: str | None
    ami_description: str | None
    ami_creation_date: str | None
    status: CMLWorkerStatus
    desired_status: CMLWorkerStatus  # Spec: What the user wants (reconciliation target)
    service_status: CMLServiceStatus

    # CML-specific attributes
    https_endpoint: str | None

    # Value Objects
    metrics: CMLMetrics
    license: CMLLicense

    # Network details
    public_ip: str | None
    private_ip: str | None

    # AWS tags
    aws_tags: dict[str, str]  # EC2 instance tags

    # EC2 Metrics (from AWS EC2 API)
    ec2_instance_state_detail: str | None  # e.g., "ok", "impaired", "insufficient-data"
    ec2_system_status_check: str | None  # e.g., "ok", "impaired"
    ec2_last_checked_at: datetime | None

    # CloudWatch Metrics (from AWS CloudWatch API)
    cloudwatch_cpu_utilization: float | None
    cloudwatch_memory_utilization: float | None
    cloudwatch_last_collected_at: datetime | None
    cloudwatch_detailed_monitoring_enabled: bool

    # Metrics Timing (for UI countdown timer)
    poll_interval: int | None  # Metrics collection interval in seconds
    next_refresh_at: datetime | None  # Next scheduled metrics collection time

    # On-demand refresh
    refresh_requested_at: datetime | None  # Timestamp of last user-triggered refresh request

    # Lifecycle timestamps
    created_at: datetime
    updated_at: datetime
    terminated_at: datetime | None
    start_initiated_at: datetime | None
    stop_initiated_at: datetime | None

    # Activity tracking
    last_activity_at: datetime | None  # Last relevant user activity detected
    last_activity_check_at: datetime | None  # Last time telemetry was checked
    recent_activity_events: list[dict]  # Last N relevant events (category, timestamp, data)

    # Pause/Resume lifecycle tracking
    auto_pause_count: int  # Count of automatic pauses by idle detection
    manual_pause_count: int  # Count of manual stop operations
    auto_resume_count: int  # Count of automatic resumes
    manual_resume_count: int  # Count of manual start operations
    last_paused_at: datetime | None  # Timestamp of last pause (auto or manual)
    last_resumed_at: datetime | None  # Timestamp of last resume (auto or manual)
    paused_by: str | None  # User/system that triggered last pause
    pause_reason: str | None  # "idle_timeout" | "manual" | "external"

    # Idle detection state
    next_idle_check_at: datetime | None  # Next scheduled activity check
    target_pause_at: datetime | None  # Calculated pause time if no activity detected
    is_idle_detection_enabled: bool  # Whether idle detection is enabled for this worker

    # Audit
    created_by: str | None
    terminated_by: str | None
    origin: WorkerOrigin  # Provenance: how this worker was created

    # Capacity Management (Phase 1 - Lablet Integration)
    template_name: str | None  # Worker template name (e.g., "m5zn.metal-cml-2.9")
    declared_capacity: WorkerCapacity | None  # Maximum capacity from template
    allocated_capacity: WorkerCapacity  # Sum of capacity used by lablet sessions
    port_allocations: list[PortAllocation]  # Ports allocated to lablet sessions
    session_ids: list[str]  # IDs of lablet sessions assigned to this worker

    # State history — audit trail of EC2 lifecycle transitions (ADR-036 §2.1.4)
    # Stored as list[dict] (StateTransition.to_dict()) for Neuroglia serialization.
    # Captures status changes with AMI/licensing context in metadata.
    state_history: list[dict]

    def __init__(self) -> None:
        super().__init__()
        self.resource_type = "cml_worker"
        self.id = ""
        self.name = ""
        self.aws_region = ""
        self.aws_instance_id = None
        self.instance_type = ""
        self.ami_id = None
        self.ami_name = None
        self.ami_description = None
        self.ami_creation_date = None
        self.status = CMLWorkerStatus.PENDING
        self.desired_status = CMLWorkerStatus.RUNNING  # Default desired state
        self.service_status = CMLServiceStatus.UNAVAILABLE

        self.metrics = CMLMetrics()
        self.license = CMLLicense()
        self.https_endpoint = None

        self.public_ip = None
        self.private_ip = None

        # AWS tags initialization
        self.aws_tags = {}

        # EC2 Metrics
        self.ec2_instance_state_detail = None
        self.ec2_system_status_check = None
        self.ec2_last_checked_at = None

        # CloudWatch Metrics
        self.cloudwatch_cpu_utilization = None
        self.cloudwatch_memory_utilization = None
        self.cloudwatch_last_collected_at = None
        self.cloudwatch_detailed_monitoring_enabled = False

        now = datetime.now(timezone.utc)
        self.created_at = now
        self.updated_at = now
        self.terminated_at = None
        self.start_initiated_at = None
        self.stop_initiated_at = None

        # Activity tracking initialization
        self.last_activity_at = None
        self.last_activity_check_at = None
        self.recent_activity_events = []

        # Pause/Resume lifecycle initialization
        self.auto_pause_count = 0
        self.manual_pause_count = 0
        self.auto_resume_count = 0
        self.manual_resume_count = 0
        self.last_paused_at = None
        self.last_resumed_at = None
        self.paused_by = None
        self.pause_reason = None

        # Idle detection state initialization
        self.next_idle_check_at = None
        self.target_pause_at = None
        self.is_idle_detection_enabled = True  # Enabled by default

        # On-demand refresh
        self.refresh_requested_at = None

        self.created_by = None
        self.terminated_by = None
        self.origin = WorkerOrigin.UNKNOWN

        # Capacity Management initialization (Phase 1 - Lablet Integration)
        self.template_name = None
        self.declared_capacity = None
        self.allocated_capacity = WorkerCapacity.zero()
        self.port_allocations = []
        self.session_ids = []

        # State history (ADR-036)
        self.state_history = []

    def _record_transition(
        self,
        from_state: str | None,
        to_state: str,
        triggered_by: str = "system",
        reason: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Record a state transition in the history.

        Overrides ResourceState._record_transition() for two reasons:
        1. Stores transitions as dicts (via StateTransition.to_dict()) instead
           of StateTransition objects, for Neuroglia serialization compatibility.
        2. Maintains updated_at behavior consistent with ResourceState base class.

        ADR-036 Batch E decision: Accept ResourceState's updated_at behavior
        (update on every transition) for consistency across all resource types.
        """
        transition = StateTransition(
            from_state=from_state,
            to_state=to_state,
            transitioned_at=datetime.now(timezone.utc),
            triggered_by=triggered_by,
            reason=reason,
            metadata=metadata,
        )
        self.state_history.append(transition.to_dict())
        self.updated_at = datetime.now(timezone.utc)

    @dispatch(CMLWorkerCreatedDomainEvent)
    def on(self, event: CMLWorkerCreatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the creation event to the state."""
        self.id = event.aggregate_id
        self.name = event.name
        self.aws_region = event.aws_region
        self.aws_instance_id = event.aws_instance_id
        self.instance_type = event.instance_type
        self.ami_id = event.ami_id
        self.ami_name = event.ami_name
        self.ami_description = event.ami_description
        self.ami_creation_date = event.ami_creation_date
        self.status = event.status
        self.desired_status = event.desired_status  # Spec: reconciliation target
        self.metrics = replace(self.metrics, version=event.cml_version)
        self.created_at = event.created_at
        self.updated_at = event.created_at
        self.created_by = event.created_by
        self.origin = event.origin
        # TimedResource lifecycle (ADR-036 §2.1.4 Batch E)
        self.started_at = event.created_at
        self.lifecycle = ManagedLifecycle(
            phases=CML_WORKER_LIFECYCLE.phases,
            current_phase="provision",
        ).to_dict()
        self._record_transition(
            from_state=None,
            to_state=event.status.value,
            triggered_by=event.created_by or "system",
            reason="Worker created",
            metadata={
                "origin": event.origin.value,
                "instance_type": event.instance_type,
                "ami_name": event.ami_name,
            },
        )

    @dispatch(CMLWorkerImportedDomainEvent)
    def on(self, event: CMLWorkerImportedDomainEvent) -> None:  # type: ignore[override]
        """Apply the import event to the state."""
        self.id = event.aggregate_id
        self.name = event.name
        self.aws_region = event.aws_region
        self.aws_instance_id = event.aws_instance_id
        self.instance_type = event.instance_type
        self.ami_id = event.ami_id
        self.ami_name = event.ami_name
        self.ami_description = event.ami_description
        self.ami_creation_date = event.ami_creation_date
        self.public_ip = event.public_ip
        self.private_ip = event.private_ip
        self.created_at = event.created_at
        self.updated_at = event.created_at
        self.created_by = event.created_by
        self.origin = event.origin

        # Map EC2 instance state to CMLWorkerStatus
        if event.instance_state == "running":
            self.status = CMLWorkerStatus.RUNNING
            self.desired_status = CMLWorkerStatus.RUNNING  # Imported running = user wants running
        elif event.instance_state == "stopped":
            self.status = CMLWorkerStatus.STOPPED
            self.desired_status = CMLWorkerStatus.STOPPED  # Imported stopped = keep stopped
        elif event.instance_state == "stopping":
            self.status = CMLWorkerStatus.STOPPING
            self.desired_status = CMLWorkerStatus.STOPPED  # Stopping = user wants stopped
        elif event.instance_state == "pending":
            self.status = CMLWorkerStatus.PENDING
            self.desired_status = CMLWorkerStatus.RUNNING  # Pending = user wants running
        else:
            self.status = CMLWorkerStatus.UNKNOWN
            self.desired_status = CMLWorkerStatus.RUNNING  # Unknown = assume user wants running
        # TimedResource lifecycle (ADR-036 §2.1.4 Batch E)
        # Imported workers assign lifecycle with current_phase based on import state.
        # Running imports skip provision/startup/initial_metrics phases.
        self.started_at = event.created_at
        if self.status == CMLWorkerStatus.RUNNING:
            import_phase = "monitor_resources"
        elif self.status == CMLWorkerStatus.STOPPED:
            import_phase = None  # Lifecycle paused
        else:
            import_phase = "provision"  # Default: start from beginning
        self.lifecycle = ManagedLifecycle(
            phases=CML_WORKER_LIFECYCLE.phases,
            current_phase=import_phase,
        ).to_dict()
        self._record_transition(
            from_state=None,
            to_state=self.status.value,
            triggered_by=event.created_by or "system",
            reason="Worker imported from existing EC2 instance",
            metadata={
                "origin": event.origin.value,
                "instance_state": event.instance_state,
                "ami_id": event.ami_id,
                "ami_name": event.ami_name,
            },
        )

    @dispatch(CMLWorkerStatusUpdatedDomainEvent)
    def on(self, event: CMLWorkerStatusUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the status updated event to the state."""
        self.status = event.new_status
        self.updated_at = event.updated_at
        self._record_transition(
            from_state=event.old_status.value,
            to_state=event.new_status.value,
        )
        # Track transition initiation timestamps for long-running operations
        if event.new_status == CMLWorkerStatus.PENDING:
            # Starting
            self.start_initiated_at = event.transition_initiated_at or event.updated_at
        elif event.new_status == CMLWorkerStatus.RUNNING:
            # Clear start transition marker once running
            self.start_initiated_at = None
        elif event.new_status == CMLWorkerStatus.STOPPING:
            self.stop_initiated_at = event.transition_initiated_at or event.updated_at
            # Set service status to unavailable when stopping
            self.service_status = CMLServiceStatus.UNAVAILABLE
        elif event.new_status == CMLWorkerStatus.STOPPED:
            self.stop_initiated_at = None
            # Reset mutable network fields - EC2 releases public IP when stopped
            self.public_ip = None
            self.private_ip = None
            self.https_endpoint = None
            # Reset service status
            self.service_status = CMLServiceStatus.UNAVAILABLE
            # Reset resource utilization metrics
            self.cloudwatch_cpu_utilization = None
            self.cloudwatch_memory_utilization = None
            self.cloudwatch_last_collected_at = None
            # Reset CML metrics (worker is not running, no CML data available)
            self.metrics = CMLMetrics()

    @dispatch(CMLWorkerDesiredStatusUpdatedDomainEvent)
    def on(self, event: CMLWorkerDesiredStatusUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the desired status updated event to the state (spec change).

        This updates the user's desired state (spec). The worker-controller
        will reconcile actual state to match this desired state.
        """
        self.desired_status = event.new_desired_status
        self.updated_at = event.updated_at

    @dispatch(CMLServiceStatusUpdatedDomainEvent)
    def on(self, event: CMLServiceStatusUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the service status updated event to the state."""
        self.service_status = event.new_service_status
        if event.https_endpoint:
            self.https_endpoint = event.https_endpoint
        self.updated_at = event.updated_at

    @dispatch(CMLWorkerInstanceAssignedDomainEvent)
    def on(self, event: CMLWorkerInstanceAssignedDomainEvent) -> None:  # type: ignore[override]
        """Apply the instance assigned event to the state."""
        self.aws_instance_id = event.aws_instance_id
        self.public_ip = event.public_ip
        self.private_ip = event.private_ip
        self.updated_at = event.assigned_at

    @dispatch(CMLWorkerLicenseUpdatedDomainEvent)
    def on(self, event: CMLWorkerLicenseUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the license updated event to the state."""
        self.license = replace(
            self.license,
            status=event.license_status,
            token=event.license_token,
        )
        self.updated_at = event.updated_at

    @dispatch(EC2MetricsUpdatedDomainEvent)
    def on(self, event: EC2MetricsUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Apply EC2 metrics event to the state."""
        self.ec2_instance_state_detail = event.instance_state_detail
        self.ec2_system_status_check = event.system_status_check
        self.ec2_last_checked_at = event.checked_at
        self.updated_at = event.updated_at

    @dispatch(EC2InstanceDetailsUpdatedDomainEvent)
    def on(self, event: EC2InstanceDetailsUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Apply EC2 instance details event to the state."""
        self.public_ip = event.public_ip
        self.private_ip = event.private_ip
        self.instance_type = event.instance_type
        self.ami_id = event.ami_id
        self.ami_name = event.ami_name
        self.ami_description = event.ami_description
        self.ami_creation_date = event.ami_creation_date
        self.updated_at = event.updated_at

    @dispatch(CloudWatchMetricsUpdatedDomainEvent)
    def on(self, event: CloudWatchMetricsUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Apply CloudWatch metrics event to the state."""
        self.cloudwatch_cpu_utilization = event.cpu_utilization
        self.cloudwatch_memory_utilization = event.memory_utilization
        self.cloudwatch_last_collected_at = event.collected_at
        self.updated_at = event.updated_at

    @dispatch(CMLMetricsUpdatedDomainEvent)
    def on(self, event: CMLMetricsUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Apply CML API metrics event to the state."""
        info = event.system_info or {}
        health = event.system_health or {}

        # Parse computes
        computes_dict = {}
        raw_computes = info.get("computes", {})
        if isinstance(raw_computes, dict):
            for compute_id, compute_data in raw_computes.items():
                if not isinstance(compute_data, dict):
                    continue

                stats_data = compute_data.get("stats", {})
                stats_vo = None

                if stats_data:
                    cpu_data = stats_data.get("cpu", {})
                    mem_data = stats_data.get("memory", {})
                    disk_data = stats_data.get("disk", {})
                    dom_data = stats_data.get("dominfo", {})

                    stats_vo = CMLSystemInfoComputeStats(
                        cpu=(
                            CpuStats(
                                load=cpu_data.get("load", []),
                                count=cpu_data.get("count"),
                                percent=cpu_data.get("percent"),
                                model=cpu_data.get("model"),
                                predicted=cpu_data.get("predicted"),
                            )
                            if cpu_data
                            else None
                        ),
                        memory=(MemoryStats(total=mem_data.get("total"), free=mem_data.get("free"), used=mem_data.get("used")) if mem_data else None),
                        disk=(DiskStats(total=disk_data.get("total"), free=disk_data.get("free"), used=disk_data.get("used")) if disk_data else None),
                        dominfo=(
                            DomInfoStats(
                                allocated_cpus=dom_data.get("allocated_cpus"),
                                allocated_memory=dom_data.get("allocated_memory"),
                                total_nodes=dom_data.get("total_nodes"),
                                total_orphans=dom_data.get("total_orphans"),
                                running_nodes=dom_data.get("running_nodes"),
                                running_orphans=dom_data.get("running_orphans"),
                            )
                            if dom_data
                            else None
                        ),
                    )

                computes_dict[compute_id] = CMLSystemInfoCompute(
                    hostname=compute_data.get("hostname"),
                    is_controller=compute_data.get("is_controller"),
                    stats=stats_vo,
                )

        system_info_vo = CMLSystemInfo(
            cpu_count=info.get("all_cpu_count"),
            cpu_utilization=info.get("all_cpu_percent"),
            memory_total=info.get("all_memory_total"),
            memory_free=info.get("all_memory_free"),
            memory_used=info.get("all_memory_used"),
            disk_total=info.get("all_disk_total"),
            disk_free=info.get("all_disk_free"),
            disk_used=info.get("all_disk_used"),
            controller_disk_total=info.get("controller_disk_total"),
            controller_disk_free=info.get("controller_disk_free"),
            controller_disk_used=info.get("controller_disk_used"),
            allocated_cpus=info.get("allocated_cpus"),
            allocated_memory=info.get("allocated_memory"),
            total_nodes=info.get("total_nodes"),
            running_nodes=info.get("running_nodes"),
            computes=computes_dict,
        )

        system_health_vo = CMLSystemHealth(
            valid=health.get("valid", False),
            is_licensed=health.get("is_licensed", False),
            is_enterprise=health.get("is_enterprise", False),
            computes=health.get("computes", {}),
            controller=health.get("controller", {}),
        )

        self.metrics = CMLMetrics(
            version=event.cml_version,
            system_info=system_info_vo,
            system_health=system_health_vo,
            ready=event.ready,
            uptime_seconds=event.uptime_seconds,
            labs_count=event.labs_count,
            last_synced_at=event.synced_at,
        )
        self.updated_at = event.updated_at

        # Sync license_status from cml_license_info if available
        if event.license_info:
            # Handle both flat and nested structure (CML 2.7+ uses nested registration.status)
            reg_status = event.license_info.get("registration_status")
            if not reg_status and isinstance(event.license_info.get("registration"), dict):
                reg_status = event.license_info["registration"].get("status")

            if reg_status:
                reg_status = reg_status.upper()
                new_status = self.license.status
                if reg_status == "COMPLETED" or reg_status == "REGISTERED":
                    new_status = LicenseStatus.REGISTERED
                elif reg_status == "EVALUATION":
                    new_status = LicenseStatus.EVALUATION

                self.license = replace(self.license, status=new_status, raw_info=event.license_info)
            else:
                self.license = replace(self.license, raw_info=event.license_info)

    @dispatch(CMLWorkerTelemetryUpdatedDomainEvent)
    def on(self, event: CMLWorkerTelemetryUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Handle telemetry updated event."""
        self.updated_at = event.updated_at
        if event.poll_interval is not None:
            self.poll_interval = event.poll_interval
        if event.next_refresh_at is not None:
            self.next_refresh_at = event.next_refresh_at

    @dispatch(CMLWorkerEndpointUpdatedDomainEvent)
    def on(self, event: CMLWorkerEndpointUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the endpoint updated event to the state."""
        self.https_endpoint = event.https_endpoint
        if event.public_ip:
            self.public_ip = event.public_ip
        self.updated_at = event.updated_at

    @dispatch(CMLWorkerTerminatedDomainEvent)
    def on(self, event: CMLWorkerTerminatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the terminated event to the state."""
        previous_status = self.status.value  # Capture before mutation
        self.status = CMLWorkerStatus.TERMINATED
        self.service_status = CMLServiceStatus.UNAVAILABLE
        self.terminated_at = event.terminated_at
        self.terminated_by = event.terminated_by
        self.updated_at = event.terminated_at
        # TimedResource lifecycle completion (ADR-036 §2.1.4 Batch E)
        self.ended_at = event.terminated_at
        self._compute_duration()
        self._record_transition(
            from_state=previous_status,
            to_state=CMLWorkerStatus.TERMINATED.value,
            triggered_by=event.terminated_by or "system",
            reason="Worker terminated",
        )

    @dispatch(CMLWorkerTagsUpdatedDomainEvent)
    def on(self, event: CMLWorkerTagsUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Apply AWS tags update to the state."""
        self.aws_tags = event.aws_tags
        self.updated_at = event.updated_at

    @dispatch(CMLWorkerLicenseRegistrationRequestedDomainEvent)
    def on(self, event: CMLWorkerLicenseRegistrationRequestedDomainEvent) -> None:  # type: ignore[override]
        """Apply license registration requested event to the state.

        ADR-016: Stores intent for worker-controller to reconcile.
        """
        self.license = replace(
            self.license,
            pending_token=event.license_token,
            pending_operation="register",
        )
        self.updated_at = datetime.fromisoformat(event.requested_at)

    @dispatch(CMLWorkerLicenseRegistrationStartedDomainEvent)
    def on(self, event: CMLWorkerLicenseRegistrationStartedDomainEvent) -> None:  # type: ignore[override]
        """Apply license registration started event to the state."""
        self.license = replace(self.license, operation_in_progress=True)
        self.updated_at = datetime.fromisoformat(event.started_at)

    @dispatch(CMLWorkerLicenseRegistrationCompletedDomainEvent)
    def on(self, event: CMLWorkerLicenseRegistrationCompletedDomainEvent) -> None:  # type: ignore[override]
        """Apply license registration completed event to the state.

        ADR-016: Clears pending fields after successful registration.
        """
        self.license = replace(
            self.license,
            status=LicenseStatus.REGISTERED,
            token=self.license.pending_token,  # Move pending to current
            pending_token=None,
            pending_operation=None,
            operation_in_progress=False,
        )
        self.updated_at = datetime.fromisoformat(event.completed_at)

    @dispatch(CMLWorkerLicenseRegistrationFailedDomainEvent)
    def on(self, event: CMLWorkerLicenseRegistrationFailedDomainEvent) -> None:  # type: ignore[override]
        """Apply license registration failed event to the state.

        ADR-016: Clears pending fields after failed registration.
        """
        self.license = replace(
            self.license,
            pending_token=None,
            pending_operation=None,
            operation_in_progress=False,
        )
        self.updated_at = datetime.fromisoformat(event.failed_at)

    @dispatch(CMLWorkerLicenseDeregistrationRequestedDomainEvent)
    def on(self, event: CMLWorkerLicenseDeregistrationRequestedDomainEvent) -> None:  # type: ignore[override]
        """Apply license deregistration requested event to the state.

        ADR-016: Stores intent for worker-controller to reconcile.
        """
        self.license = replace(
            self.license,
            pending_operation="deregister",
        )
        self.updated_at = datetime.fromisoformat(event.requested_at)

    @dispatch(CMLWorkerLicenseDeregistrationStartedDomainEvent)
    def on(self, event: CMLWorkerLicenseDeregistrationStartedDomainEvent) -> None:  # type: ignore[override]
        """Apply license deregistration started event to the state."""
        self.license = replace(self.license, operation_in_progress=True)
        self.updated_at = datetime.fromisoformat(event.started_at)

    @dispatch(CMLWorkerLicenseDeregistrationCompletedDomainEvent)
    def on(self, event: CMLWorkerLicenseDeregistrationCompletedDomainEvent) -> None:  # type: ignore[override]
        """Apply license deregistration completed event to the state.

        ADR-016: Clears pending fields and token after successful deregistration.
        """
        self.license = replace(
            self.license,
            status=LicenseStatus.UNREGISTERED,
            token=None,
            pending_token=None,
            pending_operation=None,
            operation_in_progress=False,
        )
        self.updated_at = datetime.fromisoformat(event.completed_at)

    @dispatch(CMLWorkerLicenseDeregistrationFailedDomainEvent)
    def on(self, event: CMLWorkerLicenseDeregistrationFailedDomainEvent) -> None:  # type: ignore[override]
        """Apply license deregistration failed event to the state.

        ADR-016: Clears pending fields after failed deregistration.
        """
        self.license = replace(
            self.license,
            pending_operation=None,
            operation_in_progress=False,
        )
        self.updated_at = datetime.fromisoformat(event.failed_at)

    @dispatch(CMLWorkerLicenseDeregisteredDomainEvent)
    def on(self, event: CMLWorkerLicenseDeregisteredDomainEvent) -> None:  # type: ignore[override]
        """Apply license deregistered event to the state."""
        self.license = replace(self.license, status=LicenseStatus.UNREGISTERED, raw_info=None)
        self.updated_at = datetime.fromisoformat(event.deregistered_at)

        # Clear stale license data to prevent inconsistency
        if self.metrics.system_health:
            # Create new health object with updated license status
            new_health = replace(
                self.metrics.system_health,
                is_licensed=False,
                is_enterprise=False,
            )
            self.metrics = replace(self.metrics, system_health=new_health)

    @dispatch(WorkerDataRefreshRequestedDomainEvent)
    def on(self, event: WorkerDataRefreshRequestedDomainEvent) -> None:  # type: ignore[override]
        """Apply data refresh requested event to the state."""
        # No state changes needed - event is for notification only
        pass

    @dispatch(WorkerDataRefreshSkippedDomainEvent)
    def on(self, event: WorkerDataRefreshSkippedDomainEvent) -> None:  # type: ignore[override]
        """Apply data refresh skipped event to the state."""
        # No state changes needed - event is for notification only
        pass

    @dispatch(WorkerDataRefreshCompletedDomainEvent)
    def on(self, event: WorkerDataRefreshCompletedDomainEvent) -> None:  # type: ignore[override]
        """Apply data refresh completed event to the state."""
        # No state changes needed - event is for notification only
        pass

    @dispatch(CloudWatchMonitoringUpdatedDomainEvent)
    def on(self, event: CloudWatchMonitoringUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Apply the CloudWatch monitoring updated event to the state."""
        self.cloudwatch_detailed_monitoring_enabled = event.enabled
        self.updated_at = event.updated_at

    @dispatch(WorkerActivityUpdatedDomainEvent)
    def on(self, event: WorkerActivityUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Apply activity tracking update to the state.

        Note: Only updates last_activity_at if new activity detected (non-None).
        This prevents overwriting existing activity timestamp when no events found.
        """
        # Only update last_activity_at if new activity detected
        # This prevents resetting the timestamp when no relevant events found
        if event.last_activity_at is not None:
            self.last_activity_at = event.last_activity_at

        self.last_activity_check_at = event.last_activity_check_at
        self.recent_activity_events = event.recent_activity_events
        self.next_idle_check_at = event.next_idle_check_at
        self.target_pause_at = event.target_pause_at
        self.updated_at = event.updated_at

    @dispatch(WorkerPausedDomainEvent)
    def on(self, event: WorkerPausedDomainEvent) -> None:  # type: ignore[override]
        """Apply pause event to the state."""
        self.pause_reason = event.pause_reason
        self.paused_by = event.paused_by
        self.last_paused_at = event.paused_at
        self.auto_pause_count = event.auto_pause_count
        self.manual_pause_count = event.manual_pause_count
        self.target_pause_at = None  # Clear target since paused
        self.updated_at = event.paused_at

    @dispatch(WorkerResumedDomainEvent)
    def on(self, event: WorkerResumedDomainEvent) -> None:  # type: ignore[override]
        """Apply resume event to the state."""
        self.last_resumed_at = event.resumed_at
        self.auto_resume_count = event.auto_resume_count
        self.manual_resume_count = event.manual_resume_count
        self.target_pause_at = None  # Clear target since resumed
        # Clear pause info on resume
        if event.was_auto_paused:
            self.pause_reason = None
            self.paused_by = None
        self.updated_at = event.resumed_at

    @dispatch(IdleDetectionToggledDomainEvent)
    def on(self, event: IdleDetectionToggledDomainEvent) -> None:  # type: ignore[override]
        """Apply idle detection toggle event to the state."""
        self.is_idle_detection_enabled = event.is_enabled
        self.updated_at = event.toggled_at

    # =========================================================================
    # Capacity Management Event Handlers (Phase 1 - Lablet Integration)
    # =========================================================================

    @dispatch(CMLWorkerCapacityUpdatedDomainEvent)
    def on(self, event: CMLWorkerCapacityUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Apply capacity updated event to the state."""
        self.template_name = event.template_name
        self.declared_capacity = WorkerCapacity(
            cpu_cores=event.declared_capacity_cpu_cores,
            memory_gb=event.declared_capacity_memory_gb,
            storage_gb=event.declared_capacity_storage_gb,
            max_nodes=event.declared_capacity_max_nodes,
        )
        self.updated_at = event.updated_at

    @dispatch(CMLWorkerPortsAllocatedDomainEvent)
    def on(self, event: CMLWorkerPortsAllocatedDomainEvent) -> None:  # type: ignore[override]
        """Apply ports allocated event to the state."""
        allocation = PortAllocation(
            session_id=event.session_id,
            ports=event.ports,
            allocated_at=event.allocated_at,
        )
        # Append new allocation (create new list to avoid mutation issues)
        self.port_allocations = list(self.port_allocations) + [allocation]
        self.updated_at = event.allocated_at

    @dispatch(CMLWorkerPortsReleasedDomainEvent)
    def on(self, event: CMLWorkerPortsReleasedDomainEvent) -> None:  # type: ignore[override]
        """Apply ports released event to the state."""
        # Remove allocation for this session
        self.port_allocations = [alloc for alloc in self.port_allocations if alloc.session_id != event.session_id]
        self.updated_at = event.released_at

    @dispatch(LabletSessionAssignedDomainEvent)
    def on(self, event: LabletSessionAssignedDomainEvent) -> None:  # type: ignore[override]
        """Apply lablet session assigned event to the state."""
        # Add session to tracking list
        if event.session_id not in self.session_ids:
            self.session_ids = list(self.session_ids) + [event.session_id]

        # Update allocated capacity
        session_capacity = WorkerCapacity(
            cpu_cores=event.allocated_cpu_cores,
            memory_gb=event.allocated_memory_gb,
            storage_gb=event.allocated_storage_gb,
            max_nodes=event.allocated_nodes,
        )
        self.allocated_capacity = self.allocated_capacity.add(session_capacity)
        self.updated_at = event.assigned_at

    @dispatch(LabletSessionRemovedDomainEvent)
    def on(self, event: LabletSessionRemovedDomainEvent) -> None:  # type: ignore[override]
        """Apply lablet session removed event to the state."""
        # Remove session from tracking list
        self.session_ids = [sid for sid in self.session_ids if sid != event.session_id]

        # Release capacity (subtract from allocated)
        released_capacity = WorkerCapacity(
            cpu_cores=event.released_cpu_cores,
            memory_gb=event.released_memory_gb,
            storage_gb=event.released_storage_gb,
            max_nodes=event.released_nodes,
        )
        self.allocated_capacity = WorkerCapacity(
            cpu_cores=max(0, self.allocated_capacity.cpu_cores - released_capacity.cpu_cores),
            memory_gb=max(0, self.allocated_capacity.memory_gb - released_capacity.memory_gb),
            storage_gb=max(0, self.allocated_capacity.storage_gb - released_capacity.storage_gb),
            max_nodes=(max(0, (self.allocated_capacity.max_nodes or 0) - (released_capacity.max_nodes or 0)) if self.allocated_capacity.max_nodes is not None else None),
        )
        self.updated_at = event.removed_at

    @dispatch(AllocatedCapacityRecalculatedDomainEvent)
    def on(self, event: AllocatedCapacityRecalculatedDomainEvent) -> None:  # type: ignore[override]
        """Apply allocated capacity recalculation event to the state.

        Directly replaces allocated_capacity and session_ids with
        recomputed values. Used as a repair mechanism for drifted data.
        """
        self.session_ids = list(event.active_session_ids)
        self.allocated_capacity = WorkerCapacity(
            cpu_cores=event.recalculated_cpu_cores,
            memory_gb=event.recalculated_memory_gb,
            storage_gb=event.recalculated_storage_gb,
            max_nodes=event.recalculated_max_nodes,
        )
        self.updated_at = event.recalculated_at


class InvalidCMLWorkerTransitionError(Exception):
    """Raised when an invalid CMLWorker state transition is attempted."""

    def __init__(self, from_status: CMLWorkerStatus, to_status: CMLWorkerStatus, message: str | None = None):
        self.from_status = from_status
        self.to_status = to_status
        self.message = message or f"Invalid CMLWorker transition from {from_status.value} to {to_status.value}"
        super().__init__(self.message)


class CMLWorker(AggregateRoot[CMLWorkerState, str]):
    """CML Worker aggregate root following the AggregateState pattern.

    Represents an AWS EC2 instance running Cisco Modeling Lab (CML).
    """

    def __init__(
        self,
        name: str,
        aws_region: str,
        instance_type: str,
        ami_id: str | None = None,
        ami_name: str | None = None,
        ami_description: str | None = None,
        ami_creation_date: str | None = None,
        aws_instance_id: str | None = None,
        status: CMLWorkerStatus = CMLWorkerStatus.PENDING,
        cml_version: str | None = None,
        created_at: datetime | None = None,
        created_by: str | None = None,
        worker_id: str | None = None,
        origin: WorkerOrigin = WorkerOrigin.USER_CREATED,
    ) -> None:
        """Initialize a new CML Worker.

        Args:
            name: Human-readable name for the worker
            aws_region: AWS region where the instance is/will be hosted
            instance_type: EC2 instance type (e.g., 't3.xlarge', 'c5.2xlarge')
            ami_id: AWS AMI ID to create the instance from (e.g., 'ami-0123456789abcdef0')
            ami_name: Human-readable AMI name
            aws_instance_id: AWS EC2 instance ID (if already provisioned)
            status: Initial worker status
            cml_version: CML version to be installed
            created_at: Creation timestamp
            created_by: User ID who created the worker
            worker_id: Optional worker ID (generates UUID if not provided)
        """
        super().__init__()
        aggregate_id = worker_id or str(uuid4())
        created_time = created_at or datetime.now(timezone.utc)

        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerCreatedDomainEvent(
                    aggregate_id=aggregate_id,
                    name=name,
                    aws_region=aws_region,
                    aws_instance_id=aws_instance_id,
                    instance_type=instance_type,
                    ami_id=ami_id,
                    ami_name=ami_name,
                    ami_description=ami_description,
                    ami_creation_date=ami_creation_date,
                    status=status,
                    cml_version=cml_version,
                    created_at=created_time,
                    created_by=created_by,
                    origin=origin,
                )
            )
        )

    @staticmethod
    def import_from_existing_instance(
        name: str,
        aws_region: str,
        aws_instance_id: str,
        instance_type: str,
        ami_id: str,
        instance_state: str,
        created_by: str | None = None,
        ami_name: str | None = None,
        ami_description: str | None = None,
        ami_creation_date: str | None = None,
        public_ip: str | None = None,
        private_ip: str | None = None,
        origin: WorkerOrigin = WorkerOrigin.EC2_DISCOVERY,
    ) -> "CMLWorker":
        """Factory method to import an existing EC2 instance as a CML Worker.

        This creates a worker from an already-provisioned EC2 instance without
        creating a new instance. Used for registering instances that were
        created outside of the Lablet Cloud Manager system.

        Args:
            name: Friendly name for the worker
            aws_region: AWS region where instance exists
            aws_instance_id: AWS EC2 instance ID
            instance_type: EC2 instance type (e.g., 'c5.2xlarge')
            ami_id: AMI ID used by the instance
            instance_state: Current EC2 state (running, stopped, etc.)
            created_by: User who initiated the import
            ami_name: Optional AMI name
            public_ip: Optional public IP address
            private_ip: Optional private IP address

        Returns:
            New CMLWorker aggregate with imported instance details
        """
        worker_id = str(uuid4())
        created_at = datetime.now(timezone.utc)

        # Create a new worker instance without going through __init__
        # to avoid generating a creation event
        worker = object.__new__(CMLWorker)
        AggregateRoot.__init__(worker)

        # Register and apply the import event
        event = CMLWorkerImportedDomainEvent(
            aggregate_id=worker_id,
            name=name,
            aws_region=aws_region,
            aws_instance_id=aws_instance_id,
            instance_type=instance_type,
            ami_id=ami_id,
            ami_name=ami_name,
            ami_description=ami_description,
            ami_creation_date=ami_creation_date,
            instance_state=instance_state,
            public_ip=public_ip,
            private_ip=private_ip,
            created_by=created_by,
            created_at=created_at,
            origin=origin,
        )

        worker.state.on(worker.register_event(event))  # type: ignore
        return worker

    def get_effective_endpoint(self, use_private_ip: bool = False) -> str:
        """Get the effective HTTPS endpoint for the worker.

        Args:
            use_private_ip: Whether to prefer the private IP address.

        Returns:
            The HTTPS endpoint URL.
        """
        https_endpoint = self.state.https_endpoint
        if not https_endpoint:
            return ""

        if use_private_ip and self.state.private_ip:
            try:
                parsed = urlparse(https_endpoint)
                # Construct new netloc with private IP, preserving port if present
                new_netloc = self.state.private_ip
                if parsed.port:
                    new_netloc = f"{new_netloc}:{parsed.port}"

                return parsed._replace(netloc=new_netloc).geturl()
            except Exception:  # nosec
                # Fallback to original endpoint if parsing fails
                pass

        return https_endpoint

    def id(self) -> str:
        """Return the aggregate identifier with a precise type."""
        aggregate_id = super().id()
        if aggregate_id is None:
            raise ValueError("CMLWorker aggregate identifier has not been initialized")
        return cast(str, aggregate_id)

    # =========================================================================
    # STATE MACHINE GUARD
    # =========================================================================

    def _validate_transition(self, to_status: CMLWorkerStatus) -> bool:
        """Validate that a state transition is allowed.

        Unlike LabRecord (which raises), this logs a warning and returns False
        for invalid transitions.  The reconciler receives status from AWS EC2
        which may skip intermediate states, so we must never block reconciliation.

        Returns:
            True if the transition is valid, False otherwise.
        """
        import logging

        valid_targets = CML_WORKER_VALID_TRANSITIONS.get(self.state.status, [])
        if to_status not in valid_targets:
            logger = logging.getLogger(__name__)
            logger.warning(
                "CMLWorker %s: unexpected transition %s → %s (allowed: %s). Proceeding anyway — reconciler must not be blocked.",
                self.id(),
                self.state.status.value,
                to_status.value,
                [s.value for s in valid_targets],
            )
            return False
        return True

    def update_status(self, new_status: CMLWorkerStatus) -> bool:
        """Update the EC2 instance status.

        Args:
            new_status: New worker status

        Returns:
            True if status was changed, False if already at that status
        """
        if self.state.status == new_status:
            return False

        self._validate_transition(new_status)

        old_status = self.state.status
        now = datetime.now(timezone.utc)
        transition_ts: datetime | None = None
        if new_status in (CMLWorkerStatus.PENDING, CMLWorkerStatus.STOPPING):
            transition_ts = now
        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerStatusUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    old_status=old_status,
                    new_status=new_status,
                    updated_at=now,
                    transition_initiated_at=transition_ts,
                )
            )
        )
        return True

    def update_desired_status(
        self,
        new_desired_status: CMLWorkerStatus,
        requested_by: str | None = None,
        reason: str | None = None,
    ) -> bool:
        """Update the desired status (spec) - what the user wants.

        This follows the Kubernetes-like reconciliation pattern:
        - desired_status = spec (what user wants)
        - status = state (actual EC2 state)

        The worker-controller watches for desired_status changes and
        reconciles actual state to match.

        Args:
            new_desired_status: Target status the user wants
            requested_by: User or system requesting the change
            reason: Optional reason for the change

        Returns:
            True if desired_status was changed, False if already at target
        """
        if self.state.desired_status == new_desired_status:
            return False

        old_desired_status = self.state.desired_status
        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerDesiredStatusUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    old_desired_status=old_desired_status,
                    new_desired_status=new_desired_status,
                    updated_at=datetime.now(timezone.utc),
                    requested_by=requested_by,
                    reason=reason,
                )
            )
        )
        return True

    def update_service_status(
        self,
        new_service_status: CMLServiceStatus,
        https_endpoint: str | None = None,
    ) -> bool:
        """Update the CML HTTPS service status.

        Args:
            new_service_status: New service availability status
            https_endpoint: HTTPS endpoint URL (if available)

        Returns:
            True if status was changed, False if already at that status
        """
        if self.state.service_status == new_service_status and self.state.https_endpoint == https_endpoint:
            return False

        old_service_status = self.state.service_status
        self.state.on(
            self.register_event(  # type: ignore
                CMLServiceStatusUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    old_service_status=old_service_status,
                    new_service_status=new_service_status,
                    https_endpoint=https_endpoint,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        )
        return True

    def assign_instance(
        self,
        aws_instance_id: str,
        public_ip: str | None = None,
        private_ip: str | None = None,
    ) -> None:
        """Assign AWS EC2 instance details to the worker.

        Args:
            aws_instance_id: AWS EC2 instance ID
            public_ip: Public IP address
            private_ip: Private IP address
        """
        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerInstanceAssignedDomainEvent(
                    aggregate_id=self.id(),
                    aws_instance_id=aws_instance_id,
                    public_ip=public_ip,
                    private_ip=private_ip,
                    assigned_at=datetime.now(timezone.utc),
                )
            )
        )

    def update_license(
        self,
        license_status: LicenseStatus,
        license_token: str | None = None,
    ) -> bool:
        """Update the CML license status.

        Args:
            license_status: New license status
            license_token: License token/registration key

        Returns:
            True if license was updated, False if unchanged
        """
        if self.state.license.status == license_status and self.state.license.token == license_token:
            return False

        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerLicenseUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    license_status=license_status,
                    license_token=license_token,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        )
        return True

    def update_ec2_metrics(
        self,
        instance_state_detail: str,
        system_status_check: str,
        checked_at: datetime | None = None,
    ) -> None:
        """Update EC2 instance health metrics from AWS EC2 API.

        Args:
            instance_state_detail: Instance status check (e.g., "ok", "impaired")
            system_status_check: System status check (e.g., "ok", "impaired")
            checked_at: Timestamp of the status check
        """
        self.state.on(
            self.register_event(  # type: ignore
                EC2MetricsUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    instance_state_detail=instance_state_detail,
                    system_status_check=system_status_check,
                    checked_at=checked_at or datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
        )

    def update_ec2_instance_details(
        self,
        public_ip: str | None = None,
        private_ip: str | None = None,
        instance_type: str | None = None,
        ami_id: str | None = None,
        ami_name: str | None = None,
        ami_description: str | None = None,
        ami_creation_date: str | None = None,
    ) -> None:
        """Update EC2 instance details from AWS EC2 API.

        Args:
            public_ip: Public IP address of the instance
            private_ip: Private IP address of the instance
            instance_type: EC2 instance type (e.g., "t3.medium")
            ami_id: AMI ID used to launch the instance
            ami_name: AMI name/description
        """
        self.state.on(
            self.register_event(  # type: ignore
                EC2InstanceDetailsUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    public_ip=public_ip,
                    private_ip=private_ip,
                    instance_type=instance_type,
                    ami_id=ami_id,
                    ami_name=ami_name,
                    ami_description=ami_description,
                    ami_creation_date=ami_creation_date,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        )

    def update_aws_tags(self, aws_tags: dict[str, str]) -> None:
        """Update AWS tags for the EC2 instance.

        Args:
            aws_tags: Dictionary of AWS tags (key-value pairs)
        """
        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerTagsUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    aws_tags=aws_tags,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        )

    def update_cloudwatch_metrics(
        self,
        cpu_utilization: float,
        memory_utilization: float,
        collected_at: datetime | None = None,
    ) -> None:
        """Update CloudWatch metrics from AWS CloudWatch API.

        Args:
            cpu_utilization: CPU utilization percentage (0-100)
            memory_utilization: Memory utilization percentage (0-100)
            collected_at: Timestamp when metrics were collected
        """
        self.state.on(
            self.register_event(  # type: ignore
                CloudWatchMetricsUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    cpu_utilization=cpu_utilization,
                    memory_utilization=memory_utilization,
                    collected_at=collected_at or datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
        )

    def update_cml_metrics(
        self,
        cml_version: str | None,
        system_info: dict,
        system_health: dict | None,
        license_info: dict | None,
        ready: bool,
        uptime_seconds: int | None,
        labs_count: int,
        synced_at: datetime | None = None,
        change_threshold_percent: float | None = None,
    ) -> None:
        """Update CML application metrics from CML API.

        Args:
            cml_version: CML version string (e.g., "2.9.0")
            system_info: Full system information dictionary from CML
            system_health: System health checks from CML
            license_info: License information from CML (registration, authorization, features)
            ready: CML application ready state
            uptime_seconds: CML uptime in seconds
            labs_count: Number of labs from CML API
            synced_at: Timestamp when data was synced from CML API
        """
        # Domain-level suppression: only emit event if meaningful delta
        # Always emit when no prior system_info or threshold not provided
        emit_event = True
        if change_threshold_percent is not None and self.state.metrics.system_info:
            try:
                prev_metrics = self.state.metrics
                prev_cpu, prev_mem, prev_storage = prev_metrics.get_utilization()

                # Calculate new utilization using temporary metrics object
                # This avoids duplicating the calculation logic
                temp_metrics = CMLMetrics(
                    system_info=CMLSystemInfo(
                        cpu_utilization=system_info.get("all_cpu_percent"),
                        memory_total=system_info.get("all_memory_total"),
                        memory_used=system_info.get("all_memory_used"),
                        disk_total=system_info.get("all_disk_total"),
                        disk_used=system_info.get("all_disk_used"),
                        running_nodes=system_info.get("running_nodes"),
                        total_nodes=system_info.get("total_nodes"),
                        computes=system_info.get("computes", {}),
                    )
                )
                new_cpu, new_mem, new_storage = temp_metrics.get_utilization()

                def pct_changed(old: float | None, new: float | None) -> float:
                    if old is None or new is None:
                        return 100.0 if old != new else 0.0
                    if old == 0:
                        return 100.0 if new != 0 else 0.0
                    return abs(new - old) / abs(old) * 100.0

                cpu_delta = pct_changed(prev_cpu, new_cpu)
                mem_delta = pct_changed(prev_mem, new_mem)
                storage_delta = pct_changed(prev_storage, new_storage)
                labs_changed = labs_count != self.state.metrics.labs_count
                version_changed = cml_version != self.state.metrics.version

                # Check for license changes
                license_changed = False
                if license_info:
                    current_reg = self.state.license.raw_info.get("registration_status") if self.state.license.raw_info else None
                    new_reg = license_info.get("registration_status")
                    if current_reg != new_reg:
                        license_changed = True
                    elif self.state.license.status == LicenseStatus.UNREGISTERED and new_reg == "COMPLETED":
                        license_changed = True

                # Check for system health changes (is_licensed)
                health_changed = False
                if system_health:
                    current_licensed = self.state.metrics.system_health.is_licensed if self.state.metrics.system_health else False
                    new_licensed = system_health.get("is_licensed", False)
                    if current_licensed != new_licensed:
                        health_changed = True

                emit_event = (
                    labs_changed
                    or version_changed
                    or license_changed
                    or health_changed
                    or cpu_delta >= change_threshold_percent
                    or mem_delta >= change_threshold_percent
                    or storage_delta >= change_threshold_percent
                )
            except Exception:
                # Fail open: emit event if derivation fails
                emit_event = True

        if not emit_event:
            return

        self.state.on(
            self.register_event(  # type: ignore
                CMLMetricsUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    cml_version=cml_version,
                    system_info=system_info,
                    system_health=system_health,
                    license_info=license_info,
                    ready=ready,
                    uptime_seconds=uptime_seconds,
                    labs_count=labs_count,
                    synced_at=synced_at or datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
        )

    def update_telemetry(
        self,
        last_activity_at: datetime,
        active_labs_count: int,
        cpu_utilization: float | None = None,
        memory_utilization: float | None = None,
        poll_interval: int | None = None,
        next_refresh_at: datetime | None = None,
    ) -> None:
        """Update worker telemetry data (DEPRECATED - use source-specific methods).

        This method is kept for backward compatibility. New code should use:
        - update_ec2_metrics() for EC2 instance status
        - update_cloudwatch_metrics() for CPU/memory metrics
        - update_cml_metrics() for CML application data

        Args:
            last_activity_at: Timestamp of last detected activity
            active_labs_count: Number of active labs running
            cpu_utilization: CPU utilization percentage (0-100)
            memory_utilization: Memory utilization percentage (0-100)
            poll_interval: Metrics collection interval in seconds (for countdown timer)
            next_refresh_at: Next scheduled metrics collection time (for countdown timer)
        """
        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerTelemetryUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    last_activity_at=last_activity_at,
                    active_labs_count=active_labs_count,
                    cpu_utilization=cpu_utilization,
                    memory_utilization=memory_utilization,
                    updated_at=datetime.now(timezone.utc),
                    poll_interval=poll_interval,
                    next_refresh_at=next_refresh_at,
                )
            )
        )

    def update_endpoint(
        self,
        https_endpoint: str | None,
        public_ip: str | None = None,
    ) -> bool:
        """Update the worker's HTTPS endpoint.

        Args:
            https_endpoint: HTTPS endpoint URL
            public_ip: Updated public IP address

        Returns:
            True if endpoint was updated, False if unchanged
        """
        if self.state.https_endpoint == https_endpoint and (public_ip is None or self.state.public_ip == public_ip):
            return False

        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerEndpointUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    https_endpoint=https_endpoint,
                    public_ip=public_ip,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        )
        return True

    def request_refresh(self) -> None:
        """Request an on-demand data refresh for this worker.

        Sets refresh_requested_at timestamp. The worker-controller reconciler
        checks this field and performs a full data collection (EC2 details + CML data)
        when it's set, then clears it after completion.
        """
        self.state.refresh_requested_at = datetime.now(timezone.utc)
        self.state.updated_at = datetime.now(timezone.utc)

    def clear_refresh_request(self) -> None:
        """Clear the on-demand refresh request after completion.

        Called by the CPA when worker-controller reports back the refreshed data.
        """
        self.state.refresh_requested_at = None
        self.state.updated_at = datetime.now(timezone.utc)

    def update_cloudwatch_monitoring(self, enabled: bool) -> bool:
        """Update the worker's CloudWatch detailed monitoring status.

        Args:
            enabled: Whether detailed monitoring is enabled

        Returns:
            True if monitoring status was updated, False if unchanged
        """
        if self.state.cloudwatch_detailed_monitoring_enabled == enabled:
            return False

        self.state.on(
            self.register_event(  # type: ignore
                CloudWatchMonitoringUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    enabled=enabled,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        )
        return True

    def terminate(self, terminated_by: str | None = None) -> None:
        """Mark the worker as terminated.

        Args:
            terminated_by: User ID who terminated the worker
        """
        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerTerminatedDomainEvent(
                    aggregate_id=self.id(),
                    name=self.state.name,
                    terminated_at=datetime.now(timezone.utc),
                    terminated_by=terminated_by,
                )
            )
        )

    def request_license_registration(
        self,
        license_token: str,
        initiated_by: str | None = None,
        reregister: bool = False,
    ) -> None:
        """Request license registration (ADR-016: stores intent).

        Control-plane-api calls this to store the desired license token.
        Worker-controller will reconcile by calling the CML API.

        Args:
            license_token: The license token to register
            initiated_by: User ID who initiated registration
            reregister: Whether to re-register an existing license
        """
        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerLicenseRegistrationRequestedDomainEvent(
                    aggregate_id=self.id(),
                    worker_id=self.id(),
                    license_token=license_token,
                    reregister=reregister,
                    requested_at=datetime.now(timezone.utc).isoformat(),
                    initiated_by=initiated_by or "system",
                )
            )
        )

    def request_license_deregistration(
        self,
        initiated_by: str | None = None,
    ) -> None:
        """Request license deregistration (ADR-016: stores intent).

        Control-plane-api calls this to request license deregistration.
        Worker-controller will reconcile by calling the CML API.

        Args:
            initiated_by: User ID who initiated deregistration
        """
        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerLicenseDeregistrationRequestedDomainEvent(
                    aggregate_id=self.id(),
                    worker_id=self.id(),
                    requested_at=datetime.now(timezone.utc).isoformat(),
                    initiated_by=initiated_by or "system",
                )
            )
        )

    def start_license_registration(
        self,
        started_at: str,
        initiated_by: str | None,
    ) -> None:
        """Start license registration process.

        Args:
            started_at: ISO timestamp when registration started
            initiated_by: User ID who initiated registration
        """
        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerLicenseRegistrationStartedDomainEvent(
                    aggregate_id=self.id(),
                    worker_id=self.id(),
                    started_at=started_at,
                    initiated_by=initiated_by or "system",
                )
            )
        )

    def complete_license_registration(
        self,
        registration_status: str,
        smart_account: str | None,
        virtual_account: str | None,
        completed_at: str,
    ) -> None:
        """Complete license registration successfully.

        Args:
            registration_status: CML registration status (e.g., "COMPLETED")
            smart_account: Smart Licensing account name
            virtual_account: Virtual account name
            completed_at: ISO timestamp when registration completed
        """
        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerLicenseRegistrationCompletedDomainEvent(
                    aggregate_id=self.id(),
                    worker_id=self.id(),
                    registration_status=registration_status,
                    smart_account=smart_account,
                    virtual_account=virtual_account,
                    completed_at=completed_at,
                )
            )
        )

    def fail_license_registration(
        self,
        error_message: str,
        failed_at: str,
        error_code: str | None = None,
    ) -> None:
        """Fail license registration.

        Args:
            error_message: Error description
            failed_at: ISO timestamp when registration failed
            error_code: Optional error code from CML
        """
        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerLicenseRegistrationFailedDomainEvent(
                    aggregate_id=self.id(),
                    worker_id=self.id(),
                    error_message=error_message,
                    error_code=error_code,
                    failed_at=failed_at,
                )
            )
        )

    def start_license_deregistration(
        self,
        started_at: str,
        initiated_by: str | None,
    ) -> None:
        """Start license deregistration process.

        Args:
            started_at: ISO timestamp when deregistration started
            initiated_by: User ID who initiated deregistration
        """
        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerLicenseDeregistrationStartedDomainEvent(
                    aggregate_id=self.id(),
                    worker_id=self.id(),
                    started_at=started_at,
                    initiated_by=initiated_by or "system",
                )
            )
        )

    def complete_license_deregistration(
        self,
        message: str,
        completed_at: str,
    ) -> None:
        """Complete license deregistration successfully.

        Args:
            message: Success message from CML API
            completed_at: ISO timestamp when deregistration completed
        """
        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerLicenseDeregistrationCompletedDomainEvent(
                    aggregate_id=self.id(),
                    worker_id=self.id(),
                    message=message,
                    completed_at=completed_at,
                )
            )
        )

    def fail_license_deregistration(
        self,
        error_message: str,
        failed_at: str,
    ) -> None:
        """Mark license deregistration as failed.

        Args:
            error_message: Error message describing failure
            failed_at: ISO timestamp when deregistration failed
        """
        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerLicenseDeregistrationFailedDomainEvent(
                    aggregate_id=self.id(),
                    worker_id=self.id(),
                    error_message=error_message,
                    failed_at=failed_at,
                )
            )
        )

    def deregister_license(
        self,
        deregistered_at: str,
        initiated_by: str | None,
    ) -> None:
        """Deregister license.

        Args:
            deregistered_at: ISO timestamp when deregistration completed
            initiated_by: User ID who initiated deregistration
        """
        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerLicenseDeregisteredDomainEvent(
                    aggregate_id=self.id(),
                    worker_id=self.id(),
                    deregistered_at=deregistered_at,
                    initiated_by=initiated_by or "system",
                )
            )
        )

    def request_data_refresh(
        self,
        requested_at: str,
        requested_by: str,
    ) -> None:
        """Request worker data refresh.

        Args:
            requested_at: ISO timestamp when refresh was requested
            requested_by: User ID who requested refresh
        """
        self.state.on(
            self.register_event(  # type: ignore
                WorkerDataRefreshRequestedDomainEvent(
                    aggregate_id=self.id(),
                    worker_id=self.id(),
                    requested_at=requested_at,
                    requested_by=requested_by,
                )
            )
        )

    def skip_data_refresh(
        self,
        reason: str,
        skipped_at: str,
    ) -> None:
        """Skip worker data refresh.

        Args:
            reason: Reason why refresh was skipped
            skipped_at: ISO timestamp when refresh was skipped
        """
        self.state.on(
            self.register_event(  # type: ignore
                WorkerDataRefreshSkippedDomainEvent(
                    aggregate_id=self.id(),
                    worker_id=self.id(),
                    reason=reason,
                    skipped_at=skipped_at,
                )
            )
        )

    def complete_data_refresh(
        self,
        completed_at: str,
        refresh_type: str,
    ) -> None:
        """Complete worker data refresh.

        Args:
            completed_at: ISO timestamp when refresh completed
            refresh_type: Type of refresh ('scheduled' or 'on_demand')
        """
        self.state.on(
            self.register_event(  # type: ignore
                WorkerDataRefreshCompletedDomainEvent(
                    aggregate_id=self.id(),
                    worker_id=self.id(),
                    completed_at=completed_at,
                    refresh_type=refresh_type,
                )
            )
        )

    def is_idle(self, idle_threshold_minutes: int) -> bool:
        """Check if the worker has been idle beyond the threshold.

        Args:
            idle_threshold_minutes: Idle threshold in minutes

        Returns:
            True if worker is idle beyond threshold, False otherwise
        """
        # Check last activity from either CloudWatch or CML metrics
        last_activity = self.state.cloudwatch_last_collected_at or self.state.metrics.last_synced_at
        if not last_activity:
            return False

        if self.state.metrics.labs_count > 0:
            return False

        now = datetime.now(timezone.utc)
        idle_duration = now - last_activity
        return idle_duration.total_seconds() / 60 >= idle_threshold_minutes

    def can_connect(self) -> bool:
        """Check if the worker is ready for user connections.

        Returns:
            True if worker is running and service is available
        """
        return self.state.status == CMLWorkerStatus.RUNNING and self.state.service_status == CMLServiceStatus.AVAILABLE and self.state.https_endpoint is not None

    def update_activity(
        self,
        recent_events: list[dict],
        last_activity_at: datetime | None,
        last_check_at: datetime,
        next_check_at: datetime | None,
        target_pause_at: datetime | None,
        max_events: int = 10,
    ) -> None:
        """Update worker activity tracking.

        Args:
            recent_events: List of recent relevant telemetry events
            last_activity_at: Timestamp of last detected activity (None = no new activity)
            last_check_at: Timestamp when telemetry was checked
            next_check_at: Next scheduled idle check time
            target_pause_at: Calculated auto-pause time if no activity
            max_events: Maximum number of events to store (default: 10)

        Note:
            If last_activity_at is None, the existing last_activity_at in state
            is preserved. This prevents resetting the activity timestamp when
            no relevant events are found during a check.
        """
        # Keep only the most recent N events
        events_to_store = recent_events[-max_events:] if recent_events else []

        self.state.on(
            self.register_event(  # type: ignore
                WorkerActivityUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    last_activity_at=last_activity_at,
                    last_activity_check_at=last_check_at,
                    recent_activity_events=events_to_store,
                    next_idle_check_at=next_check_at,
                    target_pause_at=target_pause_at,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        )

    def pause(
        self,
        reason: str,
        paused_by: str | None = None,
        idle_duration_minutes: float | None = None,
    ) -> None:
        """Record worker pause (stop).

        Args:
            reason: Pause reason ("idle_timeout", "manual", "external")
            paused_by: User ID or "system" for auto-pause
            idle_duration_minutes: Idle time before auto-pause (for idle_timeout reason)
        """
        # Increment appropriate counter
        auto_count = self.state.auto_pause_count
        manual_count = self.state.manual_pause_count

        if reason == "idle_timeout":
            auto_count += 1
        else:
            manual_count += 1

        paused_at = datetime.now(timezone.utc)

        self.state.on(
            self.register_event(  # type: ignore
                WorkerPausedDomainEvent(
                    aggregate_id=self.id(),
                    pause_reason=reason,
                    paused_by=paused_by,
                    paused_at=paused_at,
                    auto_pause_count=auto_count,
                    manual_pause_count=manual_count,
                    idle_duration_minutes=idle_duration_minutes,
                )
            )
        )

    def resume(
        self,
        reason: str = "manual",
        resumed_by: str | None = None,
    ) -> None:
        """Record worker resume (start).

        Args:
            reason: Resume reason ("manual", "external", "auto")
            resumed_by: User ID or None for external/auto
        """
        # Increment appropriate counter
        auto_count = self.state.auto_resume_count
        manual_count = self.state.manual_resume_count

        if reason == "auto":
            auto_count += 1
        elif reason == "manual":
            manual_count += 1
        # external doesn't increment either counter

        resumed_at = datetime.now(timezone.utc)
        was_auto_paused = self.state.pause_reason == "idle_timeout"

        self.state.on(
            self.register_event(  # type: ignore
                WorkerResumedDomainEvent(
                    aggregate_id=self.id(),
                    resume_reason=reason,
                    resumed_by=resumed_by,
                    resumed_at=resumed_at,
                    auto_resume_count=auto_count,
                    manual_resume_count=manual_count,
                    was_auto_paused=was_auto_paused,
                )
            )
        )

    def in_snooze_period(self, snooze_minutes: int) -> bool:
        """Check if worker is in snooze period (protected from auto-pause).

        Args:
            snooze_minutes: Snooze period duration in minutes

        Returns:
            True if in snooze period, False otherwise
        """
        if not self.state.last_resumed_at:
            return False

        now = datetime.now(timezone.utc)
        elapsed = now - self.state.last_resumed_at
        return elapsed.total_seconds() / 60 < snooze_minutes

    def calculate_idle_duration(self) -> float | None:
        """Calculate current idle duration in minutes.

        Returns:
            Idle duration in minutes, or None if no activity tracked
        """
        if not self.state.last_activity_at:
            return None

        now = datetime.now(timezone.utc)
        idle_duration = now - self.state.last_activity_at
        return idle_duration.total_seconds() / 60

    def enable_idle_detection(self, enabled_by: str | None = None) -> None:
        """Enable idle detection for this worker.

        Args:
            enabled_by: User ID who enabled idle detection
        """
        # Only emit event if currently disabled
        if not self.state.is_idle_detection_enabled:
            self.state.on(
                self.register_event(  # type: ignore
                    IdleDetectionToggledDomainEvent(
                        aggregate_id=self.id(),
                        is_enabled=True,
                        toggled_by=enabled_by,
                        toggled_at=datetime.now(timezone.utc),
                    )
                )
            )

    def disable_idle_detection(self, disabled_by: str | None = None) -> None:
        """Disable idle detection for this worker.

        Args:
            disabled_by: User ID who disabled idle detection
        """
        # Only emit event if currently enabled
        if self.state.is_idle_detection_enabled:
            self.state.on(
                self.register_event(  # type: ignore
                    IdleDetectionToggledDomainEvent(
                        aggregate_id=self.id(),
                        is_enabled=False,
                        toggled_by=disabled_by,
                        toggled_at=datetime.now(timezone.utc),
                    )
                )
            )

    # =========================================================================
    # Capacity Management Methods (Phase 1 - Lablet Integration)
    # =========================================================================

    def update_capacity(
        self,
        template_name: str | None,
        cpu_cores: int,
        memory_gb: int,
        storage_gb: int,
        max_nodes: int | None = None,
    ) -> None:
        """Update the worker's declared capacity.

        Args:
            template_name: Name of the worker template
            cpu_cores: Total CPU cores available
            memory_gb: Total memory in GB
            storage_gb: Total storage in GB
            max_nodes: Maximum CML node count (optional)
        """
        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerCapacityUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    template_name=template_name,
                    declared_capacity_cpu_cores=cpu_cores,
                    declared_capacity_memory_gb=memory_gb,
                    declared_capacity_storage_gb=storage_gb,
                    declared_capacity_max_nodes=max_nodes,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        )

    def allocate_ports(
        self,
        session_id: str,
        ports: dict[str, int],
    ) -> None:
        """Allocate ports for a lablet session.

        Args:
            session_id: LabletSession ID
            ports: Mapping of logical names to port numbers
        """
        self.state.on(
            self.register_event(  # type: ignore
                CMLWorkerPortsAllocatedDomainEvent(
                    aggregate_id=self.id(),
                    session_id=session_id,
                    ports=ports,
                    allocated_at=datetime.now(timezone.utc),
                )
            )
        )

    def release_ports(self, session_id: str) -> None:
        """Release ports allocated to a lablet session.

        Args:
            session_id: LabletSession ID whose ports to release
        """
        # Find the allocation to determine which ports to release
        allocation = next(
            (a for a in self.state.port_allocations if a.session_id == session_id),
            None,
        )
        if allocation:
            self.state.on(
                self.register_event(  # type: ignore
                    CMLWorkerPortsReleasedDomainEvent(
                        aggregate_id=self.id(),
                        session_id=session_id,
                        released_ports=list(allocation.ports.values()),
                        released_at=datetime.now(timezone.utc),
                    )
                )
            )

    def assign_lablet_session(
        self,
        session_id: str,
        cpu_cores: int,
        memory_gb: int,
        storage_gb: int,
        max_nodes: int | None = None,
    ) -> None:
        """Assign a lablet session to this worker.

        Args:
            session_id: LabletSession ID
            cpu_cores: CPU cores required
            memory_gb: Memory required in GB
            storage_gb: Storage required in GB
            max_nodes: Node count for this session
        """
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionAssignedDomainEvent(
                    aggregate_id=self.id(),
                    session_id=session_id,
                    allocated_cpu_cores=cpu_cores,
                    allocated_memory_gb=memory_gb,
                    allocated_storage_gb=storage_gb,
                    allocated_nodes=max_nodes,
                    assigned_at=datetime.now(timezone.utc),
                )
            )
        )

    def remove_lablet_session(
        self,
        session_id: str,
        cpu_cores: int,
        memory_gb: int,
        storage_gb: int,
        max_nodes: int | None = None,
    ) -> None:
        """Remove a lablet session from this worker.

        Args:
            session_id: LabletSession ID to remove
            cpu_cores: CPU cores to release
            memory_gb: Memory to release in GB
            storage_gb: Storage to release in GB
            max_nodes: Node count to release
        """
        self.state.on(
            self.register_event(  # type: ignore
                LabletSessionRemovedDomainEvent(
                    aggregate_id=self.id(),
                    session_id=session_id,
                    released_cpu_cores=cpu_cores,
                    released_memory_gb=memory_gb,
                    released_storage_gb=storage_gb,
                    released_nodes=max_nodes,
                    removed_at=datetime.now(timezone.utc),
                )
            )
        )

    def recalculate_capacity(
        self,
        recalculated_cpu_cores: int,
        recalculated_memory_gb: int,
        recalculated_storage_gb: int,
        recalculated_max_nodes: int | None,
        active_session_ids: list[str],
        stale_session_ids: list[str],
    ) -> None:
        """Recalculate allocated capacity from scratch.

        Repair mechanism for when allocated_capacity has drifted due to
        bugs in session lifecycle handlers. Directly replaces allocated_capacity
        and session_ids with recomputed values.

        Args:
            recalculated_cpu_cores: Correct total CPU cores allocated
            recalculated_memory_gb: Correct total memory in GB allocated
            recalculated_storage_gb: Correct total storage in GB allocated
            recalculated_max_nodes: Correct total node count allocated
            active_session_ids: Session IDs that are actually still active
            stale_session_ids: Session IDs that were tracked but are no longer active
        """
        self.state.on(
            self.register_event(  # type: ignore
                AllocatedCapacityRecalculatedDomainEvent(
                    aggregate_id=self.id(),
                    recalculated_cpu_cores=recalculated_cpu_cores,
                    recalculated_memory_gb=recalculated_memory_gb,
                    recalculated_storage_gb=recalculated_storage_gb,
                    recalculated_max_nodes=recalculated_max_nodes,
                    active_session_ids=active_session_ids,
                    stale_session_ids=stale_session_ids,
                    recalculated_at=datetime.now(timezone.utc),
                )
            )
        )

    # =========================================================================
    # Capacity Computed Properties (Phase 1 - Lablet Integration)
    # =========================================================================

    @property
    def available_capacity(self) -> WorkerCapacity | None:
        """Calculate available capacity (declared - allocated).

        When declared_capacity is not set (e.g., discovered workers that
        haven't had capacity derivation triggered yet), falls back to
        deriving capacity from CML system_info hardware metrics.

        Returns:
            WorkerCapacity representing remaining capacity,
            or None if no capacity data is available at all.
        """
        effective_declared = self.state.declared_capacity
        if effective_declared is None:
            effective_declared = self._derive_capacity_from_metrics()
        if effective_declared is None:
            return None
        return effective_declared.subtract(self.state.allocated_capacity)

    def _derive_capacity_from_metrics(self) -> WorkerCapacity | None:
        """Derive declared capacity from CML system_info hardware metrics.

        Workers discovered via EC2 may not have declared_capacity set until
        the update_capacity() domain method is called. This method provides
        a fallback by reading actual hardware specs from CML telemetry.

        Returns:
            WorkerCapacity derived from system_info, or None if metrics
            are not available.
        """
        system_info = self.state.metrics.system_info if self.state.metrics else None
        if system_info is None:
            return None

        cpu_count = system_info.cpu_count
        memory_total = system_info.memory_total  # bytes
        disk_total = system_info.disk_total  # bytes

        if cpu_count and memory_total and disk_total:
            return WorkerCapacity(
                cpu_cores=int(cpu_count),
                memory_gb=int(memory_total / (1024**3)),
                storage_gb=int(disk_total / (1024**3)),
                max_nodes=None,
            )
        return None

    @property
    def available_ports(self) -> set[int]:
        """Get ports that are currently available (not allocated).

        Returns:
            Set of available port numbers in the allowed range (2000-9999).
        """
        # Get all currently allocated ports
        allocated = set()
        for allocation in self.state.port_allocations:
            allocated.update(allocation.ports.values())

        # Available ports are the full range minus allocated
        all_ports = set(range(2000, 10000))
        return all_ports - allocated

    def can_accommodate(self, required_capacity: WorkerCapacity) -> bool:
        """Check if this worker can accommodate the required capacity.

        Args:
            required_capacity: Capacity requirements to check

        Returns:
            True if the worker has sufficient available capacity
        """
        available = self.available_capacity
        if available is None:
            return False
        return available.can_fit(required_capacity)

    def get_next_available_ports(self, count: int) -> list[int]:
        """Get the next N available ports.

        Args:
            count: Number of ports needed

        Returns:
            List of available port numbers

        Raises:
            ValueError: If not enough ports are available
        """
        available = sorted(self.available_ports)
        if len(available) < count:
            raise ValueError(f"Not enough available ports: need {count}, have {len(available)}")
        return available[:count]

    def has_session(self, session_id: str) -> bool:
        """Check if a lablet session is assigned to this worker.

        Args:
            session_id: LabletSession ID to check

        Returns:
            True if the session is assigned to this worker
        """
        return session_id in self.state.session_ids

    def get_port_allocation(self, session_id: str) -> PortAllocation | None:
        """Get port allocation for a specific session.

        Args:
            session_id: LabletSession ID

        Returns:
            PortAllocation if found, None otherwise
        """
        return next(
            (a for a in self.state.port_allocations if a.session_id == session_id),
            None,
        )
