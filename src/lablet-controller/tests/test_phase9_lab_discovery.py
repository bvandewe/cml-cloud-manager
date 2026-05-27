"""Unit tests for Phase 9: Lab Discovery V2 & Lab Reuse.

Covers:
- LabDiscoveryService: V2 discovery, legacy sync, topology checksums, CML state mapping
- LabletReconciler lab resolution: _resolve_lab_for_instance, _try_reuse_existing_lab, _import_fresh_lab
- Binding management: _bind_lab_to_instance, _release_lab_binding (now no-ops, Phase 7G)
- Run tracking: _record_lab_run_completed
- Lab record helpers: _find_lab_record_id, _update_lab_record_status

Pattern: Uses object.__new__() to bypass __init__ for reconciler tests,
and direct instantiation for LabDiscoveryService tests.
"""

import hashlib
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from lcm_core.domain.entities import LabletSessionReadModel
from lcm_core.domain.entities.read_models.lablet_definition_read_model import LabletDefinitionReadModel
from lcm_core.infrastructure.hosted_services.reconciliation_hosted_service import ReconciliationStatus

from application.hosted_services.lab_discovery_service import (
    DiscoveryRunStats,
    DiscoveryWorkerResult,
    LabDiscoveryService,
    PortRegistrationResult,
)
from application.hosted_services.lablet_reconciler import LabletReconciler
from application.services.pipeline_executor import PipelineExecutor
from integration.services.cml_labs_spi import LabInfo, LabState, NodeInfo

# =============================================================================
# Fixtures
# =============================================================================


def make_lab_discovery_service(
    labs_refresh_enabled: bool = True,
    labs_refresh_interval: int = 1800,
    use_private_ip_for_monitoring: bool = False,
) -> LabDiscoveryService:
    """Create a LabDiscoveryService with mocked dependencies."""
    api = AsyncMock()
    cml_labs = AsyncMock()
    etcd = AsyncMock()
    settings = MagicMock()
    settings.labs_refresh_enabled = labs_refresh_enabled
    settings.labs_refresh_interval = labs_refresh_interval
    settings.use_private_ip_for_monitoring = use_private_ip_for_monitoring

    svc = LabDiscoveryService(
        api_client=api,
        cml_labs_client=cml_labs,
        etcd_client=etcd,
        settings=settings,
    )
    return svc


def make_reconciler() -> LabletReconciler:
    """Create a LabletReconciler bypassing __init__."""
    r = object.__new__(LabletReconciler)
    r._api = AsyncMock()
    r._cml_labs = AsyncMock()
    r._lds = AsyncMock()
    r._settings = MagicMock()
    r._settings.worker_bootup_delay_minutes = 20
    r._definition_cache = {}
    r._labs_imported = 0
    r._labs_started = 0
    r._labs_stopped = 0
    r._labs_deleted = 0
    r._lab_sync_count = 0
    r._lds_sessions_created = 0
    r._lds_sessions_archived = 0
    r._labs_reused = 0
    r._bindings_created = 0
    r._bindings_released = 0
    r._runs_recorded = 0
    r._lab_run_started_at = {}
    r._resolved_lab_ids = {}
    r._freshly_imported_sessions = set()
    r._worker_cache = {}
    r._content_sync_service = None
    r._resource_observer = None
    # Sprint C additions
    r._session_locks = {}
    r._active_handlers = {}
    r._pipeline_executor = PipelineExecutor()
    r._pipeline_retry_counts = {}
    return r


def make_instance(
    instance_id: str = "inst-001",
    name: str = "test-lablet",
    definition_id: str = "def-001",
    status: str = "INSTANTIATING",
    worker_id: str | None = "worker-001",
    cml_lab_id: str | None = "lab-abc",
    worker_ip: str | None = "10.0.0.1",
    worker_aws_region: str | None = "us-east-1",
    worker_cml_username: str | None = "admin",
    worker_cml_password: str | None = "secret",
    timeslot_start: datetime | None = None,
    timeslot_end: datetime | None = None,
    topology_yaml: str | None = "nodes:\n  - label: router1",
    lds_session_id: str | None = None,
    lds_login_url: str | None = None,
) -> LabletSessionReadModel:
    """Create a LabletSessionReadModel for testing."""
    return LabletSessionReadModel(
        id=instance_id,
        name=name,
        definition_id=definition_id,
        status=status,
        worker_id=worker_id,
        cml_lab_id=cml_lab_id,
        worker_ip=worker_ip,
        worker_aws_region=worker_aws_region,
        worker_cml_username=worker_cml_username,
        worker_cml_password=worker_cml_password,
        timeslot_start=timeslot_start,
        timeslot_end=timeslot_end,
        topology_yaml=topology_yaml,
        lds_session_id=lds_session_id,
        lds_login_url=lds_login_url,
    )


def make_definition(
    definition_id: str = "def-001",
    name: str = "Test Definition",
    lab_reuse_enabled: bool = False,
    node_count: int = 2,
    form_qualified_name: str | None = "org/project/form",
) -> LabletDefinitionReadModel:
    """Create a LabletDefinitionReadModel for testing."""
    return LabletDefinitionReadModel(
        id=definition_id,
        name=name,
        form_qualified_name=form_qualified_name,
        lab_reuse_enabled=lab_reuse_enabled,
        node_count=node_count,
    )


def make_lab_info(
    lab_id: str = "lab-abc",
    title: str = "Test Lab",
    state: LabState = LabState.BOOTED,
    owner: str | None = "admin",
    node_count: int = 2,
    link_count: int = 1,
) -> LabInfo:
    """Create a LabInfo for testing."""
    return LabInfo(
        id=lab_id,
        title=title,
        state=state,
        owner=owner,
        node_count=node_count,
        link_count=link_count,
    )


# =============================================================================
# LabDiscoveryService Tests
# =============================================================================


