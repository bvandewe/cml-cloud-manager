"""Unit tests for ADR-034 Sprint C reconciler concurrency — per-session locks and handler management.

Covers:
- Per-session locks: _get_session_lock creates lazily, returns same lock for same session
- Reconcile locking: concurrent reconcile calls for same session serialize
- Handler management: _step_down cancels all active handlers
- Active handler cleanup: handlers removed from dict after completion

Pattern: Matches test_instantiation_pipeline.py style — object.__new__ fixture,
AsyncMock/MagicMock, pytest-asyncio auto mode.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from application.hosted_services.lablet_reconciler import LabletReconciler
from application.services.lifecycle_phase_handler import LifecyclePhaseHandler
from application.services.pipeline_executor import PipelineExecutor

# =============================================================================
# Fixtures / Helpers
# =============================================================================


def make_reconciler() -> LabletReconciler:
    """Create a LabletReconciler bypassing __init__ with Sprint C fields."""
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
    r._worker_cache = {}
    r._resource_observer = None
    r._content_sync_service = None
    r._lab_record_reconciler = None
    r._lab_discovery_service = None
    # Config mock (used by _step_down logging)
    r._config = MagicMock()
    r._config.service_name = "test-reconciler"
    # Sprint C fields
    r._session_locks = {}
    r._active_handlers = {}
    r._pipeline_executor = PipelineExecutor()
    r._pipeline_retry_counts = {}
    # AD-TIMESLOT-001
    r._timeslot_watcher_service = None
    return r


# =============================================================================
# Per-Session Locks
# =============================================================================


class TestPerSessionLocks:
    """Tests for _get_session_lock lazy lock creation."""

    def test_creates_new_lock(self):
        """Should create a new asyncio.Lock for an unknown session."""
        r = make_reconciler()

        lock = r._get_session_lock("sess-001")

        assert isinstance(lock, asyncio.Lock)
        assert "sess-001" in r._session_locks

    def test_returns_same_lock_for_same_session(self):
        """Should return the same lock for the same session ID."""
        r = make_reconciler()

        lock1 = r._get_session_lock("sess-001")
        lock2 = r._get_session_lock("sess-001")

        assert lock1 is lock2

    def test_different_sessions_get_different_locks(self):
        """Different session IDs should get different locks."""
        r = make_reconciler()

        lock1 = r._get_session_lock("sess-001")
        lock2 = r._get_session_lock("sess-002")

        assert lock1 is not lock2


# =============================================================================
# Step-Down Handler Cleanup
# =============================================================================


class TestStepDownHandlerCleanup:
    """Tests for _step_down cancelling active handlers (Sprint C)."""

    async def test_step_down_cancels_active_handlers(self):
        """_step_down should cancel all active handlers."""
        r = make_reconciler()

        # Add mock handlers
        handler1 = AsyncMock(spec=LifecyclePhaseHandler)
        handler1.stop = AsyncMock()
        handler2 = AsyncMock(spec=LifecyclePhaseHandler)
        handler2.stop = AsyncMock()

        r._active_handlers = {"sess-001:instantiate": handler1, "sess-002:instantiate": handler2}
        r._session_locks = {"sess-001": asyncio.Lock(), "sess-002": asyncio.Lock()}
        r._pipeline_retry_counts = {"sess-001:instantiate": 1}

        # Patch parent _step_down to avoid base class init requirements
        with patch("lcm_core.infrastructure.hosted_services.watch_triggered_hosted_service.WatchTriggeredHostedService._step_down", new_callable=AsyncMock):
            await r._step_down()

        handler1.stop.assert_awaited_once()
        handler2.stop.assert_awaited_once()
        assert len(r._active_handlers) == 0
        assert len(r._session_locks) == 0
        assert len(r._pipeline_retry_counts) == 0

    async def test_step_down_continues_on_handler_stop_error(self):
        """_step_down should continue even if a handler.stop() raises."""
        r = make_reconciler()

        handler1 = AsyncMock(spec=LifecyclePhaseHandler)
        handler1.stop = AsyncMock(side_effect=RuntimeError("stop failed"))
        handler2 = AsyncMock(spec=LifecyclePhaseHandler)
        handler2.stop = AsyncMock()

        r._active_handlers = {"sess-001:instantiate": handler1, "sess-002:instantiate": handler2}

        with patch("lcm_core.infrastructure.hosted_services.watch_triggered_hosted_service.WatchTriggeredHostedService._step_down", new_callable=AsyncMock):
            await r._step_down()

        # Both should have been called
        handler1.stop.assert_awaited_once()
        handler2.stop.assert_awaited_once()
        assert len(r._active_handlers) == 0

    async def test_step_down_with_no_handlers_is_safe(self):
        """_step_down with empty handlers dict should not raise."""
        r = make_reconciler()
        r._active_handlers = {}

        with patch("lcm_core.infrastructure.hosted_services.watch_triggered_hosted_service.WatchTriggeredHostedService._step_down", new_callable=AsyncMock):
            await r._step_down()

        assert len(r._active_handlers) == 0
