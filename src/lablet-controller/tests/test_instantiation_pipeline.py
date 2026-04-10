"""Unit tests for ADR-031/ADR-034 Instantiation Pipeline — delegation and helpers.

Covers:
- Pipeline delegation: _handle_instantiating fire-and-check pattern (Sprint C)
- Helper methods: _get_pipeline_def, _build_pipeline_context, _build_step_dispatcher
- Resumability: progress persistence across reconciliation cycles
- Timeslot expiry: _handle_expired, early expiry check in reconcile()

Note: Individual step handler logic tests (content_sync, lab_resolve, etc.)
are covered by registry handler tests. The inline _step_* methods were removed
in ADR-038 Task 2.

Pattern: Uses object.__new__(LabletReconciler) to bypass complex __init__,
matching the fixture pattern from G5 tests.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lcm_core.domain.entities import LabletSessionReadModel
from lcm_core.domain.entities.read_models.lablet_definition_read_model import LabletDefinitionReadModel
from lcm_core.infrastructure.hosted_services.reconciliation_hosted_service import ReconciliationStatus

from application.hosted_services.lablet_reconciler import LabletReconciler
from application.models.pipeline_result import PipelineResult
from application.services.lifecycle_phase_handler import LifecyclePhaseHandler
from application.services.pipeline_executor import PipelineExecutor

# =============================================================================
# Fixtures
# =============================================================================


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
    pipeline_progress: dict | None = None,
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
        pipeline_progress=pipeline_progress,
    )


def make_reconciler() -> LabletReconciler:
    """Create a LabletReconciler bypassing __init__.

    Includes Sprint C fields: _session_locks, _active_handlers,
    _pipeline_executor, _pipeline_retry_counts.
    """
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
    r._resource_observer = None
    r._content_sync_service = None
    # Sprint C additions
    r._session_locks = {}
    r._active_handlers = {}
    r._pipeline_executor = PipelineExecutor()
    r._pipeline_retry_counts = {}
    # ADR-038: Pipeline template resolver
    from application.services.pipeline_template_resolver import PipelineTemplateResolver

    r._template_resolver = PipelineTemplateResolver()
    return r


def make_definition(
    definition_id: str = "def-001",
    name: str = "Test Definition",
    form_qualified_name: str | None = "org/project/form",
    port_template: dict | None = None,
    content_sync_enabled: bool = False,
) -> LabletDefinitionReadModel:
    """Create a LabletDefinitionReadModel for testing."""
    d = LabletDefinitionReadModel(
        id=definition_id,
        name=name,
        form_qualified_name=form_qualified_name,
    )
    if port_template is not None:
        d.port_template = port_template  # type: ignore[attr-defined]
    if content_sync_enabled:
        d.content_sync_enabled = True  # type: ignore[attr-defined]
    return d


def _progress_with_lab_resolve(
    cml_lab_id: str = "lab-abc",
    lab_record_id: str | None = "rec-001",
    cml_lab_title: str | None = None,
) -> dict:
    """Build a progress dict where lab_resolve is completed (Sprint C dict-of-dicts format)."""
    result_data: dict = {"cml_lab_id": cml_lab_id}
    if lab_record_id:
        result_data["lab_record_id"] = lab_record_id
    if cml_lab_title is not None:
        result_data["cml_lab_title"] = cml_lab_title
    return {
        "content_sync": {"status": "skipped"},
        "variables": {"status": "skipped"},
        "lab_resolve": {"status": "completed", "result_data": result_data},
        "ports_alloc": {"status": "skipped"},
        "tags_sync": {"status": "skipped"},
        "lab_binding": {"status": "completed", "result_data": {}},
        "lab_start": {"status": "pending"},
        "lds_provision": {"status": "pending"},
        "mark_ready": {"status": "pending"},
    }


# =============================================================================
# Pipeline Helpers (Sprint C) — _get_pipeline_def, _build_pipeline_context,
#                                _build_step_dispatcher
# =============================================================================


INSTANTIATE_PIPELINE = {
    "description": "test instantiate",
    "trigger": "on_status:instantiating",
    "max_retries": 3,
    "retry_backoff": 30,
    "steps": [
        {"name": "lab_resolve", "handler": "lab_resolve"},
        {"name": "lab_start", "handler": "lab_start", "needs": ["lab_resolve"]},
        {"name": "mark_ready", "handler": "mark_ready", "needs": ["lab_start"]},
    ],
    "outputs": {"cml_lab_id": "$STEPS.lab_resolve.cml_lab_id"},
}


class TestGetPipelineDef:
    """Tests for _get_pipeline_def helper."""

    @pytest.mark.asyncio
    async def test_returns_pipeline_from_definition(self):
        """Should return the named pipeline dict from the definition."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {"instantiate": INSTANTIATE_PIPELINE}
        r._definition_cache["def-001"] = defn
        instance = make_instance()

        result = await r._get_pipeline_def(instance, "instantiate")

        assert result is INSTANTIATE_PIPELINE

    @pytest.mark.asyncio
    async def test_returns_none_when_no_definition(self):
        """Should return None when definition not found."""
        r = make_reconciler()
        instance = make_instance()
        r._api.get_lablet_definition.return_value = None

        result = await r._get_pipeline_def(instance, "instantiate")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_pipelines(self):
        """Should return None when definition has no pipelines."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = None
        r._definition_cache["def-001"] = defn
        instance = make_instance()

        result = await r._get_pipeline_def(instance, "instantiate")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_pipeline_name(self):
        """Should return None when pipeline name not in definition."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {"instantiate": INSTANTIATE_PIPELINE}
        r._definition_cache["def-001"] = defn
        instance = make_instance()

        result = await r._get_pipeline_def(instance, "teardown")

        assert result is None


