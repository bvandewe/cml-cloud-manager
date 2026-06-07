"""Content Controller — PodDefinition content sync and retrieval.

Endpoints:
- POST /api/v1/content/sync — Trigger content sync from BlobStorage
- GET /api/v1/content/{definition_id} — Get synced content status
"""

import logging
from typing import Any

from application.commands.sync_content_command import SyncContentCommand
from classy_fastapi.decorators import get, post
from classy_fastapi.routable import Routable
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator
from neuroglia.mvc import ControllerBase
from neuroglia.mvc.controller_base import generate_unique_id_function
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SyncContentRequest(BaseModel):
    """Request model for content synchronization."""

    definition_id: str = Field(default="", description="PodDefinition ID (optional for new)")
    name: str = Field(default="", description="Content package name (required if creating new)")
    version: str = Field(default="v1", description="Content version")
    source_uri: str = Field(..., min_length=1, description="BlobStorage URI for content package")
    force: bool = Field(default=False, description="Force re-sync even if already READY")


class ContentController(ControllerBase):
    """Controller for PodDefinition content synchronization.

    Routes mounted at /v1/content under the API sub-app (/api/v1/content/*).
    Manages content sync from BlobStorage (S3) to local storage.
    """

    def __init__(self, service_provider: ServiceProviderBase, mapper: Mapper, mediator: Mediator):
        self.service_provider = service_provider
        self.mapper = mapper
        self.mediator = mediator
        self.name = "Content"

        # Initialize ControllerBase (sets up json_serializer)
        ControllerBase.__init__(self, service_provider, mapper, mediator)

        # Override prefix with versioned path
        Routable.__init__(
            self,
            prefix="/v1/content",
            tags=["Content"],
            generate_unique_id_function=generate_unique_id_function,
        )

    @post("/sync", summary="Sync Content", status_code=202)
    async def sync_content(self, request: SyncContentRequest) -> Any:
        """Trigger content sync from BlobStorage.

        Initiates an async download of the content package from S3.
        The PodDefinition transitions to SYNCHRONIZING status.

        Returns:
            202 Accepted with definition_id and status.
        """
        command = SyncContentCommand(
            definition_id=request.definition_id,
            name=request.name,
            version=request.version,
            source_uri=request.source_uri,
            force=request.force,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

    @get("/{definition_id}", summary="Get Content Status")
    async def get_content(self, definition_id: str) -> Any:
        """Get synced content status.

        Returns the PodDefinition status including sync progress,
        local path, and manifest metadata.
        """
        # TODO: Add GetPodDefinitionQuery when needed
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=501, content={"detail": "Not implemented — query pending"})
