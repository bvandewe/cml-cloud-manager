"""Bind Lab to Session command.

Phase 1 (Instantiation Pipeline): Binds a LabRecord to a LabletSession
during the `lab_binding` pipeline step. This command:
1. Creates a LabRunRecord on the LabRecord (runtime tracking)
2. Binds the LabRecord to the session (sets active_lablet_session_id)
3. Denormalizes LabRecord.allocated_ports onto the LabletSession

ADR-031 / ADR-032: Lab binding is a pipeline step (not part of scheduling).
Ports live on the LabRecord (topology concern) and are denormalized to the
session for downstream consumption (LDS, grading, monitoring).

Per ADR-001: All state mutations go through Control Plane API.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.lab_record import LabRecord
from domain.entities.lablet_session import LabletSession
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from domain.value_objects.lab_run_record import LabRunRecord

log = logging.getLogger(__name__)


@dataclass
class BindLabToSessionCommand(Command[OperationResult[dict[str, Any]]]):
    """Bind a LabRecord to a LabletSession and create a LabRunRecord.

    Attributes:
        session_id: The LabletSession ID to bind to.
        worker_id: The CMLWorker hosting the lab.
        lab_record_id: The LabRecord aggregate ID to bind.
    """

    session_id: str
    worker_id: str
    lab_record_id: str
    cml_lab_id: str | None = None
    cml_lab_title: str | None = None


class BindLabToSessionCommandHandler(
    CommandHandlerBase,
    CommandHandler[BindLabToSessionCommand, OperationResult[dict[str, Any]]],
):
    """Handle lab-to-session binding during the instantiation pipeline.

    Workflow:
    1. Load LabRecord — validate it exists
    2. Create LabRunRecord (runtime tracking — NO port fields)
    3. Bind LabRecord to session (sets active_lablet_session_id, active_binding_id)
    4. Load LabletSession — denormalize allocated_ports from LabRecord
    5. Persist both aggregates
    """

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        lab_record_repository: LabRecordRepository,
        lablet_session_repository: LabletSessionRepository,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._lab_record_repo = lab_record_repository
        self._session_repo = lablet_session_repository

    async def handle_async(self, request: BindLabToSessionCommand) -> OperationResult[dict[str, Any]]:
        """Handle lab-to-session binding."""
        log.info(
            "Binding lab_record %s to session %s on worker %s",
            request.lab_record_id,
            request.session_id,
            request.worker_id,
        )

        # 1. Load LabRecord
        lab_record = await self._lab_record_repo.get_by_id_async(request.lab_record_id)
        if not lab_record:
            return self.not_found(LabRecord, request.lab_record_id)

        # 2. Load LabletSession
        session = await self._session_repo.get_by_id_async(request.session_id)
        if not session:
            return self.not_found(LabletSession, request.session_id)

        # 3. Idempotency — check if already bound to this session
        if lab_record.state.active_lablet_session_id == request.session_id and session.state.lab_record_id == request.lab_record_id:
            log.info(
                "Lab record %s already bound to session %s — returning existing binding",
                request.lab_record_id,
                request.session_id,
            )
            return self.ok(
                {
                    "lab_record_id": request.lab_record_id,
                    "already_bound": True,
                    "allocated_ports": lab_record.state.allocated_ports or {},
                }
            )

        # 4. Check if LabRecord is already bound to a DIFFERENT session
        if lab_record.state.active_lablet_session_id and lab_record.state.active_lablet_session_id != request.session_id:
            return self.conflict(f"Lab record {request.lab_record_id} is already bound to session {lab_record.state.active_lablet_session_id}")

        # 5. Create LabRunRecord (runtime tracking — NO port fields per ADR-032)
        run = LabRunRecord(
            run_id=str(uuid4()),
            started_at=datetime.now(timezone.utc),
            started_by="lablet-controller",
            lablet_session_id=request.session_id,
        )
        lab_record.record_run(run)

        # 6. Bind LabRecord to session
        lab_record.bind_to_lablet(
            lablet_session_id=request.session_id,
            binding_id=run.run_id,
            binding_role="instantiation",
        )
        await self._lab_record_repo.update_async(lab_record)

        # 7. Denormalize lab binding + allocated_ports + cml_lab_id onto LabletSession
        allocated_ports = lab_record.state.allocated_ports or {}
        session.bind_lab(
            lab_record_id=lab_record.id(),
            allocated_ports=allocated_ports,
            cml_lab_id=request.cml_lab_id,
            cml_lab_title=request.cml_lab_title,
        )
        await self._session_repo.update_async(session)

        log.info(
            "Lab record %s bound to session %s (run_id=%s, ports=%s)",
            request.lab_record_id,
            request.session_id,
            run.run_id,
            allocated_ports,
        )

        return self.ok(
            {
                "lab_record_id": lab_record.id(),
                "run_id": run.run_id,
                "allocated_ports": allocated_ports,
            }
        )