class TestLabDiscoveryServiceInit:
    """Tests for LabDiscoveryService initialization and configuration."""

    def test_initialization(self):
        """Service should initialize with all counters at zero."""
        svc = make_lab_discovery_service()

        assert svc._discovery_runs == 0
        assert svc._total_labs_synced == 0
        assert svc._total_labs_discovered == 0
        assert svc._running is False
        assert svc._topology_checksums == {}

    @pytest.mark.asyncio
    async def test_start_when_disabled_does_nothing(self):
        """When labs_refresh_enabled=False, start should not create periodic task.

        ADR-041 Phase 2: The etcd watch task still starts (for targeted discovery),
        but the periodic polling task (_task) is not created.
        """
        svc = make_lab_discovery_service(labs_refresh_enabled=False)

        await svc.start_async()

        assert svc._running is True  # Always True (etcd watch runs)
        assert svc._task is None  # Periodic polling NOT started
        assert svc._watch_task is not None  # etcd watch IS started

        # Cleanup
        await svc.stop_async()

    def test_get_stats_returns_correct_shape(self):
        """get_stats should return all expected keys."""
        svc = make_lab_discovery_service()

        stats = svc.get_stats()

        assert "enabled" in stats
        assert "running" in stats
        assert "discovery_runs" in stats
        assert "total_labs_synced" in stats
        assert "interval_seconds" in stats


class TestTopologyChecksum:
    """Tests for SHA-256 topology checksum computation (P9-2)."""

    def test_checksum_deterministic(self):
        """Same lab info should produce same checksum."""
        lab = make_lab_info(title="Lab1", node_count=3, link_count=2)

        checksum1 = LabDiscoveryService._compute_topology_checksum(lab)
        checksum2 = LabDiscoveryService._compute_topology_checksum(lab)

        assert checksum1 == checksum2
        assert len(checksum1) == 64  # SHA-256 hex digest

    def test_checksum_differs_for_different_topology(self):
        """Different topology fields should produce different checksums."""
        lab1 = make_lab_info(node_count=3, link_count=2)
        lab2 = make_lab_info(node_count=5, link_count=4)

        checksum1 = LabDiscoveryService._compute_topology_checksum(lab1)
        checksum2 = LabDiscoveryService._compute_topology_checksum(lab2)

        assert checksum1 != checksum2

    def test_checksum_uses_canonical_json(self):
        """Checksum should use sorted keys for deterministic output."""
        lab = make_lab_info(title="MyLab", owner="admin", node_count=2, link_count=1)

        expected_canonical = json.dumps(
            {"link_count": 1, "node_count": 2, "owner": "admin", "title": "MyLab"},
            sort_keys=True,
            separators=(",", ":"),
        )
        expected_checksum = hashlib.sha256(expected_canonical.encode("utf-8")).hexdigest()

        actual = LabDiscoveryService._compute_topology_checksum(lab)

        assert actual == expected_checksum

    def test_checksum_handles_none_fields(self):
        """None fields should be treated as empty strings."""
        lab = make_lab_info(title=None, owner=None, node_count=0, link_count=0)

        checksum = LabDiscoveryService._compute_topology_checksum(lab)

        assert isinstance(checksum, str)
        assert len(checksum) == 64


class TestCmlStateMapping:
    """Tests for CML state → LabRecordStatus mapping."""

    def test_defined_on_core_maps_to_defined(self):
        """DEFINED_ON_CORE should map to 'defined'."""
        result = LabDiscoveryService._map_cml_state_to_status("DEFINED_ON_CORE")
        assert result == "defined"

    def test_booted_maps_to_booted(self):
        """BOOTED should map to 'booted'."""
        result = LabDiscoveryService._map_cml_state_to_status("BOOTED")
        assert result == "booted"

    def test_started_maps_to_booted(self):
        """STARTED (still booting) should map to 'booted'."""
        result = LabDiscoveryService._map_cml_state_to_status("STARTED")
        assert result == "booted"

    def test_stopped_maps_to_stopped(self):
        """STOPPED should map to 'stopped'."""
        result = LabDiscoveryService._map_cml_state_to_status("STOPPED")
        assert result == "stopped"

    def test_queued_maps_to_queued(self):
        """QUEUED should map to 'queued'."""
        result = LabDiscoveryService._map_cml_state_to_status("QUEUED")
        assert result == "queued"

    def test_unknown_state_maps_to_discovered(self):
        """Unknown CML state should default to 'discovered'."""
        result = LabDiscoveryService._map_cml_state_to_status("SOME_UNKNOWN")
        assert result == "discovered"


class TestResolveWorkerHost:
    """Tests for worker host resolution."""

    def test_public_ip_preferred(self):
        """By default, public_ip should be preferred."""
        svc = make_lab_discovery_service(use_private_ip_for_monitoring=False)
        worker = {"public_ip": "1.2.3.4", "private_ip": "10.0.0.1"}

        host = svc._resolve_worker_host(worker)

        assert host == "1.2.3.4"

    def test_private_ip_preferred_when_configured(self):
        """When use_private_ip_for_monitoring=True, private_ip is preferred."""
        svc = make_lab_discovery_service(use_private_ip_for_monitoring=True)
        worker = {"public_ip": "1.2.3.4", "private_ip": "10.0.0.1"}

        host = svc._resolve_worker_host(worker)

        assert host == "10.0.0.1"

    def test_fallback_to_https_endpoint(self):
        """When no IPs available, fall back to https_endpoint."""
        svc = make_lab_discovery_service()
        worker = {"https_endpoint": "https://cml.example.com:443"}

        host = svc._resolve_worker_host(worker)

        assert host == "cml.example.com"

    def test_returns_none_when_no_host_available(self):
        """When no host info available, return None."""
        svc = make_lab_discovery_service()
        worker = {}

        host = svc._resolve_worker_host(worker)

        assert host is None


class TestDiscoverV2:
    """Tests for V2 discovery pipeline."""

    @pytest.mark.asyncio
    async def test_v2_sends_lab_data_with_checksums(self):
        """V2 discovery should compute checksums and POST to CPA."""
        svc = make_lab_discovery_service()
        labs = [
            make_lab_info(lab_id="lab-1", title="Lab 1", state=LabState.BOOTED),
            make_lab_info(lab_id="lab-2", title="Lab 2", state=LabState.STOPPED),
        ]
        svc._api.discover_lab_records.return_value = {
            "synced": 2,
            "discovered": 1,
            "updated": 1,
            "orphaned": 0,
            "revisions_created": 0,
        }

        result = await svc._discover("worker-001", "10.0.0.1", labs)

        assert result.synced == 2
        assert result.discovered == 1
        assert result.updated == 1
        svc._api.discover_lab_records.assert_awaited_once()

        # Verify lab_data structure
        call_kwargs = svc._api.discover_lab_records.call_args.kwargs
        assert call_kwargs["worker_id"] == "worker-001"
        assert len(call_kwargs["labs"]) == 2
        assert "topology_checksum" in call_kwargs["labs"][0]

    @pytest.mark.asyncio
    async def test_v2_detects_topology_change(self):
        """V2 should flag topology_changed when checksum differs from cache."""
        svc = make_lab_discovery_service()
        # Seed cache with old checksum
        svc._topology_checksums[("worker-001", "lab-1")] = "old_checksum"

        labs = [make_lab_info(lab_id="lab-1", title="Changed Lab")]
        svc._api.discover_lab_records.return_value = {"synced": 1}

        await svc._discover("worker-001", "10.0.0.1", labs)

        call_kwargs = svc._api.discover_lab_records.call_args.kwargs
        assert call_kwargs["labs"][0].get("topology_changed") is True

    @pytest.mark.asyncio
    async def test_v2_no_change_detected(self):
        """V2 should NOT flag topology_changed when checksum matches cache."""
        svc = make_lab_discovery_service()
        lab = make_lab_info(lab_id="lab-1", title="Stable Lab")
        checksum = LabDiscoveryService._compute_topology_checksum(lab)
        svc._topology_checksums[("worker-001", "lab-1")] = checksum

        svc._api.discover_lab_records.return_value = {"synced": 1}

        await svc._discover("worker-001", "10.0.0.1", [lab])

        call_kwargs = svc._api.discover_lab_records.call_args.kwargs
        assert "topology_changed" not in call_kwargs["labs"][0]


