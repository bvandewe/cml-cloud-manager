"""Internal API controller for service-to-service communication.

These endpoints are called by worker-controller, lablet-controller, and resource-scheduler
to mutate state. They are protected by internal API key authentication.

Per ADR-001: Control Plane API is the ONLY component that writes to MongoDB.
All other services request mutations via these internal endpoints.
"""

import logging
from typing import Annotated, Any

from classy_fastapi.decorators import get, post
from classy_fastapi.routable import Routable
from fastapi import Depends, HTTPException, Path, Query, status
from fastapi.security import APIKeyHeader
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping.mapper import Mapper
from neuroglia.mediation.mediator import Mediator
from neuroglia.mvc.controller_base import ControllerBase, generate_unique_id_function
from neuroglia.serialization.json import JsonSerializer
from pydantic import BaseModel, Field

from application.commands.lab import (
    AppendPipelineRunCommand,
    BindLabToLabletCommand,
    CompleteLabActionCommand,
    DiscoverLabRecordsCommand,
    FailLabActionCommand,
    RecordLabRunCommand,
    UnbindLabFromLabletCommand,
    UpdateLabRecordStatusCommand,
    UpdateLabTopologyCommand,
)
from application.commands.lablet_definition import RecordContentSyncResultCommand
from application.commands.worker import (
    CleanupTerminatedWorkersCommand,
    CompleteLicenseDeregistrationCommand,
    CompleteLicenseRegistrationCommand,
    DetectWorkerIdleCommand,
    DrainWorkerCommand,
    FailLicenseDeregistrationCommand,
    FailLicenseRegistrationCommand,
    InternalBulkImportWorkersCommand,
    MarkWorkerTerminatedCommand,
    RecalculateWorkerCapacityCommand,
    RequestScaleUpCommand,
    StartLicenseDeregistrationCommand,
    StartLicenseRegistrationCommand,
    UpdateCMLWorkerMetricsCommand,
    UpdateCMLWorkerStatusCommand,
    UpdateWorkerCmlDataCommand,
    UpdateWorkerEc2DetailsCommand,
)
from application.queries.get_lab_records_query import GetLabRecordsQuery
from application.queries.get_lablet_definition_query import GetLabletDefinitionQuery
from application.queries.get_worker_template_query import GetWorkerTemplateQuery
from application.queries.list_cml_workers_internal_query import ListCMLWorkersInternalQuery
from application.queries.list_lablet_definitions_query import ListLabletDefinitionsQuery
from application.queries.list_worker_templates_query import ListWorkerTemplatesQuery
from application.settings import Settings

logger = logging.getLogger(__name__)


# ==============================================================================
# Request Models
# ==============================================================================


class UpdateWorkerStatusRequest(BaseModel):
    """Request to update worker status and metrics.

    DEPRECATED: This endpoint is being removed per ADR-015.
    Use POST /workers/{worker_id}/terminate for orphan detection.
    """

    status: str = Field(..., description="New worker status")
    ec2_instance_id: str | None = Field(default=None, description="EC2 instance ID (set during provisioning)")
    metrics: dict[str, Any] | None = Field(default=None, description="Optional metrics data")


class MarkWorkerTerminatedRequest(BaseModel):
    """Request to mark a worker as terminated.

    Used by worker-controller when orphan detection discovers
    that an EC2 instance no longer exists.

    Per ADR-015: Control-plane-api does NOT call AWS EC2.
    """

    reason: str | None = Field(default="orphan_detection", description="Reason for termination")
    terminated_by: str | None = Field(default="worker-controller", description="System/user that detected termination")


class UpdateWorkerMetricsRequest(BaseModel):
    """Request to update worker metrics only.

    Accepts the nested structure from WorkerReconciler:
    {
        "collected_at": "2026-01-18T12:00:00Z",
        "ec2": {
            "cpu_utilization": 45.2,
            "network_in_bytes": 1234567,
            "network_out_bytes": 7654321
        },
        "cml": {
            "cpu_percent": 50.0,
            "memory_percent": 60.0,
            "disk_percent": 30.0,
            "uptime_seconds": 86400
        }
    }
    """

    collected_at: str | None = Field(default=None, description="Timestamp of metrics collection (ISO 8601)")
    ec2: dict[str, Any] | None = Field(default=None, description="EC2/CloudWatch metrics")
    cml: dict[str, Any] | None = Field(default=None, description="CML system stats")
    poll_interval: int | None = Field(default=None, description="Metrics poll interval in seconds")
    next_refresh_at: str | None = Field(default=None, description="Next scheduled refresh time (ISO 8601)")


class UpdateWorkerCmlDataRequest(BaseModel):
    """Request to update CML application data for a worker.

    Reports CML system information, health, license, and compute node details.
    Separate from utilization metrics (UpdateWorkerMetricsRequest).

    Called by worker-controller during reconciliation.
    """

    cml_version: str | None = Field(default=None, description="CML version string (e.g., '2.9.0')")
    ready: bool = Field(default=False, description="CML application ready state")
    system_info: dict[str, Any] | None = Field(default=None, description="Full CML system information")
    system_health: dict[str, Any] | None = Field(default=None, description="CML system health checks")
    license_info: dict[str, Any] | None = Field(default=None, description="CML license information")
    uptime_seconds: int | None = Field(default=None, description="CML uptime in seconds")
    labs_count: int = Field(default=0, description="Number of labs from CML API")
    collected_at: str | None = Field(default=None, description="Timestamp of data collection (ISO 8601)")


class UpdateWorkerEc2DetailsRequest(BaseModel):
    """Request to update EC2 instance details for a worker.

    Reports EC2 instance metadata including AMI details.
    Called by worker-controller after provisioning or on-demand refresh.
    """

    public_ip: str | None = Field(default=None, description="Public IP address")
    private_ip: str | None = Field(default=None, description="Private IP address")
    instance_type: str | None = Field(default=None, description="EC2 instance type (e.g., 'm5zn.metal')")
    ami_id: str | None = Field(default=None, description="AMI image ID")
    ami_name: str | None = Field(default=None, description="AMI name")
    ami_description: str | None = Field(default=None, description="AMI description")
    ami_creation_date: str | None = Field(default=None, description="AMI creation date (ISO 8601)")


class ScaleUpRequest(BaseModel):
    """Request to provision a new worker."""

    template: str = Field(..., description="Name of the worker template to use")
    reason: str = Field(..., description="Reason for the scale-up request")


class RecordActivityRequest(BaseModel):
    """Request to record worker activity."""

    activity_type: str = Field(..., description="Type of activity detected")
    details: dict[str, Any] | None = Field(default=None, description="Additional activity details")


class DetectIdleRequest(BaseModel):
    """Request to detect worker idle state and trigger auto-pause if eligible."""

    force_check: bool = Field(default=False, description="Skip next_idle_check_at validation")
    raw_telemetry_events: list[dict[str, Any]] | None = Field(
        default=None,
        description="Raw telemetry events fetched by worker-controller from CML API. Per ADR-015, CPA does not make external CML calls directly.",
    )


