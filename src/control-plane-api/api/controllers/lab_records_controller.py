"""Lab Records BFF Controller — Phase 8 (P8-23).

Full CQRS controller for LabRecord lifecycle management.
Replaces the legacy LabsController with flat /api/lab-records/* paths.

Architecture ref: §8.1 (BFF endpoints).

Endpoints:
    GET  /                    — List lab records with filters
    GET  /{lab_record_id}     — Get single lab record detail
    GET  /{lab_record_id}/topology  — Get topology spec
    GET  /{lab_record_id}/revisions — Get revision history
    GET  /{lab_record_id}/runs      — Get run history
    GET  /{lab_record_id}/bindings  — Get lablet bindings
    POST /{lab_record_id}/start     — Queue lab start (ADR-017)
    POST /{lab_record_id}/stop      — Queue lab stop
    POST /{lab_record_id}/wipe      — Queue lab wipe
    POST /{lab_record_id}/delete    — Queue lab delete
    POST /{lab_record_id}/clone     — Clone lab
    POST /{lab_record_id}/export    — Export/download lab YAML
    POST /{lab_record_id}/archive   — Archive lab
    POST /{lab_record_id}/bind      — Bind lab to lablet
    POST /{lab_record_id}/unbind    — Unbind lab from lablet
    POST /import                    — Import lab from YAML
"""

import logging
from typing import Annotated, Any

from api.dependencies import get_current_user
from application.commands.lab import (
    ArchiveLabRecordCommand,
    BindLabToLabletCommand,
    CloneLabRecordCommand,
    DeleteLabRecordCommand,
    DownloadLabCommand,
    ImportLabCommand,
    StartLabRecordCommand,
    StopLabRecordCommand,
    UnbindLabFromLabletCommand,
    WipeLabRecordCommand,
)
from application.queries import (
    GetLabRecordBindingsQuery,
    GetLabRecordQuery,
    GetLabRecordRevisionsQuery,
    GetLabRecordRunsQuery,
    GetLabRecordsQuery,
    GetLabRecordTopologyQuery,
)
from classy_fastapi.decorators import get, post
from classy_fastapi.routable import Routable
from fastapi import Depends, File, HTTPException, Path, Query, UploadFile
from fastapi.responses import PlainTextResponse
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping.mapper import Mapper
from neuroglia.mediation.mediator import Mediator
from neuroglia.mvc.controller_base import ControllerBase, generate_unique_id_function
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ==============================================================================
# Path Annotations
# ==============================================================================

lab_record_id_annotation = Annotated[
    str,
    Path(description="The LabRecord aggregate ID"),
]


# ==============================================================================
# Request Models
# ==============================================================================


class BindLabRequest(BaseModel):
    """Request to bind a lab to a lablet session."""

    lablet_session_id: str = Field(..., description="LabletSession aggregate ID to bind to")
    role: str = Field(default="primary", description="Binding role: primary, secondary, or auxiliary")
    metadata: dict | None = Field(default=None, description="Optional binding metadata (e.g., port mappings)")


class UnbindLabRequest(BaseModel):
    """Request to unbind a lab from a lablet session."""

    lablet_session_id: str = Field(..., description="LabletSession aggregate ID to unbind from")
    reason: str | None = Field(default=None, description="Reason for unbinding (e.g., timeslot_end, user_request)")


class CloneLabRequest(BaseModel):
    """Request to clone a lab record."""

    title: str | None = Field(default=None, description="Title for the cloned lab (None = 'Copy of <original>')")


# ==============================================================================
# Controller
# ==============================================================================