class TestDiscoverWorkerLabs:
    """Tests for per-worker discovery."""

    @pytest.mark.asyncio
    async def test_calls_discover_lab_records(self):
        """Should call discover_lab_records on CPA."""
        svc = make_lab_discovery_service()
        svc._cml_labs.list_labs.return_value = [make_lab_info()]
        svc._api.discover_lab_records.return_value = {"synced": 1}

        worker = {"id": "w-1", "public_ip": "1.2.3.4"}
        await svc._discover_worker_labs(worker)

        svc._api.discover_lab_records.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_worker_without_host(self):
        """Worker without any host should be skipped."""
        svc = make_lab_discovery_service()
        worker = {"id": "w-1"}  # No IPs or endpoint

        result = await svc._discover_worker_labs(worker)

        assert result.synced == 0
        svc._cml_labs.list_labs.assert_not_awaited()


# =============================================================================
# DiscoveryRunStats / DiscoveryWorkerResult Tests
# =============================================================================


class TestDiscoveryDataClasses:
    """Tests for DiscoveryRunStats and DiscoveryWorkerResult."""

    def test_worker_result_defaults(self):
        """Default worker result should have all zeros."""
        result = DiscoveryWorkerResult()
        assert result.synced == 0
        assert result.discovered == 0
        assert result.errors == 0

    def test_run_stats_accumulate(self):
        """RunStats should accumulate multiple worker results."""
        stats = DiscoveryRunStats()
        r1 = DiscoveryWorkerResult(synced=3, discovered=2, updated=1)
        r2 = DiscoveryWorkerResult(synced=5, orphaned=1, errors=1)

        stats.accumulate(r1)
        stats.accumulate(r2)

        assert stats.synced == 8
        assert stats.discovered == 2
        assert stats.updated == 1
        assert stats.orphaned == 1
        assert stats.errors == 1


# =============================================================================
# LabletReconciler: Lab Resolution (P9-4/5)
# =============================================================================


class TestResolveLabForInstance:
    """Tests for _resolve_lab_for_instance — reuse vs. fresh import."""

    @pytest.mark.asyncio
    async def test_reuse_disabled_goes_to_import(self):
        """When lab_reuse_enabled=False, should skip reuse and import fresh."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None)
        # Definition with reuse disabled
        r._definition_cache["def-001"] = make_definition(lab_reuse_enabled=False)
        r._cml_labs.import_lab.return_value = "lab-new-123"

        lab_id = await r._resolve_lab_for_instance(instance)

        assert lab_id == "lab-new-123"
        r._cml_labs.import_lab.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reuse_enabled_but_no_reusable_lab_imports_fresh(self):
        """When reuse enabled but no matching labs, fall back to import."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None)
        r._definition_cache["def-001"] = make_definition(lab_reuse_enabled=True, node_count=2)
        # CPA returns empty list (no reusable labs)
        r._api.get_lab_records_for_worker.return_value = []
        r._cml_labs.import_lab.return_value = "lab-fresh-456"

        lab_id = await r._resolve_lab_for_instance(instance)

        assert lab_id == "lab-fresh-456"

    @pytest.mark.asyncio
    async def test_no_definition_found_imports_fresh(self):
        """When definition lookup fails, skip reuse and import fresh."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None)
        r._api.get_lablet_definition.return_value = None  # Definition not found
        r._cml_labs.import_lab.return_value = "lab-new-789"

        lab_id = await r._resolve_lab_for_instance(instance)

        assert lab_id == "lab-new-789"

    @pytest.mark.asyncio
    async def test_import_failure_returns_none(self):
        """When import fails, should return None."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None)
        r._api.get_lablet_definition.return_value = None
        r._cml_labs.import_lab.side_effect = RuntimeError("CML down")

        lab_id = await r._resolve_lab_for_instance(instance)

        assert lab_id is None