class BulkImportWorkersRequest(BaseModel):
    """Request to bulk import discovered EC2 instances as CML Workers.

    Submitted by worker-controller after AWS discovery scan.
    """

    discovered_instances: list[dict[str, Any]] = Field(
        ...,
        description="List of discovered EC2 instances",
    )
    aws_region: str = Field(..., description="AWS region where instances were discovered")
    source: str = Field(default="worker-controller", description="Source of the import")


class DiscoverLabRecordsRequest(BaseModel):
    """Request to discover/upsert lab records for a worker.

    Submitted by worker-controller or lablet-controller after scanning CML.
    Phase 8 (P8-24): New discovery endpoint.
    """

    worker_id: str = Field(..., description="ID of the worker hosting these labs")
    labs: list[dict[str, Any]] = Field(..., description="List of lab data from CML scan")
    source: str = Field(default="lab-discovery-service", description="Source of the discovery")
    partial_scan: bool = Field(default=False, description="If true, skip orphan sweep (single-lab registration)")


class UpdateLabRecordStatusRequest(BaseModel):
    """Request to update lab record status.

    Submitted by lablet-controller after observing CML lab state changes.
    """

    new_status: str | None = Field(default=None, description="New LabRecordStatus (e.g., 'booted', 'stopped')")
    cml_state: str | None = Field(default=None, description="CML native state string")
    error_message: str | None = Field(default=None, description="Error details if status indicates failure")


class UpdateLabTopologyRequest(BaseModel):
    """Request to update lab topology spec.

    Submitted by lablet-controller after detecting topology changes.
    """

    topology_data: dict[str, Any] = Field(default_factory=dict, description="Full topology spec (nodes, links, etc.)")
    change_summary: str | None = Field(default=None, description="Human-readable summary of what changed")


class RecordLabRunRequest(BaseModel):
    """Request to record a lab run completion.

    Submitted by lablet-controller when a lab session/run completes.
    """

    started_at: str | None = Field(default=None, description="ISO 8601 run start time")
    stopped_at: str | None = Field(default=None, description="ISO 8601 run stop time")
    started_by: str = Field(default="system", description="Who started the run")
    stop_reason: str | None = Field(default=None, description="Why the run stopped (e.g., 'user_request', 'timeslot_end')")
    lablet_session_id: str | None = Field(default=None, description="LabletSession ID if bound during run")
    final_state: str | None = Field(default=None, description="Final CML state at run end")


class AppendPipelineRunRequest(BaseModel):
    """Request to record a pipeline execution on a LabRecord.

    Sprint F (ADR-034): Submitted by lablet-controller after a lifecycle
    pipeline completes (instantiate, teardown, collect_evidence, compute_grading).
    """

    pipeline_name: str = Field(..., description="Pipeline name (e.g., 'instantiate', 'teardown')")
    status: str = Field(default="completed", description="Terminal status: completed, failed, partial")
    started_at: str | None = Field(default=None, description="ISO 8601 pipeline start time")
    completed_at: str | None = Field(default=None, description="ISO 8601 pipeline completion time")
    duration_seconds: float | None = Field(default=None, description="Total pipeline duration in seconds")
    steps_completed: int = Field(default=0, description="Number of successfully completed steps")
    steps_failed: int = Field(default=0, description="Number of failed steps")
    steps_skipped: int = Field(default=0, description="Number of skipped steps")
    step_results: dict | None = Field(default=None, description="Per-step outcome dict")
    error_message: str | None = Field(default=None, description="Pipeline-level error message")
    triggered_by: str = Field(default="lablet-controller", description="Who triggered the pipeline")
    lablet_session_id: str | None = Field(default=None, description="LabletSession ID that owns this run")


class CompleteLabActionRequest(BaseModel):
    """Request to mark a pending lab action as completed.

    Submitted by lablet-controller after successfully executing
    a CML API action (start, stop, wipe, delete, clone).
    ADR-017: Reconciliation loop completion.
    """

    action: str | None = Field(default=None, description="Action that was completed (e.g., 'start', 'stop')")
    cml_state: str | None = Field(default=None, description="CML state after action completion")


class FailLabActionRequest(BaseModel):
    """Request to mark a pending lab action as failed.

    Submitted by lablet-controller when a CML API action fails.
    ADR-017: Error handling in reconciliation loop.
    """

    error_message: str = Field(..., description="Error message describing the failure")
    transition_to_error: bool = Field(default=False, description="Whether to transition the lab to ERROR state")


class BindLabToLabletRequest(BaseModel):
    """Request to bind a lab to a lablet session.

    Submitted by lablet-controller or resource-scheduler when assigning
    a lab to a lablet session.
    """

    lablet_session_id: str = Field(..., description="LabletSession aggregate ID")
    role: str = Field(default="primary", description="Binding role: primary, secondary, or auxiliary")
    metadata: dict | None = Field(default=None, description="Optional binding metadata")


class UnbindLabFromLabletRequest(BaseModel):
    """Request to unbind a lab from a lablet session.

    Submitted by lablet-controller or resource-scheduler when releasing
    a lab from a lablet session.
    """

    lablet_session_id: str = Field(..., description="LabletSession aggregate ID")
    reason: str | None = Field(default=None, description="Reason for unbinding")


class MarkLabOrphanedRequest(BaseModel):
    """Request to mark a lab as orphaned.

    Submitted by worker-controller when a lab is found without
    a matching CML lab on the worker (worker re-provisioned, etc.).
    """

    error_message: str = Field(default="Lab not found on worker during scan", description="Reason for orphan status")
    transition_to_error: bool = Field(default=True, description="Whether to transition to ERROR state")


class CleanupTerminatedWorkersRequest(BaseModel):
    """Request to cleanup (hard delete) TERMINATED worker records.

    Submitted by resource-scheduler or cron job to purge old terminated
    worker records from the database.

    Part of the soft delete pattern:
    - User delete or GC detection → Sets status=TERMINATED, keeps record
    - CleanupTerminatedWorkersCommand → Removes records older than retention period
    """

    retention_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Number of days to retain terminated records. Default: 30 days.",
    )
    dry_run: bool = Field(
        default=False,
        description="If True, only report what would be deleted without actually deleting.",
    )


# =============================================================================
# License Status Request Models (ADR-016)
# =============================================================================


class StartLicenseRegistrationRequest(BaseModel):
    """Request to mark license registration as started.

    Called by worker-controller when it begins the CML API registration call.
    """

    initiated_by: str | None = Field(default=None, description="User/system that initiated registration")


class CompleteLicenseRegistrationRequest(BaseModel):
    """Request to mark license registration as completed.

    Called by worker-controller after successful CML API registration.
    """

    registration_status: str = Field(..., description="CML registration status (e.g., 'COMPLETED')")
    smart_account: str | None = Field(default=None, description="Smart Licensing account name")
    virtual_account: str | None = Field(default=None, description="Virtual account name")


class FailLicenseRegistrationRequest(BaseModel):
    """Request to mark license registration as failed.

    Called by worker-controller when CML API registration fails.
    """

    error_message: str = Field(..., description="Error message describing the failure")
    error_code: str | None = Field(default=None, description="Optional error code from CML")


class StartLicenseDeregistrationRequest(BaseModel):
    """Request to mark license deregistration as started.

    Called by worker-controller when it begins the CML API deregistration call.
    """

    initiated_by: str | None = Field(default=None, description="User/system that initiated deregistration")


