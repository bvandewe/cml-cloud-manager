"""LabletDefinitions API controller with dual authentication (Session + JWT)."""

from api.dependencies import get_current_user, require_roles
from application.commands import (
    CreateLabletDefinitionCommand,
    SyncLabletDefinitionCommand,
    UpdateLabletDefinitionCommand,
)
from application.queries import (
    GetDefinitionResourceObservationsQuery,
    GetLabletDefinitionQuery,
    ListLabletDefinitionsQuery,
    SearchLabletDefinitionsQuery,
)
from classy_fastapi.decorators import get, post, put
from classy_fastapi.routable import Routable
from fastapi import Depends
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator
from neuroglia.mvc import ControllerBase
from neuroglia.mvc.controller_base import generate_unique_id_function
from pydantic import BaseModel, Field


class CreateLabletDefinitionRequest(BaseModel):
    """Request model for creating a LabletDefinition.

    The form_qualified_name is required and auto-derives bucket_name + lab_artifact_uri.
    Created definitions start in PENDING_SYNC status (ADR-028).
    """

    name: str = Field(..., description="Unique name for the lablet definition", min_length=1, max_length=100)
    version: str = Field(..., description="Semantic version (e.g., '1.0.0')", min_length=1, max_length=20)
    form_qualified_name: str = Field(
        ...,
        description="Form Qualified Name (6 space-separated components, e.g., 'Exam Associate CCNA v1.1 LAB 1.3a')",
        min_length=3,
        max_length=200,
    )

    # Resource requirements
    cpu_cores: int = Field(default=2, ge=1, le=64, description="Required CPU cores")
    memory_gb: int = Field(default=4, ge=1, le=256, description="Required memory in GB")
    storage_gb: int = Field(default=20, ge=1, le=1000, description="Required storage in GB")
    nested_virt: bool = Field(default=True, description="Requires nested virtualization")

    # License affinity
    license_affinity: list[str] | None = Field(
        default=None,
        description="License types this lab can run on: personal, enterprise, evaluation",
    )

    # Lab topology
    node_count: int = Field(default=1, ge=1, le=50, description="Number of nodes in the lab")

    # Port template
    port_definitions: list[dict] | None = Field(
        default=None,
        description="Port definitions: [{'name': 'ssh', 'protocol': 'tcp', 'description': 'SSH access'}]",
    )

    # Content package configuration (AD-CS-002)
    user_session_package_name: str = Field(default="SVN.zip", description="Package filename in S3 bucket for LDS")
    grading_ruleset_package_name: str = Field(default="SVN.zip", description="Grading rules package filename")
    user_session_type: str = Field(default="LDS", description="User session delivery type")
    user_session_default_region: str | None = Field(default=None, description="Default LDS region for this definition")

    # Optional fields (auto-derived or populated by sync)
    lab_artifact_uri: str | None = Field(default=None, description="Auto-derived from FQN if not provided")
    lab_yaml_hash: str = Field(default="", description="Leave empty — populated by content sync")
    lab_yaml_cached: str | None = Field(default=None, description="Cached lab YAML content")
    grading_rules_uri: str | None = Field(default=None, description="URI to grading rules")
    max_duration_minutes: int = Field(default=60, ge=1, le=480, description="Max lab duration in minutes")
    warm_pool_depth: int = Field(default=0, ge=0, le=10, description="Pre-provisioned instances to keep warm")

    # Notification config
    owner_notification: dict | None = Field(default=None, description="Notification configuration for lab owner")


class UpdateLabletDefinitionRequest(BaseModel):
    """Request model for updating a LabletDefinition.

    Only provided fields will be updated.
    For ACTIVE definitions, an edit triggers a version bump (deprecate old → create new in PENDING_SYNC).
    For PENDING_SYNC definitions, an in-place update is performed.
    """

    # Identity fields (sent by UI for context; name is immutable, version auto-incremented on bump)
    name: str | None = Field(default=None, description="Definition name (informational, cannot be changed)")
    version: str | None = Field(default=None, description="Version (informational, auto-incremented on version bump)")

    # Content identification
    form_qualified_name: str | None = Field(
        default=None,
        description="Form Qualified Name (6 space-separated components)",
        min_length=3,
        max_length=200,
    )

    lab_artifact_uri: str | None = Field(default=None, description="Updated URI to the lab YAML artifact")
    lab_yaml_hash: str | None = Field(default=None, description="Updated SHA256 hash of the lab YAML content")

    # Resource requirements
    cpu_cores: int | None = Field(default=None, ge=1, le=64, description="Required CPU cores")
    memory_gb: int | None = Field(default=None, ge=1, le=256, description="Required memory in GB")
    storage_gb: int | None = Field(default=None, ge=1, le=1000, description="Required storage in GB")
    nested_virt: bool | None = Field(default=None, description="Requires nested virtualization")

    # License affinity
    license_affinity: list[str] | None = Field(
        default=None,
        description="License types this lab can run on: personal, enterprise, evaluation",
    )

    # Lab topology
    node_count: int | None = Field(default=None, ge=1, le=50, description="Number of nodes in the lab")

    # Content sync settings
    user_session_package_name: str | None = Field(default=None, description="Package filename in S3 bucket for LDS")
    grading_ruleset_package_name: str | None = Field(default=None, description="Grading rules package filename")
    user_session_type: str | None = Field(default=None, description="User session delivery type (e.g., LDS)")
    user_session_default_region: str | None = Field(default=None, description="Default LDS region for user sessions")

    # Optional fields
    grading_rules_uri: str | None = Field(default=None, description="URI to grading rules")
    max_duration_minutes: int | None = Field(default=None, ge=1, le=480, description="Max lab duration in minutes")
    warm_pool_depth: int | None = Field(default=None, ge=0, le=10, description="Pre-provisioned instances to keep warm")


