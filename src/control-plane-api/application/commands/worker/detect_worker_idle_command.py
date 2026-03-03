"""Command for detecting worker idle state and triggering auto-pause."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from neuroglia.mediation import Command, CommandHandler, Mediator
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from application.queries.get_worker_idle_status_query import GetWorkerIdleStatusQuery
from application.queries.get_worker_telemetry_events_query import GetWorkerTelemetryEventsQuery
from application.services.system_configuration_service import SystemConfigurationService

from .pause_worker_command import PauseWorkerCommand
from .update_worker_activity_command import UpdateWorkerActivityCommand

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class DetectWorkerIdleCommand(Command):
    """Command to detect worker idle state and auto-pause if eligible.

    Attributes:
        worker_id: Worker identifier
        force_check: Skip next_idle_check_at validation
    """

    worker_id: str
    force_check: bool = False


class DetectWorkerIdleCommandHandler(CommandHandler[DetectWorkerIdleCommand, dict]):
    """Handler for DetectWorkerIdleCommand.

    Orchestrates idle detection workflow:
    1. Fetch telemetry events from CML
    2. Update worker activity state
    3. Check idle status and eligibility
    4. Persist scheduling fields (next_idle_check_at, target_pause_at)
    5. Auto-pause if conditions met
    """

    def __init__(self, mediator: Mediator, configuration_service: SystemConfigurationService):
        """Initialize the handler.

        Args:
            mediator: Mediator for executing queries and commands
            configuration_service: Service for effective system configuration
        """
        self._mediator = mediator
        self._configuration_service = configuration_service

    async def handle_async(self, command: DetectWorkerIdleCommand) -> dict:
        """Execute the command.

        Args:
            command: Command parameters

        Returns:
            OperationResult with detection results
        """
        with tracer.start_as_current_span("DetectWorkerIdleCommandHandler.handle_async") as span:
            span.set_attribute("worker_id", command.worker_id)
            span.set_attribute("force_check", command.force_check)

            detection_result = {
                "worker_id": command.worker_id,
                "checked_at": datetime.now(timezone.utc),
                "telemetry_fetched": False,
                "activity_updated": False,
                "idle_check_performed": False,
                "auto_pause_triggered": False,
                "error": None,
            }

            try:
                # Step 1: Fetch telemetry events from CML
                log.info(f"Fetching telemetry events for worker {command.worker_id}")

                telemetry_result = await self._mediator.execute_async(GetWorkerTelemetryEventsQuery(worker_id=command.worker_id))

                if not telemetry_result.is_success:
                    log.warning(f"Failed to fetch telemetry for worker {command.worker_id}: {telemetry_result.error_message}")
                    detection_result["error"] = "Failed to fetch telemetry"
                    return self.ok(detection_result)

                detection_result["telemetry_fetched"] = True
                telemetry_data = telemetry_result.data

                # Step 2: Update worker activity state (initial — scheduling calculated in step 3.5)
                log.info(f"Updating activity state for worker {command.worker_id}")

                checked_at = datetime.now(timezone.utc)

                # Get idle settings to calculate scheduling
                idle_settings = await self._configuration_service.get_idle_detection_settings_async()
                check_interval_seconds = idle_settings.check_interval_seconds
                next_check = checked_at + timedelta(seconds=check_interval_seconds)

                # Calculate target_pause_at from last_activity_at + idle timeout
                latest_activity = telemetry_data.get("latest_activity_at")
                target_pause = None
                if latest_activity and idle_settings.timeout_minutes:
                    if isinstance(latest_activity, datetime):
                        target_pause = latest_activity + timedelta(minutes=idle_settings.timeout_minutes)
                    elif isinstance(latest_activity, str):
                        try:
                            parsed = datetime.fromisoformat(latest_activity)
                            target_pause = parsed + timedelta(minutes=idle_settings.timeout_minutes)
                        except (ValueError, TypeError):
                            pass

                update_result = await self._mediator.execute_async(
                    UpdateWorkerActivityCommand(
                        worker_id=command.worker_id,
                        last_activity_at=latest_activity,
                        recent_events=telemetry_data.get("recent_events", []),
                        last_check_at=checked_at,
                        next_check_at=next_check,
                        target_pause_at=target_pause,
                    )
                )

                if not update_result.is_success:
                    log.warning(f"Failed to update activity for worker {command.worker_id}: {update_result.error_message}")
                    detection_result["error"] = "Failed to update activity"
                    return self.ok(detection_result)

                detection_result["activity_updated"] = True

                # Step 3: Check idle status and eligibility
                log.info(f"Checking idle status for worker {command.worker_id}")

                idle_status_result = await self._mediator.execute_async(GetWorkerIdleStatusQuery(worker_id=command.worker_id))

                if not idle_status_result.is_success:
                    log.warning(f"Failed to check idle status for worker {command.worker_id}: {idle_status_result.error_message}")
                    detection_result["error"] = "Failed to check idle status"
                    return self.ok(detection_result)

                detection_result["idle_check_performed"] = True
                idle_status = idle_status_result.data

                # Add idle status details to result
                detection_result.update(
                    {
                        "is_idle": idle_status.get("is_idle"),
                        "idle_minutes": idle_status.get("idle_minutes"),
                        "eligible_for_pause": idle_status.get("eligible_for_pause"),
                        "in_snooze_period": idle_status.get("in_snooze_period"),
                    }
                )

                # Step 4: Auto-pause if eligible
                if idle_status.get("eligible_for_pause"):
                    log.info(f"Worker {command.worker_id} is eligible for auto-pause (idle for {idle_status.get('idle_minutes'):.1f} minutes)")

                    pause_result = await self._mediator.execute_async(
                        PauseWorkerCommand(
                            worker_id=command.worker_id,
                            is_auto_pause=True,
                            reason=f"Auto-paused after {idle_status.get('idle_minutes'):.1f} minutes idle",
                        )
                    )

                    if pause_result.is_success:
                        log.info(f"Successfully auto-paused worker {command.worker_id}")
                        detection_result["auto_pause_triggered"] = True
                    else:
                        log.warning(f"Failed to auto-pause worker {command.worker_id}: {pause_result.error_message}")
                        detection_result["error"] = "Failed to trigger auto-pause"
                else:
                    # Log at INFO level for easier debugging
                    log.info(
                        f"Worker {command.worker_id} not eligible for auto-pause: "
                        f"is_idle={idle_status.get('is_idle')}, "
                        f"idle_minutes={idle_status.get('idle_minutes')}, "
                        f"threshold_minutes={idle_status.get('idle_threshold_minutes')}, "
                        f"auto_pause_enabled={idle_status.get('auto_pause_enabled')}, "
                        f"in_snooze={idle_status.get('in_snooze_period')}, "
                        f"last_activity={idle_status.get('last_activity_at')}"
                    )

                span.set_status(Status(StatusCode.OK))
                return self.ok(detection_result)

            except Exception as e:
                log.error(
                    f"Unexpected error during idle detection for worker {command.worker_id}: {e}",
                    exc_info=True,
                )
                detection_result["error"] = str(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return self.ok(detection_result)
