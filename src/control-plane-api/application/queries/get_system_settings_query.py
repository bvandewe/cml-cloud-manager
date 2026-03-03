"""Get System Settings query with handler."""

import logging
from dataclasses import asdict, dataclass
from typing import Any

from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

from domain.repositories.system_settings_repository import SystemSettingsRepository

logger = logging.getLogger(__name__)


@dataclass
class GetSystemSettingsQuery(Query[OperationResult[dict[str, Any]]]):
    """Query to retrieve system settings."""

    pass


class GetSystemSettingsQueryHandler(QueryHandler[GetSystemSettingsQuery, OperationResult[dict[str, Any]]]):
    """Handle retrieving system settings."""

    def __init__(self, settings_repository: SystemSettingsRepository):
        super().__init__()
        self.settings_repository = settings_repository

    async def handle_async(self, request: GetSystemSettingsQuery) -> OperationResult[dict[str, Any]]:
        """Handle get system settings query."""
        try:
            settings = await self.settings_repository.get_default_async()

            # Convert state to dict
            # Since SystemSettingsState is no longer a dataclass, we need to manually convert it
            # or use a serializer. For now, we'll construct the dict manually to match the previous behavior.
            state = settings.state
            result = {
                "id": state.id,
                "worker_provisioning": asdict(state.worker_provisioning),
                "monitoring": asdict(state.monitoring),
                "idle_detection": asdict(state.idle_detection),
                "discovery": asdict(state.discovery),  # ADR-012: Include discovery settings
                "updated_at": state.updated_at,
                "updated_by": state.updated_by,
            }

            return self.ok(result)

        except Exception as e:
            logger.error(f"Error retrieving system settings: {e}", exc_info=True)
            return self.internal_server_error(str(e))