class TestTryReuseExistingLab:
    """Tests for _try_reuse_existing_lab.

    Production code (Track 1 fixes):
    - Matches candidates on ``based_on_definition_id == instance.definition_id`` (not node_count)
    - Verifies each candidate exists on CML via ``get_lab()`` (ghost detection)
    - Marks ORPHANED via CPA if ``get_lab()`` returns None (HTTP 404)
    - Checks 4 candidate states in preference order: WIPED → STOPPED → WIPING → STOPPING
    """

    @pytest.mark.asyncio
    async def test_reuses_wiped_lab_directly(self):
        """WIPED lab matching definition_id should be reused directly (no wipe needed)."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None, definition_id="def-001")
        definition = make_definition(lab_reuse_enabled=True)
        # CPA returns a wiped lab matching based_on_definition_id
        r._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-001", "lab_id": "lab-reuse-1", "worker_id": "worker-001", "status": "wiped", "based_on_definition_id": "def-001"},
        ]
        # CML verifies lab exists
        r._cml_labs.get_lab.return_value = make_lab_info(lab_id="lab-reuse-1", state=LabState.DEFINED_ON_CORE)

        lab_id = await r._try_reuse_existing_lab(instance, definition)

        assert lab_id == "lab-reuse-1"
        r._cml_labs.wipe_lab.assert_not_awaited()  # Already wiped
        r._cml_labs.get_lab.assert_awaited_once()  # Verified existence

    @pytest.mark.asyncio
    async def test_reuses_stopped_lab_with_wipe(self):
        """STOPPED lab matching definition_id should be wiped before reuse."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None, definition_id="def-001")
        definition = make_definition(lab_reuse_enabled=True)
        # No wiped labs, but a stopped lab matches definition_id
        r._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-002", "lab_id": "lab-stopped-1", "worker_id": "worker-001", "status": "stopped", "based_on_definition_id": "def-001"},
        ]
        # CML verifies lab exists
        r._cml_labs.get_lab.return_value = make_lab_info(lab_id="lab-stopped-1", state=LabState.STOPPED)

        lab_id = await r._try_reuse_existing_lab(instance, definition)

        assert lab_id == "lab-stopped-1"
        r._cml_labs.wipe_lab.assert_awaited_once()
        r._cml_labs.get_lab.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_matching_definition_id_returns_none(self):
        """Labs with different based_on_definition_id should not match."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None, definition_id="def-001")
        definition = make_definition(lab_reuse_enabled=True)
        # Labs exist but based_on_definition_id doesn't match instance.definition_id
        r._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-003", "lab_id": "lab-x", "worker_id": "worker-001", "status": "wiped", "based_on_definition_id": "def-999"},
        ]

        lab_id = await r._try_reuse_existing_lab(instance, definition)

        assert lab_id is None
        r._cml_labs.get_lab.assert_not_awaited()  # Never reached CML verification

    @pytest.mark.asyncio
    async def test_no_based_on_definition_id_skips_candidate(self):
        """Labs without based_on_definition_id (None) should not match any definition."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None, definition_id="def-001")
        definition = make_definition(lab_reuse_enabled=True)
        # Lab record has no provenance tracking (based_on_definition_id is None)
        r._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-004", "lab_id": "lab-legacy", "worker_id": "worker-001", "status": "wiped", "node_count": 2},
        ]

        lab_id = await r._try_reuse_existing_lab(instance, definition)

        assert lab_id is None
        r._cml_labs.get_lab.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ghost_lab_skipped_and_marked_orphaned(self):
        """When CML get_lab() returns None (404), candidate should be skipped and marked ORPHANED."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None, definition_id="def-001")
        definition = make_definition(lab_reuse_enabled=True)
        # CPA returns a matching candidate
        r._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-ghost", "lab_id": "lab-ghost-1", "worker_id": "worker-001", "status": "wiped", "based_on_definition_id": "def-001"},
        ]
        # CML says lab doesn't exist (ghost)
        r._cml_labs.get_lab.return_value = None

        lab_id = await r._try_reuse_existing_lab(instance, definition)

        assert lab_id is None
        r._cml_labs.get_lab.assert_awaited_once()
        # Ghost candidate triggers ORPHANED status update via CPA
        r._api.update_lab_record_status.assert_awaited_once_with(
            lab_record_id="rec-ghost",
            new_status="orphaned",
        )

    @pytest.mark.asyncio
    async def test_ghost_lab_skipped_falls_through_to_next_candidate(self):
        """Ghost candidate should be skipped; next valid candidate should be used."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None, definition_id="def-001")
        definition = make_definition(lab_reuse_enabled=True)
        # Two matching candidates: first is ghost, second is real
        r._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-ghost", "lab_id": "lab-ghost", "worker_id": "worker-001", "status": "wiped", "based_on_definition_id": "def-001"},
            {"id": "rec-real", "lab_id": "lab-real", "worker_id": "worker-001", "status": "wiped", "based_on_definition_id": "def-001"},
        ]
        # First get_lab returns None (ghost), second returns real lab
        r._cml_labs.get_lab.side_effect = [None, make_lab_info(lab_id="lab-real", state=LabState.DEFINED_ON_CORE)]

        lab_id = await r._try_reuse_existing_lab(instance, definition)

        assert lab_id == "lab-real"
        assert r._cml_labs.get_lab.await_count == 2

    @pytest.mark.asyncio
    async def test_prefers_wiped_over_stopped(self):
        """WIPED candidates should be preferred over STOPPED (faster to ready)."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None, definition_id="def-001")
        definition = make_definition(lab_reuse_enabled=True)
        # Both wiped and stopped candidates with same definition_id
        r._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-stopped", "lab_id": "lab-stopped", "worker_id": "worker-001", "status": "stopped", "based_on_definition_id": "def-001"},
            {"id": "rec-wiped", "lab_id": "lab-wiped", "worker_id": "worker-001", "status": "wiped", "based_on_definition_id": "def-001"},
        ]
        # CML verifies first checked lab exists (wiped comes first in preference order)
        r._cml_labs.get_lab.return_value = make_lab_info(lab_id="lab-wiped", state=LabState.DEFINED_ON_CORE)

        lab_id = await r._try_reuse_existing_lab(instance, definition)

        assert lab_id == "lab-wiped"
        r._cml_labs.wipe_lab.assert_not_awaited()  # Already wiped, no need

    @pytest.mark.asyncio
    async def test_skips_candidates_with_pending_action(self):
        """Candidates with an active pending_action should be skipped."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None, definition_id="def-001")
        definition = make_definition(lab_reuse_enabled=True)
        # Candidate has a pending action — should be skipped
        r._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-busy", "lab_id": "lab-busy", "worker_id": "worker-001", "status": "wiped", "based_on_definition_id": "def-001", "pending_action": "wipe"},
        ]

        lab_id = await r._try_reuse_existing_lab(instance, definition)

        assert lab_id is None
        r._cml_labs.get_lab.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_transitional_states_skipped_gracefully(self):
        """WIPING/STOPPING candidates are verified but skipped (transitional)."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None, definition_id="def-001")
        definition = make_definition(lab_reuse_enabled=True)
        # Only a WIPING candidate — exists but transitional
        r._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-wiping", "lab_id": "lab-wiping", "worker_id": "worker-001", "status": "wiping", "based_on_definition_id": "def-001"},
        ]
        r._cml_labs.get_lab.return_value = make_lab_info(lab_id="lab-wiping", state=LabState.STOPPED)

        lab_id = await r._try_reuse_existing_lab(instance, definition)

        # Transitional states are logged but skipped (not reusable yet)
        assert lab_id is None
        r._cml_labs.get_lab.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_api_error_returns_none_gracefully(self):
        """API errors during reuse lookup should return None (graceful)."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None)
        definition = make_definition(lab_reuse_enabled=True)
        r._api.get_lab_records_for_worker.side_effect = RuntimeError("CPA down")

        lab_id = await r._try_reuse_existing_lab(instance, definition)

        assert lab_id is None