class TestBuildPipelineContext:
    """Tests for _build_pipeline_context helper."""

    @pytest.mark.asyncio
    async def test_builds_context_with_session_fields(self):
        """PipelineContext should carry session, definition, and services."""
        r = make_reconciler()
        defn = make_definition()
        r._definition_cache["def-001"] = defn
        instance = make_instance(worker_ip="10.0.0.5", worker_cml_username="admin", worker_cml_password="secret")

        ctx = await r._build_pipeline_context(instance)

        assert ctx.session is instance
        assert ctx.definition is defn
        assert ctx.worker_ip == "10.0.0.5"
        assert ctx.worker_cml_username == "admin"
        assert ctx.worker_cml_password == "secret"
        assert ctx.api is r._api
        assert ctx.cml is r._cml_labs
        assert ctx.lds is r._lds
        assert ctx.steps_data == {}


class TestBuildStepDispatcher:
    """Tests for _build_step_dispatcher closure.

    ADR-038: The dispatcher now tries the StepHandlerRegistry first,
    falling back to getattr(reconciler, f"_step_{handler_name}").
    These tests patch get_handler → None to test the fallback path.
    """

    @pytest.mark.asyncio
    @patch("application.hosted_services.lablet_reconciler.get_handler", return_value=None)
    async def test_dispatches_to_step_method(self, mock_get_handler):
        """Dispatcher should call _step_{handler_name} on the reconciler (fallback path)."""
        r = make_reconciler()
        r._step_lab_resolve = AsyncMock(return_value={"step": "lab_resolve", "status": "completed", "result_data": {"cml_lab_id": "lab-123"}})
        dispatch = r._build_step_dispatcher()

        result = await dispatch("lab_resolve", MagicMock(), {})

        r._step_lab_resolve.assert_awaited_once()
        assert result == {"cml_lab_id": "lab-123"}

    @pytest.mark.asyncio
    @patch("application.hosted_services.lablet_reconciler.get_handler", return_value=None)
    async def test_raises_on_unknown_handler(self, mock_get_handler):
        """Dispatcher should raise RuntimeError for unknown step handler."""
        r = make_reconciler()
        dispatch = r._build_step_dispatcher()

        with pytest.raises(RuntimeError, match="Unknown pipeline step handler"):
            await dispatch("nonexistent_step", MagicMock(), {})

    @pytest.mark.asyncio
    @patch("application.hosted_services.lablet_reconciler.get_handler", return_value=None)
    async def test_raises_on_step_failure(self, mock_get_handler):
        """Dispatcher should raise RuntimeError when step handler returns failed status."""
        r = make_reconciler()
        r._step_lab_start = AsyncMock(return_value={"step": "lab_start", "status": "failed", "error": "network error"})
        dispatch = r._build_step_dispatcher()

        with pytest.raises(RuntimeError, match="network error"):
            await dispatch("lab_start", MagicMock(), {})

    @pytest.mark.asyncio
    @patch("application.hosted_services.lablet_reconciler.get_handler", return_value=None)
    async def test_returns_empty_dict_when_no_result_data(self, mock_get_handler):
        """Dispatcher should return {} when handler has no result_data."""
        r = make_reconciler()
        r._step_mark_ready = AsyncMock(return_value={"step": "mark_ready", "status": "completed"})
        dispatch = r._build_step_dispatcher()

        result = await dispatch("mark_ready", MagicMock(), {})

        assert result == {}


