"""Query for fetching a LabRecord's current topology specification.

Phase 8 (P8-17): Returns the LabTopologySpec value object contents
including node/link counts, checksum, and external interfaces.
"""

import logging
from dataclasses import dataclass
from typing import Any

from domain.entities.lab_record import LabRecord
from domain.repositories.lab_record_repository import LabRecordRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class GetLabRecordTopologyQuery(Query[OperationResult[dict[str, Any]]]):
    """Query to retrieve the current topology of a LabRecord.

    Attributes:
        lab_record_id: The LabRecord aggregate ID.
    """

    lab_record_id: str


class GetLabRecordTopologyQueryHandler(
    QueryHandler[GetLabRecordTopologyQuery, OperationResult[dict[str, Any]]],
):
    """Handler for GetLabRecordTopologyQuery.

    Returns the current topology specification including checksum,
    node/link counts, and external interfaces.
    """

    def __init__(self, lab_record_repository: LabRecordRepository):
        super().__init__()
        self._lab_repository = lab_record_repository

    @tracer.start_as_current_span("get_lab_record_topology_query_handler")
    async def handle_async(self, request: GetLabRecordTopologyQuery) -> OperationResult[dict[str, Any]]:
        """Handle the get lab record topology query."""
        span = trace.get_current_span()
        span.set_attribute("lab_record.id", request.lab_record_id)

        try:
            lab = await self._lab_repository.get_by_id_async(request.lab_record_id)
            if not lab:
                return self.not_found(LabRecord, request.lab_record_id)

            topology_spec = lab.state.topology_spec
            if topology_spec is None:
                return self.ok(
                    {
                        "lab_record_id": lab.id(),
                        "lab_id": lab.state.lab_id,
                        "has_topology": False,
                        "topology": None,
                        "nodes": [],
                        "links": [],
                        "external_interfaces": [],
                        "node_count": lab.state.node_count,
                        "link_count": lab.state.link_count,
                    }
                )

            # Extract nodes and links from topology_spec dict for direct access
            nodes = topology_spec.get("nodes", []) if isinstance(topology_spec, dict) else []
            links = topology_spec.get("links", []) if isinstance(topology_spec, dict) else []

            result: dict[str, Any] = {
                "lab_record_id": lab.id(),
                "lab_id": lab.state.lab_id,
                "has_topology": True,
                "topology": topology_spec,
                "nodes": nodes,
                "links": links,
                "external_interfaces": lab.state.external_interfaces,
                "node_count": lab.state.node_count,
                "link_count": lab.state.link_count,
                "revision": lab.state.revision,
            }

            span.set_status(Status(StatusCode.OK))
            return self.ok(result)

        except Exception as e:
            error = f"Error fetching topology for lab record {request.lab_record_id}: {e}"
            log.exception(error)
            span.set_status(Status(StatusCode.ERROR, error))
            span.record_exception(e)
            return self.internal_server_error(str(e))
