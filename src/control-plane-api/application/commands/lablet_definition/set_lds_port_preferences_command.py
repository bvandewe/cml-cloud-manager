"""Set LDS port preferences command — user-configurable per-device port override (AD-LDS-002 Phase 3)."""

import logging
from dataclasses import dataclass, field

from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.lablet_definition import LabletDefinition
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository

logger = logging.getLogger(__name__)


@dataclass
class SetLdsPortPreferencesCommand(Command[OperationResult[dict]]):
    """Command to set per-device LDS port preferences on a LabletDefinition.

    Maps device_label → preferred port_name (e.g., {"ubuntu-desktop": "ubuntu-desktop_serial"}).
    These preferences override the global protocol priority at runtime when resolving
    multi-port device conflicts.

    Set to None or empty dict to clear preferences (revert to auto-resolution).
    """

    definition_id: str = ""
    lds_port_preferences: dict[str, str] = field(default_factory=dict)
    updated_by: str = ""


class SetLdsPortPreferencesCommandHandler(
    CommandHandlerBase,
    CommandHandler[SetLdsPortPreferencesCommand, OperationResult[dict]],
):
    """Handle setting LDS port preferences on a LabletDefinition."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        lablet_definition_repository: LabletDefinitionRepository,
    ):
        super().__init__(
            mediator,
            mapper,
            cloud_event_bus,
            cloud_event_publishing_options,
        )
        self._repository = lablet_definition_repository

    async def handle_async(self, request: SetLdsPortPreferencesCommand) -> OperationResult[dict]:
        """Set LDS port preferences for a LabletDefinition.

        Validates that each preference references a port from the definition's
        port_conflicts available_ports list.
        """
        if not request.definition_id:
            return self.bad_request("definition_id is required")

        definition: LabletDefinition | None = await self._repository.get_by_id_async(request.definition_id)
        if not definition:
            return self.not_found(LabletDefinition, request.definition_id)

        # Normalize: empty dict → None (clears preferences)
        preferences = request.lds_port_preferences or None

        # Validate preferences against port_conflicts
        if preferences:
            port_conflicts = getattr(definition.state, "port_conflicts", None) or []
            conflict_map: dict[str, list[str]] = {c["device_label"]: c.get("available_ports", []) for c in port_conflicts if "device_label" in c}

            for device_label, preferred_port in preferences.items():
                if device_label not in conflict_map:
                    return self.bad_request(f"Device '{device_label}' is not in the port conflicts list. Port preferences can only be set for devices with multiple ports.")
                available = conflict_map[device_label]
                if preferred_port not in available:
                    return self.bad_request(f"Port '{preferred_port}' is not available for device '{device_label}'. Available ports: {available}")

        try:
            definition.update(
                changes={"lds_port_preferences": preferences},
                updated_by=request.updated_by,
            )
        except ValueError as e:
            return self.bad_request(str(e))

        await self._repository.update_async(definition)

        logger.info(
            "LDS port preferences updated: %s (name=%s, preferences=%s, by=%s)",
            definition.id(),
            definition.state.name,
            preferences,
            request.updated_by,
        )

        return self.ok(
            {
                "definition_id": definition.id(),
                "name": definition.state.name,
                "lds_port_preferences": definition.state.lds_port_preferences,
            }
        )
