import logging
from typing import Annotated, Any

from classy_fastapi.decorators import delete, get, post
from fastapi import Depends, HTTPException, Path
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping.mapper import Mapper
from neuroglia.mediation.mediator import Mediator
from neuroglia.mvc.controller_base import ControllerBase

from api.dependencies import get_current_user, require_roles
from api.models import CreateCMLWorkerRequest, DeleteCMLWorkerRequest, ImportCMLWorkerRequest, RegisterLicenseRequest, UpdateCMLWorkerTagsRequest
from application.commands import (
    CreateCMLWorkerCommand,
    DeleteCMLWorkerCommand,
    DeregisterCMLWorkerLicenseCommand,
    DisableIdleDetectionCommand,
    EnableIdleDetectionCommand,
    EnableWorkerDetailedMonitoringCommand,
    RegisterCMLWorkerLicenseCommand,
    RequestWorkerRefreshCommand,
    StartCMLWorkerCommand,
    StopCMLWorkerCommand,
    UpdateCMLWorkerStatusCommand,
    UpdateCMLWorkerTagsCommand,
)
from application.queries import GetCMLWorkerByIdQuery, GetCMLWorkerResourcesQuery, GetCMLWorkersQuery
from application.queries.get_cml_worker_resources_query import CachedResourcesUtilization
from application.queries.get_worker_activity_query import GetWorkerActivityQuery
from application.queries.get_worker_idle_status_query import GetWorkerIdleStatusQuery
from domain.enums import CMLWorkerStatus
from integration.enums import AwsRegion

logger = logging.getLogger(__name__)

aws_region_annotation = Annotated[
    AwsRegion,
    Path(description="The identifier of the AWS Region where the CML Worker instance is hosted."),
]
instance_id_annotation = Annotated[
    str,
    Path(
        description="The AWS identifier of the CML Worker instance.",
        example="i-abcdef12345abcdef",
        min_length=19,
        max_length=19,
        pattern=r"^i-[a-z0-9]{17}$",
    ),
]
worker_id_annotation = Annotated[str, Path(description="The CML Worker UUID.")]