class CompleteLicenseDeregistrationRequest(BaseModel):
    """Request to mark license deregistration as completed.

    Called by worker-controller after successful CML API deregistration.
    """

    message: str = Field(default="License deregistered successfully", description="Success message")


class FailLicenseDeregistrationRequest(BaseModel):
    """Request to mark license deregistration as failed.

    Called by worker-controller when CML API deregistration fails.
    """

    error_message: str = Field(..., description="Error message describing the failure")


class RecordContentSyncResultRequest(BaseModel):
    """Request to record content sync result from lablet-controller.

    Called via POST /api/internal/lablet-definitions/{id}/content-synced
    after the ContentSyncService completes the sync pipeline.
    """

    sync_status: str = Field(..., description="Sync outcome: 'success' or 'failed'")
    error_message: str | None = Field(default=None, description="Error details if sync failed")

    # Content metadata (populated on success)
    lab_yaml_hash: str = Field(default="", description="SHA-256 hash of the CML YAML content")
    content_package_hash: str | None = Field(default=None, description="SHA-256 hash of the downloaded content package")
    upstream_version: str | None = Field(default=None, description="Version from mosaic_meta.json")
    upstream_date_published: str | None = Field(default=None, description="DatePublished from mosaic_meta.json")
    upstream_instance_name: str | None = Field(default=None, description="InstanceName from mosaic_meta.json")
    upstream_form_id: str | None = Field(default=None, description="FormId from mosaic_meta.json")
    grade_xml_path: str | None = Field(default=None, description="Relative path to grade.xml in the package")
    cml_yaml_path: str | None = Field(default=None, description="Relative path to cml.yml/cml.yaml in the package")
    cml_yaml_content: str | None = Field(default=None, description="Cached CML YAML content for lab import")
    devices_json: str | None = Field(default=None, description="Cached devices.json (serialized JSON string)")
    upstream_sync_status: dict[str, Any] | None = Field(default=None, description="Per-service sync status dict")

    # Port template extracted from CML YAML nodes (ADR-029)
    port_template: dict[str, Any] | None = Field(default=None, description="Port template extracted from CML YAML node tags")

    # Topology metadata auto-derived from CML YAML (AD-SEED-001)
    node_count: int | None = Field(default=None, description="Number of nodes in the CML topology")
    node_definitions_required: list[str] | None = Field(default=None, description="Unique node definitions from CML topology")


# ==============================================================================
# Authentication Dependency
# ==============================================================================

# Define the API Key security scheme for OpenAPI documentation
api_key_header = APIKeyHeader(
    name="X-API-Key",
    description="Internal API key for service-to-service authentication",
    auto_error=False,
)