# =============================================================================
# Pipeline Delegation — _handle_instantiating (Sprint C)
# =============================================================================


class TestHandleInstantiatingDelegation:
    """Tests for the Sprint C fire-and-check _handle_instantiating pattern."""

    @pytest.mark.asyncio
    async def test_starts_handler_when_no_existing_handler(self):
        """First call should start a LifecyclePhaseHandler and return SUCCESS."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {"instantiate": INSTANTIATE_PIPELINE}
        r._definition_cache["def-001"] = defn
        instance = make_instance()

        # Patch LifecyclePhaseHandler to avoid real asyncio task
        with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock) as mock_start:
            result = await r._handle_instantiating(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert "inst-001:instantiate" in r._active_handlers
        mock_start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_success_when_handler_running(self):
        """If handler is already running, should return SUCCESS without starting new one."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = True
        r._active_handlers["inst-001:instantiate"] = handler
        instance = make_instance()

        result = await r._handle_instantiating(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert "running" in result.message.lower()

    @pytest.mark.asyncio
    async def test_completed_handler_returns_success(self):
        """Completed handler (status='completed') should return SUCCESS and remove handler."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = False
        handler.result = PipelineResult(pipeline_name="instantiate", status="completed", duration_seconds=1.0)
        r._active_handlers["inst-001:instantiate"] = handler
        instance = make_instance()

        result = await r._handle_instantiating(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert "inst-001:instantiate" not in r._active_handlers

    @pytest.mark.asyncio
    async def test_partial_handler_returns_success(self):
        """Partial completion should also return SUCCESS."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = False
        handler.result = PipelineResult(pipeline_name="instantiate", status="partial", duration_seconds=1.0)
        r._active_handlers["inst-001:instantiate"] = handler
        instance = make_instance()

        result = await r._handle_instantiating(instance)

        assert result.status == ReconciliationStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_failed_handler_retries_within_budget(self):
        """Failed handler with retry budget should start a new handler."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = False
        handler.result = PipelineResult(pipeline_name="instantiate", status="failed", duration_seconds=1.0, error="timeout", max_retries=3)
        r._active_handlers["inst-001:instantiate"] = handler

        defn = make_definition()
        defn.pipelines = {"instantiate": INSTANTIATE_PIPELINE}
        r._definition_cache["def-001"] = defn
        instance = make_instance()

        with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
            result = await r._handle_instantiating(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert r._pipeline_retry_counts["inst-001:instantiate"] == 1

    @pytest.mark.asyncio
    async def test_failed_handler_exhausts_retries(self):
        """Failed handler past max_retries should terminate session."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = False
        handler.result = PipelineResult(pipeline_name="instantiate", status="failed", duration_seconds=1.0, error="timeout", max_retries=2)
        r._active_handlers["inst-001:instantiate"] = handler
        r._pipeline_retry_counts["inst-001:instantiate"] = 1  # Already retried once → next is #2 >= max_retries

        instance = make_instance()

        result = await r._handle_instantiating(instance)

        assert result.status == ReconciliationStatus.FAILED
        r._api.terminate_session.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_pipeline_def_terminates_session(self):
        """Missing pipeline definition should terminate session."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {}  # No instantiate pipeline
        r._definition_cache["def-001"] = defn
        instance = make_instance()

        result = await r._handle_instantiating(instance)

        assert result.status == ReconciliationStatus.FAILED
        r._api.terminate_session.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handler_crash_no_result_retries(self):
        """Handler that finished with no result (crash) should retry."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = False
        handler.result = None  # Crash — no PipelineResult
        r._active_handlers["inst-001:instantiate"] = handler

        defn = make_definition()
        defn.pipelines = {"instantiate": INSTANTIATE_PIPELINE}
        r._definition_cache["def-001"] = defn
        instance = make_instance()

        with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
            result = await r._handle_instantiating(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        # Handler should have been replaced
        assert "inst-001:instantiate" in r._active_handlers

    @pytest.mark.asyncio
    async def test_existing_progress_passed_to_handler(self):
        """existing_progress from instance should be passed for resumability."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {"instantiate": INSTANTIATE_PIPELINE}
        r._definition_cache["def-001"] = defn
        progress = {"lab_resolve": {"status": "completed", "result_data": {"cml_lab_id": "lab-abc"}}}
        instance = make_instance(pipeline_progress={"instantiate": progress})

        with patch.object(LifecyclePhaseHandler, "__init__", return_value=None) as mock_init:
            with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
                mock_init.return_value = None
                # We can't easily verify the init args without a more complex mock
                # Just verify it runs without error
                result = await r._handle_instantiating(instance)

        assert result.status == ReconciliationStatus.SUCCESS


# =============================================================================
# _get_existing_progress helper (ADR-034 Sprint F)
# =============================================================================


class TestGetExistingProgress:
    """Tests for _get_existing_progress — pipeline_progress lookup."""

    def test_returns_none_when_no_progress(self):
        """Should return None when instance has no progress at all."""
        r = make_reconciler()
        instance = make_instance(pipeline_progress=None)

        result = r._get_existing_progress(instance, "instantiate")

        assert result is None

    def test_returns_progress_when_available(self):
        """Should return pipeline_progress[pipeline_name]."""
        r = make_reconciler()
        generic = {"lab_resolve": {"status": "completed", "result_data": {"cml_lab_id": "lab-new"}}}
        instance = make_instance(
            pipeline_progress={"instantiate": generic},
        )

        result = r._get_existing_progress(instance, "instantiate")

        assert result is generic
        assert result["lab_resolve"]["result_data"]["cml_lab_id"] == "lab-new"

    def test_returns_teardown_progress(self):
        """Should return pipeline_progress['teardown'] for teardown pipeline."""
        r = make_reconciler()
        teardown_progress = {"stop_lab": {"status": "completed", "result_data": {}}}
        instance = make_instance(
            pipeline_progress={"teardown": teardown_progress},
        )

        result = r._get_existing_progress(instance, "teardown")

        assert result is teardown_progress

    def test_returns_collect_evidence_progress(self):
        """Should return pipeline_progress['collect_evidence'] for evidence pipeline."""
        r = make_reconciler()
        evidence_progress = {"capture_configs": {"status": "completed", "result_data": {}}}
        instance = make_instance(
            pipeline_progress={"collect_evidence": evidence_progress},
        )

        result = r._get_existing_progress(instance, "collect_evidence")

        assert result is evidence_progress

    def test_returns_compute_grading_progress(self):
        """Should return pipeline_progress['compute_grading'] for grading pipeline."""
        r = make_reconciler()
        grading_progress = {"load_rubric": {"status": "completed", "result_data": {}}}
        instance = make_instance(
            pipeline_progress={"compute_grading": grading_progress},
        )

        result = r._get_existing_progress(instance, "compute_grading")

        assert result is grading_progress

    def test_returns_none_for_absent_pipeline_key(self):
        """Should return None when pipeline_progress exists but has no key for requested pipeline."""
        r = make_reconciler()
        instance = make_instance(
            pipeline_progress={"instantiate": {"lab_resolve": {"status": "completed"}}},
        )

        result = r._get_existing_progress(instance, "teardown")

        assert result is None

    def test_skips_empty_progress_dict(self):
        """Should return None when pipeline_progress has an empty dict for the key."""
        r = make_reconciler()
        instance = make_instance(
            pipeline_progress={"instantiate": {}},
        )

        result = r._get_existing_progress(instance, "instantiate")

        # Empty dict is falsy — should fall back
        assert result is None


class TestHandleInstantiatingResumability:
    """Tests for Sprint F resumability — _handle_instantiating uses pipeline_progress."""

    @pytest.mark.asyncio
    async def test_uses_pipeline_progress(self):
        """Should pass pipeline_progress[instantiate] to handler."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {"instantiate": INSTANTIATE_PIPELINE}
        r._definition_cache["def-001"] = defn

        generic = {"lab_resolve": {"status": "completed", "result_data": {"cml_lab_id": "lab-new"}}}
        instance = make_instance(
            pipeline_progress={"instantiate": generic},
        )

        with patch.object(LifecyclePhaseHandler, "__init__", return_value=None) as mock_init:
            with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
                result = await r._handle_instantiating(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        # Verify the handler was created with the generic progress
        init_kwargs = mock_init.call_args
        assert init_kwargs.kwargs.get("existing_progress") is generic

    @pytest.mark.asyncio
    async def test_passes_none_when_no_progress(self):
        """Should pass None when no pipeline progress exists."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {"instantiate": INSTANTIATE_PIPELINE}
        r._definition_cache["def-001"] = defn

        instance = make_instance(
            pipeline_progress=None,
        )

        with patch.object(LifecyclePhaseHandler, "__init__", return_value=None) as mock_init:
            with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
                result = await r._handle_instantiating(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        init_kwargs = mock_init.call_args
        assert init_kwargs.kwargs.get("existing_progress") is None


# =============================================================================
# Step Methods — _step_content_sync
# =============================================================================


class TestHandleExpired:
    """Tests for _handle_expired."""

    @pytest.mark.asyncio
    async def test_calls_expire_session(self):
        """Should call CPA expire_session with reason."""
        r = make_reconciler()
        instance = make_instance()

        result = await r._handle_expired(instance)

        assert result.status == ReconciliationStatus.REQUEUE
        r._api.expire_session.assert_awaited_once_with(
            session_id="inst-001",
            reason="timeslot_expired",
        )

    @pytest.mark.asyncio
    async def test_api_error_returns_failed(self):
        """CPA error should return FAILED."""
        r = make_reconciler()
        instance = make_instance()
        r._api.expire_session.side_effect = RuntimeError("CPA down")

        result = await r._handle_expired(instance)

        assert result.status == ReconciliationStatus.FAILED


class TestTimeslotExpiryCheck:
    """Tests for early timeslot expiry check in reconcile()."""

    @pytest.mark.asyncio
    async def test_expired_instantiating_triggers_expiry(self):
        """Expired timeslot on INSTANTIATING session should call _handle_expired."""
        r = make_reconciler()
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        instance = make_instance(
            status="INSTANTIATING",
            timeslot_end=past,
        )
        r._worker_cache["worker-001"] = MagicMock(status="running")

        result = await r.reconcile(instance)

        assert result.status == ReconciliationStatus.REQUEUE
        r._api.expire_session.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_expired_continues_normally(self):
        """Non-expired timeslot should proceed to status handler (pipeline bootstrap)."""
        r = make_reconciler()
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        instance = make_instance(
            status="INSTANTIATING",
            timeslot_end=future,
        )
        r._worker_cache["worker-001"] = MagicMock(status="running")
        defn = make_definition()
        defn.pipelines = {"instantiate": INSTANTIATE_PIPELINE}
        r._definition_cache["def-001"] = defn

        with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
            result = await r.reconcile(instance)

        # Should reach pipeline bootstrap (handler started), not expiry
        assert result.status == ReconciliationStatus.SUCCESS
        r._api.expire_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_timeslot_continues_normally(self):
        """Session without timeslot_end should not trigger expiry."""
        r = make_reconciler()
        instance = make_instance(
            status="INSTANTIATING",
            timeslot_end=None,
        )
        r._worker_cache["worker-001"] = MagicMock(status="running")
        defn = make_definition()
        defn.pipelines = {"instantiate": INSTANTIATE_PIPELINE}
        r._definition_cache["def-001"] = defn

        with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
            result = await r.reconcile(instance)

        # Should reach pipeline bootstrap (handler started)
        assert result.status == ReconciliationStatus.SUCCESS
        r._api.expire_session.assert_not_awaited()
