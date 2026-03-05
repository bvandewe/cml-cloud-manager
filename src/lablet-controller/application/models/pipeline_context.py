"""Pipeline execution context — immutable bag of dependencies for pipeline steps.

ADR-034: The PipelineContext replaces the implicit dependency on reconciler `self`
attributes (self._api, self._cml_labs, self._lds) that step handlers currently use.
Step handlers will receive this context as a parameter when the executor dispatches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from integration.services.cml_labs_spi import CmlLabsSpiClient
    from integration.services.lds_spi import LdsSpiClient
    from lcm_core.domain.entities import LabletSessionReadModel
    from lcm_core.domain.entities.read_models.lablet_definition_read_model import LabletDefinitionReadModel
    from lcm_core.integration.clients.control_plane_client import ControlPlaneApiClient


@dataclass
class PipelineContext:
    """Immutable context available to all pipeline steps.

    Carries the session being reconciled, its definition, worker credentials,
    and service clients needed by step handlers. Also accumulates per-step
    result data for output resolution and cross-step dependencies.

    Attributes:
        session: The lablet session read model being processed.
        definition: The lablet definition (includes pipelines, topology, etc.).
        worker_ip: IP address of the assigned CML worker.
        worker_cml_username: CML admin username on the worker.
        worker_cml_password: CML admin password on the worker.
        api: Control Plane API client for CPA calls (progress persistence, etc.).
        cml: CML Labs SPI client for lab operations.
        lds: Lab Delivery System SPI client (None if no LDS configured).
        steps_data: Accumulated step result_data keyed by step name.
    """

    session: LabletSessionReadModel
    definition: LabletDefinitionReadModel
    worker_ip: str
    worker_cml_username: str
    worker_cml_password: str
    api: ControlPlaneApiClient
    cml: CmlLabsSpiClient
    lds: LdsSpiClient | None
    steps_data: dict[str, dict] = field(default_factory=dict)
