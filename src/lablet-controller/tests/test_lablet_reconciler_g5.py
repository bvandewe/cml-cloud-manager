"""Unit tests for LabletReconciler — G5 Comprehensive Coverage.

Covers the full lablet session lifecycle state machine (canonical):
- reconcile() router: status routing, worker validation, unknown status
- State handlers: SCHEDULED → INSTANTIATING → READY → RUNNING → STOPPING → ARCHIVED
- LDS provisioning: _provision_lds_session (8-step flow with UserSession)
- Device mapping: _build_device_access_list (static, tag parsing)
- Definition cache: _get_definition (cache hit/miss)
- Session archival: _archive_lds_session (graceful error handling)

Pattern: Uses object.__new__(LabletReconciler) to bypass complex __init__,
matching the fixture pattern from worker-controller G4 tests.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lcm_core.domain.entities import LabletSessionReadModel
from lcm_core.domain.entities.read_models.lablet_definition_read_model import LabletDefinitionReadModel
from lcm_core.domain.enums import LabletSessionStatus
from lcm_core.infrastructure.hosted_services.reconciliation_hosted_service import ReconciliationStatus

from application.hosted_services.lablet_reconciler import LabletReconciler
from application.services.pipeline_executor import PipelineExecutor
from integration.services.cml_labs_spi import LabInfo, LabState, NodeInfo
from integration.services.lds_spi import DeviceAccessInfo, LdsSessionInfo, LdsSpiError

# =============================================================================
# Fixtures
# =============================================================================


def make_instance(
    instance_id: str = "inst-001",
    name: str = "test-lablet",
    definition_id: str = "def-001",
    status: str = "SCHEDULED",
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


def make_reconciler() -> LabletReconciler:
    """Create a LabletReconciler bypassing __init__ (no etcd/leader election needed)."""
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
    # P9 additions: reuse, binding, and run tracking
    r._labs_reused = 0
    r._bindings_created = 0
    r._bindings_released = 0
    r._runs_recorded = 0
    r._lab_run_started_at = {}
    r._resolved_lab_ids = {}
    r._freshly_imported_sessions = set()
    r._worker_cache = {}
    r._resource_observer = None
    r._content_sync_service = None
    # Sprint C additions
    r._session_locks = {}
    r._active_handlers = {}
    r._pipeline_executor = PipelineExecutor()
    r._pipeline_retry_counts = {}
    return r


def make_definition(
    definition_id: str = "def-001",
    name: str = "Test Definition",
    form_qualified_name: str | None = "org/project/form",
) -> LabletDefinitionReadModel:
    """Create a LabletDefinitionReadModel for testing."""
    return LabletDefinitionReadModel(
        id=definition_id,
        name=name,
        form_qualified_name=form_qualified_name,
    )


def _progress_with_lab_resolve(
    cml_lab_id: str = "lab-abc",
    lab_record_id: str | None = None,
) -> dict:
    """Build a progress dict where lab_resolve is completed — for testing downstream steps."""
    result_data = {"cml_lab_id": cml_lab_id}
    if lab_record_id:
        result_data["lab_record_id"] = lab_record_id
    return {
        "steps": [
            {"step": "content_sync", "requires": [], "status": "skipped"},
            {"step": "variables", "requires": [], "status": "skipped"},
            {
                "step": "lab_resolve",
                "requires": ["content_sync", "variables"],
                "status": "completed",
                "result_data": result_data,
            },
            {"step": "ports_alloc", "requires": ["lab_resolve"], "status": "skipped"},
            {"step": "tags_sync", "requires": ["ports_alloc"], "status": "skipped"},
            {"step": "lab_binding", "requires": ["lab_resolve", "tags_sync"], "status": "completed"},
            {"step": "lab_start", "requires": ["lab_binding"], "status": "pending"},
            {"step": "lds_provision", "requires": ["lab_start"], "status": "pending"},
            {"step": "mark_ready", "requires": ["lds_provision"], "status": "pending"},
        ],
        "pipeline_version": "1.0",
    }


def make_node(
    node_id: str = "n0",
    label: str = "router1",
    node_definition: str = "iosv",
    state: str = "BOOTED",
    tags: list[str] | None = None,
) -> NodeInfo:
    """Create a NodeInfo for testing."""
    return NodeInfo(
        id=node_id,
        label=label,
        node_definition=node_definition,
        state=state,
        tags=tags,
    )


def make_lab_info(
    lab_id: str = "lab-abc",
    title: str = "Test Lab",
    state: LabState = LabState.STARTED,
) -> LabInfo:
    """Create a LabInfo for testing."""
    return LabInfo(id=lab_id, title=title, state=state)


# =============================================================================
# reconcile() Router Tests
# =============================================================================


class TestReconcileRouter:
    """Tests for reconcile() status routing and validation."""

    @pytest.mark.asyncio
    async def test_unassigned_worker_for_active_status_fails(self):
        """Instance in INSTANTIATING without worker_id should fail."""
        r = make_reconciler()
        instance = make_instance(status="INSTANTIATING", worker_id=None, worker_ip=None)

        result = await r.reconcile(instance)

        assert result.status == ReconciliationStatus.FAILED

    @pytest.mark.asyncio
    async def test_unassigned_worker_for_non_active_status_succeeds(self):
        """Instance in SCHEDULED without worker can still succeed (no worker needed yet)."""
        r = make_reconciler()
        instance = make_instance(status="SCHEDULED", worker_id=None, worker_ip=None, timeslot_start=None)

        result = await r.reconcile(instance)

        assert result.status == ReconciliationStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_unknown_status_returns_success(self):
        """Unknown status should be logged and return success (no-op)."""
        r = make_reconciler()
        instance = make_instance(status="SOME_UNKNOWN_STATE")

        result = await r.reconcile(instance)

        assert result.status == ReconciliationStatus.SUCCESS

    @pytest.mark.skip(reason="ADR-034 Sprint C: _handle_instantiating refactored to fire-and-check. See test_instantiation_pipeline.py.")
    @pytest.mark.asyncio
    async def test_exception_in_handler_returns_failed(self):
        """Exception during pipeline step should be caught and return REQUEUE (with failed step)."""
        r = make_reconciler()
        # Provide progress with lab_start as the next step (lab_resolve + lab_binding done)
        instance = make_instance(
            status="INSTANTIATING",
            pipeline_progress={
                "instantiate": {
                    "content_sync": {"status": "skipped", "order": 1},
                    "variables": {"status": "skipped", "order": 2},
                    "lab_resolve": {"status": "completed", "order": 3, "result_data": {"cml_lab_id": "lab-abc", "lab_record_id": "rec-001"}},
                    "ports_alloc": {"status": "skipped", "order": 4},
                    "tags_sync": {"status": "skipped", "order": 5},
                    "lab_binding": {"status": "completed", "order": 6},
                    "lab_start": {"status": "pending", "order": 7},
                    "lds_provision": {"status": "pending", "order": 8},
                    "mark_ready": {"status": "pending", "order": 9},
                }
            },
        )
        r._cml_labs.get_lab_state = AsyncMock(side_effect=RuntimeError("network error"))

        result = await r.reconcile(instance)

        # Pipeline catches the exception and persists a failed step — returns REQUEUE
        assert result.status == ReconciliationStatus.REQUEUE
        r._api.update_pipeline_progress.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_running_status_no_worker_ip_fails(self):
        """RUNNING instance with worker_id but no worker_ip should fail."""
        r = make_reconciler()
        instance = make_instance(status="RUNNING", worker_id="w-1", worker_ip=None)

        result = await r.reconcile(instance)

        assert result.status == ReconciliationStatus.FAILED


# =============================================================================
# _handle_scheduled Tests
# =============================================================================


class TestHandleScheduled:
    """Tests for SCHEDULED → INSTANTIATING transition."""

    @pytest.mark.asyncio
    async def test_no_timeslot_start_transitions_immediately(self):
        """No timeslot_start means on-demand — transition to INSTANTIATING immediately."""
        r = make_reconciler()
        instance = make_instance(status="SCHEDULED", timeslot_start=None)

        result = await r._handle_scheduled(instance)

        assert result.status == ReconciliationStatus.REQUEUE
        r._api.start_instantiation.assert_awaited_once_with(
            session_id="inst-001",
        )

    @pytest.mark.asyncio
    async def test_within_boot_window_transitions(self):
        """Start time within boot window should transition to INSTANTIATING."""
        r = make_reconciler()
        r._api.get_lablet_definition.return_value = None  # Use global boot window
        # Boot window = 20 min, scheduled in 10 min → should trigger
        scheduled = datetime.now(timezone.utc) + timedelta(minutes=10)
        instance = make_instance(status="SCHEDULED", timeslot_start=scheduled)

        result = await r._handle_scheduled(instance)

        assert result.status == ReconciliationStatus.REQUEUE
        r._api.start_instantiation.assert_awaited_once_with(
            session_id="inst-001",
        )

    @pytest.mark.asyncio
    async def test_outside_boot_window_stays_scheduled(self):
        """Start time far in the future should not trigger transition."""
        r = make_reconciler()
        r._api.get_lablet_definition.return_value = None  # Use global boot window
        # Boot window = 20 min, scheduled in 60 min → should NOT trigger
        scheduled = datetime.now(timezone.utc) + timedelta(minutes=60)
        instance = make_instance(status="SCHEDULED", timeslot_start=scheduled)

        result = await r._handle_scheduled(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        r._api.start_instantiation.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_timeslot_start_as_string_parsed(self):
        """timeslot_start as ISO string should be parsed correctly."""
        r = make_reconciler()
        r._api.get_lablet_definition.return_value = None  # Use global boot window
        # Within boot window (5 minutes from now)
        scheduled = datetime.now(timezone.utc) + timedelta(minutes=5)
        instance = make_instance(
            status="SCHEDULED",
            timeslot_start=scheduled.isoformat(),
        )

        result = await r._handle_scheduled(instance)

        assert result.status == ReconciliationStatus.REQUEUE


# =============================================================================
# _handle_instantiating Tests
# =============================================================================


@pytest.mark.skip(reason="ADR-034 Sprint C: _handle_instantiating refactored to fire-and-check delegation. See test_instantiation_pipeline.py.")
class TestHandleInstantiating:
    """Tests for INSTANTIATING state — DAG-based pipeline executor (ADR-031)."""

    @pytest.mark.asyncio
    async def test_no_progress_bootstraps_pipeline(self):
        """No pipeline_progress should trigger pipeline bootstrap."""
        r = make_reconciler()
        instance = make_instance(status="INSTANTIATING")
        r._definition_cache["def-001"] = make_definition()

        result = await r._handle_instantiating(instance)

        assert result.status == ReconciliationStatus.REQUEUE
        r._api.update_pipeline_progress.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_topology_yaml_fails_in_lab_resolve(self):
        """Missing topology YAML (both instance and definition) should fail _step_lab_resolve."""
        r = make_reconciler()
        # Definition has no topology fields
        definition = make_definition()
        definition.cml_yaml_content = None
        definition.topology_yaml = None
        r._definition_cache["def-001"] = definition

        instance = make_instance(status="INSTANTIATING", topology_yaml=None)
        progress = LabletReconciler._build_default_progress()

        result = await r._step_lab_resolve(instance, progress)

        assert result["status"] == "failed"
        assert "No topology YAML" in result["error"]

    @pytest.mark.asyncio
    async def test_no_lab_id_imports_lab(self):
        """No cml_lab_id should trigger lab import via _step_lab_resolve."""
        r = make_reconciler()
        instance = make_instance(
            status="INSTANTIATING",
            cml_lab_id=None,
            topology_yaml="nodes:\n  - label: router1",
        )
        r._api.get_lablet_definition.return_value = None
        r._cml_labs.import_lab.return_value = "lab-new-123"
        r._api.get_lab_records_for_worker.return_value = []

        progress = LabletReconciler._build_default_progress()
        result = await r._step_lab_resolve(instance, progress)

        assert result["status"] == "completed"
        assert result["result_data"]["cml_lab_id"] == "lab-new-123"
        r._cml_labs.import_lab.assert_awaited_once()
        assert r._labs_imported == 1

    @pytest.mark.asyncio
    async def test_import_failure_returns_failed_step(self):
        """Failed lab import should return failed step result."""
        r = make_reconciler()
        instance = make_instance(
            status="INSTANTIATING",
            cml_lab_id=None,
            topology_yaml="nodes:\n  - label: router1",
        )
        r._api.get_lablet_definition.return_value = None
        r._cml_labs.import_lab.side_effect = RuntimeError("CML import failed")

        progress = LabletReconciler._build_default_progress()
        result = await r._step_lab_resolve(instance, progress)

        assert result["status"] == "failed"
        assert "unable to import" in result["error"]

    @pytest.mark.asyncio
    async def test_lab_started_converged_completes_lab_start_step(self):
        """STARTED+converged lab should complete the lab_start step."""
        r = make_reconciler()
        instance = make_instance(status="INSTANTIATING")
        r._cml_labs.get_lab_state.return_value = LabState.STARTED
        r._cml_labs.check_if_converged.return_value = True

        progress = _progress_with_lab_resolve(cml_lab_id="lab-abc")
        result = await r._step_lab_start(instance, progress)

        assert result["status"] == "completed"
        assert result["result_data"]["lab_state"] == "CONVERGED"

    @pytest.mark.asyncio
    async def test_lab_stopped_starts_lab(self):
        """STOPPED lab should start and fail on next poll (unexpected state)."""
        r = make_reconciler()
        instance = make_instance(status="INSTANTIATING")
        r._cml_labs.get_lab_state.return_value = LabState.STOPPED
        progress = _progress_with_lab_resolve(cml_lab_id="lab-abc", lab_record_id="rec-001")

        with patch("application.hosted_services.lablet_reconciler.asyncio.sleep", new_callable=AsyncMock):
            result = await r._step_lab_start(instance, progress)

        # Returns failed (STOPPED is unexpected in polling loop)
        assert result["status"] == "failed"
        r._cml_labs.start_lab.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lab_defined_on_core_starts_lab(self):
        """DEFINED_ON_CORE lab should be started."""
        r = make_reconciler()
        instance = make_instance(status="INSTANTIATING")
        r._cml_labs.get_lab_state.return_value = LabState.DEFINED_ON_CORE
        progress = _progress_with_lab_resolve(cml_lab_id="lab-abc")

        with patch("application.hosted_services.lablet_reconciler.asyncio.sleep", new_callable=AsyncMock):
            result = await r._step_lab_start(instance, progress)

        assert result["status"] == "failed"  # DEFINED_ON_CORE unexpected in polling
        r._cml_labs.start_lab.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lab_started_not_converged_polls_until_converged(self):
        """STARTED but not converged should poll until convergence."""
        r = make_reconciler()
        instance = make_instance(status="INSTANTIATING")
        r._cml_labs.get_lab_state.return_value = LabState.STARTED
        # First check (early path): not converged; second check (poll): converged
        r._cml_labs.check_if_converged.side_effect = [False, True]
        progress = _progress_with_lab_resolve(cml_lab_id="lab-abc")

        with patch("application.hosted_services.lablet_reconciler.asyncio.sleep", new_callable=AsyncMock):
            result = await r._step_lab_start(instance, progress)

        assert result["status"] == "completed"
        assert result["result_data"]["lab_state"] == "CONVERGED"
        r._cml_labs.start_lab.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_lab_queued_polls_until_started_and_converged(self):
        """QUEUED lab should poll until STARTED+converged."""
        r = make_reconciler()
        instance = make_instance(status="INSTANTIATING")
        # Initial call: QUEUED, poll1: QUEUED (continue), poll2: STARTED
        r._cml_labs.get_lab_state.side_effect = [LabState.QUEUED, LabState.QUEUED, LabState.STARTED]
        r._cml_labs.check_if_converged.return_value = True
        progress = _progress_with_lab_resolve(cml_lab_id="lab-abc")

        with patch("application.hosted_services.lablet_reconciler.asyncio.sleep", new_callable=AsyncMock):
            result = await r._step_lab_start(instance, progress)

        assert result["status"] == "completed"
        assert result["result_data"]["lab_state"] == "CONVERGED"
        r._cml_labs.start_lab.assert_not_awaited()


# =============================================================================
# _provision_lds_session Tests
# =============================================================================


class TestProvisionLdsSession:
    """Tests for the 7-step LDS provisioning flow."""

    @pytest.mark.asyncio
    async def test_happy_path_full_provisioning(self):
        """Complete provisioning: definition → nodes → session → devices → URL → ready."""
        r = make_reconciler()
        instance = make_instance(
            status="INSTANTIATING",
            cml_lab_id="lab-abc",
            worker_ip="10.0.0.1",
            worker_aws_region="us-east-1",
        )

        # Step 1: Definition lookup
        definition = make_definition(form_qualified_name="cisco/ccna/form1")
        r._definition_cache["def-001"] = definition

        # Step 2: Get nodes
        nodes = [
            make_node(node_id="n0", label="router1", tags=["ssh:22", "serial:5041"]),
            make_node(node_id="n1", label="switch1", tags=["ssh:22"]),
        ]
        r._cml_labs.get_lab_nodes.return_value = nodes

        # Step 3: Create LDS session
        session_info = LdsSessionInfo(session_id="sess-123", login_url="", status="active")
        r._lds.create_session.return_value = session_info

        # Step 6: Get launch URL
        r._lds.get_lablet_launch_url.return_value = "https://lds.example.com/lab/sess-123"

        # Step 7: Create user session via CPA
        r._api.create_user_session.return_value = {"id": "us-001", "session_id": "inst-001"}

        result = await r._provision_lds_session(instance, "lab-abc")

        assert result.status == ReconciliationStatus.SUCCESS

        # Verify all steps executed
        r._cml_labs.get_lab_nodes.assert_awaited_once()
        r._lds.create_session.assert_awaited_once()
        r._lds.set_devices.assert_awaited_once()
        r._lds.get_lablet_launch_url.assert_awaited_once()
        r._api.create_user_session.assert_awaited_once_with(
            session_id="inst-001",
            lds_session_id="sess-123",
            lds_login_url="https://lds.example.com/lab/sess-123",
            cml_lab_id="lab-abc",
        )
        r._api.mark_session_ready.assert_awaited_once_with(
            session_id="inst-001",
            user_session_id="us-001",
            cml_lab_id="lab-abc",
        )

        # Counters updated
        assert r._lds_sessions_created == 1
        assert r._labs_started == 1

    @pytest.mark.asyncio
    async def test_definition_not_found_fails(self):
        """Missing definition should fail provisioning."""
        r = make_reconciler()
        instance = make_instance(status="INSTANTIATING")
        r._api.get_lablet_definition.return_value = None  # no definition

        result = await r._provision_lds_session(instance, "lab-abc")

        assert result.status == ReconciliationStatus.FAILED
        r._lds.create_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_definition_no_form_qualified_name_fails(self):
        """Definition without form_qualified_name should fail."""
        r = make_reconciler()
        instance = make_instance(status="INSTANTIATING")
        # Cache a definition without form_qualified_name
        r._definition_cache["def-001"] = make_definition(form_qualified_name=None)

        result = await r._provision_lds_session(instance, "lab-abc")

        assert result.status == ReconciliationStatus.FAILED

    @pytest.mark.asyncio
    async def test_lds_error_returns_failed(self):
        """LdsSpiError during provisioning should return FAILED."""
        r = make_reconciler()
        instance = make_instance(status="INSTANTIATING")
        r._definition_cache["def-001"] = make_definition()
        r._cml_labs.get_lab_nodes.return_value = []
        r._lds.create_session.side_effect = LdsSpiError("LDS unavailable")

        result = await r._provision_lds_session(instance, "lab-abc")

        assert result.status == ReconciliationStatus.FAILED

    @pytest.mark.asyncio
    async def test_no_devices_skips_set_devices(self):
        """When no devices (no nodes with tags), set_devices should be skipped."""
        r = make_reconciler()
        instance = make_instance(status="INSTANTIATING", worker_ip="10.0.0.1", worker_aws_region="us-east-1")
        r._definition_cache["def-001"] = make_definition()

        # Nodes without tags → empty device list
        r._cml_labs.get_lab_nodes.return_value = [make_node(tags=None)]
        session_info = LdsSessionInfo(session_id="sess-456", login_url="", status="active")
        r._lds.create_session.return_value = session_info
        r._lds.get_lablet_launch_url.return_value = "https://lds.example.com/lab/sess-456"
        r._api.create_user_session.return_value = {"id": "us-002", "session_id": "inst-001"}

        result = await r._provision_lds_session(instance, "lab-abc")

        assert result.status == ReconciliationStatus.SUCCESS
        r._lds.set_devices.assert_not_awaited()  # Skipped because no devices


# =============================================================================
# _handle_ready Tests
# =============================================================================


class TestHandleReady:
    """Tests for READY state — verify lab is still BOOTED."""

    @pytest.mark.asyncio
    async def test_no_cml_lab_id_fails(self):
        """READY instance without lab ID should fail."""
        r = make_reconciler()
        instance = make_instance(status="READY", cml_lab_id=None)

        result = await r._handle_ready(instance)

        assert result.status == ReconciliationStatus.FAILED

    @pytest.mark.asyncio
    async def test_lab_started_returns_success(self):
        """Lab STARTED in READY state returns success."""
        r = make_reconciler()
        instance = make_instance(status="READY")
        r._cml_labs.get_lab_state.return_value = LabState.STARTED

        result = await r._handle_ready(instance)

        assert result.status == ReconciliationStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_lab_not_started_still_succeeds(self):
        """Lab unexpectedly not STARTED in READY state still returns success (warns only)."""
        r = make_reconciler()
        instance = make_instance(status="READY")
        r._cml_labs.get_lab_state.return_value = LabState.STOPPED

        result = await r._handle_ready(instance)

        assert result.status == ReconciliationStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_lab_state_error_still_succeeds(self):
        """Error checking lab state in READY doesn't fail (graceful)."""
        r = make_reconciler()
        instance = make_instance(status="READY")
        r._cml_labs.get_lab_state.side_effect = RuntimeError("timeout")

        result = await r._handle_ready(instance)

        assert result.status == ReconciliationStatus.SUCCESS


