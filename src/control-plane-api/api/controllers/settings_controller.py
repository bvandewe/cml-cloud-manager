"""System Settings Controller."""

import logging
from typing import Any

from classy_fastapi.decorators import get, patch, put
from fastapi import Depends
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping.mapper import Mapper
from neuroglia.mediation.mediator import Mediator
from neuroglia.mvc.controller_base import ControllerBase

from api.dependencies import get_current_user, require_roles
from api.models import UpdateSystemSettingsRequest
from api.models.system_settings_requests import DiscoverySettingsRequest
from application.commands import UpdateSystemSettingsCommand
from application.queries.get_system_settings_query import GetSystemSettingsQuery

logger = logging.getLogger(__name__)


class SettingsController(ControllerBase):
    """Controller for managing system settings."""

    def __init__(self, service_provider: ServiceProviderBase, mapper: Mapper, mediator: Mediator):
        ControllerBase.__init__(self, service_provider, mapper, mediator)

    @get(
        "/",
        response_model=dict[str, Any],
        response_description="System Settings",
        status_code=200,
        responses=ControllerBase.error_responses,
        dependencies=[Depends(require_roles("admin"))],
    )
    async def get_settings(
        self,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Get system settings.

        (**Requires admin role.**)
        """
        query = GetSystemSettingsQuery()
        return self.process(await self.mediator.execute_async(query))

    @put(
        "/",
        response_model=dict[str, Any],
        response_description="Updated System Settings",
        status_code=200,
        responses=ControllerBase.error_responses,
        dependencies=[Depends(require_roles("admin"))],
    )
    async def update_settings(
        self,
        request: UpdateSystemSettingsRequest,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Update system settings.

        (**Requires admin role.**)
        """
        command = UpdateSystemSettingsCommand(
            worker_provisioning=request.worker_provisioning,
            monitoring=request.monitoring,
            idle_detection=request.idle_detection,
            discovery=request.discovery,
            updated_by="admin",  # In a real app, extract user from token
        )
        return self.process(await self.mediator.execute_async(command))

    # ==========================================================================
    # Discovery Settings Endpoints (ADR-012)
    # ==========================================================================

    @get(
        "/discovery",
        response_model=dict[str, Any],
        response_description="Worker Discovery Settings",
        status_code=200,
        responses=ControllerBase.error_responses,
        dependencies=[Depends(require_roles("admin", "manager"))],
    )
    async def get_discovery_settings(
        self,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Get worker discovery settings.

        Returns the current configuration for worker discovery:
        - enabled: Whether discovery is active
        - regions: AWS regions to scan
        - ami_name_pattern: AMI pattern to match
        - scan_interval_seconds: Discovery scan interval

        (**Requires admin or manager role.**)
        """
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

    @patch(
        "/discovery",
        response_model=dict[str, Any],
        response_description="Updated Discovery Settings",
        status_code=200,
        responses=ControllerBase.error_responses,
        dependencies=[Depends(require_roles("admin"))],
    )
    async def update_discovery_settings(
        self,
        request: DiscoverySettingsRequest,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Update worker discovery settings.

        Allows admins to configure:
        - enabled: Enable/disable worker discovery
        - regions: AWS regions to scan for CML workers
        - ami_name_pattern: AMI name pattern to match (e.g., "cisco-cml2.9*")
        - scan_interval_seconds: Seconds between discovery scans (60-3600)

        Changes take effect within the next scan interval.

        (**Requires admin role.**)
        """
        command = UpdateSystemSettingsCommand(
            discovery={
                "enabled": request.enabled,
                "regions": request.regions,
                "ami_name_pattern": request.ami_name_pattern,
                "scan_interval_seconds": request.scan_interval_seconds,
            },
            updated_by="admin",
        )
        result = await self.mediator.execute_async(command)
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
