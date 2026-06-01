"""Get CML Worker resources utilization query with handler.

ADR-015: This query returns cached metrics from the database.
It does NOT call CloudWatch directly. Metrics are collected by worker-controller
and stored in the database for efficient retrieval.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from application.queries.query_handler_base import QueryHandlerBase
from domain.repositories import CMLWorkerRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

logger = logging.getLogger(__name__)


@dataclass
class CachedResourcesUtilization:
    """Cached resource utilization metrics from database.

    ADR-015: This replaces live CloudWatch queries with cached data.
    Metrics are collected by worker-controller and stored in MongoDB.
    """

    cpu_utilization: float | None
    memory_utilization: float | None
    storage_utilization: float | None
    last_collected_at: datetime | None
    detailed_monitoring_enabled: bool
    source: str = "cached"  # Indicates this is cached data, not live


@dataclass
class GetCMLWorkerResourcesQuery(Query[OperationResult[CachedResourcesUtilization]]):
    """Query to retrieve CML Worker resource utilization metrics.

    ADR-015: Returns cached metrics from database. Does NOT call CloudWatch.
    """

    worker_id: str | None = None
    aws_instance_id: str | None = None
    aws_region: str | None = None


class GetCMLWorkerResourcesQueryHandler(QueryHandlerBase, QueryHandler[GetCMLWorkerResourcesQuery, OperationResult[CachedResourcesUtilization]]):
    """Handle retrieving CML Worker cached metrics.

    ADR-015: Returns cached data from database. Does NOT call CloudWatch.
    Worker-controller handles live metrics collection and updates the database.
    """

    def __init__(
        self,
        worker_repository: CMLWorkerRepository,
    ):
        super().__init__()
        self.worker_repository = worker_repository

    async def handle_async(self, request: GetCMLWorkerResourcesQuery) -> OperationResult[CachedResourcesUtilization]:
        """Handle get CML worker resources query.

        ADR-015: Returns cached data from database. No CloudWatch calls.

        Args:
            request: Query with worker ID or instance ID

        Returns:
            OperationResult with cached resource utilization metrics
        """
        try:
            worker = None

            # Resolve worker by ID or instance ID
            if request.worker_id:
                worker = await self.worker_repository.get_by_id_async(request.worker_id)
                if not worker:
                    return self.not_found("CML Worker", request.worker_id)
            elif request.aws_instance_id:
                # Find worker by instance ID
                all_workers = await self.worker_repository.get_all_async()
                for w in all_workers:
                    if w.state.aws_instance_id == request.aws_instance_id:
                        if request.aws_region is None or w.state.aws_region == request.aws_region:
                            worker = w
                            break
                if not worker:
                    return self.not_found("CML Worker", f"instance {request.aws_instance_id}")
            else:
                return self.bad_request("Either worker_id or aws_instance_id must be provided")

            # Build cached utilization from worker state
            state = worker.state
            cached_metrics = CachedResourcesUtilization(
                cpu_utilization=state.cloudwatch_cpu_utilization,
                memory_utilization=state.cloudwatch_memory_utilization,
                storage_utilization=None,  # Storage is tracked via CML metrics
                last_collected_at=state.cloudwatch_last_collected_at,
                detailed_monitoring_enabled=state.cloudwatch_detailed_monitoring_enabled,
                source="cached",
            )

            logger.info(f"Returning cached metrics for worker {worker.id()} (last collected: {state.cloudwatch_last_collected_at})")

            return self.ok(cached_metrics)

        except Exception as e:
            logger.error(f"Error retrieving CML worker resources: {e}", exc_info=True)
            return self.internal_server_error(str(e))