# =============================================================================
# _handle_running Tests
# =============================================================================


class TestHandleRunning:
    """Tests for RUNNING state — timeslot checks and lab sync."""

    @pytest.mark.asyncio
    async def test_no_cml_lab_id_fails(self):
        """RUNNING instance without lab ID should fail."""
        r = make_reconciler()
        instance = make_instance(status="RUNNING", cml_lab_id=None)

        result = await r._handle_running(instance)

        assert result.status == ReconciliationStatus.FAILED

    @pytest.mark.asyncio
    async def test_timeslot_ended_transitions_to_stopping(self):
        """Past timeslot_end should transition to STOPPING."""
        r = make_reconciler()
        instance = make_instance(
            status="RUNNING",
            timeslot_end=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        r._cml_labs.get_lab_state.return_value = LabState.STARTED

        result = await r._handle_running(instance)

        assert result.status == ReconciliationStatus.REQUEUE
        r._api.transition_session.assert_awaited_once_with(
            session_id="inst-001",
            new_status=LabletSessionStatus.STOPPING,
            reason="Timeslot ended",
        )

    @pytest.mark.asyncio
    async def test_timeslot_active_syncs_state(self):
        """Active timeslot should sync lab state and return success."""
        r = make_reconciler()
        instance = make_instance(
            status="RUNNING",
            timeslot_end=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        r._cml_labs.get_lab_state.return_value = LabState.STARTED

        result = await r._handle_running(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert r._lab_sync_count == 1

    @pytest.mark.asyncio
    async def test_no_timeslot_end_syncs_normally(self):
        """No timeslot_end should still sync lab state."""
        r = make_reconciler()
        instance = make_instance(status="RUNNING", timeslot_end=None)
        r._cml_labs.get_lab_state.return_value = LabState.STARTED

        result = await r._handle_running(instance)

        assert result.status == ReconciliationStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_timeslot_end_as_string_parsed(self):
        """timeslot_end as ISO string should be parsed correctly."""
        r = make_reconciler()
        past_end = datetime.now(timezone.utc) - timedelta(minutes=1)
        instance = make_instance(
            status="RUNNING",
            timeslot_end=past_end.isoformat(),
        )

        result = await r._handle_running(instance)

        assert result.status == ReconciliationStatus.REQUEUE

    @pytest.mark.asyncio
    async def test_sync_error_still_succeeds(self):
        """Error during lab state sync doesn't fail (graceful)."""
        r = make_reconciler()
        instance = make_instance(status="RUNNING", timeslot_end=None)
        r._cml_labs.get_lab_state.side_effect = RuntimeError("timeout")

        result = await r._handle_running(instance)

        assert result.status == ReconciliationStatus.SUCCESS


# =============================================================================
# _handle_stopping Tests
# =============================================================================


@pytest.mark.skip(reason="ADR-034 Sprint D: _handle_stopping refactored to fire-and-check delegation. See test_teardown_pipeline.py.")
class TestHandleStopping:
    """Tests for STOPPING state — archive LDS, stop/wipe/delete lab, transition to ARCHIVED."""

    @pytest.mark.asyncio
    async def test_no_cml_lab_id_marks_archived(self):
        """No lab ID → archive LDS (if any) and mark ARCHIVED."""
        r = make_reconciler()
        instance = make_instance(status="STOPPING", cml_lab_id=None, lds_session_id=None)

        result = await r._handle_stopping(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        r._api.transition_session.assert_awaited_once_with(
            session_id="inst-001",
            new_status=LabletSessionStatus.ARCHIVED,
            reason="No lab to clean up",
        )

    @pytest.mark.asyncio
    async def test_lab_stopped_wipes_and_archives(self):
        """Stopped lab should be wiped (for reuse, not deleted) and marked ARCHIVED."""
        r = make_reconciler()
        instance = make_instance(status="STOPPING")
        r._cml_labs.get_lab_state.return_value = LabState.STOPPED

        result = await r._handle_stopping(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        r._cml_labs.wipe_lab.assert_awaited_once()
        r._cml_labs.delete_lab.assert_not_awaited()  # P9: wipe only, keep for reuse
        r._api.transition_session.assert_awaited_once_with(
            session_id="inst-001",
            new_status=LabletSessionStatus.ARCHIVED,
            reason="Lab wiped and available for reuse",
        )
        assert r._labs_stopped == 1

    @pytest.mark.asyncio
    async def test_lab_defined_on_core_wipes_and_archives(self):
        """DEFINED_ON_CORE is also treated as stopped — wipe for reuse (no delete)."""
        r = make_reconciler()
        instance = make_instance(status="STOPPING")
        r._cml_labs.get_lab_state.return_value = LabState.DEFINED_ON_CORE

        result = await r._handle_stopping(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        r._cml_labs.wipe_lab.assert_awaited_once()
        r._cml_labs.delete_lab.assert_not_awaited()  # P9: wipe only, keep for reuse

    @pytest.mark.asyncio
    async def test_lab_started_stops_first(self):
        """STARTED (running) lab should be stopped and requeued."""
        r = make_reconciler()
        instance = make_instance(status="STOPPING")
        r._cml_labs.get_lab_state.return_value = LabState.STARTED

        result = await r._handle_stopping(instance)

        assert result.status == ReconciliationStatus.REQUEUE
        r._cml_labs.stop_lab.assert_awaited_once()
        r._cml_labs.wipe_lab.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_lab_in_transition_requeues(self):
        """Lab in STARTED state (transitioning) should requeue."""
        r = make_reconciler()
        instance = make_instance(status="STOPPING")
        r._cml_labs.get_lab_state.return_value = LabState.STARTED

        result = await r._handle_stopping(instance)

        assert result.status == ReconciliationStatus.REQUEUE
        r._cml_labs.stop_lab.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_lds_archive_failure_does_not_block_cleanup(self):
        """LDS archive failure should not prevent lab cleanup."""
        r = make_reconciler()
        instance = make_instance(
            status="STOPPING",
            lds_session_id="sess-old",
        )
        r._lds.archive_session.side_effect = LdsSpiError("LDS down")
        r._cml_labs.get_lab_state.return_value = LabState.STOPPED

        result = await r._handle_stopping(instance)

        # Cleanup still succeeds despite LDS failure
        assert result.status == ReconciliationStatus.SUCCESS
        r._cml_labs.wipe_lab.assert_awaited_once()
        r._cml_labs.delete_lab.assert_not_awaited()  # P9: wipe only, keep for reuse

    @pytest.mark.asyncio
    async def test_cleanup_error_returns_failed(self):
        """Error during lab cleanup returns FAILED."""
        r = make_reconciler()
        instance = make_instance(status="STOPPING")
        r._cml_labs.get_lab_state.return_value = LabState.STOPPED
        r._cml_labs.wipe_lab.side_effect = RuntimeError("CML API error")

        result = await r._handle_stopping(instance)

        assert result.status == ReconciliationStatus.FAILED


# =============================================================================
# _build_device_access_list Tests (Static Method)
# =============================================================================


class TestBuildDeviceAccessList:
    """Tests for static device mapping from CML nodes to LDS devices."""

    def test_nodes_with_valid_tags(self):
        """Nodes with protocol:port tags should produce DeviceAccessInfo entries.

        Multi-tag nodes get _{protocol} suffix to satisfy LDS unique constraint
        on (session_part_id, device_label). Single-tag nodes keep plain label.
        """
        nodes = [
            make_node(label="router1", tags=["ssh:22", "serial:5041"]),
            make_node(label="switch1", tags=["vnc:5044"]),
        ]

        devices = LabletReconciler._build_device_access_list(nodes, "10.0.0.1")

        assert len(devices) == 3
        # router1 has 2 valid tags → suffixed labels
        assert devices[0] == DeviceAccessInfo(device_label="router1_ssh", protocol="ssh", host="10.0.0.1", port=22)
        assert devices[1] == DeviceAccessInfo(device_label="router1_serial", protocol="serial", host="10.0.0.1", port=5041)
        # switch1 has 1 valid tag → plain label
        assert devices[2] == DeviceAccessInfo(device_label="switch1", protocol="vnc", host="10.0.0.1", port=5044)

    def test_nodes_without_tags_skipped(self):
        """Nodes without tags should produce no devices."""
        nodes = [make_node(tags=None), make_node(tags=[])]

        devices = LabletReconciler._build_device_access_list(nodes, "10.0.0.1")

        assert len(devices) == 0

    def test_invalid_port_skipped(self):
        """Tags with non-numeric port should be skipped (only 1 valid → plain label)."""
        nodes = [make_node(label="router1", tags=["ssh:abc", "vnc:5044"])]

        devices = LabletReconciler._build_device_access_list(nodes, "10.0.0.1")

        assert len(devices) == 1
        assert devices[0].device_label == "router1"  # single valid tag → plain label
        assert devices[0].protocol == "vnc"
        assert devices[0].port == 5044

    def test_tag_without_colon_skipped(self):
        """Tags without colon separator should be skipped."""
        nodes = [make_node(label="router1", tags=["some-label", "ssh:22"])]

        devices = LabletReconciler._build_device_access_list(nodes, "10.0.0.1")

        assert len(devices) == 1
        assert devices[0].protocol == "ssh"

    def test_empty_nodes_list(self):
        """Empty node list should produce empty device list."""
        devices = LabletReconciler._build_device_access_list([], "10.0.0.1")

        assert devices == []

    def test_mixed_valid_and_invalid_tags(self):
        """Mix of valid and invalid tags should only produce valid devices.

        2 valid tags remain after filtering → suffixed labels.
        """
        nodes = [
            make_node(label="r1", tags=["ssh:22", "badtag", "vnc:notaport", "telnet:2023"]),
        ]

        devices = LabletReconciler._build_device_access_list(nodes, "192.168.1.1")

        assert len(devices) == 2
        labels = {d.device_label for d in devices}
        assert labels == {"r1_ssh", "r1_telnet"}
        protocols = [d.protocol for d in devices]
        assert "ssh" in protocols
        assert "telnet" in protocols

    def test_device_labels_unique_for_multi_tag_node(self):
        """Regression: LDS requires unique device_label per session part.

        A node with multiple protocol tags (e.g., ubuntu-desktop with serial + vnc)
        must produce distinct device_labels to avoid LDS UniqueViolation.
        """
        nodes = [
            make_node(label="ubuntu-desktop", tags=["serial:5041", "vnc:5044"]),
        ]

        devices = LabletReconciler._build_device_access_list(nodes, "98.93.120.155")

        assert len(devices) == 2
        labels = [d.device_label for d in devices]
        # All labels must be unique
        assert len(labels) == len(set(labels)), f"Duplicate device_labels: {labels}"
        assert "ubuntu-desktop_serial" in labels
        assert "ubuntu-desktop_vnc" in labels


# =============================================================================
# _get_definition Tests
# =============================================================================


class TestGetDefinition:
    """Tests for definition caching and fetch."""

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        """Cached definition should be returned without API call."""
        r = make_reconciler()
        cached_def = make_definition()
        r._definition_cache["def-001"] = cached_def

        result = await r._get_definition("def-001")

        assert result is cached_def
        r._api.get_lablet_definition.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cache_miss_fetches_and_caches(self):
        """Cache miss should fetch from API and cache result."""
        r = make_reconciler()
        r._api.get_lablet_definition.return_value = {
            "id": "def-002",
            "name": "New Def",
            "form_qualified_name": "org/proj/form",
        }

        result = await r._get_definition("def-002")

        assert result is not None
        assert result.id == "def-002"
        assert result.form_qualified_name == "org/proj/form"
        assert "def-002" in r._definition_cache

    @pytest.mark.asyncio
    async def test_api_returns_none(self):
        """API returning None should return None without caching."""
        r = make_reconciler()
        r._api.get_lablet_definition.return_value = None

        result = await r._get_definition("def-missing")

        assert result is None
        assert "def-missing" not in r._definition_cache

    @pytest.mark.asyncio
    async def test_api_error_returns_none(self):
        """API error should return None (graceful)."""
        r = make_reconciler()
        r._api.get_lablet_definition.side_effect = RuntimeError("API down")

        result = await r._get_definition("def-err")

        assert result is None


# =============================================================================
# _archive_lds_session Tests
# =============================================================================


class TestArchiveLdsSession:
    """Tests for graceful LDS session archival."""

    @pytest.mark.asyncio
    async def test_no_session_id_skips(self):
        """No lds_session_id should skip archival."""
        r = make_reconciler()
        instance = make_instance(lds_session_id=None)

        await r._archive_lds_session(instance)

        r._lds.archive_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_successful_archive(self):
        """Successful archival should increment counter."""
        r = make_reconciler()
        instance = make_instance(lds_session_id="sess-123", worker_aws_region="us-east-1")

        await r._archive_lds_session(instance)

        r._lds.archive_session.assert_awaited_once_with(
            session_id="sess-123",
            region="us-east-1",
        )
        assert r._lds_sessions_archived == 1

    @pytest.mark.asyncio
    async def test_lds_error_is_swallowed(self):
        """LdsSpiError should be caught and logged, not propagated."""
        r = make_reconciler()
        instance = make_instance(lds_session_id="sess-fail")
        r._lds.archive_session.side_effect = LdsSpiError("session not found")

        # Should NOT raise
        await r._archive_lds_session(instance)

        assert r._lds_sessions_archived == 0

    @pytest.mark.asyncio
    async def test_generic_error_is_swallowed(self):
        """Generic exceptions should also be caught and logged."""
        r = make_reconciler()
        instance = make_instance(lds_session_id="sess-fail")
        r._lds.archive_session.side_effect = RuntimeError("unexpected")

        # Should NOT raise
        await r._archive_lds_session(instance)

        assert r._lds_sessions_archived == 0


# =============================================================================
# Worker Enrichment Tests (AD-P10-02)
# =============================================================================


class TestWorkerEnrichment:
    """Tests for _enrich_with_worker_details, _get_cached_worker, _extract_host_from_worker."""

    @pytest.mark.asyncio
    async def test_enrich_resolves_worker_ip_and_credentials(self):
        """Enrichment should set worker_ip, credentials, and region from CPA worker."""
        r = make_reconciler()
        r._settings.use_private_ip_for_monitoring = False
        r._settings.cml_worker_api_username = "admin"
        r._settings.cml_worker_api_password = "pass123"
        r._api.get_worker.return_value = {
            "public_ip": "54.1.2.3",
            "private_ip": "10.0.0.5",
            "aws_region": "us-west-2",
        }
        session = make_instance(worker_id="w-100", worker_ip=None)

        await r._enrich_with_worker_details(session)

        assert session.worker_ip == "54.1.2.3"
        assert session.worker_cml_username == "admin"
        assert session.worker_cml_password == "pass123"
        assert session.worker_aws_region == "us-west-2"

    @pytest.mark.asyncio
    async def test_enrich_prefers_private_ip_when_setting_enabled(self):
        """When use_private_ip_for_monitoring is True, prefer private_ip."""
        r = make_reconciler()
        r._settings.use_private_ip_for_monitoring = True
        r._settings.cml_worker_api_username = "admin"
        r._settings.cml_worker_api_password = ""
        r._api.get_worker.return_value = {
            "public_ip": "54.1.2.3",
            "private_ip": "10.0.0.5",
        }
        session = make_instance(worker_id="w-200", worker_ip=None)

        await r._enrich_with_worker_details(session)

        assert session.worker_ip == "10.0.0.5"

    @pytest.mark.asyncio
    async def test_enrich_skips_when_no_worker_id(self):
        """No worker_id should skip enrichment entirely."""
        r = make_reconciler()
        session = make_instance(worker_id=None, worker_ip=None)

        await r._enrich_with_worker_details(session)

        r._api.get_worker.assert_not_awaited()
        assert session.worker_ip is None

    @pytest.mark.asyncio
    async def test_enrich_handles_worker_not_found(self):
        """CPA returning None for worker should leave session unchanged."""
        r = make_reconciler()
        r._api.get_worker.return_value = None
        session = make_instance(worker_id="w-gone", worker_ip=None)

        await r._enrich_with_worker_details(session)

        assert session.worker_ip is None

    @pytest.mark.asyncio
    async def test_cached_worker_avoids_repeated_api_calls(self):
        """Second enrichment for same worker_id should use cache, not API."""
        r = make_reconciler()
        r._settings.use_private_ip_for_monitoring = False
        r._settings.cml_worker_api_username = "admin"
        r._settings.cml_worker_api_password = ""
        r._api.get_worker.return_value = {
            "public_ip": "54.1.2.3",
            "private_ip": "10.0.0.5",
            "aws_region": "us-east-1",
        }
        session1 = make_instance(instance_id="s-1", worker_id="w-300", worker_ip=None)
        session2 = make_instance(instance_id="s-2", worker_id="w-300", worker_ip=None)

        await r._enrich_with_worker_details(session1)
        await r._enrich_with_worker_details(session2)

        # Only one API call (second was cached)
        r._api.get_worker.assert_awaited_once_with("w-300")
        assert session1.worker_ip == "54.1.2.3"
        assert session2.worker_ip == "54.1.2.3"

    def test_extract_host_falls_back_to_https_endpoint(self):
        """When no IPs available, fallback to https_endpoint."""
        r = make_reconciler()
        r._settings.use_private_ip_for_monitoring = False
        worker = {"https_endpoint": "https://cml.example.com:443"}

        host = r._extract_host_from_worker(worker)

        assert host == "cml.example.com"

    def test_extract_host_returns_none_when_empty(self):
        """Empty worker dict should return None."""
        r = make_reconciler()
        r._settings.use_private_ip_for_monitoring = False
        worker = {}

        host = r._extract_host_from_worker(worker)

        assert host is None


# =============================================================================
# Boot Lead Time From Definition Tests (AD-P10-01)
# =============================================================================


class TestBootLeadTimeFromDefinition:
    """Tests for per-definition boot_lead_time_minutes override."""

    @pytest.mark.asyncio
    async def test_definition_boot_lead_time_overrides_global(self):
        """Definition's boot_lead_time_minutes should override global setting."""
        r = make_reconciler()
        r._settings.worker_bootup_delay_minutes = 20  # global = 20 min

        # Definition overrides to 5 minutes
        definition = make_definition()
        definition.boot_lead_time_minutes = 5
        r._definition_cache["def-001"] = definition

        # Scheduled in 4 minutes → within 5-min window → should trigger
        scheduled = datetime.now(timezone.utc) + timedelta(minutes=4)
        instance = make_instance(status="SCHEDULED", timeslot_start=scheduled)

        result = await r._handle_scheduled(instance)

        assert result.status == ReconciliationStatus.REQUEUE
        r._api.start_instantiation.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_definition_boot_lead_time_narrower_window(self):
        """Smaller boot_lead_time means farther-out sessions stay SCHEDULED."""
        r = make_reconciler()
        r._settings.worker_bootup_delay_minutes = 20  # global = 20 min

        # Definition overrides to 3 minutes (much narrower)
        definition = make_definition()
        definition.boot_lead_time_minutes = 3
        r._definition_cache["def-001"] = definition

        # Scheduled in 10 minutes → outside 3-min window → should NOT trigger
        scheduled = datetime.now(timezone.utc) + timedelta(minutes=10)
        instance = make_instance(status="SCHEDULED", timeslot_start=scheduled)

        result = await r._handle_scheduled(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        r._api.start_instantiation.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_definition_boot_lead_time_uses_global(self):
        """When definition has no boot_lead_time_minutes, use global setting."""
        r = make_reconciler()
        r._settings.worker_bootup_delay_minutes = 20

        # Definition without boot_lead_time_minutes
        definition = make_definition()
        # boot_lead_time_minutes defaults to None
        r._definition_cache["def-001"] = definition

        # Scheduled in 15 minutes → within 20-min window → should trigger
        scheduled = datetime.now(timezone.utc) + timedelta(minutes=15)
        instance = make_instance(status="SCHEDULED", timeslot_start=scheduled)

        result = await r._handle_scheduled(instance)

        assert result.status == ReconciliationStatus.REQUEUE
        r._api.start_instantiation.assert_awaited_once()


# =============================================================================
# Topology Resolution From Definition Tests
# =============================================================================


@pytest.mark.skip(reason="ADR-034 Sprint C: _build_default_progress() removed (AD-PIPELINE-009). Topology tests covered in test_instantiation_pipeline.py.")
class TestTopologyFromDefinition:
    """Tests for resolving topology_yaml in _step_lab_resolve (formerly in _handle_instantiating)."""

    @pytest.mark.asyncio
    async def test_topology_from_definition_cml_yaml_content(self):
        """Definition's cml_yaml_content should be preferred over topology_yaml."""
        r = make_reconciler()
        instance = make_instance(
            status="INSTANTIATING",
            cml_lab_id=None,
            topology_yaml=None,  # NOT on the session
        )
        # Definition provides topology via cml_yaml_content (synced from content package)
        definition = make_definition()
        definition.cml_yaml_content = "lab:\n  nodes:\n    - label: synced-router"
        definition.topology_yaml = "lab:\n  nodes:\n    - label: old-router"
        r._definition_cache["def-001"] = definition
        r._cml_labs.import_lab.return_value = "lab-from-content"
        r._api.get_lab_records_for_worker.return_value = []

        progress = LabletReconciler._build_default_progress()
        result = await r._step_lab_resolve(instance, progress)

        assert result["status"] == "completed"
        # Verify the import used cml_yaml_content, not topology_yaml
        call_kwargs = r._cml_labs.import_lab.call_args.kwargs
        assert "synced-router" in call_kwargs["topology_yaml"]

    @pytest.mark.asyncio
    async def test_topology_from_definition_topology_yaml_fallback(self):
        """Definition's topology_yaml should be used when cml_yaml_content is None."""
        r = make_reconciler()
        instance = make_instance(
            status="INSTANTIATING",
            cml_lab_id=None,
            topology_yaml=None,
        )
        definition = make_definition()
        definition.cml_yaml_content = None  # not synced yet
        definition.topology_yaml = "lab:\n  nodes:\n    - label: fallback-router"
        r._definition_cache["def-001"] = definition
        r._cml_labs.import_lab.return_value = "lab-from-topo"
        r._api.get_lab_records_for_worker.return_value = []

        progress = LabletReconciler._build_default_progress()
        result = await r._step_lab_resolve(instance, progress)

        assert result["status"] == "completed"
        call_kwargs = r._cml_labs.import_lab.call_args.kwargs
        assert "fallback-router" in call_kwargs["topology_yaml"]

    @pytest.mark.asyncio
    async def test_session_topology_yaml_used_when_present(self):
        """Session's own topology_yaml should be used when available (legacy path)."""
        r = make_reconciler()
        instance = make_instance(
            status="INSTANTIATING",
            cml_lab_id=None,
            topology_yaml="lab:\n  nodes:\n    - label: session-router",
        )
        # Definition also has topology — but session's should take precedence
        definition = make_definition()
        definition.cml_yaml_content = "lab:\n  nodes:\n    - label: def-router"
        r._definition_cache["def-001"] = definition
        r._cml_labs.import_lab.return_value = "lab-from-session"
        r._api.get_lab_records_for_worker.return_value = []

        progress = LabletReconciler._build_default_progress()
        result = await r._step_lab_resolve(instance, progress)

        assert result["status"] == "completed"
        call_kwargs = r._cml_labs.import_lab.call_args.kwargs
        assert "session-router" in call_kwargs["topology_yaml"]


# =============================================================================
# Reconcile Guard Clause Tests (Post-Fix)
# =============================================================================


class TestReconcileGuardClauses:
    """Tests for the updated guard clause logic in reconcile()."""

    @pytest.mark.asyncio
    async def test_scheduled_with_worker_id_no_worker_ip_reaches_handler(self):
        """SCHEDULED session with worker_id but no worker_ip should reach _handle_scheduled."""
        r = make_reconciler()
        instance = make_instance(
            status="SCHEDULED",
            worker_id="w-assigned",
            worker_ip=None,
            timeslot_start=None,
        )

        result = await r.reconcile(instance)

        # Should reach _handle_scheduled (on-demand → immediate transition)
        assert result.status == ReconciliationStatus.REQUEUE
        r._api.start_instantiation.assert_awaited_once_with(session_id="inst-001")

    @pytest.mark.asyncio
    async def test_instantiating_without_worker_ip_fails(self):
        """INSTANTIATING session without worker_ip should fail (needs CML access)."""
        r = make_reconciler()
        instance = make_instance(
            status="INSTANTIATING",
            worker_id="w-assigned",
            worker_ip=None,
        )

        result = await r.reconcile(instance)

        assert result.status == ReconciliationStatus.FAILED

    @pytest.mark.asyncio
    async def test_running_without_worker_ip_fails(self):
        """RUNNING session without worker_ip should fail."""
        r = make_reconciler()
        instance = make_instance(
            status="RUNNING",
            worker_id="w-assigned",
            worker_ip=None,
        )

        result = await r.reconcile(instance)

        assert result.status == ReconciliationStatus.FAILED

    @pytest.mark.asyncio
    async def test_scheduled_without_worker_id_succeeds_silently(self):
        """SCHEDULED session without worker_id should succeed (not yet assigned)."""
        r = make_reconciler()
        instance = make_instance(
            status="SCHEDULED",
            worker_id=None,
            worker_ip=None,
        )

        result = await r.reconcile(instance)

        assert result.status == ReconciliationStatus.SUCCESS