class WorkersController(ControllerBase):
    def __init__(self, service_provider: ServiceProviderBase, mapper: Mapper, mediator: Mediator):
        """Runs API Calls to AWS EC2."""
        ControllerBase.__init__(self, service_provider, mapper, mediator)

    @get(
        "/",
        response_model=list[dict],
        response_description="List of all CML Workers across all regions",
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def list_all_cml_workers(
        self,
        status: CMLWorkerStatus | None = None,
        include_terminated: bool = False,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Queries for all CML Worker instances across all regions.

        (**Requires valid token.**)"""
        query = GetCMLWorkersQuery(aws_region=None, status=status, include_terminated=include_terminated)
        return self.process(await self.mediator.execute_async(query))

    @get(
        "/region/{aws_region}/workers",
        response_model=list[dict],
        response_description="List of CML Workers",
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def list_cml_workers(
        self,
        aws_region: aws_region_annotation,
        status: CMLWorkerStatus | None = None,
        include_terminated: bool = False,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Queries for all CML Worker instances in a region.

        (**Requires valid token.**)"""
        query = GetCMLWorkersQuery(aws_region=aws_region, status=status, include_terminated=include_terminated)
        return self.process(await self.mediator.execute_async(query))

    @get(
        "/region/{aws_region}/workers/{worker_id}",
        response_model=dict,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def get_worker_details(
        self,
        aws_region: aws_region_annotation,
        worker_id: worker_id_annotation,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Queries for CML Worker instance details by worker ID.

        (**Requires valid token.**)"""
        query = GetCMLWorkerByIdQuery(worker_id=worker_id)
        return self.process(await self.mediator.execute_async(query))

    @post(
        "/region/{aws_region}/workers/{worker_id}/refresh",
        status_code=202,
        responses=ControllerBase.error_responses,
    )
    async def request_worker_refresh(
        self,
        aws_region: aws_region_annotation,
        worker_id: worker_id_annotation,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Request an on-demand data refresh for a worker.

        Triggers the worker-controller to perform a full data collection
        on the next reconciliation cycle, including:
        - EC2 instance details (AMI info, IPs, instance type)
        - CML system data (version, health, system_info, license)

        Worker must be in RUNNING state.

        (**Requires valid token.**)"""
        command = RequestWorkerRefreshCommand(
            worker_id=worker_id,
            requested_by="user",
        )
        return self.process(await self.mediator.execute_async(command))

    @get(
        "/region/{aws_region}/instance/{instance_id}",
        response_model=dict,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def get_worker_by_instance_id(
        self,
        aws_region: aws_region_annotation,
        instance_id: instance_id_annotation,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Queries for CML Worker instance details by AWS instance ID.

        (**Requires valid token.**)"""
        query = GetCMLWorkerByIdQuery(aws_instance_id=instance_id)
        return self.process(await self.mediator.execute_async(query))

    @get(
        "/region/{aws_region}/workers/{worker_id}/resources",
        response_model=CachedResourcesUtilization,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def get_worker_resources(
        self,
        aws_region: aws_region_annotation,
        worker_id: worker_id_annotation,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Returns cached CloudWatch metrics for a CML Worker.

        ADR-015: Returns cached data from database. Metrics are collected
        by worker-controller and stored periodically. Does NOT call CloudWatch.

        (**Requires valid token.**)"""
        query = GetCMLWorkerResourcesQuery(
            worker_id=worker_id,
            aws_region=aws_region,
        )
        return self.process(await self.mediator.execute_async(query))

    @post(
        "/region/{aws_region}/workers",
        response_model=Any,
        status_code=201,
        responses=ControllerBase.error_responses,
    )
    async def create_new_cml_worker(
        self,
        aws_region: aws_region_annotation,
        request: CreateCMLWorkerRequest,
        token: str = Depends(require_roles("admin")),
    ) -> Any:
        """Creates a new CML Worker instance in AWS EC2.

        (**Requires `admin` role!**)"""
        logger.info(f"Creating CML worker '{request.name}' in region {aws_region}")
        command = CreateCMLWorkerCommand(
            aws_region=aws_region,
            name=request.name,
            instance_type=request.instance_type,
            ami_id=request.ami_id,
            ami_name=request.ami_name,
            cml_version=request.cml_version,
        )
        return self.process(await self.mediator.execute_async(command))

    @post(
        "/region/{aws_region}/workers/import",
        response_model=Any,
        status_code=202,
        responses=ControllerBase.error_responses,
    )
    async def import_existing_cml_worker(
        self,
        aws_region: aws_region_annotation,
        request: ImportCMLWorkerRequest,
        token: str = Depends(require_roles("admin")),
    ) -> Any:
        """Request import of existing EC2 instance(s) as CML Worker(s).

        ADR-015: Worker discovery is handled by worker-controller.

        The worker-controller continuously watches for EC2 instances with CML tags
        and automatically imports them. Use this endpoint to request an immediate
        discovery scan.

        **Note**: This endpoint returns immediately. Worker-controller will
        perform the discovery asynchronously and register any new workers.

        (**Requires `admin` role!**)"""
        logger.info(f"Worker import requested for region {aws_region}")
        # ADR-015: No direct EC2 calls from control-plane-api.
        # Worker-controller handles discovery via etcd watch.
        # TODO: Implement proper refresh request mechanism via etcd/event
        return {
            "message": "Worker import request accepted",
            "region": aws_region.value,
            "status": "accepted",
            "note": "Worker-controller will perform discovery asynchronously. New workers will appear in the workers list once discovered.",
        }

    @delete(
        "/region/{aws_region}/workers/{worker_id}",
        response_model=Any,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def delete_cml_worker(
        self,
        aws_region: aws_region_annotation,
        worker_id: worker_id_annotation,
        request: DeleteCMLWorkerRequest,
        token: str = Depends(require_roles("admin")),
    ) -> Any:
        """Deletes a CML Worker (soft delete).

        ADR-015: Uses soft delete pattern for consistency with GC behavior.

        Default behavior (soft delete):
        1. Sets desired_status=TERMINATED
        2. Worker-controller terminates EC2 instance via etcd watch
        3. Record is retained for audit
        4. CleanupTerminatedWorkersJob purges old records

        Set 'force_hard_delete' to true for immediate removal (admin escape hatch).

        (**Requires `admin` role!**)
        """
        logger.info(f"Deleting CML worker {worker_id} in region {aws_region}, force_hard_delete={request.force_hard_delete}")
        command = DeleteCMLWorkerCommand(
            worker_id=worker_id,
            force_hard_delete=request.force_hard_delete,
            deleted_by=token.get("sub") if isinstance(token, dict) else None,
        )
        return self.process(await self.mediator.execute_async(command))

    @post(
        "/region/{aws_region}/workers/{worker_id}/start",
        response_model=Any,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def start_cml_worker(
        self,
        aws_region: aws_region_annotation,
        worker_id: worker_id_annotation,
        token: str = Depends(require_roles("admin")),
    ) -> Any:
        """Starts a stopped CML Worker instance.

        (**Requires `admin` role!**)"""
        logger.info(f"Starting CML worker {worker_id} in region {aws_region}")
        command = StartCMLWorkerCommand(worker_id=worker_id)
        return self.process(await self.mediator.execute_async(command))

    @post(
        "/region/{aws_region}/workers/{worker_id}/stop",
        response_model=Any,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def stop_cml_worker(
        self,
        aws_region: aws_region_annotation,
        worker_id: worker_id_annotation,
        token: str = Depends(require_roles("admin")),
    ) -> Any:
        """Stops a running CML Worker instance.

        (**Requires `admin` role!**)"""
        logger.info(f"Stopping CML worker {worker_id} in region {aws_region}")
        command = StopCMLWorkerCommand(worker_id=worker_id)
        return self.process(await self.mediator.execute_async(command))

    @post(
        "/region/{aws_region}/workers/{worker_id}/tags",
        response_model=Any,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def update_cml_worker_tags(
        self,
        aws_region: aws_region_annotation,
        worker_id: worker_id_annotation,
        request: UpdateCMLWorkerTagsRequest,
        token: str = Depends(require_roles("admin")),
    ) -> Any:
        """Updates tags for a CML Worker instance.

        (**Requires `admin` role!**)"""
        logger.info(f"Updating tags for CML worker {worker_id} in region {aws_region}")
        command = UpdateCMLWorkerTagsCommand(worker_id=worker_id, tags=request.tags)
        return self.process(await self.mediator.execute_async(command))

    @get(
        "/region/{aws_region}/workers/{worker_id}/status",
        response_model=Any,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def get_cml_worker_status(
        self,
        aws_region: aws_region_annotation,
        worker_id: worker_id_annotation,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Gets the current status of a CML Worker instance.

        (**Requires valid token.**)"""
        logger.info(f"Getting status for CML worker {worker_id} in region {aws_region}")
        command = UpdateCMLWorkerStatusCommand(worker_id=worker_id)
        return self.process(await self.mediator.execute_async(command))

    @post(
        "/region/{aws_region}/workers/{worker_id}/refresh",
        response_model=Any,
        status_code=202,
        responses=ControllerBase.error_responses,
    )
    async def refresh_worker(
        self,
        aws_region: aws_region_annotation,
        worker_id: worker_id_annotation,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Request worker data refresh (asynchronous).

        ADR-015: Worker data refresh is handled by worker-controller.

        The worker-controller continuously monitors worker state via EC2 and CloudWatch
        APIs. This endpoint accepts a refresh request and returns immediately.

        Data refreshed by worker-controller:
        - EC2 instance status and metadata
        - CloudWatch metrics (CPU, memory, storage)

        Data refreshed by lablet-controller:
        - CML service data (version, license, uptime, stats)
        - Lab records (topology, nodes, state)

        Use SSE events to receive real-time updates when refresh completes.

        (**Requires valid token.**)"""
        logger.info(f"Worker refresh requested for {worker_id} in region {aws_region}")
        # ADR-015: No direct EC2/CloudWatch/CML calls from control-plane-api.
        # Worker-controller and lablet-controller handle refresh via etcd watch.
        # TODO: Implement proper refresh request mechanism via etcd/event
        return {
            "message": "Worker refresh request accepted",
            "worker_id": worker_id,
            "region": aws_region.value,
            "status": "accepted",
            "note": "Worker-controller will refresh data asynchronously. Subscribe to SSE events for real-time updates.",
        }

    @post(
        "/region/{aws_region}/workers/{worker_id}/monitoring",
        response_model=Any,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def enable_detailed_monitoring(
        self,
        aws_region: aws_region_annotation,
        worker_id: worker_id_annotation,
        token: str = Depends(require_roles("admin")),
    ) -> Any:
        """Enables detailed CloudWatch monitoring on a CML Worker instance.

        This enables 1-minute metric granularity instead of 5-minute (costs ~$2.10/month).

        (**Requires `admin` role!**)"""
        logger.info(f"Enabling detailed monitoring for CML worker {worker_id} in region {aws_region}")
        command = EnableWorkerDetailedMonitoringCommand(worker_id=worker_id)
        result = await self.mediator.execute_async(command)

        if not result or not result.is_success:
            logger.error(f"Failed to enable monitoring for worker {worker_id}: {result}")
            raise HTTPException(status_code=500, detail="Failed to enable detailed monitoring")

        logger.info(f"✅ Successfully enabled monitoring for worker {worker_id}")
        return self.process(result)

    @post(
        "/region/{aws_region}/workers/{worker_id}/license",
        response_model=Any,
        status_code=202,
        responses=ControllerBase.error_responses,
    )
    async def register_license(
        self,
        aws_region: aws_region_annotation,
        worker_id: worker_id_annotation,
        request: RegisterLicenseRequest,
        token: str = Depends(require_roles("admin")),
    ) -> Any:
        """Registers a license for a CML Worker instance.

        This is an asynchronous operation that returns immediately with 202 Accepted.
        The actual registration process (which can take 5-90 seconds) happens in
        a background job. Monitor SSE events for completion status:

        - worker.license.registration.started: Registration initiated
        - worker.license.registration.completed: Registration successful
        - worker.license.registration.failed: Registration failed

        (**Requires `admin` role!**)"""
        logger.info(f"Registering license for CML worker {worker_id} in region {aws_region}")

        command = RegisterCMLWorkerLicenseCommand(
            worker_id=worker_id,
            license_token=request.license_token,
            reregister=request.reregister,
            initiated_by=token.get("sub") if isinstance(token, dict) else None,
        )

        return self.process(await self.mediator.execute_async(command))

    @delete(
        "/region/{aws_region}/workers/{worker_id}/license",
        response_model=Any,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def deregister_license(
        self,
        aws_region: aws_region_annotation,
        worker_id: worker_id_annotation,
        token: str = Depends(require_roles("admin")),
    ) -> Any:
        """Deregisters the license from a CML Worker instance.

        This removes the worker from Cisco Smart Licensing. The operation
        can take 10-60 seconds and is handled synchronously.

        (**Requires `admin` role!**)"""
        logger.info(f"Deregistering license for CML worker {worker_id} in region {aws_region}")

        command = DeregisterCMLWorkerLicenseCommand(
            worker_id=worker_id,
            initiated_by=token.get("sub") if isinstance(token, dict) else None,
        )

        return self.process(await self.mediator.execute_async(command))

    @get(
        "/region/{aws_region}/workers/{worker_id}/activity",
        response_model=dict[str, Any],
        summary="Get Worker Activity Tracking Data",
        description="Retrieve activity tracking information including recent telemetry events and lifecycle timestamps.",
    )
    async def get_worker_activity(
        self,
        aws_region: aws_region_annotation,
        worker_id: worker_id_annotation,
        current_user: Annotated[dict, Depends(get_current_user)],
    ) -> Any:
        """Get activity tracking data for a CML worker.

        Returns recent telemetry events, last activity timestamp, pause/resume history,
        and idle detection state.

        (**Requires authentication!**)"""
        logger.info(f"Fetching activity data for worker {worker_id} in region {aws_region}")
        query = GetWorkerActivityQuery(worker_id=worker_id)
        return self.process(await self.mediator.execute_async(query))

    @get(
        "/region/{aws_region}/workers/{worker_id}/idle-status",
        response_model=dict[str, Any],
        summary="Check Worker Idle Status",
        description="Check if worker is idle and eligible for auto-pause based on activity thresholds.",
    )
    async def get_worker_idle_status(
        self,
        aws_region: aws_region_annotation,
        worker_id: worker_id_annotation,
        current_user: Annotated[dict, Depends(get_current_user)],
    ) -> Any:
        """Check idle status for a CML worker.

        Returns idle state, eligibility for auto-pause, snooze period status,
        and timing information for next checks.

        (**Requires authentication!**)"""
        logger.info(f"Checking idle status for worker {worker_id} in region {aws_region}")
        query = GetWorkerIdleStatusQuery(worker_id=worker_id)
        return self.process(await self.mediator.execute_async(query))

    @post(
        "/region/{aws_region}/workers/{worker_id}/idle-detection/enable",
        response_model=dict[str, Any],
        summary="Enable Idle Detection",
        description="Enable automatic idle detection and auto-pause for a CML worker. **Admin only**.",
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def enable_idle_detection(
        self,
        aws_region: aws_region_annotation,
        worker_id: worker_id_annotation,
        current_user: Annotated[dict, Depends(require_roles("admin"))],
    ) -> Any:
        """Enable idle detection for a CML worker.

        When enabled, the worker will be automatically stopped after
        a configured idle timeout period to save costs.

        (**Requires admin role!**)"""
        logger.info(f"Enabling idle detection for worker {worker_id} in region {aws_region}")

        # Extract user ID from current_user if available
        user_id = current_user.get("sub") if isinstance(current_user, dict) else None

        command = EnableIdleDetectionCommand(worker_id=worker_id, enabled_by=user_id)
        return self.process(await self.mediator.execute_async(command))

    @post(
        "/region/{aws_region}/workers/{worker_id}/idle-detection/disable",
        response_model=dict[str, Any],
        summary="Disable Idle Detection",
        description="Disable automatic idle detection and auto-pause for a CML worker. **Admin only**.",
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def disable_idle_detection(
        self,
        aws_region: aws_region_annotation,
        worker_id: worker_id_annotation,
        current_user: Annotated[dict, Depends(require_roles("admin"))],
    ) -> Any:
        """Disable idle detection for a CML worker.

        When disabled, the worker will not be automatically stopped
        due to inactivity, even if the idle timeout threshold is reached.

        (**Requires admin role!**)"""
        logger.info(f"Disabling idle detection for worker {worker_id} in region {aws_region}")

        # Extract user ID from current_user if available
        user_id = current_user.get("sub") if isinstance(current_user, dict) else None

        command = DisableIdleDetectionCommand(worker_id=worker_id, disabled_by=user_id)
        return self.process(await self.mediator.execute_async(command))

    @post(
        "/workers/refresh",
        response_model=dict[str, Any],
        summary="Trigger Workers Refresh",
        description="Trigger the auto-import workers job to refresh the workers list.",
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def trigger_workers_refresh(
        self,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Trigger a full workers refresh via the auto-import job.

        This endpoint triggers the AutoImportWorkersJob to:
        1. Discover EC2 instances matching the configured AMI
        2. Import any new instances not already registered
        3. Refresh data for newly imported workers

        If the next scheduled job run is within 10 seconds, the request
        is skipped to avoid redundant execution.

        If a job is currently running, returns a status indicating
        the job is in progress.

        (**Requires authentication!**)
        """
        import datetime

        from application.services import BackgroundTaskScheduler

        logger.info("Manual workers refresh requested")

        try:
            scheduler: BackgroundTaskScheduler = self.service_provider.get_required_service(BackgroundTaskScheduler)
            if not scheduler or not scheduler._scheduler:
                raise HTTPException(status_code=503, detail="Scheduler not available")

            job_id = "AutoImportWorkersJob-global"
            job = scheduler._scheduler.get_job(job_id)

            if not job:
                # Job not scheduled - may be disabled
                logger.warning("AutoImportWorkersJob not found - auto-import may be disabled")
                return {
                    "status": "unavailable",
                    "message": "Auto-import workers job is not scheduled. Check if auto-import is enabled.",
                    "job_id": job_id,
                }

            # Check if job is running (next_run_time is None when executing)
            if job.next_run_time is None:
                logger.info("AutoImportWorkersJob is currently running")
                return {
                    "status": "running",
                    "message": "Workers refresh is already in progress. Please wait for completion.",
                    "job_id": job_id,
                }

            # Check if next scheduled run is within 10 seconds
            now = datetime.datetime.now(datetime.timezone.utc)
            next_run = job.next_run_time
            if next_run.tzinfo is None:
                next_run = next_run.replace(tzinfo=datetime.timezone.utc)

            seconds_until_next = (next_run - now).total_seconds()

            if seconds_until_next <= 10:
                logger.info(f"AutoImportWorkersJob scheduled in {seconds_until_next:.1f}s - skipping manual trigger")
                return {
                    "status": "scheduled",
                    "message": f"Workers refresh is scheduled to run in {seconds_until_next:.0f} seconds.",
                    "job_id": job_id,
                    "next_run_time": next_run.isoformat(),
                    "seconds_until_next": round(seconds_until_next, 1),
                }

            # Trigger the job to run now
            await scheduler.trigger_job_now(job_id)

            logger.info(f"AutoImportWorkersJob triggered manually (was scheduled in {seconds_until_next:.0f}s)")
            return {
                "status": "triggered",
                "message": "Workers refresh triggered successfully. The list will update when complete.",
                "job_id": job_id,
                "previous_next_run": next_run.isoformat(),
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to trigger workers refresh: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to trigger workers refresh: {str(e)}")
