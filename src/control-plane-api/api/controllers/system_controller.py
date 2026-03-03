import logging
from typing import Any

from classy_fastapi.decorators import get
from fastapi import Depends
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping.mapper import Mapper
from neuroglia.mediation.mediator import Mediator
from neuroglia.mvc.controller_base import ControllerBase

from api.dependencies import get_current_user, require_roles

logger = logging.getLogger(__name__)


class SystemController(ControllerBase):
    """Controller for system internals and monitoring endpoints.

    Note: APScheduler has been removed per ADR-011. Background jobs are now handled by:
    - worker-controller: WorkerReconciler (includes discovery loop)
    - lablet-controller: LabletReconciler
    - resource-scheduler: ResourceScheduler

    The scheduler/* endpoints have been deprecated and removed.
    """

    # Class-level prefix so decorators pick it up reliably
    prefix = "system"

    def __init__(self, service_provider: ServiceProviderBase, mapper: Mapper, mediator: Mediator):
        ControllerBase.__init__(self, service_provider, mapper, mediator)

    @get(
        "/health",
        response_model=dict,
        response_description="System health status",
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def get_system_health(
        self,
        token: str = Depends(get_current_user),
        roles: str = Depends(require_roles("admin", "manager", "user")),
    ) -> Any:
        """Return aggregated system health using `SystemHealthService`."""
        from application.services.system_health_service import SystemHealthService

        svc: SystemHealthService = self.service_provider.get_required_service(SystemHealthService)
        return await svc.get_system_health(self.mediator, self.service_provider)

    @get(
        "/scheduler/status",
        response_model=dict,
        response_description="Controller-based job execution status",
        status_code=200,
        responses=ControllerBase.error_responses,
        deprecated=True,
    )
    async def get_scheduler_status(
        self,
        token: str = Depends(get_current_user),
        roles: str = Depends(require_roles("admin", "manager", "user")),
    ) -> Any:
        """Get status of background job execution.

        **DEPRECATED**: APScheduler has been removed per ADR-011.
        Background jobs are now executed by dedicated controllers:
        - worker-controller: Worker discovery and reconciliation
        - lablet-controller: Lablet instance reconciliation
        - resource-scheduler: Resource scheduling

        Use the controller health endpoints to check their status.
        """
        return {
            "deprecated": True,
            "message": "APScheduler removed per ADR-011. Jobs now run in dedicated controllers.",
            "controllers": {
                "worker-controller": "Handles WorkerReconciler (includes discovery loop)",
                "lablet-controller": "Handles LabletReconciler",
                "resource-scheduler": "Handles resource scheduling",
            },
            "migration_guide": "See docs/architecture/adr/ADR-011-apscheduler-removal.md",
        }

    @get(
        "/monitoring/workers",
        response_model=dict,
        response_description="Worker monitoring status (via worker-controller)",
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def get_worker_monitoring_status(
        self,
        token: str = Depends(get_current_user),
        roles: str = Depends(require_roles("admin", "manager", "user")),
    ) -> Any:
        """Get worker monitoring status.

        Worker monitoring is now handled by worker-controller's WorkerReconciler.
        This endpoint provides a summary of workers being monitored.
        """
        from application.queries.list_cml_workers_internal_query import ListCMLWorkersInternalQuery

        # Get workers via internal query
        query = ListCMLWorkersInternalQuery(
            status="RUNNING",
            include_terminated=False,
        )
        result = await self.mediator.execute_async(query)

        if result.is_success:
            workers = result.data or []
            return {
                "monitoring_service": "worker-controller",
                "monitored_workers": len(workers),
                "workers": [
                    {
                        "worker_id": w.get("id"),
                        "name": w.get("name"),
                        "status": w.get("status"),
                        "last_metrics_at": w.get("last_metrics_at"),
                    }
                    for w in workers[:20]  # Limit to 20 for summary
                ],
                "message": "Worker metrics collected by worker-controller WorkerReconciler",
            }
        else:
            return {
                "monitoring_service": "worker-controller",
                "monitored_workers": 0,
                "workers": [],
                "error": result.error_message,
            }