async def verify_internal_api_key(
    x_api_key: str | None = Depends(api_key_header),
) -> str:
    """Verify internal API key for service-to-service calls.

    Controllers and schedulers must provide a valid API key to call
    internal endpoints. This prevents external access to mutation endpoints.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    # Validate against Settings.internal_api_key
    settings = Settings()
    if x_api_key != settings.internal_api_key:
        logger.warning("Invalid API key attempt from service")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    return x_api_key


# ==============================================================================
# Path Annotations
# ==============================================================================

lab_record_id_annotation = Annotated[str, Path(description="The LabRecord aggregate ID")]
worker_id_annotation = Annotated[str, Path(description="The CML worker UUID")]


# ==============================================================================
# Internal Controller
# ==============================================================================


class InternalController(ControllerBase):
    """Internal API controller for service-to-service communication.

    These endpoints are called by:
    - resource-scheduler: schedule_instance, request_scale_up
    - worker-controller: update_worker_status, update_worker_metrics, record_activity
    - lablet-controller: transition_instance, allocate_ports

    All endpoints require X-API-Key header for authentication.

    Note: This controller does NOT register a default "Internal" tag. Each endpoint
    specifies its own tag (e.g., "Internal - Workers") to organize the API docs properly.
    We call Routable.__init__ directly with empty tags to prevent an empty "Internal"
    group from appearing in Swagger UI.
    """

    def __init__(self, service_provider: ServiceProviderBase, mapper: Mapper, mediator: Mediator):
        """Initialize the internal controller.

        Bypasses ControllerBase's default tag generation by calling Routable.__init__
        directly with empty tags. Each endpoint explicitly specifies its own tag
        (e.g., tags=["Internal - Workers"]).
        """
        # Store dependency injection services (normally done by ControllerBase)
        self.service_provider = service_provider
        self.mapper = mapper
        self.mediator = mediator
        self.json_serializer = self.service_provider.get_required_service(JsonSerializer)
        self.name = "Internal"

        # Call Routable.__init__ directly to control tags behavior
        # Use empty tags list so only endpoint-level tags appear in Swagger
        Routable.__init__(
            self,
            prefix="/internal",  # Explicit prefix
            tags=[],  # Empty tags - endpoints define their own (Internal - Workers, etc.)
            generate_unique_id_function=generate_unique_id_function,
        )

    # ==========================================================================
    # Worker Read Operations (for controllers)
    # ==========================================================================

    @get(
        "/workers",
        summary="List Workers (Internal)",
        tags=["Internal - Workers"],
        status_code=200,
    )
    async def list_workers(
        self,
        status: str | None = Query(default=None, description="Filter by worker status"),
        aws_region: str | None = Query(default=None, description="Filter by AWS region"),
        include_terminated: bool = Query(default=False, description="Include terminated workers"),
        api_key: str = Depends(verify_internal_api_key),
    ) -> list[dict[str, Any]]:
        """List CML workers for service-to-service calls.

        Called by worker-controller and other controllers during reconciliation
        to get the list of workers to process.

        Args:
            status: Optional filter by worker status (e.g., "RUNNING", "STOPPED").
            aws_region: Optional filter by AWS region (e.g., "us-east-1").
            include_terminated: Include terminated workers in results.
            api_key: Internal API key (from header).

        Returns:
            List of worker dictionaries.
        """
        logger.info(f"[Internal] Listing workers (status={status}, region={aws_region})")

        query = ListCMLWorkersInternalQuery(
            status=status,
            aws_region=aws_region,
            include_terminated=include_terminated,
        )
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @get(
        "/workers/{worker_id}",
        summary="Get Worker by ID (Internal)",
        tags=["Internal - Workers"],
        status_code=200,
    )
    async def get_worker(
        self,
        worker_id: worker_id_annotation,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Get a single CML worker by ID for service-to-service calls.

        Called by worker-controller and other controllers during reconciliation.

        Args:
            worker_id: ID of the worker to retrieve.
            api_key: Internal API key (from header).

        Returns:
            Worker dictionary with full details.
        """
        from application.queries.get_cml_worker_by_id_query import GetCMLWorkerByIdQuery

        logger.info(f"[Internal] Getting worker {worker_id}")

        query = GetCMLWorkerByIdQuery(worker_id=worker_id)
        result = await self.mediator.execute_async(query)
        return self.process(result)

    # ==========================================================================
    # Worker Operations  (Phase 7E: Session endpoints extracted to InternalSessionsController)
    # ==========================================================================

    @post(
        "/workers/{worker_id}/terminate",
        summary="Mark Worker as Terminated",
        tags=["Internal - Workers"],
        status_code=200,
    )
    async def mark_worker_terminated(
        self,
        worker_id: worker_id_annotation,
        request: MarkWorkerTerminatedRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Mark a worker as terminated (database-only, no AWS calls).

        Called by worker-controller when orphan detection discovers
        that an EC2 instance no longer exists. Per ADR-015, control-plane-api
        NEVER calls AWS EC2 directly.

        Args:
            worker_id: ID of the worker to mark as terminated.
            request: Contains optional reason and terminated_by fields.
            api_key: Internal API key (from header).

        Returns:
            Worker termination result with old/new status.
        """
        logger.info(f"[Internal] Marking worker {worker_id} as terminated (reason: {request.reason})")

        command = MarkWorkerTerminatedCommand(
            worker_id=worker_id,
            terminated_by=request.terminated_by,
            reason=request.reason,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/workers/{worker_id}/metrics",
        summary="Update Worker Metrics",
        tags=["Internal - Workers"],
        status_code=200,
    )
    async def update_worker_metrics(
        self,
        worker_id: worker_id_annotation,
        request: UpdateWorkerMetricsRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Update worker metrics only (no status change).

        Called by worker-controller during periodic metrics collection.

        Args:
            worker_id: ID of the worker.
            request: Contains metrics data.
            api_key: Internal API key (from header).

        Returns:
            Acknowledgment.
        """
        logger.info(f"[Internal] Updating metrics for worker {worker_id}")

        command = UpdateCMLWorkerMetricsCommand(
            worker_id=worker_id,
            collected_at=request.collected_at,
            ec2=request.ec2,
            cml=request.cml,
            poll_interval=request.poll_interval,
            next_refresh_at=request.next_refresh_at,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/workers/{worker_id}/cml-data",
        summary="Update Worker CML Data",
        tags=["Internal - Workers"],
        status_code=200,
    )
    async def update_worker_cml_data(
        self,
        worker_id: worker_id_annotation,
        request: UpdateWorkerCmlDataRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Update CML application data for a worker.

        Reports CML system information (version, readiness, compute nodes),
        system health, and license information. Separate from utilization metrics.

        Called by worker-controller during reconciliation.

        Args:
            worker_id: ID of the worker.
            request: Contains CML data fields.
            api_key: Internal API key (from header).

        Returns:
            Acknowledgment with update details.
        """
        logger.info(f"[Internal] Updating CML data for worker {worker_id} (version={request.cml_version})")

        command = UpdateWorkerCmlDataCommand(
            worker_id=worker_id,
            cml_version=request.cml_version,
            ready=request.ready,
            system_info=request.system_info,
            system_health=request.system_health,
            license_info=request.license_info,
            uptime_seconds=request.uptime_seconds,
            labs_count=request.labs_count,
            collected_at=request.collected_at,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/workers/{worker_id}/ec2-details",
        summary="Update Worker EC2 Details",
        tags=["Internal - Workers"],
        status_code=200,
    )
    async def update_worker_ec2_details(
        self,
        worker_id: worker_id_annotation,
        request: UpdateWorkerEc2DetailsRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Update EC2 instance details for a worker.

        Reports EC2 instance metadata including AMI details (ID, name,
        description, creation date) and IP addresses.

        Called by worker-controller after provisioning or on-demand refresh.

        Args:
            worker_id: ID of the worker.
            request: Contains EC2 detail fields.
            api_key: Internal API key (from header).

        Returns:
            Acknowledgment with update details.
        """
        logger.info(f"[Internal] Updating EC2 details for worker {worker_id} (ami={request.ami_id})")

        command = UpdateWorkerEc2DetailsCommand(
            worker_id=worker_id,
            public_ip=request.public_ip,
            private_ip=request.private_ip,
            instance_type=request.instance_type,
            ami_id=request.ami_id,
            ami_name=request.ami_name,
            ami_description=request.ami_description,
            ami_creation_date=request.ami_creation_date,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/workers/scale-up",
        summary="Request Worker Scale-Up",
        tags=["Internal - Workers"],
        status_code=202,
    )
    async def request_scale_up(
        self,
        request: ScaleUpRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Request a new worker to be provisioned.

        Called by resource-scheduler when no worker has sufficient capacity.

        Args:
            request: Contains template name and reason.
            api_key: Internal API key (from header).

        Returns:
            Scale-up request details including new worker ID.
        """
        logger.info(f"[Internal] Scale-up requested: template={request.template}, reason={request.reason}")

        command = RequestScaleUpCommand(
            template_name=request.template,
            reason=request.reason,
            requested_by="resource-scheduler",
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/workers/{worker_id}/status",
        summary="Update Worker Status",
        tags=["Internal - Workers"],
        status_code=200,
    )
    async def update_worker_status(
        self,
        worker_id: worker_id_annotation,
        request: UpdateWorkerStatusRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Update worker status (and optionally EC2 instance ID).

        Called by worker-controller during reconciliation to update worker status
        and attach EC2 instance ID after provisioning.

        Args:
            worker_id: ID of the worker.
            request: Contains status, optional ec2_instance_id, optional metrics.
            api_key: Internal API key (from header).

        Returns:
            Updated worker status info.
        """
        logger.info(f"[Internal] Updating status for worker {worker_id}: status={request.status}, ec2_instance_id={request.ec2_instance_id}")

        command = UpdateCMLWorkerStatusCommand(
            worker_id=worker_id,
            status=request.status,
            ec2_instance_id=request.ec2_instance_id,
            metrics=request.metrics,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/workers/{worker_id}/drain",
        summary="Drain Worker",
        tags=["Internal - Workers"],
        status_code=200,
    )
    async def drain_worker(
        self,
        worker_id: worker_id_annotation,
        reason: str = Query(default="scale_down", description="Reason for draining"),
        requested_by: str = Query(default="worker-controller", description="System requesting drain"),
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Initiate graceful drain of a worker.

        Sets worker to DRAINING status. Worker-controller will:
        1. Stop accepting new lab assignments
        2. Wait for active labs to complete or be migrated
        3. Transition to STOPPING → STOPPED

        Called by worker-controller during scale-down.

        Args:
            worker_id: ID of the worker to drain.
            reason: Reason for draining (e.g., "scale_down", "maintenance").
            requested_by: System requesting the drain.
            api_key: Internal API key (from header).

        Returns:
            Drain status info.
        """
        logger.info(f"[Internal] Drain requested for worker {worker_id}: reason={reason}")

        command = DrainWorkerCommand(
            worker_id=worker_id,
            reason=reason,
            requested_by=requested_by,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/workers/{worker_id}/recalculate-capacity",
        summary="Recalculate Worker Capacity",
        tags=["Internal - Workers"],
        status_code=200,
    )
    async def recalculate_worker_capacity(
        self,
        worker_id: worker_id_annotation,
        requested_by: str = Query(default="admin", description="Who requested the recalculation"),
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Recalculate a worker's allocated capacity from its active sessions.

        Repair mechanism: iterates the worker's tracked session_ids, validates
        each against the actual session status, sums resource_requirements for
        active sessions, and replaces allocated_capacity with correct values.

        Use this when allocated_capacity has drifted due to expired/terminated
        sessions that failed to release their capacity (phantom allocations).

        Args:
            worker_id: ID of the worker to recalculate.
            requested_by: Who/what triggered the recalculation.
            api_key: Internal API key (from header).

        Returns:
            Old and new allocated capacity, active/stale session details.
        """
        logger.info(f"[Internal] Recalculating capacity for worker {worker_id} (requested_by={requested_by})")

        command = RecalculateWorkerCapacityCommand(
            worker_id=worker_id,
            requested_by=requested_by,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/workers/bulk-import",
        summary="Bulk Import Discovered Workers",
        tags=["Internal - Workers"],
        status_code=200,
    )
    async def bulk_import_workers(
        self,
        request: BulkImportWorkersRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Bulk import EC2 instances discovered by worker-controller.

        Called by worker-controller's WorkerReconciler discovery loop after AWS discovery scan.
        This endpoint handles persistence - the controller only does discovery.

        Args:
            request: Contains discovered instances and AWS region.
            api_key: Internal API key (from header).

        Returns:
            Import results including imported/skipped counts.
        """
        logger.info(f"[Internal] Bulk import request: {len(request.discovered_instances)} instances from {request.source} in {request.aws_region}")

        command = InternalBulkImportWorkersCommand(
            discovered_instances=request.discovered_instances,
            aws_region=request.aws_region,
            source=request.source,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @get(
        "/workers/{worker_id}/idle-status",
        summary="Get Worker Idle Status (Internal)",
        tags=["Internal - Workers"],
        status_code=200,
    )
    async def get_worker_idle_status(
        self,
        worker_id: worker_id_annotation,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Get idle status for a worker.

        Called by controllers to check if a worker is idle and eligible
        for auto-pause without requiring aws_region parameter.

        Args:
            worker_id: ID of the worker.
            api_key: Internal API key (from header).

        Returns:
            Idle status including:
            - is_idle: Whether the worker is considered idle
            - idle_minutes: Duration of idle time
            - eligible_for_pause: Whether the worker can be auto-paused
            - last_activity_at: Timestamp of last detected activity
        """
        from application.queries.get_worker_idle_status_query import GetWorkerIdleStatusQuery

        logger.info(f"[Internal] Getting idle status for worker {worker_id}")

        query = GetWorkerIdleStatusQuery(worker_id=worker_id)
        result = await self.mediator.execute_async(query)
        return self.process(result)

    # ==========================================================================
    # Lab Record Operations
    # ==========================================================================

    @get(
        "/lab-records",
        summary="List Lab Records (Internal)",
        tags=["Internal - Labs"],
        status_code=200,
    )
    async def list_lab_records_internal(
        self,
        worker_id: str | None = Query(default=None, description="Filter by worker ID"),
        status: str | None = Query(default=None, description="Filter by LabRecordStatus"),
        include_terminal: bool = Query(default=False, description="Include terminal-state labs"),
        api_key: str = Depends(verify_internal_api_key),
    ) -> Any:
        """List lab records with optional filters (internal).

        Phase 9 (P9-4): Called by lablet-controller's reconciler to query
        existing LabRecords for lab resolution and reuse logic.

        Args:
            worker_id: Filter by hosting worker ID.
            status: Filter by LabRecordStatus (case-insensitive).
            include_terminal: Include deleted/archived labs.
            api_key: Internal API key (from header).

        Returns:
            List of lab record summaries.
        """
        logger.info(f"[Internal] Listing lab records (worker_id={worker_id}, status={status})")

        query = GetLabRecordsQuery(
            worker_id=worker_id,
            status=status,
            include_terminal=include_terminal,
        )
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @post(
        "/lab-records/discover",
        summary="Discover Lab Records",
        tags=["Internal - Labs"],
        status_code=200,
    )
    async def discover_lab_records(
        self,
        request: DiscoverLabRecordsRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Discover lab records for a worker.

        Phase 8 (P8-24): Called by worker-controller or lablet-controller after
        scanning CML for labs. Creates new LabRecords for unknown labs, updates
        existing ones, and marks orphaned labs.

        Args:
            request: Contains worker_id and list of labs from CML scan.
            api_key: Internal API key (from header).

        Returns:
            Discovery results (synced, discovered, updated, orphaned counts).
        """
        logger.info(
            "[Internal] Lab records discovery: %d labs for worker %s from %s",
            len(request.labs),
            request.worker_id,
            request.source,
        )
        command = DiscoverLabRecordsCommand(
            worker_id=request.worker_id,
            labs=request.labs,
            source=request.source,
            partial_scan=request.partial_scan,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/lab-records/{lab_record_id}/status",
        summary="Update Lab Record Status",
        tags=["Internal - Labs"],
        status_code=200,
    )
    async def update_lab_record_status(
        self,
        lab_record_id: lab_record_id_annotation,
        request: UpdateLabRecordStatusRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Update the status of a lab record.

        Phase 8 (P8-24): Called by lablet-controller when it observes
        CML lab state changes during reconciliation or polling.

        Args:
            lab_record_id: LabRecord aggregate ID.
            request: New status and optional CML state/error.
            api_key: Internal API key (from header).

        Returns:
            Updated lab record summary.
        """
        logger.info(
            "[Internal] Lab record %s status update: status=%s, cml_state=%s",
            lab_record_id,
            request.new_status,
            request.cml_state,
        )
        command = UpdateLabRecordStatusCommand(
            lab_record_id=lab_record_id,
            new_status=request.new_status,
            cml_state=request.cml_state,
            error_message=request.error_message,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/lab-records/{lab_record_id}/topology",
        summary="Update Lab Topology",
        tags=["Internal - Labs"],
        status_code=200,
    )
    async def update_lab_topology(
        self,
        lab_record_id: lab_record_id_annotation,
        request: UpdateLabTopologyRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Update the topology specification of a lab record.

        Phase 8 (P8-24): Called by lablet-controller when it detects
        topology changes (node/link additions/removals, config changes).
        Creates a new LabRevision if the topology checksum differs.

        Args:
            lab_record_id: LabRecord aggregate ID.
            request: Topology data and optional change summary.
            api_key: Internal API key (from header).

        Returns:
            Topology update result with revision info.
        """
        logger.info("[Internal] Lab record %s topology update", lab_record_id)
        command = UpdateLabTopologyCommand(
            lab_record_id=lab_record_id,
            topology_data=request.topology_data,
            change_summary=request.change_summary,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/lab-records/{lab_record_id}/run-completed",
        summary="Record Lab Run Completed",
        tags=["Internal - Labs"],
        status_code=200,
    )
    async def record_lab_run_completed(
        self,
        lab_record_id: lab_record_id_annotation,
        request: RecordLabRunRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Record a completed lab run.

        Phase 8 (P8-24): Called by lablet-controller when a lab session
        ends (user stops lab, timeslot expires, etc.). Creates a LabRunRecord
        documenting the execution cycle.

        Args:
            lab_record_id: LabRecord aggregate ID.
            request: Run timing, initiator, and outcome data.
            api_key: Internal API key (from header).

        Returns:
            Created run record summary.
        """
        logger.info("[Internal] Lab record %s run completed", lab_record_id)
        command = RecordLabRunCommand(
            lab_record_id=lab_record_id,
            started_at=request.started_at,
            stopped_at=request.stopped_at,
            started_by=request.started_by,
            stop_reason=request.stop_reason,
            lablet_session_id=request.lablet_session_id,
            final_state=request.final_state,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/lab-records/{lab_record_id}/pipeline-run",
        summary="Record Pipeline Run",
        tags=["Internal - Labs"],
        status_code=201,
    )
    async def append_pipeline_run(
        self,
        lab_record_id: lab_record_id_annotation,
        request: AppendPipelineRunRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Record a completed pipeline execution on a LabRecord.

        Sprint F (ADR-034): Called by lablet-controller after a lifecycle
        pipeline completes (instantiate, teardown, collect_evidence,
        compute_grading). Appends a PipelineRunRecord to the aggregate.

        Args:
            lab_record_id: LabRecord aggregate ID.
            request: Pipeline execution data.
            api_key: Internal API key (from header).

        Returns:
            Created pipeline run record summary.
        """
        logger.info(
            "[Internal] Lab record %s pipeline run: %s (%s)",
            lab_record_id,
            request.pipeline_name,
            request.status,
        )
        command = AppendPipelineRunCommand(
            lab_record_id=lab_record_id,
            pipeline_name=request.pipeline_name,
            status=request.status,
            started_at=request.started_at,
            completed_at=request.completed_at,
            duration_seconds=request.duration_seconds,
            steps_completed=request.steps_completed,
            steps_failed=request.steps_failed,
            steps_skipped=request.steps_skipped,
            step_results=request.step_results,
            error_message=request.error_message,
            triggered_by=request.triggered_by,
            lablet_session_id=request.lablet_session_id,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/lab-records/{lab_record_id}/complete-action",
        summary="Complete Lab Action",
        tags=["Internal - Labs"],
        status_code=200,
    )
    async def complete_lab_action(
        self,
        lab_record_id: lab_record_id_annotation,
        request: CompleteLabActionRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Mark a pending lab action as completed.

        ADR-017 reconciliation: Called by lablet-controller after successfully
        executing a CML API action (start, stop, wipe, delete, clone).
        Clears the pending_action and updates status.

        Args:
            lab_record_id: LabRecord aggregate ID.
            request: Completed action type and resulting CML state.
            api_key: Internal API key (from header).

        Returns:
            Updated lab record summary.
        """
        logger.info(
            "[Internal] Lab record %s action completed: %s",
            lab_record_id,
            request.action,
        )
        command = CompleteLabActionCommand(
            lab_record_id=lab_record_id,
            action=request.action,
            cml_state=request.cml_state,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/lab-records/{lab_record_id}/fail-action",
        summary="Fail Lab Action",
        tags=["Internal - Labs"],
        status_code=200,
    )
    async def fail_lab_action(
        self,
        lab_record_id: lab_record_id_annotation,
        request: FailLabActionRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Mark a pending lab action as failed.

        ADR-017 reconciliation: Called by lablet-controller when a CML API
        action fails. Records the error and optionally transitions the lab
        to ERROR state.

        Args:
            lab_record_id: LabRecord aggregate ID.
            request: Error message and error-transition flag.
            api_key: Internal API key (from header).

        Returns:
            Updated lab record summary.
        """
        logger.warning(
            "[Internal] Lab record %s action failed: %s",
            lab_record_id,
            request.error_message,
        )
        command = FailLabActionCommand(
            lab_record_id=lab_record_id,
            error_message=request.error_message,
            transition_to_error=request.transition_to_error,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/lab-records/{lab_record_id}/bind",
        summary="Bind Lab to Lablet",
        tags=["Internal - Labs"],
        status_code=200,
    )
    async def bind_lab_to_lablet(
        self,
        lab_record_id: lab_record_id_annotation,
        request: BindLabToLabletRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Bind a lab record to a lablet instance.

        Phase 8 (P8-24): Called by lablet-controller or resource-scheduler
        to assign a lab to a lablet session. Creates a LabletLabBinding entity.

        Args:
            lab_record_id: LabRecord aggregate ID.
            request: Lablet instance ID, role, and optional metadata.
            api_key: Internal API key (from header).

        Returns:
            Created binding summary.
        """
        logger.info(
            "[Internal] Bind lab %s to lablet %s (role=%s)",
            lab_record_id,
            request.lablet_session_id,
            request.role,
        )
        command = BindLabToLabletCommand(
            lab_record_id=lab_record_id,
            lablet_session_id=request.lablet_session_id,
            role=request.role,
            metadata=request.metadata,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/lab-records/{lab_record_id}/unbind",
        summary="Unbind Lab from Lablet",
        tags=["Internal - Labs"],
        status_code=200,
    )
    async def unbind_lab_from_lablet(
        self,
        lab_record_id: lab_record_id_annotation,
        request: UnbindLabFromLabletRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Unbind a lab record from a lablet instance.

        Phase 8 (P8-24): Called by lablet-controller or resource-scheduler
        when releasing a lab from a lablet session (timeslot end, teardown).

        Args:
            lab_record_id: LabRecord aggregate ID.
            request: Lablet instance ID and reason for unbinding.
            api_key: Internal API key (from header).

        Returns:
            Updated binding summary.
        """
        logger.info(
            "[Internal] Unbind lab %s from lablet %s (reason=%s)",
            lab_record_id,
            request.lablet_session_id,
            request.reason,
        )
        command = UnbindLabFromLabletCommand(
            lab_record_id=lab_record_id,
            lablet_session_id=request.lablet_session_id,
            reason=request.reason,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/lab-records/{lab_record_id}/mark-orphaned",
        summary="Mark Lab as Orphaned",
        tags=["Internal - Labs"],
        status_code=200,
    )
    async def mark_lab_orphaned(
        self,
        lab_record_id: lab_record_id_annotation,
        request: MarkLabOrphanedRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Mark a lab record as orphaned.

        Phase 8 (P8-24): Called by worker-controller when a lab record
        exists in the database but is not found on the CML worker
        (e.g., after worker re-provisioning).

        Uses FailLabActionCommand to transition to error state since
        orphaned labs represent an abnormal condition.

        Args:
            lab_record_id: LabRecord aggregate ID.
            request: Error message and error-transition flag.
            api_key: Internal API key (from header).

        Returns:
            Updated lab record summary.
        """
        logger.warning("[Internal] Marking lab record %s as orphaned", lab_record_id)
        command = FailLabActionCommand(
            lab_record_id=lab_record_id,
            error_message=request.error_message,
            transition_to_error=request.transition_to_error,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/workers/{worker_id}/activity",
        summary="Record Worker Activity",
        tags=["Internal - Workers"],
        status_code=200,
    )
    async def record_worker_activity(
        self,
        worker_id: worker_id_annotation,
        request: RecordActivityRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Record activity detected on a worker.

        Called by worker-controller during activity detection.

        Args:
            worker_id: ID of the worker.
            request: Contains activity type and details.
            api_key: Internal API key (from header).

        Returns:
            Acknowledgment.
        """
        logger.info(f"[Internal] Recording activity for worker {worker_id}: {request.activity_type}")

        # TODO: Create a proper RecordWorkerActivityCommand
        # For now, return success acknowledgment
        return {"status": "recorded", "worker_id": worker_id, "activity_type": request.activity_type}

    @post(
        "/workers/{worker_id}/detect-idle",
        summary="Detect Worker Idle State",
        tags=["Internal - Workers"],
        status_code=200,
    )
    async def detect_worker_idle(
        self,
        worker_id: worker_id_annotation,
        request: DetectIdleRequest | None = None,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Execute idle detection workflow for a worker.

        Called by worker-controller during reconciliation.
        Orchestrates the idle detection workflow:
        1. Process telemetry events (provided by worker-controller per ADR-015)
        2. Update worker activity state
        3. Check idle status and eligibility
        4. Auto-pause if conditions met

        Args:
            worker_id: ID of the worker.
            request: Optional request with force_check flag.
            api_key: Internal API key (from header).

        Returns:
            Detection results including:
            - is_idle: Whether the worker is considered idle
            - idle_minutes: Duration of idle time
            - auto_pause_triggered: Whether auto-pause was executed
        """
        force_check = request.force_check if request else False
        raw_telemetry_events = request.raw_telemetry_events if request else None
        logger.info(f"[Internal] Detecting idle state for worker {worker_id} (force={force_check}, telemetry_events={len(raw_telemetry_events) if raw_telemetry_events else 'none'})")

        command = DetectWorkerIdleCommand(
            worker_id=worker_id,
            force_check=force_check,
            raw_telemetry_events=raw_telemetry_events,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/workers/cleanup",
        summary="Cleanup Terminated Workers",
        tags=["Internal - Workers"],
        status_code=200,
    )
    async def cleanup_terminated_workers(
        self,
        request: CleanupTerminatedWorkersRequest | None = None,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Cleanup (hard delete) old TERMINATED worker records.

        Called by resource-scheduler or cron job to purge terminated
        worker records that have exceeded the retention period.

        Part of the soft delete pattern:
        - User delete or GC detection → Sets status=TERMINATED, keeps record
        - This endpoint → Removes records older than retention period

        Args:
            request: Optional request with retention_days and dry_run flags.
            api_key: Internal API key (from header).

        Returns:
            Cleanup results including:
            - workers_found: Number of terminated workers found
            - workers_deleted: Number of workers actually deleted
            - workers_skipped: Number of workers skipped (errors)
            - retention_days: Retention period used
            - cutoff_date: Date used as cutoff for deletion
            - dry_run: Whether this was a dry run
            - deleted_worker_ids: List of deleted worker IDs
        """
        retention_days = request.retention_days if request else 30
        dry_run = request.dry_run if request else False

        logger.info(f"[Internal] Cleaning up terminated workers (retention={retention_days} days, dry_run={dry_run})")

        command = CleanupTerminatedWorkersCommand(
            retention_days=retention_days,
            dry_run=dry_run,
            initiated_by="internal-api",
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    # ==========================================================================
    # Lablet Definition Operations
    # ==========================================================================

    @get(
        "/lablet-definitions",
        summary="List Lablet Definitions",
        tags=["Internal - Definitions"],
        status_code=200,
    )
    async def list_lablet_definitions_internal(
        self,
        api_key: str = Depends(verify_internal_api_key),
        name: str | None = Query(default=None, description="Filter by name"),
        status: str | None = Query(default=None, description="Filter by status"),
        sync_status: str | None = Query(default=None, description="Filter by sync_status (sync_requested, success, failed)"),
        include_deprecated: bool = Query(default=False, description="Include deprecated definitions"),
        skip: int = Query(default=0, ge=0, description="Number of records to skip"),
        limit: int = Query(default=100, ge=1, le=1000, description="Maximum number of records"),
    ) -> dict[str, Any]:
        """List lablet definitions with optional filtering.

        Called by resource-scheduler and lablet-controller to get available definitions.
        The lablet-controller uses `sync_status=sync_requested` to discover definitions
        that need content synchronization.

        Args:
            api_key: Internal API key (from header).
            name: Filter by definition name.
            status: Filter by definition status.
            sync_status: Filter by sync status (sync_requested, success, failed).
            include_deprecated: Whether to include deprecated definitions.
            skip: Pagination offset.
            limit: Maximum results to return.

        Returns:
            List of lablet definition summaries.
        """
        logger.info(f"[Internal] Listing lablet definitions (name={name}, status={status}, sync_status={sync_status})")

        query = ListLabletDefinitionsQuery(
            name=name,
            status=status,
            sync_status=sync_status,
            include_deprecated=include_deprecated,
            skip=skip,
            limit=limit,
        )
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @get(
        "/lablet-definitions/{definition_id}",
        summary="Get Lablet Definition by ID",
        tags=["Internal - Definitions"],
        status_code=200,
    )
    async def get_lablet_definition_internal(
        self,
        definition_id: Annotated[str, Path(description="Lablet definition ID")],
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Get a single lablet definition by ID.

        Called by lablet-controller to get definition details for provisioning.

        Args:
            definition_id: ID of the definition.
            api_key: Internal API key (from header).

        Returns:
            Full lablet definition details.
        """
        logger.info(f"[Internal] Getting lablet definition {definition_id}")

        query = GetLabletDefinitionQuery(id=definition_id)
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @post(
        "/lablet-definitions/{definition_id}/content-synced",
        summary="Record content sync result",
        tags=["Internal - Definitions"],
        status_code=200,
    )
    async def record_content_sync_result(
        self,
        definition_id: Annotated[str, Path(description="Lablet definition ID")],
        request: RecordContentSyncResultRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Record content synchronization result from lablet-controller.

        Called by lablet-controller's ContentSyncService after completing the
        sync pipeline (download, extract, upload, upstream notification).
        AD-CS-001: CPA records result and transitions definition state.

        Args:
            definition_id: ID of the definition that was synced.
            request: Sync result payload from lablet-controller.
            api_key: Internal API key (from header).

        Returns:
            LabletDefinitionSyncResultDto with sync outcome.
        """
        logger.info(f"[Internal] Recording content sync result for definition {definition_id} (status={request.sync_status})")

        command = RecordContentSyncResultCommand(
            definition_id=definition_id,
            sync_status=request.sync_status,
            error_message=request.error_message,
            lab_yaml_hash=request.lab_yaml_hash,
            content_package_hash=request.content_package_hash,
            upstream_version=request.upstream_version,
            upstream_date_published=request.upstream_date_published,
            upstream_instance_name=request.upstream_instance_name,
            upstream_form_id=request.upstream_form_id,
            grade_xml_path=request.grade_xml_path,
            cml_yaml_path=request.cml_yaml_path,
            cml_yaml_content=request.cml_yaml_content,
            devices_json=request.devices_json,
            upstream_sync_status=request.upstream_sync_status,
            port_template=request.port_template,
            node_count=request.node_count,
            node_definitions_required=request.node_definitions_required,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    # ==========================================================================
    # Worker Template Operations (for resource-scheduler)
    # ==========================================================================

    @get(
        "/worker-templates",
        summary="List Worker Templates (Internal)",
        tags=["Internal - Worker Templates"],
        status_code=200,
    )
    async def list_worker_templates(
        self,
        enabled_only: bool = Query(default=False, description="Only return enabled templates"),
        api_key: str = Depends(verify_internal_api_key),
    ) -> list[dict[str, Any]]:
        """List worker templates for service-to-service calls.

        Called by resource-scheduler for scale-up template selection.

        Args:
            enabled_only: Only return enabled templates.
            api_key: Internal API key (from header).

        Returns:
            List of worker template dictionaries.
        """
        logger.info(f"[Internal] Listing worker templates (enabled_only={enabled_only})")

        query = ListWorkerTemplatesQuery(enabled_only=enabled_only)
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @get(
        "/worker-templates/by-name/{name}",
        summary="Get Worker Template by Name (Internal)",
        tags=["Internal - Worker Templates"],
        status_code=200,
    )
    async def get_worker_template_by_name(
        self,
        name: str = Path(..., description="Template name"),
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Get a worker template by name for service-to-service calls.

        Called by worker-controller at provisioning time (ADR-016)
        and by resource-scheduler for scale-up recommendations.

        Args:
            name: Template name (e.g., "multi-sessions", "single-session").
            api_key: Internal API key (from header).

        Returns:
            Worker template dictionary.
        """
        logger.info(f"[Internal] Getting worker template by name: {name}")

        query = GetWorkerTemplateQuery(name=name)
        result = await self.mediator.execute_async(query)
        return self.process(result)

    # ==========================================================================
    # Settings Operations (for controllers)
    # ==========================================================================

    @get(
        "/settings/discovery",
        summary="Get Discovery Settings (Internal)",
        tags=["Internal - Settings"],
        status_code=200,
    )
    async def get_discovery_settings_internal(
        self,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Get worker discovery settings for controllers.

        Called by worker-controller to fetch current discovery configuration:
        - enabled: Whether discovery is active
        - regions: AWS regions to scan
        - ami_name_pattern: AMI pattern to match
        - scan_interval_seconds: Discovery scan interval

        Args:
            api_key: Internal API key (from header).

        Returns:
            Discovery settings dictionary.
        """
        from application.queries.get_system_settings_query import GetSystemSettingsQuery

        logger.info("[Internal] Getting discovery settings")

        query = GetSystemSettingsQuery()
        result = await self.mediator.execute_async(query)

        if result.is_success:
            settings = result.data
            discovery = settings.get("discovery", {})
            return {
                "enabled": discovery.get("enabled", True),
                "regions": discovery.get("regions", ["us-east-1"]),
                "ami_name_pattern": discovery.get("ami_name_pattern", "cisco-cml2.9*"),
                "scan_interval_seconds": discovery.get("scan_interval_seconds", 300),
            }
        return self.process(result)

    # ==========================================================================
    # License Status Operations (ADR-016)
    # ==========================================================================

    @post(
        "/workers/{worker_id}/license/start-registration",
        summary="Mark license registration as started",
        tags=["Internal - License"],
        status_code=200,
    )
    async def start_license_registration(
        self,
        worker_id: worker_id_annotation,
        request: StartLicenseRegistrationRequest | None = None,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Mark license registration as started.

        Called by worker-controller when it begins the CML API registration call.
        ADR-016: License operations go through worker-controller reconciliation.

        Args:
            worker_id: ID of the worker.
            request: Optional request with initiator info.
            api_key: Internal API key (from header).

        Returns:
            Status confirmation.
        """
        logger.info(f"[Internal] Starting license registration for worker {worker_id}")

        command = StartLicenseRegistrationCommand(
            worker_id=worker_id,
            initiated_by=request.initiated_by if request else None,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/workers/{worker_id}/license/complete-registration",
        summary="Mark license registration as completed",
        tags=["Internal - License"],
        status_code=200,
    )
    async def complete_license_registration(
        self,
        worker_id: worker_id_annotation,
        request: CompleteLicenseRegistrationRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Mark license registration as completed successfully.

        Called by worker-controller after successful CML API registration.
        ADR-016: License operations go through worker-controller reconciliation.

        Args:
            worker_id: ID of the worker.
            request: Registration completion details.
            api_key: Internal API key (from header).

        Returns:
            Status confirmation.
        """
        logger.info(f"[Internal] Completing license registration for worker {worker_id}")

        command = CompleteLicenseRegistrationCommand(
            worker_id=worker_id,
            registration_status=request.registration_status,
            smart_account=request.smart_account,
            virtual_account=request.virtual_account,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/workers/{worker_id}/license/fail-registration",
        summary="Mark license registration as failed",
        tags=["Internal - License"],
        status_code=200,
    )
    async def fail_license_registration(
        self,
        worker_id: worker_id_annotation,
        request: FailLicenseRegistrationRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Mark license registration as failed.

        Called by worker-controller when CML API registration fails.
        ADR-016: License operations go through worker-controller reconciliation.

        Args:
            worker_id: ID of the worker.
            request: Failure details.
            api_key: Internal API key (from header).

        Returns:
            Status confirmation.
        """
        logger.warning(f"[Internal] License registration failed for worker {worker_id}: {request.error_message}")

        command = FailLicenseRegistrationCommand(
            worker_id=worker_id,
            error_message=request.error_message,
            error_code=request.error_code,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/workers/{worker_id}/license/start-deregistration",
        summary="Mark license deregistration as started",
        tags=["Internal - License"],
        status_code=200,
    )
    async def start_license_deregistration(
        self,
        worker_id: worker_id_annotation,
        request: StartLicenseDeregistrationRequest | None = None,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Mark license deregistration as started.

        Called by worker-controller when it begins the CML API deregistration call.
        ADR-016: License operations go through worker-controller reconciliation.

        Args:
            worker_id: ID of the worker.
            request: Optional request with initiator info.
            api_key: Internal API key (from header).

        Returns:
            Status confirmation.
        """
        logger.info(f"[Internal] Starting license deregistration for worker {worker_id}")

        command = StartLicenseDeregistrationCommand(
            worker_id=worker_id,
            initiated_by=request.initiated_by if request else None,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/workers/{worker_id}/license/complete-deregistration",
        summary="Mark license deregistration as completed",
        tags=["Internal - License"],
        status_code=200,
    )
    async def complete_license_deregistration(
        self,
        worker_id: worker_id_annotation,
        request: CompleteLicenseDeregistrationRequest | None = None,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Mark license deregistration as completed successfully.

        Called by worker-controller after successful CML API deregistration.
        ADR-016: License operations go through worker-controller reconciliation.

        Args:
            worker_id: ID of the worker.
            request: Optional completion message.
            api_key: Internal API key (from header).

        Returns:
            Status confirmation.
        """
        logger.info(f"[Internal] Completing license deregistration for worker {worker_id}")

        command = CompleteLicenseDeregistrationCommand(
            worker_id=worker_id,
            message=request.message if request else "License deregistered successfully",
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post(
        "/workers/{worker_id}/license/fail-deregistration",
        summary="Mark license deregistration as failed",
        tags=["Internal - License"],
        status_code=200,
    )
    async def fail_license_deregistration(
        self,
        worker_id: worker_id_annotation,
        request: FailLicenseDeregistrationRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        """Mark license deregistration as failed.

        Called by worker-controller when CML API deregistration fails.
        ADR-016: License operations go through worker-controller reconciliation.

        Args:
            worker_id: ID of the worker.
            request: Failure details.
            api_key: Internal API key (from header).

        Returns:
            Status confirmation.
        """
        logger.warning(f"[Internal] License deregistration failed for worker {worker_id}: {request.error_message}")

        command = FailLicenseDeregistrationCommand(
            worker_id=worker_id,
            error_message=request.error_message,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)
