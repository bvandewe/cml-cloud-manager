"""Update System Settings command with handler."""

import logging
from dataclasses import asdict, dataclass
from typing import Any

from domain.repositories.system_settings_repository import SystemSettingsRepository
from infrastructure.observability.cqrs_instrumentation import instrumented
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

logger = logging.getLogger(__name__)


@dataclass
class UpdateSystemSettingsCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to update system settings."""

    worker_provisioning: dict[str, Any] | None = None
    monitoring: dict[str, Any] | None = None
    idle_detection: dict[str, Any] | None = None
    discovery: dict[str, Any] | None = None
    updated_by: str | None = None


@instrumented
class UpdateSystemSettingsCommandHandler(CommandHandler[UpdateSystemSettingsCommand, OperationResult[dict[str, Any]]]):
    """Handle updating system settings."""

    def __init__(self, settings_repository: SystemSettingsRepository):
        super().__init__()
        self.settings_repository = settings_repository

    async def handle_async(self, request: UpdateSystemSettingsCommand) -> OperationResult[dict[str, Any]]:
        """Handle update system settings command."""
        try:
            settings = await self.settings_repository.get_default_async()

            worker_provisioning = None
            if request.worker_provisioning:
                # Merge with existing or create new
                current = settings.state.worker_provisioning
                # Simple merge logic - in a real app we might want more validation
                # Using replace to create a new instance with updated fields
                from dataclasses import replace

                worker_provisioning = replace(current, **request.worker_provisioning)

            monitoring = None
            if request.monitoring:
                current = settings.state.monitoring
                from dataclasses import replace

                monitoring = replace(current, **request.monitoring)

            idle_detection = None
            if request.idle_detection:
                current = settings.state.idle_detection
                from dataclasses import replace

                idle_detection = replace(current, **request.idle_detection)

            discovery = None
            if request.discovery:
                current = settings.state.discovery
                from dataclasses import replace

                discovery = replace(current, **request.discovery)

            settings.update(
                worker_provisioning=worker_provisioning,
                monitoring=monitoring,
                idle_detection=idle_detection,
                discovery=discovery,
                updated_by=request.updated_by,
            )

            await self.settings_repository.update_async(settings)

            state = settings.state
            result = {
                "id": state.id,
                "worker_provisioning": asdict(state.worker_provisioning),
                "monitoring": asdict(state.monitoring),
                "idle_detection": asdict(state.idle_detection),
                "discovery": asdict(state.discovery),
                "updated_at": state.updated_at,
                "updated_by": state.updated_by,
            }
            return self.ok(result)

        except Exception as e:
            logger.error(f"Error updating system settings: {e}", exc_info=True)
            return self.internal_server_error(str(e))