class TestImportFreshLab:
    """Tests for _import_fresh_lab."""

    @pytest.mark.asyncio
    async def test_successful_import(self):
        """Successful import should return new lab ID."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None)
        r._cml_labs.import_lab.return_value = "lab-fresh-001"

        lab_id = await r._import_fresh_lab(instance)

        assert lab_id == "lab-fresh-001"
        r._cml_labs.import_lab.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_import_error_returns_none(self):
        """CML import error should return None (not raise)."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None)
        r._cml_labs.import_lab.side_effect = RuntimeError("CML unreachable")

        lab_id = await r._import_fresh_lab(instance)

        assert lab_id is None

    @pytest.mark.asyncio
    async def test_import_tags_freshly_imported_lab_id(self):
        """Import should set _freshly_imported_lab_id on instance for metrics."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None)
        r._cml_labs.import_lab.return_value = "lab-tagged-001"

        await r._import_fresh_lab(instance)

        assert instance._freshly_imported_lab_id == "lab-tagged-001"  # type: ignore[attr-defined]


# =============================================================================
# LabletReconciler: Binding Management (P9-6)
# =============================================================================


class TestRecordLabRunCompleted:
    """Tests for _record_lab_run_completed."""

    @pytest.mark.asyncio
    async def test_records_run_with_tracked_start_time(self):
        """Should use tracked start time from _lab_run_started_at."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id="lab-abc", worker_id="w-001")
        start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        r._lab_run_started_at["inst-001"] = start_time
        r._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-001", "lab_id": "lab-abc"},
        ]

        await r._record_lab_run_completed(instance)

        r._api.record_lab_run_completed.assert_awaited_once()
        call_kwargs = r._api.record_lab_run_completed.call_args.kwargs
        assert call_kwargs["started_at"] == start_time.isoformat()
        assert call_kwargs["lab_record_id"] == "rec-001"
        assert r._runs_recorded == 1

    @pytest.mark.asyncio
    async def test_records_run_without_start_time(self):
        """Should still record run even without tracked start time."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id="lab-abc", worker_id="w-001")
        # No entry in _lab_run_started_at
        r._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-001", "lab_id": "lab-abc"},
        ]

        await r._record_lab_run_completed(instance)

        r._api.record_lab_run_completed.assert_awaited_once()
        call_kwargs = r._api.record_lab_run_completed.call_args.kwargs
        assert call_kwargs["started_at"] is None

    @pytest.mark.asyncio
    async def test_no_lab_record_does_nothing(self):
        """When no LabRecord found, should skip run recording."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id="lab-abc", worker_id="w-001")
        r._api.get_lab_records_for_worker.return_value = []

        await r._record_lab_run_completed(instance)

        r._api.record_lab_run_completed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_cml_lab_id_returns_early(self):
        """Without cml_lab_id, should skip run recording."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None)

        await r._record_lab_run_completed(instance)

        r._api.get_lab_records_for_worker.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_recording_error_is_graceful(self):
        """API error during run recording should be caught."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id="lab-abc", worker_id="w-001")
        r._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-001", "lab_id": "lab-abc"},
        ]
        r._api.record_lab_run_completed.side_effect = RuntimeError("CPA error")

        # Should not raise
        await r._record_lab_run_completed(instance)

        assert r._runs_recorded == 0


# =============================================================================
# LabletReconciler: Lab Record Helpers
# =============================================================================


class TestFindLabRecordId:
    """Tests for _find_lab_record_id."""

    @pytest.mark.asyncio
    async def test_finds_matching_lab_record(self):
        """Should find and return LabRecord ID matching CML lab_id."""
        r = make_reconciler()
        r._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-001", "lab_id": "lab-xxx"},
            {"id": "rec-002", "lab_id": "lab-abc"},
            {"id": "rec-003", "lab_id": "lab-yyy"},
        ]

        result = await r._find_lab_record_id("lab-abc", "w-001")

        assert result == "rec-002"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_match(self):
        """Should return None when no LabRecord matches."""
        r = make_reconciler()
        r._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-001", "lab_id": "lab-other"},
        ]

        result = await r._find_lab_record_id("lab-abc", "w-001")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_response(self):
        """Should return None when CPA returns empty list."""
        r = make_reconciler()
        r._api.get_lab_records_for_worker.return_value = []

        result = await r._find_lab_record_id("lab-abc", "w-001")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_api_error(self):
        """Should return None on API error (graceful)."""
        r = make_reconciler()
        r._api.get_lab_records_for_worker.side_effect = RuntimeError("CPA down")

        result = await r._find_lab_record_id("lab-abc", "w-001")

        assert result is None


# =============================================================================
# Integration: _handle_instantiating with P9 resolution
# =============================================================================


@pytest.mark.skip(reason="ADR-034 Sprint C: _build_default_progress() removed (AD-PIPELINE-009). Lab resolution tests covered in test_instantiation_pipeline.py.")
class TestHandleInstantiatingWithResolution:
    """Integration tests for _handle_instantiating using P9 lab resolution via pipeline."""

    @pytest.mark.asyncio
    async def test_reuse_lab_increments_reuse_counter(self):
        """Successful lab reuse should increment _labs_reused via _step_lab_resolve."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None)
        # Definition with reuse enabled
        r._definition_cache["def-001"] = make_definition(lab_reuse_enabled=True, node_count=2)
        r._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-001", "lab_id": "lab-reuse-1", "status": "wiped", "node_count": 2},
        ]

        progress = LabletReconciler._build_default_progress()
        result = await r._step_lab_resolve(instance, progress)

        assert result["status"] == "completed"
        assert result["result_data"]["cml_lab_id"] == "lab-reuse-1"
        assert r._labs_reused == 1
        assert r._labs_imported == 0

    @pytest.mark.asyncio
    async def test_fresh_import_increments_import_counter(self):
        """Fresh lab import should increment _labs_imported via _step_lab_resolve."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None)
        r._api.get_lablet_definition.return_value = None
        r._cml_labs.import_lab.return_value = "lab-new-001"
        r._api.get_lab_records_for_worker.return_value = []

        progress = LabletReconciler._build_default_progress()
        result = await r._step_lab_resolve(instance, progress)

        assert result["status"] == "completed"
        assert result["result_data"]["cml_lab_id"] == "lab-new-001"
        assert r._labs_imported == 1
        assert r._labs_reused == 0

    @pytest.mark.asyncio
    async def test_resolution_failure_returns_failed_step(self):
        """Failed resolution should return a failed step result (not transition to TERMINATED)."""
        r = make_reconciler()
        instance = make_instance(cml_lab_id=None)
        r._api.get_lablet_definition.return_value = None
        r._cml_labs.import_lab.side_effect = RuntimeError("CML down")

        progress = LabletReconciler._build_default_progress()
        result = await r._step_lab_resolve(instance, progress)

        assert result["status"] == "failed"
        assert "unable to import" in result["error"]

    @pytest.mark.asyncio
    async def test_started_converged_lab_records_run_start(self):
        """When lab is STARTED+converged, _step_lab_start should record run start time."""
        r = make_reconciler()
        instance = make_instance(status="INSTANTIATING", cml_lab_id="lab-abc")
        r._cml_labs.get_lab_state.return_value = LabState.STARTED
        r._cml_labs.check_if_converged.return_value = True

        progress = {
            "steps": [
                {"step": "lab_resolve", "requires": [], "status": "completed", "result_data": {"cml_lab_id": "lab-abc"}},
            ],
        }
        result = await r._step_lab_start(instance, progress)

        assert result["status"] == "completed"
        assert result["result_data"]["lab_state"] == "CONVERGED"
        assert "inst-001" in r._lab_run_started_at


