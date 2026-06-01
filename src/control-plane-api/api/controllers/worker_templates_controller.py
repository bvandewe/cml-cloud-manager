"""WorkerTemplates API controller with dual authentication (Session + JWT).

All operations use CQRS pattern via Mediator (ADR-001, ADR-015).
"""

from classy_fastapi.decorators import delete, get, patch, post, put
from classy_fastapi.routable import Routable
from fastapi import Depends
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator
from neuroglia.mvc import ControllerBase
from neuroglia.mvc.controller_base import generate_unique_id_function
from pydantic import BaseModel, Field

from api.dependencies import get_current_user, require_roles
from application.commands import (
    CreateWorkerTemplateCommand,
    DeleteWorkerTemplateCommand,
    DisableWorkerTemplateCommand,
    EnableWorkerTemplateCommand,
    UpdateWorkerTemplateCommand,
)
from application.queries import (
    GetWorkerTemplateQuery,
    ListWorkerTemplatesQuery,
)

# -------------------------------------------------------------------------
# Request Models (Pydantic — for OpenAPI schema / validation)
# -------------------------------------------------------------------------


class CreateWorkerTemplateRequest(BaseModel):
    """Request model for creating a WorkerTemplate."""

    name: str = Field(..., description="Unique template name", min_length=1, max_length=50)
    description: str = Field(..., description="Template description", min_length=1, max_length=200)
    instance_type: str = Field(..., description="EC2 instance type (e.g., t3.small, m5zn.metal)")

    # Capacity configuration
    cpu_cores: int = Field(default=4, ge=1, le=192, description="CPU cores")
    memory_gb: int = Field(default=8, ge=1, le=768, description="Memory in GB")
    storage_gb: int = Field(default=100, ge=10, le=2000, description="Storage in GB")
    max_nodes: int | None = Field(default=50, ge=1, le=500, description="Maximum lab nodes")

    # Configuration
    ami_name_pattern: str = Field(default="cisco-cml2.9*", description="AMI name pattern")
    cost_per_hour_usd: float = Field(default=0.0, ge=0, description="Cost per hour in USD")
    enabled: bool = Field(default=True, description="Whether template is enabled")


class UpdateWorkerTemplateRequest(BaseModel):
    """Request model for updating a WorkerTemplate.

    Only provided fields will be updated. Name is immutable.
    """

    description: str | None = Field(default=None, description="Updated description", min_length=1, max_length=200)
    instance_type: str | None = Field(default=None, description="Updated EC2 instance type")
    ami_name_pattern: str | None = Field(default=None, description="Updated AMI name pattern")
    cost_per_hour_usd: float | None = Field(default=None, ge=0, description="Updated cost per hour in USD")

    # Capacity fields (partial update supported)
    cpu_cores: int | None = Field(default=None, ge=1, le=192, description="Updated CPU cores")
    memory_gb: int | None = Field(default=None, ge=1, le=768, description="Updated memory in GB")
    storage_gb: int | None = Field(default=None, ge=10, le=2000, description="Updated storage in GB")
    max_nodes: int | None = Field(default=None, ge=1, le=500, description="Updated max lab nodes")


# -------------------------------------------------------------------------
# Controller
# -------------------------------------------------------------------------


class WorkerTemplatesController(ControllerBase):
    """Controller for WorkerTemplate management endpoints.

    All operations use CQRS pattern via Mediator (ADR-001, ADR-015).
    """

    def __init__(self, service_provider: ServiceProviderBase, mapper: Mapper, mediator: Mediator):
        self.service_provider = service_provider
        self.mapper = mapper
        self.mediator = mediator
        self.name = "WorkerTemplates"

        ControllerBase.__init__(self, service_provider, mapper, mediator)

        Routable.__init__(
            self,
            prefix="/worker-templates",
            tags=["Worker Templates"],
            generate_unique_id_function=generate_unique_id_function,
        )

    # ----- Queries -----

    @get("/", summary="List Worker Templates", tags=["Worker Templates"])
    async def list_templates(
        self,
        enabled_only: bool = False,
        include_deleted: bool = False,
        user: dict = Depends(get_current_user),
    ):
        """List all worker templates with optional filtering."""
        query = ListWorkerTemplatesQuery(
            enabled_only=enabled_only,
            include_deleted=include_deleted,
        )
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @get("/{template_id}", summary="Get Worker Template", tags=["Worker Templates"])
    async def get_template(
        self,
        template_id: str,
        user: dict = Depends(get_current_user),
    ):
        """Get a worker template by ID."""
        query = GetWorkerTemplateQuery(id=template_id)
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @get("/by-name/{name}", summary="Get Worker Template by Name", tags=["Worker Templates"])
    async def get_template_by_name(
        self,
        name: str,
        user: dict = Depends(get_current_user),
    ):
        """Get a worker template by name."""
        query = GetWorkerTemplateQuery(name=name)
        result = await self.mediator.execute_async(query)
        return self.process(result)

    # ----- Commands -----

    @post("/", summary="Create Worker Template", tags=["Worker Templates"], status_code=201)
    async def create_template(
        self,
        request: CreateWorkerTemplateRequest,
        user: dict = Depends(require_roles("admin", "lcm-admin")),
    ):
        """Create a new worker template. Requires admin role."""
        command = CreateWorkerTemplateCommand(
            name=request.name,
            description=request.description,
            instance_type=request.instance_type,
            cpu_cores=request.cpu_cores,
            memory_gb=request.memory_gb,
            storage_gb=request.storage_gb,
            max_nodes=request.max_nodes,
            ami_name_pattern=request.ami_name_pattern,
            cost_per_hour_usd=request.cost_per_hour_usd,
            enabled=request.enabled,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @put("/{template_id}", summary="Update Worker Template", tags=["Worker Templates"])
    async def update_template(
        self,
        template_id: str,
        request: UpdateWorkerTemplateRequest,
        user: dict = Depends(require_roles("admin", "lcm-admin")),
    ):
        """Update mutable fields of a worker template. Requires admin role."""
        command = UpdateWorkerTemplateCommand(
            template_id=template_id,
            description=request.description,
            instance_type=request.instance_type,
            ami_name_pattern=request.ami_name_pattern,
            cost_per_hour_usd=request.cost_per_hour_usd,
            cpu_cores=request.cpu_cores,
            memory_gb=request.memory_gb,
            storage_gb=request.storage_gb,
            max_nodes=request.max_nodes,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @delete("/{template_id}", summary="Delete Worker Template", tags=["Worker Templates"])
    async def delete_template(
        self,
        template_id: str,
        user: dict = Depends(require_roles("admin", "lcm-admin")),
    ):
        """Soft-delete a worker template. Requires admin role."""
        command = DeleteWorkerTemplateCommand(template_id=template_id)
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @patch("/{template_id}/enable", summary="Enable Worker Template", tags=["Worker Templates"])
    async def enable_template(
        self,
        template_id: str,
        user: dict = Depends(require_roles("admin", "lcm-admin")),
    ):
        """Enable a worker template for provisioning. Requires admin role."""
        command = EnableWorkerTemplateCommand(template_id=template_id)
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @patch("/{template_id}/disable", summary="Disable Worker Template", tags=["Worker Templates"])
    async def disable_template(
        self,
        template_id: str,
        user: dict = Depends(require_roles("admin", "lcm-admin")),
    ):
        """Disable a worker template. Requires admin role."""
        command = DisableWorkerTemplateCommand(template_id=template_id)
        result = await self.mediator.execute_async(command)
        return self.process(result)
