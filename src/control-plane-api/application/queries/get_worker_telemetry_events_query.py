"""Query for fetching and filtering CML worker telemetry events."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from application.settings import Settings
from application.utils.telemetry_filter import (
    filter_relevant_events,
    get_latest_activity_timestamp,
    get_most_recent_events,
)
from domain.repositories import CMLWorkerRepository
from integration.exceptions import IntegrationException
from integration.services.cml_api_client import CMLApiClientFactory

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class GetWorkerTelemetryEventsQuery(Query[OperationResult[dict[str, Any]]]):
    """Query to fetch and filter telemetry events from a CML worker.

    Attributes:
        worker_id: Worker identifier
        since: Optional timestamp to filter events (only return events after this time)
    """

    worker_id: str
    since: datetime | None = None


class GetWorkerTelemetryEventsQueryHandler(QueryHandler[GetWorkerTelemetryEventsQuery, OperationResult[dict[str, Any]]]):
    """Handler for GetWorkerTelemetryEventsQuery.

    Fetches raw telemetry events from CML API and filters for relevant user activity.
    """

    def __init__(
        self,
        worker_repository: CMLWorkerRepository,
        cml_api_client_factory: CMLApiClientFactory,
        settings: Settings,
    ):
        """Initialize the handler.

        Args:
            worker_repository: Repository for CML worker aggregates
            cml_api_client_factory: Factory for creating CML API clients
            settings: Application settings
        """
        self._repository = worker_repository
        self._cml_client_factory = cml_api_client_factory
        self._settings = settings

    async def handle_async(self, query: GetWorkerTelemetryEventsQuery) -> OperationResult[dict[str, Any]]:
        """Execute the query.

        Args:
            query: Query parameters

        Returns:
            OperationResult with filtered telemetry data
        """
        with tracer.start_as_current_span("GetWorkerTelemetryEventsQueryHandler.handle_async") as span:
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

                # Check if worker has endpoint (required for CML API access)
                if not worker.state.https_endpoint:
                    log.warning(f"Worker {query.worker_id} has no HTTPS endpoint configured")
                    return self.bad_request("Worker has no HTTPS endpoint")

                # Determine endpoint to use (public or private based on settings)
                endpoint = worker.get_effective_endpoint(self._settings.use_private_ip_for_monitoring)
                if endpoint != worker.state.https_endpoint:
                    log.debug(f"Using private IP endpoint for telemetry: {endpoint}")

                # Create CML API client for this worker using factory
                cml_client = self._cml_client_factory.create(base_url=endpoint)

                # Fetch raw telemetry events from CML
                log.info(f"Fetching telemetry events from worker {query.worker_id}")
                raw_events = await cml_client.get_telemetry_events()
                span.set_attribute("raw_events_count", len(raw_events))

                # Filter for relevant activity events
                filtered_events = filter_relevant_events(
                    events=raw_events,
                    relevant_categories=self._settings.worker_activity_relevant_categories,
                    exclude_user_pattern=self._settings.worker_activity_excluded_user_pattern,
                    since=query.since or worker.state.last_activity_check_at,
                )
                span.set_attribute("filtered_events_count", len(filtered_events))

                # Get most recent events for display
                recent_events = get_most_recent_events(filtered_events, self._settings.worker_activity_events_max_stored)

                # Extract latest activity timestamp
                latest_activity = get_latest_activity_timestamp(filtered_events)

                result = {
                    "worker_id": query.worker_id,
                    "raw_events_count": len(raw_events),
                    "filtered_events_count": len(filtered_events),
                    "recent_events": recent_events,
                    "latest_activity_at": latest_activity,
                    "checked_at": datetime.now(timezone.utc),
                }

                log.info(f"Retrieved {len(filtered_events)} relevant events " f"from {len(raw_events)} total for worker {query.worker_id}")

                span.set_status(Status(StatusCode.OK))
                return self.ok(result)

            except IntegrationException as e:
                log.error(f"Integration error fetching telemetry for worker {query.worker_id}: {e}")
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return self.bad_request(f"Integration error: {e}")

            except Exception as e:
                log.error(
                    f"Unexpected error fetching telemetry for worker {query.worker_id}: {e}",
                    exc_info=True,
                )
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return self.bad_request(f"Error fetching telemetry: {e}")
