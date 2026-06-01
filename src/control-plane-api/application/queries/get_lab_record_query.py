"""Query for fetching a single LabRecord by ID with full details.

Phase 8 (P8-16): Returns comprehensive LabRecord data including
topology summary, revision count, run count, binding status, and
pending action information.

Phase 7F: Refactored to use LabletSession.lab_record_id (direct 1:1 FK)
instead of the deprecated LabletLabBinding entity (ADR-020 §2).
"""

import logging
from dataclasses import dataclass
from typing import Any

from application.queries.query_handler_base import QueryHandlerBase
from domain.entities.lab_record import LabRecord
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def _get_related_session_id(lab: LabRecord) -> str | None:
    """Resolve the best-known LabletSession reference for a LabRecord."""

    if lab.state.active_lablet_session_id:
        return lab.state.active_lablet_session_id

    for run in reversed(lab.run_history_vo):
        if run.lablet_session_id:
            return run.lablet_session_id

    return None


@dataclass
class GetLabRecordQuery(Query[OperationResult[dict[str, Any]]]):
    """Query to retrieve a single LabRecord by its aggregate ID.

    Attributes:
        lab_record_id: The LabRecord aggregate ID (not the CML lab_id).
    """

    lab_record_id: str


class GetLabRecordQueryHandler(QueryHandlerBase, QueryHandler[GetLabRecordQuery, OperationResult[dict[str, Any]]]):
    """Handler for GetLabRecordQuery.

    Returns a comprehensive detail view of a single LabRecord.
    """

    def __init__(
        self,
        lab_record_repository: LabRecordRepository,
        lablet_session_repository: LabletSessionRepository,
        cml_worker_repository: CMLWorkerRepository,
    ):
        super().__init__()
        self._lab_repository = lab_record_repository
        self._session_repository = lablet_session_repository
        self._worker_repository = cml_worker_repository

    @tracer.start_as_current_span("get_lab_record_query_handler")
    async def handle_async(self, request: GetLabRecordQuery) -> OperationResult[dict[str, Any]]:
        """Handle the get lab record query."""
        span = trace.get_current_span()
        span.set_attribute("lab_record.id", request.lab_record_id)

        try:
            lab = await self._lab_repository.get_by_id_async(request.lab_record_id)
            if not lab:
                return self.not_found(LabRecord, request.lab_record_id)

            # Get active binding (1:1 via LabletSession.lab_record_id)
            session = await self._session_repository.get_by_lab_record_async(request.lab_record_id)

            # Fallback to the LabRecord's own history so completed sessions
            # remain visible as the related lablet/session.
            if session is None:
                related_session_id = _get_related_session_id(lab)
                if related_session_id:
                    session = await self._session_repository.get_by_id_async(related_session_id)
            s = lab.state
            active_bindings = []
            if session:
                active_bindings.append(
                    {
                        "binding_id": session.id(),
                        "lablet_session_id": session.id(),
                        "role": "primary",
                    }
                )
            # Resolve worker name for display
            worker_name = None
            if s.worker_id:
                worker = await self._worker_repository.get_by_id_async(s.worker_id)
                if worker and worker.state.name:
                    worker_name = worker.state.name

            result: dict[str, Any] = {
                # Identity
                "id": lab.id(),
                "lab_id": s.lab_id,
                "worker_id": s.worker_id,
                "worker_name": worker_name,
                "worker_ip": s.worker_ip,
                # Status
                "status": s.status.value,
                "state": s.state,
                "is_terminal": lab.is_terminal,
                "is_running": lab.is_running,
                "is_reusable": lab.is_reusable,
                # Metadata
                "title": s.title,
                "description": s.description,
                "notes": s.notes,
                "owner_username": s.owner_username,
                "owner_fullname": s.owner_fullname,
                "node_count": s.node_count,
                "link_count": s.link_count,
                "groups": s.groups,
                # Provenance
                "source": s.source,
                "based_on_definition_id": s.based_on_definition_id,
                # Versioning
                "revision": s.revision,
                "revision_count": len(s.revision_history),
                # Run history
                "run_count": len(s.run_history_v2),
                # Bindings
                "active_binding_count": len(active_bindings),
                "active_bindings": active_bindings,
                # Runtime binding
                "runtime_binding": s.runtime_binding,
                # Port allocation (ADR-032)
                "allocated_ports": s.allocated_ports,
                # Topology summary
                "has_topology": s.topology_spec is not None,
                "topology_spec": s.topology_spec,
                "external_interfaces": s.external_interfaces,
                # Pending action (ADR-017)
                "pending_action": s.pending_action,
                "pending_action_at": (s.pending_action_at.isoformat() if s.pending_action_at else None),
                "pending_action_error": s.pending_action_error,
                # Error tracking
                "last_error": s.last_error,
                "last_error_at": (s.last_error_at.isoformat() if s.last_error_at else None),
                "previous_status_before_error": s.previous_status_before_error,
                # Timestamps
                "created": (s.cml_created_at.isoformat() if s.cml_created_at else None),
                "modified": (s.modified_at.isoformat() if s.modified_at else None),
                "first_seen": (s.first_seen_at.isoformat() if s.first_seen_at else None),
                "last_synced": (s.last_synced_at.isoformat() if s.last_synced_at else None),
            }

            span.set_status(Status(StatusCode.OK))
            return self.ok(result)

        except Exception as e:
            error = f"Error fetching lab record {request.lab_record_id}: {e}"
            log.exception(error)
            span.set_status(Status(StatusCode.ERROR, error))
            span.record_exception(e)
            return self.internal_server_error(str(e))
