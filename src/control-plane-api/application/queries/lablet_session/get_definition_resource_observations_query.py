"""Query to aggregate resource observations across sessions for a given definition.

Returns max, average, and latest observed resources — enabling admin
to make informed decisions about definition resource_requirements updates.

Self-contained query + handler (established CQRS pattern).

ADR-030: Resource & Port Observation — "Learn from Live"
"""

import logging
from dataclasses import dataclass
from typing import Any

from application.queries.query_handler_base import QueryHandlerBase
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

logger = logging.getLogger(__name__)


@dataclass
class GetDefinitionResourceObservationsQuery(Query[OperationResult[dict[str, Any]]]):
    """Query for aggregated resource observations by definition_id."""

    definition_id: str
    limit: int = 20  # Max sessions to include


class GetDefinitionResourceObservationsQueryHandler(
    QueryHandlerBase,
    QueryHandler[GetDefinitionResourceObservationsQuery, OperationResult[dict[str, Any]]],
):
    """Handle aggregation of resource observations across sessions for a definition.

    Fetches sessions with recorded observations and computes aggregate
    statistics (max, average, latest) for resource consumption metrics.
    """

    def __init__(self, lablet_session_repository: LabletSessionRepository):
        super().__init__()
        self._session_repository = lablet_session_repository

    async def handle_async(self, request: GetDefinitionResourceObservationsQuery) -> OperationResult[dict[str, Any]]:
        """Handle the aggregated observations query."""
        logger.info("Aggregating resource observations for definition %s", request.definition_id)

        try:
            # Fetch sessions with observations for this definition
            sessions = await self._session_repository.find_with_observations_async(
                definition_id=request.definition_id,
                limit=request.limit,
            )

            if not sessions:
                return self.ok(
                    {
                        "definition_id": request.definition_id,
                        "observation_count": 0,
                        "sessions": [],
                        "aggregate": None,
                    }
                )

            # Aggregate observations
            cpu_values: list[float] = []
            memory_values: list[int] = []
            storage_values: list[int] = []
            node_counts: list[int] = []
            port_drift_count = 0

            session_summaries = []
            for session in sessions:
                obs = session.state.observed_resources
                if obs:
                    cpu_values.append(obs.get("total_cpu_cores", 0))
                    memory_values.append(obs.get("total_memory_mb", 0))
                    if obs.get("total_storage_mb") is not None:
                        storage_values.append(obs["total_storage_mb"])
                    node_counts.append(obs.get("actual_node_count", 0))

                if session.state.port_drift_detected:
                    port_drift_count += 1

                session_summaries.append(
                    {
                        "session_id": session.id(),
                        "observed_at": session.state.observed_at.isoformat() if session.state.observed_at else None,
                        "total_cpu_cores": obs.get("total_cpu_cores") if obs else None,
                        "total_memory_mb": obs.get("total_memory_mb") if obs else None,
                        "actual_node_count": obs.get("actual_node_count") if obs else None,
                        "port_drift_detected": session.state.port_drift_detected,
                        "observation_count": session.state.observation_count,
                    }
                )

            aggregate = {
                "cpu_cores": {
                    "max": max(cpu_values) if cpu_values else None,
                    "avg": sum(cpu_values) / len(cpu_values) if cpu_values else None,
                    "latest": cpu_values[-1] if cpu_values else None,
                },
                "memory_mb": {
                    "max": max(memory_values) if memory_values else None,
                    "avg": sum(memory_values) / len(memory_values) if memory_values else None,
                    "latest": memory_values[-1] if memory_values else None,
                },
                "storage_mb": (
                    {
                        "max": max(storage_values) if storage_values else None,
                        "avg": sum(storage_values) / len(storage_values) if storage_values else None,
                        "latest": storage_values[-1] if storage_values else None,
                    }
                    if storage_values
                    else None
                ),
                "node_count": {
                    "max": max(node_counts) if node_counts else None,
                    "avg": sum(node_counts) / len(node_counts) if node_counts else None,
                    "latest": node_counts[-1] if node_counts else None,
                },
                "port_drift_sessions": port_drift_count,
            }

            return self.ok(
                {
                    "definition_id": request.definition_id,
                    "observation_count": len(sessions),
                    "sessions": session_summaries,
                    "aggregate": aggregate,
                }
            )

        except Exception as e:
            logger.error("Error aggregating resource observations: %s", e, exc_info=True)
            return self.internal_server_error(str(e))
