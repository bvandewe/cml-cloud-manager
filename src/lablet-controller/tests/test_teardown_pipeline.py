"""Unit tests for ADR-034 Sprint D — Teardown, Evidence, and Grading Pipelines.

Covers:
- Pipeline delegation: _handle_stopping, _handle_collecting, _handle_grading
- Status routing: COLLECTING/GRADING dispatched correctly in _reconcile_inner
- Seed file validation: all handler names resolve to registered step handlers (D7)

Note: Individual step handler logic tests (stop_lab, wipe_lab, archive, etc.)
are covered by registry handler tests. The inline _step_* methods were removed
in ADR-038 Task 2.

Pattern: Uses object.__new__(LabletReconciler) to bypass complex __init__,
matching the fixture pattern from test_instantiation_pipeline.py.
"""

import glob
import os
from unittest.mock import AsyncMock, MagicMock, patch

import yaml
from application.hosted_services.lablet_reconciler import LabletReconciler
from application.models.pipeline_result import PipelineResult
from application.services.lifecycle_phase_handler import LifecyclePhaseHandler
from application.services.pipeline_executor import PipelineExecutor
from application.services.pipeline_template_resolver import PipelineTemplateResolver
from application.services.step_registry import get_handler
from lcm_core.domain.entities import LabletSessionReadModel
from lcm_core.domain.entities.read_models.lablet_definition_read_model import LabletDefinitionReadModel
from lcm_core.infrastructure.hosted_services.reconciliation_hosted_service import ReconciliationStatus

# =============================================================================
# Fixtures
# =============================================================================


