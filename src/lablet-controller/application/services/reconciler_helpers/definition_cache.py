"""Cached definition lookup helper.

ADR-038 Task 3: Extracted from LabletReconciler._get_definition().
"""

import logging
from typing import Any

from lcm_core.domain.entities.read_models.lablet_definition_read_model import LabletDefinitionReadModel
from lcm_core.integration.clients import ControlPlaneApiClient

logger = logging.getLogger(__name__)


async def get_definition(
    definition_id: str,
    api: ControlPlaneApiClient,
    cache: dict[str, LabletDefinitionReadModel],
) -> LabletDefinitionReadModel | None:
    """Fetch lablet definition, using *cache* for repeated lookups.

    Args:
        definition_id: The definition ID to fetch.
        api: Control Plane API client.
        cache: Mutable cache dict (caller owns lifetime).

    Returns:
        LabletDefinitionReadModel or None.
    """
    if definition_id in cache:
        return cache[definition_id]

    try:
        data: dict[str, Any] | None = await api.get_lablet_definition(definition_id)
        if data:
            definition = LabletDefinitionReadModel.from_dict(data)
            cache[definition_id] = definition
            return definition
    except Exception as e:
        logger.error(f"Failed to fetch definition {definition_id}: {e}")

    return None
