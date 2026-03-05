"""Update Instantiation Progress command.

Phase 1 (Instantiation Pipeline): Records per-step progress updates
from the lablet-controller reconciler. The CPA is the source of truth
for pipeline state — the controller sends step-level deltas, and this
handler applies them to the full InstantiationProgress on the session.

ADR-031: Checkpoint-based instantiation pipeline.
Per ADR-001: All state mutations go through Control Plane API.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.lablet_session import LabletSession
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from domain.value_objects.instantiation_progress import InstantiationProgress
from domain.value_objects.port_template import PortTemplate
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

log = logging.getLogger(__name__)

VALID_STEP_STATUSES = ("pending", "completed", "failed", "skipped")


@dataclass
class UpdateInstantiationProgressCommand(Command[OperationResult[dict[str, Any]]]):
    """Update a single pipeline step on a LabletSession's instantiation progress.

    The command handler loads the full InstantiationProgress from the
    session, applies the step delta, and persists the merged result.

    Attributes:
        session_id: The LabletSession ID.
        step_name: Pipeline step name (e.g., "ports_alloc", "lab_resolve").
        step_status: Step outcome — "completed", "failed", or "skipped".
        result_data: Optional result payload for completed steps.
        error: Optional error message for failed steps.
    """

    session_id: str
    step_name: str
    step_status: str
    result_data: dict[str, Any] | None = field(default=None)
    error: str | None = field(default=None)


class UpdateInstantiationProgressCommandHandler(
    CommandHandlerBase,
    CommandHandler[UpdateInstantiationProgressCommand, OperationResult[dict[str, Any]]],
):
    """Handle instantiation progress updates.

    Workflow:
    1. Load LabletSession
    2. Load or initialize InstantiationProgress
    3. Apply step-level delta (complete/fail/skip)
    4. Persist updated progress on session aggregate
    """

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        lablet_session_repository: LabletSessionRepository,
        lablet_definition_repository: LabletDefinitionRepository,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._session_repo = lablet_session_repository
        self._definition_repo = lablet_definition_repository

    async def handle_async(self, request: UpdateInstantiationProgressCommand) -> OperationResult[dict[str, Any]]:
        """Handle instantiation progress update."""
        log.info(
            "Updating progress for session %s — step=%s status=%s",
            request.session_id,
            request.step_name,
            request.step_status,
        )

        # Validate step_status
        if request.step_status not in VALID_STEP_STATUSES:
            return self.bad_request(f"Invalid step_status '{request.step_status}'. Must be one of {VALID_STEP_STATUSES}")

        # 1. Load session
        session = await self._session_repo.get_by_id_async(request.session_id)
        if not session:
            return self.not_found(LabletSession, request.session_id)

        # 2. Load or initialize InstantiationProgress
        raw_progress = session.state.instantiation_progress
        if raw_progress:
            progress = InstantiationProgress.from_dict(raw_progress)
        else:
            progress = await self._build_default_progress(session)

        # 3. Validate step exists in the pipeline
        step = progress.get_step(request.step_name)
        if not step:
            return self.bad_request(f"Unknown pipeline step: '{request.step_name}'")

        # 4. Apply step-level delta
        if request.step_status == "pending":
            # No-op: step stays in pending state. Used by lablet-controller
            # to bootstrap the pipeline (ensure progress is initialized and
            # persisted on the session without mutating any step status).
            progress.mark_in_progress(request.step_name)
        elif request.step_status == "completed":
            progress.complete_step(request.step_name, request.result_data)
        elif request.step_status == "failed":
            progress.fail_step(request.step_name, request.error or "Unknown error")
        elif request.step_status == "skipped":
            progress.skip_step(request.step_name, request.error)

        # 5. Persist via domain event
        session.update_instantiation_progress(
            step_name=request.step_name,
            step_status=request.step_status,
            progress_data=progress.to_dict(),
        )
        await self._session_repo.update_async(session)

        log.info(
            "Progress updated for session %s — step=%s → %s (pipeline_complete=%s)",
            request.session_id,
            request.step_name,
            request.step_status,
            progress.is_complete,
        )

        return self.ok(
            {
                "session_id": request.session_id,
                "step_name": request.step_name,
                "step_status": request.step_status,
                "pipeline_complete": progress.is_complete,
            }
        )

    async def _build_default_progress(self, session: LabletSession) -> InstantiationProgress:
        """Build a default InstantiationProgress from the session's definition.

        Determines capability flags (port_template, content_sync, LDS) from
        the associated LabletDefinition to pre-skip irrelevant steps.

        Args:
            session: The LabletSession aggregate.

        Returns:
            A new InstantiationProgress with steps pre-skipped as appropriate.
        """
        has_port_template = False
        has_content_sync = False
        has_lds = False

        definition_id = session.state.definition_id
        if definition_id:
            definition = await self._definition_repo.get_by_id_async(definition_id)
            if definition:
                # Port template — may be stored as dict (MongoDB) or PortTemplate (event replay)
                raw_template = definition.state.port_template
                if isinstance(raw_template, dict):
                    has_port_template = bool(raw_template.get("ports"))
                elif isinstance(raw_template, PortTemplate):
                    has_port_template = raw_template.port_count > 0

                # Content sync — relevant if definition has sync_status set
                has_content_sync = definition.state.sync_status is not None

                # LDS — relevant if definition has a form_qualified_name
                has_lds = bool(definition.state.form_qualified_name)

        log.debug(
            "Building default progress for session %s (port_template=%s, content_sync=%s, lds=%s)",
            session.id(),
            has_port_template,
            has_content_sync,
            has_lds,
        )

        return InstantiationProgress.build_default(
            has_port_template=has_port_template,
            has_content_sync=has_content_sync,
            has_lds=has_lds,
        )