def make_instance(
    instance_id: str = "inst-001",
    name: str = "test-lablet",
    definition_id: str = "def-001",
    status: str = "STOPPING",
    worker_id: str | None = "worker-001",
    cml_lab_id: str | None = "lab-abc",
    worker_ip: str | None = "10.0.0.1",
    worker_aws_region: str | None = "us-east-1",
    worker_cml_username: str | None = "admin",
    worker_cml_password: str | None = "secret",
    timeslot_start=None,
    timeslot_end=None,
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
    r._settings.resource_observation_enabled = False
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
    # ADR-038: template resolver populated by __init__ — required when
    # _handle_pipeline_phase calls self._template_resolver.resolve(...).
    r._template_resolver = PipelineTemplateResolver()
    # Phase 3 / AD-CSI-008: SE client used by _build_pipeline_context.
    r._scenario_engine_client = None
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


# Pipeline definitions matching seed YAML structure
TEARDOWN_PIPELINE = {
    "description": "test teardown",
    "trigger": "on_status:stopping",
    "max_retries": 2,
    "steps": [
        {"name": "stop_lab", "handler": "stop_lab", "timeout_seconds": 120},
        {"name": "deregister_lds", "handler": "deregister_lds", "needs": ["stop_lab"], "optional": True, "timeout_seconds": 30},
        {"name": "wipe_lab", "handler": "wipe_lab", "needs": ["stop_lab"], "timeout_seconds": 120},
        {"name": "archive", "handler": "archive", "needs": ["wipe_lab", "deregister_lds"], "timeout_seconds": 10},
    ],
    "outputs": {"archived_at": "$STEPS.archive.archived_at"},
}

COLLECT_EVIDENCE_PIPELINE = {
    "description": "test collect evidence",
    "trigger": "on_status:collecting",
    "max_retries": 2,
    "steps": [
        {"name": "capture_configs", "handler": "capture_configs", "timeout_seconds": 120},
        {"name": "capture_screenshots", "handler": "capture_screenshots", "needs": ["capture_configs"], "optional": True, "timeout_seconds": 60},
        {"name": "export_pcaps", "handler": "export_pcaps", "needs": ["capture_configs"], "optional": True, "timeout_seconds": 60},
        {"name": "package_evidence", "handler": "package_evidence", "needs": ["capture_configs"], "timeout_seconds": 30},
    ],
    "outputs": {"evidence_uri": "$STEPS.package_evidence.evidence_uri"},
}

COMPUTE_GRADING_PIPELINE = {
    "description": "test compute grading",
    "trigger": "on_status:grading",
    "max_retries": 2,
    "steps": [
        {"name": "load_rubric", "handler": "load_rubric", "timeout_seconds": 30},
        {"name": "evaluate", "handler": "evaluate", "needs": ["load_rubric"], "timeout_seconds": 120},
        {"name": "record_score", "handler": "record_score", "needs": ["evaluate"], "timeout_seconds": 10},
    ],
    "outputs": {"score": "$STEPS.evaluate.score", "score_report_id": "$STEPS.record_score.score_report_id"},
}


# =============================================================================
# Teardown Step Handlers — _step_stop_lab
# =============================================================================


class TestHandleStoppingDelegation:
    """Tests for the Sprint D fire-and-check _handle_stopping pattern."""

    async def test_starts_handler_when_no_existing_handler(self):
        """First call should start a LifecyclePhaseHandler for teardown."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {"teardown": TEARDOWN_PIPELINE}
        r._definition_cache["def-001"] = defn
        instance = make_instance(status="STOPPING")

        with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock) as mock_start:
            result = await r._handle_stopping(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert "inst-001:teardown" in r._active_handlers
        mock_start.assert_awaited_once()

    async def test_returns_success_when_handler_running(self):
        """If handler is already running, should return SUCCESS."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = True
        r._active_handlers["inst-001:teardown"] = handler
        instance = make_instance(status="STOPPING")

        result = await r._handle_stopping(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert "running" in result.message.lower()

    async def test_completed_handler_returns_success(self):
        """Completed handler should return SUCCESS and remove handler."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = False
        handler.result = PipelineResult(pipeline_name="teardown", status="completed", duration_seconds=1.0)
        r._active_handlers["inst-001:teardown"] = handler
        instance = make_instance(status="STOPPING")

        result = await r._handle_stopping(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert "inst-001:teardown" not in r._active_handlers

    async def test_partial_handler_returns_success(self):
        """Partial completion should return SUCCESS."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = False
        handler.result = PipelineResult(pipeline_name="teardown", status="partial", duration_seconds=1.0)
        r._active_handlers["inst-001:teardown"] = handler
        instance = make_instance(status="STOPPING")

        result = await r._handle_stopping(instance)

        assert result.status == ReconciliationStatus.SUCCESS

    async def test_failed_handler_retries_within_budget(self):
        """Failed handler with retry budget should start a new handler."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = False
        handler.result = PipelineResult(pipeline_name="teardown", status="failed", duration_seconds=1.0, error="timeout", max_retries=3)
        r._active_handlers["inst-001:teardown"] = handler

        defn = make_definition()
        defn.pipelines = {"teardown": TEARDOWN_PIPELINE}
        r._definition_cache["def-001"] = defn
        instance = make_instance(status="STOPPING")

        with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
            result = await r._handle_stopping(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert r._pipeline_retry_counts["inst-001:teardown"] == 1

    async def test_failed_handler_exhausts_retries(self):
        """Failed handler past max_retries should terminate session."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = False
        handler.result = PipelineResult(pipeline_name="teardown", status="failed", duration_seconds=1.0, error="timeout", max_retries=2)
        r._active_handlers["inst-001:teardown"] = handler
        r._pipeline_retry_counts["inst-001:teardown"] = 1  # Already retried once

        instance = make_instance(status="STOPPING")

        result = await r._handle_stopping(instance)

        assert result.status == ReconciliationStatus.FAILED
        r._api.terminate_session.assert_awaited_once()

    async def test_no_pipeline_def_terminates_session(self):
        """Missing teardown pipeline should terminate session."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {}  # No teardown pipeline
        r._definition_cache["def-001"] = defn
        instance = make_instance(status="STOPPING")

        result = await r._handle_stopping(instance)

        assert result.status == ReconciliationStatus.FAILED
        r._api.terminate_session.assert_awaited_once()

    async def test_handler_crash_no_result_retries(self):
        """Handler that finished with no result (crash) should retry."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = False
        handler.result = None  # Crash
        r._active_handlers["inst-001:teardown"] = handler

        defn = make_definition()
        defn.pipelines = {"teardown": TEARDOWN_PIPELINE}
        r._definition_cache["def-001"] = defn
        instance = make_instance(status="STOPPING")

        with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
            result = await r._handle_stopping(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert "inst-001:teardown" in r._active_handlers


class TestHandleStoppingResumability:
    """Tests for Sprint F resumability — _handle_stopping uses pipeline_progress."""

    async def test_passes_generic_progress_to_handler(self):
        """Should pass pipeline_progress['teardown'] as existing_progress."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {"teardown": TEARDOWN_PIPELINE}
        r._definition_cache["def-001"] = defn

        teardown_progress = {"stop_lab": {"status": "completed", "result_data": {}}}
        instance = make_instance(
            status="STOPPING",
            pipeline_progress={"teardown": teardown_progress},
        )

        with patch.object(LifecyclePhaseHandler, "__init__", return_value=None) as mock_init:
            with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
                result = await r._handle_stopping(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        init_kwargs = mock_init.call_args
        assert init_kwargs.kwargs.get("existing_progress") is teardown_progress

    async def test_passes_none_when_no_progress(self):
        """Should pass None when no pipeline_progress exists for teardown."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {"teardown": TEARDOWN_PIPELINE}
        r._definition_cache["def-001"] = defn

        instance = make_instance(status="STOPPING", pipeline_progress=None)

        with patch.object(LifecyclePhaseHandler, "__init__", return_value=None) as mock_init:
            with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
                result = await r._handle_stopping(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        init_kwargs = mock_init.call_args
        assert init_kwargs.kwargs.get("existing_progress") is None

    async def test_no_legacy_fallback_for_teardown(self):
        """Should return None when only instantiate progress exists."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {"teardown": TEARDOWN_PIPELINE}
        r._definition_cache["def-001"] = defn

        instance = make_instance(
            status="STOPPING",
            pipeline_progress={"instantiate": {"lab_resolve": {"status": "completed"}}},
        )

        with patch.object(LifecyclePhaseHandler, "__init__", return_value=None) as mock_init:
            with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
                result = await r._handle_stopping(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        init_kwargs = mock_init.call_args
        assert init_kwargs.kwargs.get("existing_progress") is None


# =============================================================================
# Pipeline Delegation — _handle_collecting (Sprint D)
# =============================================================================


class TestHandleCollectingDelegation:
    """Tests for the Sprint D fire-and-check _handle_collecting pattern."""

    async def test_starts_handler_when_no_existing_handler(self):
        """First call should start a LifecyclePhaseHandler for collect_evidence."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {"collect_evidence": COLLECT_EVIDENCE_PIPELINE}
        r._definition_cache["def-001"] = defn
        instance = make_instance(status="COLLECTING")

        with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock) as mock_start:
            result = await r._handle_collecting(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert "inst-001:collect_evidence" in r._active_handlers
        mock_start.assert_awaited_once()

    async def test_returns_success_when_handler_running(self):
        """If handler is already running, should return SUCCESS."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = True
        r._active_handlers["inst-001:collect_evidence"] = handler
        instance = make_instance(status="COLLECTING")

        result = await r._handle_collecting(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert "running" in result.message.lower()

    async def test_completed_handler_returns_success(self):
        """Completed handler should return SUCCESS and remove handler."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = False
        handler.result = PipelineResult(pipeline_name="collect_evidence", status="completed", duration_seconds=1.0)
        r._active_handlers["inst-001:collect_evidence"] = handler
        instance = make_instance(status="COLLECTING")

        result = await r._handle_collecting(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert "inst-001:collect_evidence" not in r._active_handlers

    async def test_failed_handler_retries_within_budget(self):
        """Failed handler with retry budget should start a new handler."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = False
        handler.result = PipelineResult(pipeline_name="collect_evidence", status="failed", duration_seconds=1.0, error="timeout", max_retries=3)
        r._active_handlers["inst-001:collect_evidence"] = handler

        defn = make_definition()
        defn.pipelines = {"collect_evidence": COLLECT_EVIDENCE_PIPELINE}
        r._definition_cache["def-001"] = defn
        instance = make_instance(status="COLLECTING")

        with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
            result = await r._handle_collecting(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert r._pipeline_retry_counts["inst-001:collect_evidence"] == 1

    async def test_failed_handler_exhausts_retries(self):
        """Failed handler past max_retries should terminate session."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = False
        handler.result = PipelineResult(pipeline_name="collect_evidence", status="failed", duration_seconds=1.0, error="fail", max_retries=2)
        r._active_handlers["inst-001:collect_evidence"] = handler
        r._pipeline_retry_counts["inst-001:collect_evidence"] = 1

        instance = make_instance(status="COLLECTING")

        result = await r._handle_collecting(instance)

        assert result.status == ReconciliationStatus.FAILED
        r._api.terminate_session.assert_awaited_once()

    async def test_no_pipeline_def_terminates_session(self):
        """Missing collect_evidence pipeline should terminate session."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {}
        r._definition_cache["def-001"] = defn
        instance = make_instance(status="COLLECTING")

        result = await r._handle_collecting(instance)

        assert result.status == ReconciliationStatus.FAILED
        r._api.terminate_session.assert_awaited_once()


class TestHandleCollectingResumability:
    """Tests for Sprint F resumability — _handle_collecting uses pipeline_progress."""

    async def test_passes_generic_progress_to_handler(self):
        """Should pass pipeline_progress['collect_evidence'] as existing_progress."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {"collect_evidence": COLLECT_EVIDENCE_PIPELINE}
        r._definition_cache["def-001"] = defn

        evidence_progress = {"capture_configs": {"status": "completed", "result_data": {"artifacts_count": 5}}}
        instance = make_instance(
            status="COLLECTING",
            pipeline_progress={"collect_evidence": evidence_progress},
        )

        with patch.object(LifecyclePhaseHandler, "__init__", return_value=None) as mock_init:
            with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
                result = await r._handle_collecting(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        init_kwargs = mock_init.call_args
        assert init_kwargs.kwargs.get("existing_progress") is evidence_progress

    async def test_passes_none_when_no_progress(self):
        """Should pass None when no pipeline_progress exists for collect_evidence."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {"collect_evidence": COLLECT_EVIDENCE_PIPELINE}
        r._definition_cache["def-001"] = defn

        instance = make_instance(status="COLLECTING", pipeline_progress=None)

        with patch.object(LifecyclePhaseHandler, "__init__", return_value=None) as mock_init:
            with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
                result = await r._handle_collecting(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        init_kwargs = mock_init.call_args
        assert init_kwargs.kwargs.get("existing_progress") is None


# =============================================================================
# Pipeline Delegation — _handle_grading (Sprint D)
# =============================================================================


class TestHandleGradingDelegation:
    """Tests for the Sprint D fire-and-check _handle_grading pattern."""

    async def test_starts_handler_when_no_existing_handler(self):
        """First call should start a LifecyclePhaseHandler for compute_grading."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {"compute_grading": COMPUTE_GRADING_PIPELINE}
        r._definition_cache["def-001"] = defn
        instance = make_instance(status="GRADING")

        with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock) as mock_start:
            result = await r._handle_grading(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert "inst-001:compute_grading" in r._active_handlers
        mock_start.assert_awaited_once()

    async def test_returns_success_when_handler_running(self):
        """If handler is already running, should return SUCCESS."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = True
        r._active_handlers["inst-001:compute_grading"] = handler
        instance = make_instance(status="GRADING")

        result = await r._handle_grading(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert "running" in result.message.lower()

    async def test_completed_handler_returns_success(self):
        """Completed handler should return SUCCESS and remove handler."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = False
        handler.result = PipelineResult(pipeline_name="compute_grading", status="completed", duration_seconds=1.0)
        r._active_handlers["inst-001:compute_grading"] = handler
        instance = make_instance(status="GRADING")

        result = await r._handle_grading(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert "inst-001:compute_grading" not in r._active_handlers

    async def test_failed_handler_retries_within_budget(self):
        """Failed handler with retry budget should start a new handler."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = False
        handler.result = PipelineResult(pipeline_name="compute_grading", status="failed", duration_seconds=1.0, error="timeout", max_retries=3)
        r._active_handlers["inst-001:compute_grading"] = handler

        defn = make_definition()
        defn.pipelines = {"compute_grading": COMPUTE_GRADING_PIPELINE}
        r._definition_cache["def-001"] = defn
        instance = make_instance(status="GRADING")

        with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
            result = await r._handle_grading(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert r._pipeline_retry_counts["inst-001:compute_grading"] == 1

    async def test_failed_handler_exhausts_retries(self):
        """Failed handler past max_retries should terminate session."""
        r = make_reconciler()
        handler = MagicMock(spec=LifecyclePhaseHandler)
        handler.is_running = False
        handler.result = PipelineResult(pipeline_name="compute_grading", status="failed", duration_seconds=1.0, error="fail", max_retries=2)
        r._active_handlers["inst-001:compute_grading"] = handler
        r._pipeline_retry_counts["inst-001:compute_grading"] = 1

        instance = make_instance(status="GRADING")

        result = await r._handle_grading(instance)

        assert result.status == ReconciliationStatus.FAILED
        r._api.terminate_session.assert_awaited_once()

    async def test_no_pipeline_def_terminates_session(self):
        """Missing compute_grading pipeline should terminate session."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {}
        r._definition_cache["def-001"] = defn
        instance = make_instance(status="GRADING")

        result = await r._handle_grading(instance)

        assert result.status == ReconciliationStatus.FAILED
        r._api.terminate_session.assert_awaited_once()


class TestHandleGradingResumability:
    """Tests for Sprint F resumability — _handle_grading uses pipeline_progress."""

    async def test_passes_generic_progress_to_handler(self):
        """Should pass pipeline_progress['compute_grading'] as existing_progress."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {"compute_grading": COMPUTE_GRADING_PIPELINE}
        r._definition_cache["def-001"] = defn

        grading_progress = {"load_rubric": {"status": "completed", "result_data": {"rubric_id": "rub-001"}}}
        instance = make_instance(
            status="GRADING",
            pipeline_progress={"compute_grading": grading_progress},
        )

        with patch.object(LifecyclePhaseHandler, "__init__", return_value=None) as mock_init:
            with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
                result = await r._handle_grading(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        init_kwargs = mock_init.call_args
        assert init_kwargs.kwargs.get("existing_progress") is grading_progress

    async def test_passes_none_when_no_progress(self):
        """Should pass None when no pipeline_progress exists for compute_grading."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {"compute_grading": COMPUTE_GRADING_PIPELINE}
        r._definition_cache["def-001"] = defn

        instance = make_instance(status="GRADING", pipeline_progress=None)

        with patch.object(LifecyclePhaseHandler, "__init__", return_value=None) as mock_init:
            with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
                result = await r._handle_grading(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        init_kwargs = mock_init.call_args
        assert init_kwargs.kwargs.get("existing_progress") is None


# =============================================================================
# Status Routing — COLLECTING/GRADING dispatched in _reconcile_inner
# =============================================================================


class TestStatusRouting:
    """Tests for COLLECTING and GRADING status routing."""

    async def test_collecting_status_dispatches_to_handle_collecting(self):
        """COLLECTING status should route to _handle_collecting."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {"collect_evidence": COLLECT_EVIDENCE_PIPELINE}
        r._definition_cache["def-001"] = defn
        instance = make_instance(status="COLLECTING")
        r._worker_cache["worker-001"] = MagicMock(status="running")

        with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
            result = await r.reconcile(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert "inst-001:collect_evidence" in r._active_handlers

    async def test_grading_status_dispatches_to_handle_grading(self):
        """GRADING status should route to _handle_grading."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {"compute_grading": COMPUTE_GRADING_PIPELINE}
        r._definition_cache["def-001"] = defn
        instance = make_instance(status="GRADING")
        r._worker_cache["worker-001"] = MagicMock(status="running")

        with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
            result = await r.reconcile(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert "inst-001:compute_grading" in r._active_handlers

    async def test_stopping_status_dispatches_to_handle_stopping(self):
        """STOPPING status should route to _handle_stopping (fire-and-check)."""
        r = make_reconciler()
        defn = make_definition()
        defn.pipelines = {"teardown": TEARDOWN_PIPELINE}
        r._definition_cache["def-001"] = defn
        instance = make_instance(status="STOPPING")
        r._worker_cache["worker-001"] = MagicMock(status="running")

        with patch.object(LifecyclePhaseHandler, "start", new_callable=AsyncMock):
            result = await r.reconcile(instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert "inst-001:teardown" in r._active_handlers

    async def test_collecting_requires_worker_ip(self):
        """COLLECTING status without worker_ip should fail."""
        r = make_reconciler()
        instance = make_instance(status="COLLECTING", worker_ip=None)
        r._worker_cache["worker-001"] = MagicMock(status="running")

        result = await r.reconcile(instance)

        assert result.status == ReconciliationStatus.FAILED
        assert "connection details missing" in result.message.lower()

    async def test_grading_requires_worker_ip(self):
        """GRADING status without worker_ip should fail."""
        r = make_reconciler()
        instance = make_instance(status="GRADING", worker_ip=None)
        r._worker_cache["worker-001"] = MagicMock(status="running")

        result = await r.reconcile(instance)

        assert result.status == ReconciliationStatus.FAILED
        assert "connection details missing" in result.message.lower()


# =============================================================================
# D7: Seed File Validation — all handler names resolve to _step_* methods
# =============================================================================


class TestSeedFileHandlerValidation:
    """Meta-test: ensures all handler names in seed YAML files resolve to registered step handlers.

    Prevents drift between seed definitions and the step handler registry (ADR-038).
    """

    @staticmethod
    def _get_seed_files() -> list[str]:
        """Find all seed YAML files with pipeline definitions."""
        # Walk up from test dir to find the control-plane-api seeds
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        seeds_dir = os.path.join(base, "control-plane-api", "data", "seeds", "lablet_definitions")
        pattern = os.path.join(seeds_dir, "*.yaml")
        files = glob.glob(pattern)
        assert len(files) > 0, f"No seed YAML files found at {seeds_dir}"
        return files

    @staticmethod
    def _extract_handler_names(yaml_path: str) -> set[str]:
        """Extract all handler names from all pipelines in a seed YAML file."""
        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        handlers: set[str] = set()
        pipelines = data.get("pipelines", {})
        for _pipeline_name, pipeline_def in pipelines.items():
            if not isinstance(pipeline_def, dict):
                continue
            for step in pipeline_def.get("steps", []):
                handler_name = step.get("handler")
                if handler_name:
                    handlers.add(handler_name)

        return handlers

    def test_all_seed_handlers_have_registered_handlers(self):
        """Every handler in every seed YAML must be registered in the step handler registry (ADR-038)."""
        # Ensure step handlers are registered. If a prior test (test_step_registry)
        # cleared the global registry, we must reload each handler module to
        # re-trigger the @step_handler decorator side-effects.
        import importlib

        from application.services.step_handlers import (
            archive_step,
            capture_configs_step,
            capture_screenshots_step,
            cml_command_step,
            content_sync_step,
            deregister_lds_step,
            evaluate_step,
            export_pcaps_step,
            lab_binding_step,
            lab_resolve_step,
            lab_start_step,
            lds_provision_step,
            load_rubric_step,
            mark_ready_step,
            package_evidence_step,
            ports_alloc_step,
            record_score_step,
            stop_lab_step,
            tags_sync_step,
            variables_step,
            wipe_lab_step,
        )

        for mod in [
            archive_step,
            capture_configs_step,
            capture_screenshots_step,
            cml_command_step,
            content_sync_step,
            deregister_lds_step,
            evaluate_step,
            export_pcaps_step,
            lab_binding_step,
            lab_resolve_step,
            lab_start_step,
            lds_provision_step,
            load_rubric_step,
            mark_ready_step,
            package_evidence_step,
            ports_alloc_step,
            record_score_step,
            stop_lab_step,
            tags_sync_step,
            variables_step,
            wipe_lab_step,
        ]:
            importlib.reload(mod)

        seed_files = self._get_seed_files()

        missing: list[str] = []
        for seed_file in seed_files:
            handler_names = self._extract_handler_names(seed_file)
            filename = os.path.basename(seed_file)
            for handler_name in sorted(handler_names):
                if get_handler(handler_name) is None:
                    missing.append(f"{filename}: {handler_name}")

        assert not missing, "Missing registered step handlers for seed definitions:\n  " + "\n  ".join(missing)

    def test_all_seed_files_have_pipelines(self):
        """Every seed YAML must define at least one pipeline."""
        seed_files = self._get_seed_files()

        for seed_file in seed_files:
            with open(seed_file) as f:
                data = yaml.safe_load(f)

            filename = os.path.basename(seed_file)
            pipelines = data.get("pipelines", {})
            assert len(pipelines) > 0, f"Seed file {filename} has no pipelines defined"

    def test_teardown_pipeline_present_in_all_seeds(self):
        """Every seed YAML must have a 'teardown' pipeline (all sessions must be cleanable)."""
        seed_files = self._get_seed_files()

        for seed_file in seed_files:
            with open(seed_file) as f:
                data = yaml.safe_load(f)

            filename = os.path.basename(seed_file)
            pipelines = data.get("pipelines", {})
            assert "teardown" in pipelines, f"Seed file {filename} missing 'teardown' pipeline"
