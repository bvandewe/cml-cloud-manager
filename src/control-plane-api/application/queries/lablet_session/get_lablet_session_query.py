"""Get LabletSession query with handler.

Phase 7D: Replaces get_lablet_instance_query.py.
Supports lookup by ID or reservation_id.
"""

import logging
from dataclasses import dataclass

from application.dtos.lablet_session_dto import LabletSessionDto, map_lablet_session_to_dto
from domain.entities.lablet_session import LabletSession
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

logger = logging.getLogger(__name__)


@dataclass
class GetLabletSessionQuery(Query[OperationResult[LabletSessionDto]]):
    """Query to retrieve a single LabletSession by ID or reservation_id."""

    id: str | None = None
    reservation_id: str | None = None


class GetLabletSessionQueryHandler(QueryHandler[GetLabletSessionQuery, OperationResult[LabletSessionDto]]):
    """Handle LabletSession retrieval with cross-aggregate enrichment."""

    def __init__(
        self,
        lablet_session_repository: LabletSessionRepository,
        lablet_definition_repository: LabletDefinitionRepository,
        cml_worker_repository: CMLWorkerRepository,
        lab_record_repository: LabRecordRepository,
    ):
        super().__init__()
        self._repository = lablet_session_repository
        self._definition_repository = lablet_definition_repository
        self._worker_repository = cml_worker_repository
        self._lab_record_repository = lab_record_repository

    async def handle_async(self, request: GetLabletSessionQuery) -> OperationResult[LabletSessionDto]:
        if not request.id and not request.reservation_id:
            return self.bad_request("Must provide either 'id' or 'reservation_id'")

        try:
            session = None
            if request.id:
                session = await self._repository.get_by_id_async(request.id)
                if not session:
                    return self.not_found(LabletSession, request.id)
            else:
                session = await self._repository.get_by_reservation_id_async(request.reservation_id)
                if not session:
                    return self.not_found(LabletSession, request.reservation_id, "reservation_id")

            # Cross-aggregate enrichment — graceful None if FK aggregate is missing
            definition_enrichment = None
            if session.state.definition_id:
                try:
                    defn = await self._definition_repository.get_by_id_async(session.state.definition_id)
                    if defn:
                        definition_enrichment = {
                            "form_qualified_name": defn.state.form_qualified_name,
                            "node_count": defn.state.node_count,
                            "resource_requirements": defn.state.resource_requirements.to_dict() if defn.state.resource_requirements else None,
                            "port_template": defn.state.port_template.to_dict() if defn.state.port_template else None,
                            "upstream_sync_status": defn.state.upstream_sync_status,
                            "upstream_version": defn.state.upstream_version,
                            "content_package_hash": defn.state.content_package_hash,
                        }
                except Exception:
                    logger.warning("Failed to fetch LabletDefinition %s for enrichment", session.state.definition_id)

            worker_enrichment = None
            if session.state.worker_id:
                try:
                    worker = await self._worker_repository.get_by_id_async(session.state.worker_id)
                    if worker:
                        worker_enrichment = {
                            "name": worker.state.name,
                            "aws_region": worker.state.aws_region,
                        }
                except Exception:
                    logger.warning("Failed to fetch CMLWorker %s for enrichment", session.state.worker_id)

            lab_record_enrichment = None
            if session.state.lab_record_id:
                try:
                    lab_record = await self._lab_record_repository.get_by_id_async(session.state.lab_record_id)
                    if lab_record:
                        lab_record_enrichment = {
                            "status": lab_record.state.status.value if lab_record.state.status else None,
                            "node_count": lab_record.state.node_count,
                            "link_count": lab_record.state.link_count,
                        }
                except Exception:
                    logger.warning("Failed to fetch LabRecord %s for enrichment", session.state.lab_record_id)

            dto = map_lablet_session_to_dto(
                session,
                definition_enrichment=definition_enrichment,
                worker_enrichment=worker_enrichment,
                lab_record_enrichment=lab_record_enrichment,
            )
            logger.info("Retrieved LabletSession: %s (status=%s)", session.id(), session.state.status.value)
            return self.ok(dto)

        except Exception as e:
            logger.error("Error retrieving LabletSession: %s", e, exc_info=True)
            return self.internal_server_error(str(e))