# =============================================================================
# Integration: _handle_stopping with P9 reuse
# =============================================================================


@pytest.mark.skip(reason="ADR-034 Sprint D: _handle_stopping refactored to fire-and-check delegation. See test_teardown_pipeline.py.")
class TestHandleStoppingWithReuse:
    """Integration tests for _handle_stopping using P9 wipe-for-reuse pattern."""

    @pytest.mark.asyncio
    async def test_stopped_lab_wiped_not_deleted(self):
        """Stopped lab should be wiped but NOT deleted (available for reuse)."""
        r = make_reconciler()
        instance = make_instance(status="STOPPING", cml_lab_id="lab-abc")
        r._cml_labs.get_lab_state.return_value = LabState.STOPPED
        r._api.get_lab_records_for_worker.return_value = []  # No binding/run (graceful)

        result = await r._handle_stopping(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        r._cml_labs.wipe_lab.assert_awaited_once()
        r._cml_labs.delete_lab.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stopping_does_not_call_unbind(self):
        """Phase 7G: Stopping should NOT call unbind (handled by session termination).

        unbind_lab_from_lablet was removed from ControlPlaneApiClient in Phase 7G.
        Session termination now handles cleanup automatically.
        """
        r = make_reconciler()
        instance = make_instance(status="STOPPING", cml_lab_id="lab-abc")
        r._cml_labs.get_lab_state.return_value = LabState.STOPPED
        r._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-001", "lab_id": "lab-abc"},
        ]

        await r._handle_stopping(instance)

        # Phase 7G: unbind_lab_from_lablet was removed, no binding calls made.
        # _handle_stopping still calls transition_session (expected), but should
        # NOT attempt any lab binding/unbinding operations.

    @pytest.mark.asyncio
    async def test_stopping_records_lab_run(self):
        """Stopping should record completed lab run before cleanup."""
        r = make_reconciler()
        instance = make_instance(status="STOPPING", cml_lab_id="lab-abc")
        r._lab_run_started_at["inst-001"] = datetime(2024, 1, 1, tzinfo=timezone.utc)
        r._cml_labs.get_lab_state.return_value = LabState.STOPPED
        r._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-001", "lab_id": "lab-abc"},
        ]

        await r._handle_stopping(instance)

        r._api.record_lab_run_completed.assert_awaited()


# =============================================================================
# Phase 5: Port Registration & Tag Sync during Discovery (ADR-031)
# =============================================================================


class TestPortRegistrationResult:
    """Tests for the PortRegistrationResult data class."""

    def test_defaults_to_zero(self):
        """PortRegistrationResult should default all fields to zero."""
        result = PortRegistrationResult()
        assert result.ports_registered == 0
        assert result.tags_synced == 0
        assert result.errors == 0

    def test_custom_values(self):
        """PortRegistrationResult should accept custom values."""
        result = PortRegistrationResult(ports_registered=3, tags_synced=5, errors=1)
        assert result.ports_registered == 3
        assert result.tags_synced == 5
        assert result.errors == 1


