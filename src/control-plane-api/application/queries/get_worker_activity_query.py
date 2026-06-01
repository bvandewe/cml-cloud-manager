"""Query for retrieving worker activity tracking data."""

import logging
from dataclasses import dataclass
from typing import Any

from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler
from opentelemetry import trace

from application.queries.query_handler_base import QueryHandlerBase
from opentelemetry.trace import Status, StatusCode

from domain.repositories import CMLWorkerRepository

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class GetWorkerActivityQuery(Query[OperationResult[dict[str, Any]]]):
    """Query to retrieve activity tracking data for a CML worker.

    Attributes:
        worker_id: Worker identifier
    """

    worker_id: str


class GetWorkerActivityQueryHandler(QueryHandlerBase, QueryHandler[GetWorkerActivityQuery, OperationResult[dict[str, Any]]]):
    """Handler for GetWorkerActivityQuery.

    Returns aggregated activity data including recent events and lifecycle timestamps.
    """

    def __init__(self, worker_repository: CMLWorkerRepository):
        """Initialize the handler.

        Args:
            worker_repository: Repository for CML worker aggregates
        """
        self._repository = worker_repository

    async def handle_async(self, query: GetWorkerActivityQuery) -> OperationResult[dict[str, Any]]:
        """Execute the query.

        Args:
            query: Query parameters

        Returns:
            OperationResult with activity tracking data
        """
        with tracer.start_as_current_span("GetWorkerActivityQueryHandler.handle_async") as span:
            span.set_attribute("worker_id", query.worker_id)

            try:
                # Retrieve worker
                worker = await self._repository.get_by_id_async(query.worker_id)

                if not worker:
                    log.warning(f"Worker {query.worker_id} not found")
                    span.set_status(Status(StatusCode.ERROR, "Worker not found"))
                    return self.not_found(
                        f"Worker {query.worker_id}",
                        f"Worker {query.worker_id} not found",
                    )

                # Build activity summary from worker state
                activity_data = {
                    "worker_id": query.worker_id,
                    "last_activity_at": worker.state.last_activity_at,
                    "last_activity_check_at": worker.state.last_activity_check_at,
                    "recent_activity_events": worker.state.recent_activity_events or [],
                    "last_paused_at": worker.state.last_paused_at,
                    "last_resumed_at": worker.state.last_resumed_at,
                    "auto_pause_count": worker.state.auto_pause_count,
                    "manual_pause_count": worker.state.manual_pause_count,
                    "next_idle_check_at": worker.state.next_idle_check_at,
                    "target_pause_at": worker.state.target_pause_at,
                    "is_idle_detection_enabled": worker.state.is_idle_detection_enabled,
                    "in_snooze_period": worker.in_snooze_period(),
                    "idle_duration_minutes": (worker.calculate_idle_duration().total_seconds() / 60 if worker.calculate_idle_duration() else None),
                }

                log.debug(f"Retrieved activity data for worker {query.worker_id}")
                span.set_status(Status(StatusCode.OK))
                return self.ok(activity_data)

            except Exception as e:
                log.error(
                    f"Error retrieving activity for worker {query.worker_id}: {e}",
                    exc_info=True,
                )
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return self.bad_request(f"Error retrieving activity: {e}")