class LabRecordsController(ControllerBase):
    """BFF controller for LabRecord lifecycle management.

    Phase 8 (P8-23): Full CQRS surface for LabRecords with 16 endpoints.
    Replaces the legacy LabsController.
    """

    def __init__(self, service_provider: ServiceProviderBase, mapper: Mapper, mediator: Mediator):
        """Initialize the LabRecords controller."""
        # Store DI services first
        self.service_provider = service_provider
        self.mapper = mapper
        self.mediator = mediator
        self.name = "LabRecords"

        # Initialize base Controller (incl. JsonSerializer)
        ControllerBase.__init__(self, service_provider, mapper, mediator)

        # Call Routable.__init__ directly with custom kebab-case prefix
        Routable.__init__(
            self,
            prefix="/lab-records",
            tags=["Lab Records"],
            generate_unique_id_function=generate_unique_id_function,
        )

    # ==========================================================================
    # Read Operations (Queries)
    # ==========================================================================

    @get(
        "/",
        response_model=Any,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def list_lab_records(
        self,
        worker_id: str | None = Query(default=None, description="Filter by worker ID"),
        status: str | None = Query(default=None, description="Filter by LabRecordStatus (e.g., booted, stopped, defined)"),
        owner: str | None = Query(default=None, description="Filter by owner username"),
        bound: bool | None = Query(default=None, description="Filter by bound state (true=has active binding)"),
        include_terminal: bool = Query(default=False, description="Include terminal/orphaned-state labs (deleted, archived, orphaned)"),
        token: str = Depends(get_current_user),
    ) -> Any:
        """List lab records with optional filters.

        Returns a summary list of LabRecords, optionally filtered by worker,
        status, owner, and binding state.

        (**Requires valid token.**)
        """
        logger.info(
            "Listing lab records (worker_id=%s, status=%s, owner=%s, bound=%s)",
            worker_id,
            status,
            owner,
            bound,
        )
        query = GetLabRecordsQuery(
            worker_id=worker_id,
            status=status,
            owner=owner,
            bound=bound,
            include_terminal=include_terminal,
        )
        return self.process(await self.mediator.execute_async(query))

    @get(
        "/{lab_record_id}",
        response_model=Any,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def get_lab_record(
        self,
        lab_record_id: lab_record_id_annotation,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Get a single lab record with full details.

        Returns comprehensive LabRecord data including topology summary,
        revision count, run count, binding status, and pending action info.

        (**Requires valid token.**)
        """
        logger.info("Getting lab record %s", lab_record_id)
        query = GetLabRecordQuery(lab_record_id=lab_record_id)
        return self.process(await self.mediator.execute_async(query))

    @get(
        "/{lab_record_id}/topology",
        response_model=Any,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def get_lab_record_topology(
        self,
        lab_record_id: lab_record_id_annotation,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Get the current topology specification for a lab record.

        Returns topology spec with node/link counts, checksum, and
        external interfaces.

        (**Requires valid token.**)
        """
        logger.info("Getting topology for lab record %s", lab_record_id)
        query = GetLabRecordTopologyQuery(lab_record_id=lab_record_id)
        return self.process(await self.mediator.execute_async(query))

    @get(
        "/{lab_record_id}/revisions",
        response_model=Any,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def get_lab_record_revisions(
        self,
        lab_record_id: lab_record_id_annotation,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Get the revision history for a lab record.

        Returns ordered list of LabRevision entries documenting topology
        changes over time with checksums and change summaries.

        (**Requires valid token.**)
        """
        logger.info("Getting revisions for lab record %s", lab_record_id)
        query = GetLabRecordRevisionsQuery(lab_record_id=lab_record_id)
        return self.process(await self.mediator.execute_async(query))

    @get(
        "/{lab_record_id}/runs",
        response_model=Any,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def get_lab_record_runs(
        self,
        lab_record_id: lab_record_id_annotation,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Get the run history for a lab record.

        Returns ordered list of LabRunRecord entries documenting execution
        cycles with timing and outcome data (most recent first).

        (**Requires valid token.**)
        """
        logger.info("Getting runs for lab record %s", lab_record_id)
        query = GetLabRecordRunsQuery(lab_record_id=lab_record_id)
        return self.process(await self.mediator.execute_async(query))

    @get(
        "/{lab_record_id}/bindings",
        response_model=Any,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def get_lab_record_bindings(
        self,
        lab_record_id: lab_record_id_annotation,
        include_released: bool = Query(default=False, description="Include released bindings"),
        token: str = Depends(get_current_user),
    ) -> Any:
        """Get the lablet bindings for a lab record.

        Returns active (and optionally released) LabletLabBinding entries
        showing which LabletSessions are using this lab.

        (**Requires valid token.**)
        """
        logger.info("Getting bindings for lab record %s", lab_record_id)
        query = GetLabRecordBindingsQuery(
            lab_record_id=lab_record_id,
            include_released=include_released,
        )
        return self.process(await self.mediator.execute_async(query))

    # ==========================================================================
    # Write Operations (Commands)
    # ==========================================================================

    @post(
        "/{lab_record_id}/start",
        response_model=Any,
        status_code=202,
        responses=ControllerBase.error_responses,
    )
    async def start_lab_record(
        self,
        lab_record_id: lab_record_id_annotation,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Start a lab (boot all nodes).

        ADR-017: Sets pending_action=start for reconciliation.
        The actual CML API call is performed by lablet-controller.
        Returns 202 Accepted immediately.

        (**Requires valid token.**)
        """
        logger.info("Starting lab record %s", lab_record_id)
        command = StartLabRecordCommand(
            lab_record_id=lab_record_id,
            started_by="user",
        )
        return self.process(await self.mediator.execute_async(command))

    @post(
        "/{lab_record_id}/stop",
        response_model=Any,
        status_code=202,
        responses=ControllerBase.error_responses,
    )
    async def stop_lab_record(
        self,
        lab_record_id: lab_record_id_annotation,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Stop a lab (stop all nodes).

        ADR-017: Sets pending_action=stop for reconciliation.
        Returns 202 Accepted immediately.

        (**Requires valid token.**)
        """
        logger.info("Stopping lab record %s", lab_record_id)
        command = StopLabRecordCommand(
            lab_record_id=lab_record_id,
            stop_reason="user_request",
        )
        return self.process(await self.mediator.execute_async(command))

    @post(
        "/{lab_record_id}/wipe",
        response_model=Any,
        status_code=202,
        responses=ControllerBase.error_responses,
    )
    async def wipe_lab_record(
        self,
        lab_record_id: lab_record_id_annotation,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Wipe a lab (factory reset all nodes).

        ADR-017: Sets pending_action=wipe for reconciliation.
        Returns 202 Accepted immediately.

        (**Requires valid token.**)
        """
        logger.info("Wiping lab record %s", lab_record_id)
        command = WipeLabRecordCommand(
            lab_record_id=lab_record_id,
        )
        return self.process(await self.mediator.execute_async(command))

    @post(
        "/{lab_record_id}/delete",
        response_model=Any,
        status_code=202,
        responses=ControllerBase.error_responses,
    )
    async def delete_lab_record(
        self,
        lab_record_id: lab_record_id_annotation,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Delete a lab from the worker.

        ADR-017: Sets pending_action=delete for reconciliation.
        Returns 202 Accepted immediately. The lab will be permanently
        deleted from the CML runtime by lablet-controller.

        (**Requires valid token.**)
        """
        logger.info("Deleting lab record %s", lab_record_id)
        command = DeleteLabRecordCommand(
            lab_record_id=lab_record_id,
            deleted_by="user",
        )
        return self.process(await self.mediator.execute_async(command))

    @post(
        "/{lab_record_id}/clone",
        response_model=Any,
        status_code=202,
        responses=ControllerBase.error_responses,
    )
    async def clone_lab_record(
        self,
        lab_record_id: lab_record_id_annotation,
        request: CloneLabRequest | None = None,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Clone a lab record.

        Creates a copy of the lab on the same or different worker.
        Uses the current topology YAML for import.

        (**Requires valid token.**)
        """
        clone_title = request.title if request else None
        logger.info("Cloning lab record %s", lab_record_id)
        command = CloneLabRecordCommand(
            source_lab_record_id=lab_record_id,
            title=clone_title,
            cloned_by="user",
        )
        return self.process(await self.mediator.execute_async(command))

    @post(
        "/{lab_record_id}/export",
        response_class=PlainTextResponse,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def export_lab_record(
        self,
        lab_record_id: lab_record_id_annotation,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Export/download lab topology as YAML.

        Returns the lab topology in YAML format suitable for import/backup.
        Requires the lab's worker_id and CML lab_id (resolved from LabRecord).

        (**Requires valid token.**)
        """
        logger.info("Exporting lab record %s", lab_record_id)

        # First resolve the LabRecord to get worker_id and lab_id
        query = GetLabRecordQuery(lab_record_id=lab_record_id)
        lab_result = await self.mediator.execute_async(query)

        if not lab_result.is_success:
            return self.process(lab_result)

        lab_data = lab_result.data
        command = DownloadLabCommand(
            worker_id=lab_data["worker_id"],
            lab_id=lab_data["lab_id"],
        )
        result = await self.mediator.execute_async(command)

        if not result.is_success:
            return self.process(result)

        return PlainTextResponse(content=result.data, media_type="text/yaml")

    @post(
        "/{lab_record_id}/archive",
        response_model=Any,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def archive_lab_record(
        self,
        lab_record_id: lab_record_id_annotation,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Archive a lab record.

        Exports the lab topology and marks the LabRecord as ARCHIVED.
        Archived labs are retained for audit but considered terminal.

        (**Requires valid token.**)
        """
        logger.info("Archiving lab record %s", lab_record_id)
        command = ArchiveLabRecordCommand(
            lab_record_id=lab_record_id,
            archived_by="user",
        )
        return self.process(await self.mediator.execute_async(command))

    @post(
        "/{lab_record_id}/bind",
        response_model=Any,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def bind_lab_to_lablet(
        self,
        lab_record_id: lab_record_id_annotation,
        request: BindLabRequest,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Bind a lab to a lablet session.

        Creates a LabletLabBinding entity linking this lab to the specified
        lablet session with the given role (primary, secondary, auxiliary).

        (**Requires valid token.**)
        """
        logger.info(
            "Binding lab %s to lablet session %s (role=%s)",
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
        return self.process(await self.mediator.execute_async(command))

    @post(
        "/{lab_record_id}/unbind",
        response_model=Any,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def unbind_lab_from_lablet(
        self,
        lab_record_id: lab_record_id_annotation,
        request: UnbindLabRequest,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Unbind a lab from a lablet session.

        Releases the active LabletLabBinding between this lab and the
        specified lablet session.

        (**Requires valid token.**)
        """
        logger.info(
            "Unbinding lab %s from lablet session %s",
            lab_record_id,
            request.lablet_session_id,
        )
        command = UnbindLabFromLabletCommand(
            lab_record_id=lab_record_id,
            lablet_session_id=request.lablet_session_id,
            reason=request.reason,
        )
        return self.process(await self.mediator.execute_async(command))

    @post(
        "/import",
        response_model=Any,
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def import_lab(
        self,
        worker_id: str = Query(..., description="Worker ID to import the lab to"),
        file: UploadFile = File(..., description="Lab YAML file to import"),
        token: str = Depends(get_current_user),
    ) -> Any:
        """Import a lab topology from uploaded YAML file.

        Uploads a CML2 YAML topology file and creates a new lab on the
        specified worker. The lab title will be taken from the YAML file.

        (**Requires valid token.**)
        """
        logger.info("Importing lab to worker %s from file %s", worker_id, file.filename)

        try:
            yaml_content = await file.read()
            yaml_str = yaml_content.decode("utf-8")
        except Exception as e:
            logger.error("Failed to read uploaded file: %s", e)
            raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")

        command = ImportLabCommand(worker_id=worker_id, yaml_content=yaml_str)
        return self.process(await self.mediator.execute_async(command))