class TestRegisterPortsAndSyncTags:
    """Tests for _register_ports_and_sync_tags (ADR-031 Phase 5)."""

    @pytest.mark.asyncio
    async def test_skips_when_no_booted_labs(self):
        """Should return empty result when no BOOTED/STARTED labs."""
        svc = make_lab_discovery_service()
        labs = [make_lab_info(state=LabState.STOPPED)]

        result = await svc._register_ports_and_sync_tags("worker-001", "10.0.0.1", labs)

        assert result.ports_registered == 0
        assert result.tags_synced == 0
        svc._api.get_lab_records_for_worker.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_when_labs_list_empty(self):
        """Should return empty result for empty labs list."""
        svc = make_lab_discovery_service()

        result = await svc._register_ports_and_sync_tags("worker-001", "10.0.0.1", [])

        assert result.ports_registered == 0
        svc._api.get_lab_records_for_worker.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handles_cpa_lab_records_failure(self):
        """Should return empty result when fetching lab records fails."""
        svc = make_lab_discovery_service()
        svc._api.get_lab_records_for_worker.side_effect = RuntimeError("CPA down")
        labs = [make_lab_info(state=LabState.BOOTED)]

        result = await svc._register_ports_and_sync_tags("worker-001", "10.0.0.1", labs)

        assert result.ports_registered == 0
        assert result.errors == 0  # Graceful return, not an error per-lab

    @pytest.mark.asyncio
    async def test_skips_lab_without_matching_record(self):
        """Should skip labs with no matching LabRecord."""
        svc = make_lab_discovery_service()
        svc._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-999", "lab_id": "other-lab"},
        ]
        labs = [make_lab_info(lab_id="lab-abc", state=LabState.BOOTED)]

        result = await svc._register_ports_and_sync_tags("worker-001", "10.0.0.1", labs)

        assert result.ports_registered == 0
        svc._api.allocate_lab_record_ports.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_lab_without_definition(self):
        """Should skip labs whose LabRecord has no based_on_definition_id."""
        svc = make_lab_discovery_service()
        svc._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-001", "lab_id": "lab-abc", "based_on_definition_id": None},
        ]
        labs = [make_lab_info(lab_id="lab-abc", state=LabState.BOOTED)]

        result = await svc._register_ports_and_sync_tags("worker-001", "10.0.0.1", labs)

        assert result.ports_registered == 0
        svc._api.allocate_lab_record_ports.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_allocates_ports_for_booted_lab_with_definition(self):
        """Should call allocate_lab_record_ports for BOOTED lab with definition."""
        svc = make_lab_discovery_service()
        svc._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-001", "lab_id": "lab-abc", "based_on_definition_id": "def-001"},
        ]
        svc._api.allocate_lab_record_ports.return_value = {
            "allocated_ports": {"router1_serial": 3001, "router1_vnc": 3002},
        }
        svc._cml_labs.get_lab_nodes.return_value = [
            NodeInfo(id="n0", label="router1", node_definition="iosv", state="BOOTED", tags=["serial:3001", "vnc:3002"]),
        ]
        labs = [make_lab_info(lab_id="lab-abc", state=LabState.BOOTED)]

        result = await svc._register_ports_and_sync_tags("worker-001", "10.0.0.1", labs)

        assert result.ports_registered == 1
        svc._api.allocate_lab_record_ports.assert_awaited_once_with(
            lab_record_id="rec-001",
            worker_id="worker-001",
        )

    @pytest.mark.asyncio
    async def test_processes_started_lab_same_as_booted(self):
        """Should also process STARTED labs (not just BOOTED)."""
        svc = make_lab_discovery_service()
        svc._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-001", "lab_id": "lab-abc", "based_on_definition_id": "def-001"},
        ]
        svc._api.allocate_lab_record_ports.return_value = {
            "allocated_ports": {"router1_serial": 3001},
        }
        svc._cml_labs.get_lab_nodes.return_value = [
            NodeInfo(id="n0", label="router1", node_definition="iosv", state="STARTED", tags=["serial:3001"]),
        ]
        labs = [make_lab_info(lab_id="lab-abc", state=LabState.STARTED)]

        result = await svc._register_ports_and_sync_tags("worker-001", "10.0.0.1", labs)

        assert result.ports_registered == 1

    @pytest.mark.asyncio
    async def test_handles_allocation_failure(self):
        """Should log warning and increment errors on allocation failure."""
        svc = make_lab_discovery_service()
        svc._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-001", "lab_id": "lab-abc", "based_on_definition_id": "def-001"},
        ]
        svc._api.allocate_lab_record_ports.side_effect = RuntimeError("etcd down")
        labs = [make_lab_info(lab_id="lab-abc", state=LabState.BOOTED)]

        result = await svc._register_ports_and_sync_tags("worker-001", "10.0.0.1", labs)

        assert result.ports_registered == 0
        assert result.errors == 1

    @pytest.mark.asyncio
    async def test_skips_when_no_ports_allocated(self):
        """Should skip tag sync when allocation returns empty ports."""
        svc = make_lab_discovery_service()
        svc._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-001", "lab_id": "lab-abc", "based_on_definition_id": "def-001"},
        ]
        svc._api.allocate_lab_record_ports.return_value = {
            "allocated_ports": {},
            "skipped": True,
            "reason": "no_port_template",
        }
        labs = [make_lab_info(lab_id="lab-abc", state=LabState.BOOTED)]

        result = await svc._register_ports_and_sync_tags("worker-001", "10.0.0.1", labs)

        assert result.ports_registered == 0
        svc._cml_labs.get_lab_nodes.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_idempotent_already_allocated(self):
        """Should count as registered even when ports already allocated."""
        svc = make_lab_discovery_service()
        svc._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-001", "lab_id": "lab-abc", "based_on_definition_id": "def-001"},
        ]
        svc._api.allocate_lab_record_ports.return_value = {
            "allocated_ports": {"router1_serial": 3001},
            "already_allocated": True,
        }
        svc._cml_labs.get_lab_nodes.return_value = [
            NodeInfo(id="n0", label="router1", node_definition="iosv", state="BOOTED", tags=["serial:3001"]),
        ]
        labs = [make_lab_info(lab_id="lab-abc", state=LabState.BOOTED)]

        result = await svc._register_ports_and_sync_tags("worker-001", "10.0.0.1", labs)

        assert result.ports_registered == 1
        # Tags already present — no patch needed
        assert result.tags_synced == 0


