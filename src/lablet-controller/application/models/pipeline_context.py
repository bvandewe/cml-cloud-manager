"""Pipeline execution context — immutable bag of dependencies for pipeline steps.

ADR-034: The PipelineContext replaces the implicit dependency on reconciler `self`
attributes (self._api, self._cml_labs, self._lds) that step handlers currently use.
Step handlers will receive this context as a parameter when the executor dispatches.

ADR-038 Task 1: Enriched with helper callables and tracking dicts so registry
handlers achieve full parity with the reconciler's original ``_step_*`` methods.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lcm_core.domain.entities import LabletSessionReadModel
    from lcm_core.domain.entities.read_models.lablet_definition_read_model import LabletDefinitionReadModel
    from lcm_core.integration.clients.control_plane_client import ControlPlaneApiClient

    from application.services.reconciler_helpers.lab_resolution import LabResolutionResult
    from integration.services.cml_labs_spi import CmlLabsSpiClient
    from integration.services.lds_spi import LdsSpiClient


@dataclass
class PipelineContext:
    """Context available to all pipeline steps.

    Carries the session being reconciled, its definition, worker credentials,
    service clients, and helper callables needed by step handlers. Also
    accumulates per-step result data for output resolution and cross-step
    dependencies.

    ADR-038 Task 1 additions (helper callables & tracking state):
        resolve_lab_for_instance: Resolve a lab (reuse or import fresh).
        find_lab_record_id: Find LabRecord aggregate ID by CML lab ID + worker.
        register_lab_record: Register a CML lab as a LabRecord in CPA.
        update_lab_record_status: Update a lab record's status via CPA.
        build_device_access_list: Build LDS DeviceAccessInfo list from CML nodes.
        record_lab_run_completed: Record a completed lab run via CPA.
        request_content_sync: Trigger content sync for a definition.
        resolved_lab_ids: Shared dict tracking lab IDs resolved per session (mutable ref).
        freshly_imported_sessions: Shared set tracking freshly imported sessions (mutable ref).
    """

    # ── Core fields ──────────────────────────────────────────
    session: LabletSessionReadModel
    definition: LabletDefinitionReadModel
    worker_ip: str
    worker_cml_username: str
    worker_cml_password: str
    api: ControlPlaneApiClient
    cml: CmlLabsSpiClient
    lds: LdsSpiClient | None
    steps_data: dict[str, dict] = field(default_factory=dict)

    # ── ADR-038 Task 1: Helper callables for parity with reconciler ──
    # Each is Optional so PipelineContext remains backward-compatible
    # for tests that don't need the full reconciler wiring.

    resolve_lab_for_instance: Callable[[LabletSessionReadModel, str | None], Coroutine[Any, Any, LabResolutionResult | None]] | None = None
    """Resolve a lab for a session: reuse existing or import fresh.
    Signature: async (instance, topology_yaml) -> LabResolutionResult | None"""

    find_lab_record_id: Callable[[str, str], Coroutine[Any, Any, str | None]] | None = None
    """Find LabRecord aggregate ID by CML lab ID + worker ID.
    Signature: async (cml_lab_id, worker_id) -> lab_record_id | None"""

    register_lab_record: Callable[[str, LabletSessionReadModel], Coroutine[Any, Any, str | None]] | None = None
    """Register a CML lab as a LabRecord in CPA via discover_lab_records.
    Signature: async (cml_lab_id, instance) -> lab_record_id | None"""

    update_lab_record_status: Callable[[str, str, str], Coroutine[Any, Any, None]] | None = None
    """Update a lab record's status via CPA.
    Signature: async (cml_lab_id, worker_id, new_status) -> None"""

    build_device_access_list: Callable[[list, str], list] | None = None
    """Build LDS DeviceAccessInfo list from CML nodes (static/sync).
    Signature: (nodes, worker_ip) -> list[DeviceAccessInfo]"""

    record_lab_run_completed: Callable[[LabletSessionReadModel], Coroutine[Any, Any, None]] | None = None
    """Record a completed lab run via CPA (best-effort).
    Signature: async (instance) -> None"""

    request_content_sync: Callable[[str], Coroutine[Any, Any, None]] | None = None
    """Trigger content sync for a definition ID.
    Signature: async (definition_id) -> None"""

    # ── ADR-038 Task 1: Shared mutable tracking state ────────
    # These are references to reconciler-level dicts/sets, passed by
    # reference so step handlers can read/write shared state.

    resolved_lab_ids: dict[str, str] | None = None
    """Shared dict: session_id → cml_lab_id (populated by lab_resolve, cleaned by mark_ready)."""

    freshly_imported_sessions: set[str] | None = None
    """Shared set: session IDs whose labs were freshly imported (not reused)."""

    # ── AD-LDS-002: LDS protocol priority for multi-port devices ──
    lds_protocol_priority: list[str] | None = None

    # AD-LDS-002 Phase 3: User-configurable per-device port override
    # Maps device_label → preferred port_name (from LabletDefinition)
    lds_port_preferences: dict[str, str] | None = None
    """Protocol priority for resolving multi-port devices.
    When a device has multiple ports, highest-priority protocol wins."""
