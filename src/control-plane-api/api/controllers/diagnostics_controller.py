"""Diagnostics API controller exposing system configuration and controller status.

Note: APScheduler-based background jobs were removed in ADR-011. Worker monitoring
and discovery are now handled by dedicated controller microservices (worker-controller,
lablet-controller) using the HostedService pattern.
"""

import logging

from classy_fastapi.decorators import get
from fastapi import Depends
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator
from neuroglia.mvc import ControllerBase

from api.dependencies import get_current_user, require_roles
from application.settings import app_settings

log = logging.getLogger(__name__)


class DiagnosticsController(ControllerBase):
    """Controller providing operational diagnostics and system configuration."""

    def __init__(self, service_provider: ServiceProviderBase, mapper: Mapper, mediator: Mediator):
        super().__init__(service_provider, mapper, mediator)
        # Prefix override to serve under /api/diagnostics
        self.prefix = "diagnostics"

    @get("/intervals")
    async def get_intervals(self, user: dict = Depends(get_current_user)):
        """Return configured system settings and controller information.

        Note: APScheduler job scheduling was removed in ADR-011.
        Worker monitoring is now handled by dedicated controller microservices.

        Authentication: session cookie or bearer token.
        """
        return {
            "settings": {
                "worker_metrics_poll_interval": app_settings.worker_metrics_poll_interval,
                "labs_refresh_interval": getattr(app_settings, "labs_refresh_interval", None),
                "auto_import_workers_interval": getattr(app_settings, "auto_import_workers_interval", None),
            },
            "note": "APScheduler removed per ADR-011. Monitoring handled by controller microservices.",
            "controllers": {
                "worker_controller": {
                    "description": "Handles worker discovery, metrics collection, and reconciliation",
                    "endpoint": getattr(app_settings, "worker_controller_url", None),
                },
                "lablet_controller": {
                    "description": "Handles lab resource management and reconciliation",
                    "endpoint": getattr(app_settings, "lablet_controller_url", None),
                },
            },
        }

    @get("/jobs")
    async def list_jobs(self, user: dict = Depends(require_roles("admin", "manager"))):
        """Return deprecation notice for APScheduler jobs endpoint.

        APScheduler was removed in ADR-011. Background job scheduling is now
        handled by controller microservices using the HostedService pattern.

        Returns deprecation notice instead of job list.
        """
        return {
            "deprecated": True,
            "message": "APScheduler removed per ADR-011. Background tasks now run in controller microservices.",
            "documentation": "See docs/architecture/worker-monitoring.md for current architecture.",
            "jobs": [],
        }