class TestSyncTagsIfMissing:
    """Tests for _sync_tags_if_missing (AD-TAGS-001)."""

    @pytest.mark.asyncio
    async def test_syncs_missing_tags(self):
        """Should PATCH node tags when port tags are missing."""
        svc = make_lab_discovery_service()
        svc._cml_labs.get_lab_nodes.return_value = [
            NodeInfo(id="n0", label="router1", node_definition="iosv", state="BOOTED", tags=[]),
        ]

        count = await svc._sync_tags_if_missing(
            host="10.0.0.1",
            lab_id="lab-abc",
            allocated_ports={"router1_serial": 3001, "router1_vnc": 3002},
        )

        assert count == 1
        svc._cml_labs.patch_node_tags.assert_awaited_once()
        call_kwargs = svc._cml_labs.patch_node_tags.call_args.kwargs
        assert call_kwargs["lab_id"] == "lab-abc"
        assert call_kwargs["node_id"] == "n0"
        assert "serial:3001" in call_kwargs["tags"]
        assert "vnc:3002" in call_kwargs["tags"]

    @pytest.mark.asyncio
    async def test_skips_when_tags_already_present(self):
        """Should NOT patch when all expected tags are already on the node."""
        svc = make_lab_discovery_service()
        svc._cml_labs.get_lab_nodes.return_value = [
            NodeInfo(id="n0", label="router1", node_definition="iosv", state="BOOTED", tags=["serial:3001", "vnc:3002"]),
        ]

        count = await svc._sync_tags_if_missing(
            host="10.0.0.1",
            lab_id="lab-abc",
            allocated_ports={"router1_serial": 3001, "router1_vnc": 3002},
        )

        assert count == 0
        svc._cml_labs.patch_node_tags.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_merges_existing_tags_with_port_tags(self):
        """Should preserve existing tags and add missing port tags."""
        svc = make_lab_discovery_service()
        svc._cml_labs.get_lab_nodes.return_value = [
            NodeInfo(id="n0", label="router1", node_definition="iosv", state="BOOTED", tags=["custom:tag"]),
        ]

        count = await svc._sync_tags_if_missing(
            host="10.0.0.1",
            lab_id="lab-abc",
            allocated_ports={"router1_serial": 3001},
        )

        assert count == 1
        call_kwargs = svc._cml_labs.patch_node_tags.call_args.kwargs
        assert "custom:tag" in call_kwargs["tags"]
        assert "serial:3001" in call_kwargs["tags"]

    @pytest.mark.asyncio
    async def test_handles_node_with_special_characters_in_label(self):
        """Should sanitize node labels with special characters."""
        svc = make_lab_discovery_service()
        svc._cml_labs.get_lab_nodes.return_value = [
            NodeInfo(id="n0", label="router 1", node_definition="iosv", state="BOOTED", tags=[]),
        ]

        count = await svc._sync_tags_if_missing(
            host="10.0.0.1",
            lab_id="lab-abc",
            allocated_ports={"router_1_serial": 3001},  # sanitized label
        )

        assert count == 1

    @pytest.mark.asyncio
    async def test_skips_nodes_without_matching_ports(self):
        """Should not patch nodes that have no allocated ports."""
        svc = make_lab_discovery_service()
        svc._cml_labs.get_lab_nodes.return_value = [
            NodeInfo(id="n0", label="switch1", node_definition="iosvl2", state="BOOTED", tags=[]),
            NodeInfo(id="n1", label="router1", node_definition="iosv", state="BOOTED", tags=[]),
        ]

        count = await svc._sync_tags_if_missing(
            host="10.0.0.1",
            lab_id="lab-abc",
            allocated_ports={"router1_serial": 3001},
        )

        assert count == 1
        call_kwargs = svc._cml_labs.patch_node_tags.call_args.kwargs
        assert call_kwargs["node_id"] == "n1"

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_allocated_ports(self):
        """Should return 0 when allocated_ports is empty."""
        svc = make_lab_discovery_service()

        count = await svc._sync_tags_if_missing(
            host="10.0.0.1",
            lab_id="lab-abc",
            allocated_ports={},
        )

        assert count == 0
        svc._cml_labs.get_lab_nodes.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_zero_for_unparseable_port_names(self):
        """Should return 0 when port names don't follow label_protocol convention."""
        svc = make_lab_discovery_service()

        count = await svc._sync_tags_if_missing(
            host="10.0.0.1",
            lab_id="lab-abc",
            allocated_ports={"badportname": 3001},
        )

        assert count == 0
        svc._cml_labs.get_lab_nodes.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_fatal_on_patch_failure(self):
        """AD-TAGS-001: Should log warning and continue on patch failure."""
        svc = make_lab_discovery_service()
        svc._cml_labs.get_lab_nodes.return_value = [
            NodeInfo(id="n0", label="router1", node_definition="iosv", state="BOOTED", tags=[]),
            NodeInfo(id="n1", label="switch1", node_definition="iosvl2", state="BOOTED", tags=[]),
        ]
        svc._cml_labs.patch_node_tags.side_effect = RuntimeError("CML PATCH not supported")

        count = await svc._sync_tags_if_missing(
            host="10.0.0.1",
            lab_id="lab-abc",
            allocated_ports={"router1_serial": 3001, "switch1_vnc": 3002},
        )

        # Both nodes failed, but no exception propagated
        assert count == 0
        assert svc._cml_labs.patch_node_tags.await_count == 2

    @pytest.mark.asyncio
    async def test_multiple_nodes_partial_sync(self):
        """Should sync only nodes with missing tags."""
        svc = make_lab_discovery_service()
        svc._cml_labs.get_lab_nodes.return_value = [
            NodeInfo(id="n0", label="router1", node_definition="iosv", state="BOOTED", tags=["serial:3001"]),
            NodeInfo(id="n1", label="switch1", node_definition="iosvl2", state="BOOTED", tags=[]),
        ]

        count = await svc._sync_tags_if_missing(
            host="10.0.0.1",
            lab_id="lab-abc",
            allocated_ports={"router1_serial": 3001, "switch1_vnc": 3002},
        )

        assert count == 1  # Only switch1 synced
        call_kwargs = svc._cml_labs.patch_node_tags.call_args.kwargs
        assert call_kwargs["node_id"] == "n1"
        assert "vnc:3002" in call_kwargs["tags"]


class TestDiscoveryPortRegistrationIntegration:
    """Integration tests: _discover_worker_labs with port registration."""

    @pytest.mark.asyncio
    async def test_discover_worker_labs_calls_port_registration(self):
        """_discover_worker_labs should call port registration after discovery."""
        svc = make_lab_discovery_service()
        worker = {"id": "worker-001", "public_ip": "10.0.0.1"}

        booted_lab = make_lab_info(lab_id="lab-abc", state=LabState.BOOTED)
        svc._cml_labs.list_labs.return_value = [booted_lab]
        svc._cml_labs.get_lab_nodes.return_value = []
        svc._cml_labs.get_lab_links.return_value = []
        svc._api.discover_lab_records.return_value = {"synced": 1, "discovered": 0}

        svc._api.get_lab_records_for_worker.return_value = [
            {"id": "rec-001", "lab_id": "lab-abc", "based_on_definition_id": "def-001"},
        ]
        svc._api.allocate_lab_record_ports.return_value = {
            "allocated_ports": {"router1_serial": 3001},
        }

        await svc._discover_worker_labs(worker)

        svc._api.allocate_lab_record_ports.assert_awaited_once()
        assert svc._total_ports_registered == 1

    @pytest.mark.asyncio
    async def test_port_registration_does_not_affect_discovery_result(self):
        """Port registration errors should not affect the discovery result."""
        svc = make_lab_discovery_service()
        worker = {"id": "worker-001", "public_ip": "10.0.0.1"}

        svc._cml_labs.list_labs.return_value = [make_lab_info(state=LabState.BOOTED)]
        svc._cml_labs.get_lab_nodes.return_value = []
        svc._cml_labs.get_lab_links.return_value = []
        svc._api.discover_lab_records.return_value = {"synced": 1, "discovered": 1}
        svc._api.get_lab_records_for_worker.side_effect = RuntimeError("CPA down")

        result = await svc._discover_worker_labs(worker)

        # Discovery result unaffected by port registration failure
        assert result.synced == 1
        assert result.discovered == 1

    @pytest.mark.asyncio
    async def test_stats_include_port_and_tag_counts(self):
        """get_stats should include port registration and tag sync totals."""
        svc = make_lab_discovery_service()
        svc._total_ports_registered = 5
        svc._total_tags_synced = 12

        stats = svc.get_stats()

        assert stats["total_ports_registered"] == 5
        assert stats["total_tags_synced"] == 12
