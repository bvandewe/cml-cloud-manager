"""Unit tests for Sprint G3: Admin Pipeline Control Endpoints.

Tests the 4 new AdminController endpoints:
- POST /admin/sessions/{session_id}/retry-pipeline
- POST /admin/sessions/{session_id}/cancel-pipeline
- GET  /admin/sessions/{session_id}/pipeline-status
- GET  /admin/active-handlers

Pattern: Matches test_lifecycle_phase_handler.py style — plain fixtures, AsyncMock/MagicMock,
pytest-asyncio auto mode. Tests call endpoint functions directly (no TestClient/HTTP layer)
since AdminController uses plain FastAPI router with closures.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.controllers.admin_controller import AdminController
from application.models.pipeline_result import PipelineResult
from application.services.lifecycle_phase_handler import LifecyclePhaseHandler

# =============================================================================
# Fixtures / Helpers
# =============================================================================


def make_mock_handler(
    session_id: str = "sess-001",
    pipeline_name: str = "instantiate",
    is_running: bool = True,
    pipeline_attempt: int = 1,
    result: PipelineResult | None = None,
    error: Exception | None = None,
) -> MagicMock:
    """Build a mock LifecyclePhaseHandler with configurable state."""
    handler = MagicMock(spec=LifecyclePhaseHandler)
    handler.session_id = session_id
    handler.pipeline_name = pipeline_name
    handler.is_running = is_running
    handler.pipeline_attempt = pipeline_attempt
    handler.result = result
    handler.error = error
    handler.stop = AsyncMock()
    return handler


def make_reconciler(
    is_leader: bool = True,
    active_handlers: dict | None = None,
    retry_counts: dict | None = None,
) -> MagicMock:
    """Build a mock LabletReconciler with _active_handlers and _pipeline_retry_counts."""
    reconciler = MagicMock()
    reconciler.is_leader = is_leader
    reconciler._active_handlers = active_handlers or {}
    reconciler._pipeline_retry_counts = retry_counts or {}
    return reconciler


def make_admin_user() -> dict:
    """Build a mock admin user dict."""
    return {"username": "test-admin", "roles": ["admin"]}


def build_controller(reconciler: MagicMock) -> AdminController:
    """Build AdminController with mock reconciler."""
    return AdminController(reconciler)


async def call_endpoint(controller: AdminController, endpoint_name: str, **kwargs):
    """Call an endpoint function from the controller's router by operation_id/summary.

    Since AdminController registers routes as closures inside _register_routes,
    we need to look them up in the router's routes by path.
    """
    for route in controller.router.routes:
        if hasattr(route, "path") and hasattr(route, "endpoint"):
            if route.name == endpoint_name:
                return await route.endpoint(**kwargs)
    raise ValueError(f"Endpoint '{endpoint_name}' not found in router routes")


# =============================================================================
# Retry Pipeline Tests
# =============================================================================


class TestRetryPipeline:
    """Tests for POST /admin/sessions/{session_id}/retry-pipeline."""

    async def test_retry_clears_handler_and_resets_retry_count(self):
        """Retry removes handler from active, resets retry count, returns 200."""
        handler = make_mock_handler(session_id="sess-001", pipeline_name="instantiate", is_running=False)
        reconciler = make_reconciler(
            active_handlers={"sess-001:instantiate": handler},
            retry_counts={"sess-001:instantiate": 3},
        )
        controller = build_controller(reconciler)
        user = make_admin_user()

        result = await call_endpoint(controller, "retry_pipeline", session_id="sess-001", user=user)

        assert result["status"] == "retry_scheduled"
        assert "sess-001:instantiate" in result["cleared_handlers"]
        assert "sess-001:instantiate" not in reconciler._active_handlers
        assert "sess-001:instantiate" not in reconciler._pipeline_retry_counts

    async def test_retry_stops_running_handler_before_clearing(self):
        """Retry stops a still-running handler before removing it."""
        handler = make_mock_handler(session_id="sess-002", pipeline_name="teardown", is_running=True)
        reconciler = make_reconciler(
            active_handlers={"sess-002:teardown": handler},
        )
        controller = build_controller(reconciler)
        user = make_admin_user()

        result = await call_endpoint(controller, "retry_pipeline", session_id="sess-002", user=user)

        handler.stop.assert_awaited_once()
        assert result["status"] == "retry_scheduled"
        assert "sess-002:teardown" not in reconciler._active_handlers

    async def test_retry_returns_404_for_unknown_session(self):
        """Retry raises 404 when no handler exists for the session."""
        reconciler = make_reconciler(active_handlers={})
        controller = build_controller(reconciler)
        user = make_admin_user()

        with pytest.raises(Exception) as exc_info:
            await call_endpoint(controller, "retry_pipeline", session_id="unknown", user=user)
        assert exc_info.value.status_code == 404

    async def test_retry_requires_leader(self):
        """Retry raises 409 when instance is not the leader."""
        reconciler = make_reconciler(is_leader=False)
        controller = build_controller(reconciler)
        user = make_admin_user()

        with pytest.raises(Exception) as exc_info:
            await call_endpoint(controller, "retry_pipeline", session_id="sess-001", user=user)
        assert exc_info.value.status_code == 409


# =============================================================================
# Cancel Pipeline Tests
# =============================================================================


class TestCancelPipeline:
    """Tests for POST /admin/sessions/{session_id}/cancel-pipeline."""

    async def test_cancel_stops_handler_and_removes(self):
        """Cancel stops the handler and removes from active handlers."""
        handler = make_mock_handler(session_id="sess-001", pipeline_name="instantiate", is_running=True)
        reconciler = make_reconciler(
            active_handlers={"sess-001:instantiate": handler},
        )
        controller = build_controller(reconciler)
        user = make_admin_user()

        result = await call_endpoint(controller, "cancel_pipeline", session_id="sess-001", user=user)

        handler.stop.assert_awaited_once()
        assert result["status"] == "cancelled"
        assert "sess-001:instantiate" not in reconciler._active_handlers

    async def test_cancel_keeps_retry_count(self):
        """Cancel preserves retry count to prevent reconciler from restarting."""
        handler = make_mock_handler(session_id="sess-001", pipeline_name="instantiate")
        reconciler = make_reconciler(
            active_handlers={"sess-001:instantiate": handler},
            retry_counts={"sess-001:instantiate": 2},
        )
        controller = build_controller(reconciler)
        user = make_admin_user()

        await call_endpoint(controller, "cancel_pipeline", session_id="sess-001", user=user)

        # Retry count preserved — reconciler won't restart automatically
        assert reconciler._pipeline_retry_counts.get("sess-001:instantiate") == 2

    async def test_cancel_returns_404_for_unknown_session(self):
        """Cancel raises 404 when no handler exists for the session."""
        reconciler = make_reconciler(active_handlers={})
        controller = build_controller(reconciler)
        user = make_admin_user()

        with pytest.raises(Exception) as exc_info:
            await call_endpoint(controller, "cancel_pipeline", session_id="unknown", user=user)
        assert exc_info.value.status_code == 404


# =============================================================================
# Pipeline Status Tests
# =============================================================================


class TestPipelineStatus:
    """Tests for GET /admin/sessions/{session_id}/pipeline-status."""

    async def test_status_returns_running_handler_state(self):
        """Status returns handler info for a running pipeline."""
        handler = make_mock_handler(
            session_id="sess-001",
            pipeline_name="instantiate",
            is_running=True,
            pipeline_attempt=2,
        )
        reconciler = make_reconciler(
            active_handlers={"sess-001:instantiate": handler},
            retry_counts={"sess-001:instantiate": 1},
        )
        controller = build_controller(reconciler)

        result = await call_endpoint(controller, "pipeline_status", session_id="sess-001")

        assert result["session_id"] == "sess-001"
        assert len(result["handlers"]) == 1
        h = result["handlers"][0]
        assert h["pipeline_name"] == "instantiate"
        assert h["is_running"] is True
        assert h["attempt"] == 2
        assert h["retry_count"] == 1
        assert h["result_status"] == "running"

    async def test_status_returns_completed_handler_with_result(self):
        """Status returns result details for a completed pipeline."""
        completed_result = PipelineResult(
            pipeline_name="instantiate",
            status="completed",
            steps_completed=5,
            steps_failed=0,
            steps_skipped=1,
            duration_seconds=12.5,
        )
        handler = make_mock_handler(
            session_id="sess-001",
            pipeline_name="instantiate",
            is_running=False,
            pipeline_attempt=1,
            result=completed_result,
        )
        reconciler = make_reconciler(
            active_handlers={"sess-001:instantiate": handler},
        )
        controller = build_controller(reconciler)

        result = await call_endpoint(controller, "pipeline_status", session_id="sess-001")

        h = result["handlers"][0]
        assert h["result_status"] == "completed"
        assert h["steps_completed"] == 5
        assert h["steps_skipped"] == 1
        assert h["duration_seconds"] == 12.5

    async def test_status_returns_404_for_unknown_session(self):
        """Status raises 404 when no handler exists for the session."""
        reconciler = make_reconciler(active_handlers={})
        controller = build_controller(reconciler)

        with pytest.raises(Exception) as exc_info:
            await call_endpoint(controller, "pipeline_status", session_id="unknown")
        assert exc_info.value.status_code == 404

    async def test_status_returns_crashed_handler(self):
        """Status returns crash info when handler errored."""
        handler = make_mock_handler(
            session_id="sess-001",
            pipeline_name="instantiate",
            is_running=False,
            error=RuntimeError("CML API timeout"),
        )
        reconciler = make_reconciler(
            active_handlers={"sess-001:instantiate": handler},
        )
        controller = build_controller(reconciler)

        result = await call_endpoint(controller, "pipeline_status", session_id="sess-001")

        h = result["handlers"][0]
        assert h["result_status"] == "crashed"
        assert "CML API timeout" in h["crash_error"]


# =============================================================================
# Active Handlers Tests
# =============================================================================


class TestActiveHandlers:
    """Tests for GET /admin/active-handlers."""

    async def test_active_handlers_lists_all(self):
        """Active handlers returns all handlers with status."""
        handler1 = make_mock_handler(session_id="sess-001", pipeline_name="instantiate", is_running=True)
        handler2 = make_mock_handler(
            session_id="sess-002",
            pipeline_name="teardown",
            is_running=False,
            result=PipelineResult(pipeline_name="teardown", status="completed", steps_completed=3, duration_seconds=5.0),
        )
        reconciler = make_reconciler(
            active_handlers={
                "sess-001:instantiate": handler1,
                "sess-002:teardown": handler2,
            },
        )
        controller = build_controller(reconciler)

        result = await call_endpoint(controller, "active_handlers")

        assert result["total"] == 2
        names = {h["pipeline_name"] for h in result["handlers"]}
        assert names == {"instantiate", "teardown"}
        # Verify completed handler has result info
        teardown = next(h for h in result["handlers"] if h["pipeline_name"] == "teardown")
        assert teardown["result_status"] == "completed"

    async def test_active_handlers_empty(self):
        """Active handlers returns empty list when no handlers exist."""
        reconciler = make_reconciler(active_handlers={})
        controller = build_controller(reconciler)

        result = await call_endpoint(controller, "active_handlers")

        assert result["total"] == 0
        assert result["handlers"] == []
