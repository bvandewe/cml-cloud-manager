"""Query for checking worker idle status and auto-pause eligibility."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from application.services.system_configuration_service import SystemConfigurationService
from application.settings import app_settings
from domain.repositories import CMLWorkerRepository
from domain.services.idle_detection_service import IdleDetectionService

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class GetWorkerIdleStatusQuery(Query[OperationResult[dict[str, Any]]]):
    """Query to check if a worker is idle and eligible for auto-pause.

    Attributes:
        worker_id: Worker identifier
    """

    worker_id: str


class GetWorkerIdleStatusQueryHandler(QueryHandler[GetWorkerIdleStatusQuery, OperationResult[dict[str, Any]]]):
    """Handler for GetWorkerIdleStatusQuery.

    Evaluates idle conditions and determines if worker should be auto-paused.
    """

    def __init__(
        self,
        worker_repository: CMLWorkerRepository,
        idle_service: IdleDetectionService,
        configuration_service: SystemConfigurationService,
    ):
        """Initialize the handler.

        Args:
            worker_repository: Repository for CML worker aggregates
            idle_service: Domain service for idle detection
            configuration_service: Service for effective system configuration
        """
        self._repository = worker_repository
        self._idle_service = idle_service
        self._configuration_service = configuration_service

    async def handle_async(self, request: GetWorkerIdleStatusQuery) -> OperationResult[dict[str, Any]]:
        """Execute the query.

        Args:
            request: Query parameters

        Returns:
            OperationResult with idle status and eligibility information
        """
        with tracer.start_as_current_span("GetWorkerIdleStatusQueryHandler.handle_async") as span:
            span.set_attribute("worker_id", request.worker_id)

            try:
                # Retrieve worker
                worker = await self._repository.get_by_id_async(request.worker_id)

                if not worker:
                    log.warning(f"Worker {request.worker_id} not found")
                    span.set_status(Status(StatusCode.ERROR, "Worker not found"))
                    return self.not_found(
                        f"Worker {request.worker_id}",
                        f"Worker {request.worker_id} not found",
                    )

                # Get effective idle settings
                idle_settings = await self._configuration_service.get_idle_detection_settings_async()

                # Calculate idle duration
                idle_minutes = worker.calculate_idle_duration()

                # Check if currently in snooze period
                in_snooze = worker.in_snooze_period(app_settings.worker_auto_pause_snooze_minutes)

                # Determine if worker is idle based on threshold using domain service
                is_idle = self._idle_service.is_worker_idle(worker, idle_settings.timeout_minutes)

                # Check if auto-pause is enabled (globally and for this worker)
                auto_pause_enabled = idle_settings.enabled and worker.state.is_idle_detection_enabled

                # Determine if eligible for auto-pause
                eligible_for_pause = is_idle and auto_pause_enabled and not in_snooze and worker.state.status.value == "running"

                # Build status response
                status_data = {
                    "worker_id": request.worker_id,
                    "is_idle": is_idle,
                    "idle_minutes": idle_minutes,
                    "idle_threshold_minutes": idle_settings.timeout_minutes,
                    "last_activity_at": worker.state.last_activity_at,
                    "in_snooze_period": in_snooze,
                    "snooze_until": worker.state.last_resumed_at,
                    "auto_pause_enabled": auto_pause_enabled,
                    "eligible_for_pause": eligible_for_pause,
                    "next_idle_check_at": worker.state.next_idle_check_at,
                    "target_pause_at": worker.state.target_pause_at,
                    "checked_at": datetime.now(timezone.utc),
                }

                log.debug(f"Worker {request.worker_id} idle status: " f"idle={is_idle}, eligible_for_pause={eligible_for_pause}")

                span.set_attribute("is_idle", is_idle)
                span.set_attribute("eligible_for_pause", eligible_for_pause)
                span.set_status(Status(StatusCode.OK))

                return self.ok(status_data)

            except Exception as e:
                log.error(
                    f"Error checking idle status for worker {request.worker_id}: {e}",
                    exc_info=True,
                )
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return self.bad_request(f"Error checking idle status: {e}")