class LabletDefinitionsController(ControllerBase):
    """Controller for LabletDefinition management endpoints.

    Provides CRUD operations for lablet definitions, which are versioned
    templates that define how lab instances are created.
    """

    def __init__(self, service_provider: ServiceProviderBase, mapper: Mapper, mediator: Mediator):
        # Store DI services first (don't call super().__init__ to avoid double route registration)
        self.service_provider = service_provider
        self.mapper = mapper
        self.mediator = mediator
        self.name = "LabletDefinitions"

        # Initialize base Controller (incl. JsonSerializer)
        ControllerBase.__init__(self, service_provider, mapper, mediator)

        # Call Routable.__init__ directly with custom kebab-case prefix
        Routable.__init__(
            self,
            prefix="/lablet-definitions",
            tags=["Lablet Definitions"],
            generate_unique_id_function=generate_unique_id_function,
        )

    @get("/search", summary="Search Lablet Definitions", tags=["Lablet Definitions"])
    async def search_definitions(
        self,
        q: str,
        limit: int = 10,
        include_deprecated: bool = False,
        user: dict = Depends(get_current_user),
    ):
        """Search lablet definitions by name for autocomplete/typeahead.

        Returns matching definitions where the search query appears anywhere
        in the definition name (case-insensitive).

        Parameters:
        - **q**: Search query (minimum 2 characters)
        - **limit**: Maximum results (default 10, max 50)
        - **include_deprecated**: Include deprecated definitions (default false)

        Returns:
            List of matching LabletDefinitionSummaryDto
        """
        query = SearchLabletDefinitionsQuery(
            q=q,
            limit=limit,
            include_deprecated=include_deprecated,
        )
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @get("/", summary="List Lablet Definitions", tags=["Lablet Definitions"])
    async def list_definitions(
        self,
        name: str | None = None,
        status: str | None = None,
        include_deprecated: bool = False,
        skip: int = 0,
        limit: int = 100,
        user: dict = Depends(get_current_user),
    ):
        """List lablet definitions with optional filtering.

        Filters:
        - **name**: Filter by definition name (exact match)
        - **status**: Filter by status (active, deprecated, archived)
        - **include_deprecated**: Include deprecated definitions

        Pagination:
        - **skip**: Number of records to skip
        - **limit**: Maximum number of records to return
        """
        query = ListLabletDefinitionsQuery(
            name=name,
            status=status,
            include_deprecated=include_deprecated,
            skip=skip,
            limit=limit,
        )
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @get("/{definition_id}", summary="Get Lablet Definition", tags=["Lablet Definitions"])
    async def get_definition(
        self,
        definition_id: str,
        user: dict = Depends(get_current_user),
    ):
        """Get a single lablet definition by ID.

        Returns the full definition details including resource requirements,
        port template, and lifecycle status.
        """
        query = GetLabletDefinitionQuery(id=definition_id)
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @get(
        "/by-name/{name}/version/{version}",
        summary="Get Lablet Definition by Name and Version",
        tags=["Lablet Definitions"],
    )
    async def get_definition_by_name_version(
        self,
        name: str,
        version: str,
        user: dict = Depends(get_current_user),
    ):
        """Get a lablet definition by name and version.

        Useful for retrieving a specific version of a definition.
        """
        query = GetLabletDefinitionQuery(name=name, version=version)
        result = await self.mediator.execute_async(query)
        return self.process(result)

    @post("/", summary="Create Lablet Definition", tags=["Lablet Definitions"], status_code=201)
    async def create_definition(
        self,
        request: CreateLabletDefinitionRequest,
        user: dict = Depends(require_roles("admin", "lab-author")),
    ):
        """Create a new lablet definition in PENDING_SYNC status (ADR-028).

        **RBAC Protected**: Requires 'admin' or 'lab-author' role.

        Creates a versioned template for lab instances. The form_qualified_name
        auto-derives bucket_name and lab_artifact_uri. The definition starts in
        PENDING_SYNC status — use the sync endpoint to trigger content synchronization.
        """
        # Extract created_by from user info
        created_by = user.get("sub", user.get("preferred_username", "unknown"))

        command = CreateLabletDefinitionCommand(
            name=request.name,
            version=request.version,
            form_qualified_name=request.form_qualified_name,
            created_by=created_by,
            cpu_cores=request.cpu_cores,
            memory_gb=request.memory_gb,
            storage_gb=request.storage_gb,
            nested_virt=request.nested_virt,
            license_affinity=request.license_affinity,
            node_count=request.node_count,
            port_definitions=request.port_definitions,
            user_session_package_name=request.user_session_package_name,
            grading_ruleset_package_name=request.grading_ruleset_package_name,
            user_session_type=request.user_session_type,
            user_session_default_region=request.user_session_default_region,
            lab_artifact_uri=request.lab_artifact_uri,
            lab_yaml_hash=request.lab_yaml_hash,
            lab_yaml_cached=request.lab_yaml_cached,
            grading_rules_uri=request.grading_rules_uri,
            max_duration_minutes=request.max_duration_minutes,
            warm_pool_depth=request.warm_pool_depth,
            owner_notification=request.owner_notification,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @post("/{definition_id}/sync", summary="Trigger Content Sync", tags=["Lablet Definitions"], status_code=202)
    async def sync_definition(
        self,
        definition_id: str,
        user: dict = Depends(require_roles("admin", "lab-author")),
    ):
        """Trigger content synchronization for a lablet definition (AD-CS-001).

        **RBAC Protected**: Requires 'admin' or 'lab-author' role.

        Sets sync_status to 'sync_requested' and emits a domain event that
        triggers the etcd projector. The lablet-controller's ContentSyncService
        watches for this key and executes the sync pipeline asynchronously.

        Returns 202 Accepted — sync happens asynchronously.
        """
        synced_by = user.get("sub", user.get("preferred_username", "unknown"))

        command = SyncLabletDefinitionCommand(
            id=definition_id,
            synced_by=synced_by,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @put("/{definition_id}", summary="Update Lablet Definition", tags=["Lablet Definitions"])
    async def update_definition(
        self,
        definition_id: str,
        request: UpdateLabletDefinitionRequest,
        user: dict = Depends(require_roles("admin", "lab-author")),
    ):
        """Update mutable fields of a lablet definition.

        **RBAC Protected**: Requires 'admin' or 'lab-author' role.

        Only the fields provided in the request body will be updated.
        Name and version are immutable and cannot be changed through this endpoint.
        """
        updated_by = user.get("sub", user.get("preferred_username", "unknown"))

        command = UpdateLabletDefinitionCommand(
            definition_id=definition_id,
            updated_by=updated_by,
            form_qualified_name=request.form_qualified_name,
            lab_artifact_uri=request.lab_artifact_uri,
            lab_yaml_hash=request.lab_yaml_hash,
            cpu_cores=request.cpu_cores,
            memory_gb=request.memory_gb,
            storage_gb=request.storage_gb,
            nested_virt=request.nested_virt,
            license_affinity=request.license_affinity,
            node_count=request.node_count,
            user_session_package_name=request.user_session_package_name,
            grading_ruleset_package_name=request.grading_ruleset_package_name,
            user_session_type=request.user_session_type,
            user_session_default_region=request.user_session_default_region,
            max_duration_minutes=request.max_duration_minutes,
            warm_pool_depth=request.warm_pool_depth,
            grading_rules_uri=request.grading_rules_uri,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @get(
        "/{definition_id}/resource-observations",
        summary="Get Aggregated Resource Observations",
        tags=["Lablet Definitions"],
    )
    async def get_resource_observations(
        self,
        definition_id: str,
        limit: int = 20,
        user: dict = Depends(get_current_user),
    ):
        """Get aggregated resource observations for a definition (ADR-030).

        Returns max/avg/latest observed resources across all sessions
        that have completed resource observation for this definition.
        Enables admin to review actual runtime consumption before
        updating definition resource_requirements.

        Parameters:
        - **definition_id**: Definition UUID
        - **limit**: Max sessions to include in aggregation (default 20)

        Returns:
            Aggregated observation data with per-session summaries.
        """
        query = GetDefinitionResourceObservationsQuery(
            definition_id=definition_id,
            limit=limit,
        )
        result = await self.mediator.execute_async(query)
        return self.process(result)
