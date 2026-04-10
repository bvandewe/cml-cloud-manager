"""Unit tests for Sprint H admin timeslot query endpoints.

Tests cover the three new admin endpoints:
- GET /admin/timeslots/approaching — PENDING sessions entering scheduling window
- GET /admin/timeslots/expired — Sessions with expired timeslots
- GET /admin/timeslots/landscape — Timeslot distribution for next 24h

Pattern: AsyncMock for CPA client and TimeslotManagerHostedService,
direct invocation of route handler callables via AdminController.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.controllers.admin_controller import AdminController
from application.hosted_services import SchedulerHostedService

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_scheduler():
    """Mock SchedulerHostedService."""
    scheduler = MagicMock(spec=SchedulerHostedService)
    scheduler._api = AsyncMock()
    scheduler.stats = {"reconcile_count": 0}
    return scheduler


@pytest.fixture
def mock_timeslot_manager():
    """Mock TimeslotManagerHostedService with async methods."""
    mgr = AsyncMock()
    mgr.stats = {
        "enabled": True,
        "is_leader": True,
        "scan_count": 5,
        "triggers": 2,
        "expirations": 1,
        "tracked_triggered": 2,
        "tracked_expired": 1,
        "last_scan_at": "2026-03-10T12:00:00+00:00",
        "last_error": None,
        "interval_seconds": 60,
        "lead_time_minutes": 35,
        "expiry_grace_minutes": 5,
    }
    mgr.triggered_session_ids = {"sess-1", "sess-2"}
    mgr.expired_session_ids = {"sess-3"}
    mgr.get_approaching_sessions = AsyncMock(return_value=[])
    mgr.get_expired_sessions = AsyncMock(return_value=[])
    return mgr


@pytest.fixture
def controller(mock_scheduler, mock_timeslot_manager):
    """Create AdminController with mock dependencies."""
    return AdminController(
        scheduler=mock_scheduler,
        timeslot_manager=mock_timeslot_manager,
    )


@pytest.fixture
def controller_no_timeslot(mock_scheduler):
    """Create AdminController with no TimeslotManager (disabled)."""
    return AdminController(
        scheduler=mock_scheduler,
        timeslot_manager=None,
    )


def _get_route_handler(controller: AdminController, path: str):
    """Get the route handler function for a given path from the router.

    Routes are registered with the full prefix (e.g., /admin/timeslots/status).
    We match against the full path including the router prefix.
    """
    full_path = f"/admin{path}"
    for route in controller.router.routes:
        if hasattr(route, "path") and route.path == full_path:
            return route.endpoint
    raise ValueError(f"No route found for path: {full_path}")


# =============================================================================
# Tests: /admin/timeslots/approaching
# =============================================================================


class TestTimeslotApproaching:
    """Tests for GET /admin/timeslots/approaching."""

    @pytest.mark.asyncio
    async def test_returns_approaching_sessions(self, controller, mock_timeslot_manager):
        """Should return approaching sessions from live CPA query."""
        sessions = [
            {"id": "sess-1", "status": "PENDING", "timeslot_start": "2026-03-10T12:30:00Z"},
            {"id": "sess-2", "status": "PENDING", "timeslot_start": "2026-03-10T12:45:00Z"},
        ]
        mock_timeslot_manager.get_approaching_sessions = AsyncMock(return_value=sessions)

        handler = _get_route_handler(controller, "/timeslots/approaching")
        result = await handler()

        assert result["total"] == 2
        assert result["sessions"] == sessions
        assert result["lead_time_minutes"] == 35
        mock_timeslot_manager.get_approaching_sessions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_includes_triggered_ids(self, controller, mock_timeslot_manager):
        """Should include the set of already-triggered session IDs."""
        mock_timeslot_manager.get_approaching_sessions = AsyncMock(return_value=[])

        handler = _get_route_handler(controller, "/timeslots/approaching")
        result = await handler()

        assert set(result["tracked_triggered_ids"]) == {"sess-1", "sess-2"}

    @pytest.mark.asyncio
    async def test_empty_when_no_approaching(self, controller, mock_timeslot_manager):
        """Should return empty list when no sessions are approaching."""
        mock_timeslot_manager.get_approaching_sessions = AsyncMock(return_value=[])

        handler = _get_route_handler(controller, "/timeslots/approaching")
        result = await handler()

        assert result["total"] == 0
        assert result["sessions"] == []

    @pytest.mark.asyncio
    async def test_disabled_when_no_timeslot_manager(self, controller_no_timeslot):
        """Should return disabled message when TimeslotManager not configured."""
        handler = _get_route_handler(controller_no_timeslot, "/timeslots/approaching")
        result = await handler()

        assert result["enabled"] is False
        assert "not configured" in result["message"].lower()


# =============================================================================
# Tests: /admin/timeslots/expired
# =============================================================================


class TestTimeslotExpired:
    """Tests for GET /admin/timeslots/expired."""

    @pytest.mark.asyncio
    async def test_returns_expired_sessions(self, controller, mock_timeslot_manager):
        """Should return expired sessions from live CPA query."""
        sessions = [
            {"id": "sess-3", "status": "PENDING", "timeslot_start": "2026-03-10T10:00:00Z"},
        ]
        mock_timeslot_manager.get_expired_sessions = AsyncMock(return_value=sessions)

        handler = _get_route_handler(controller, "/timeslots/expired")
        result = await handler()

        assert result["total"] == 1
        assert result["sessions"] == sessions
        assert result["expiry_grace_minutes"] == 5
        mock_timeslot_manager.get_expired_sessions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_includes_expired_ids(self, controller, mock_timeslot_manager):
        """Should include the set of already-expired session IDs."""
        mock_timeslot_manager.get_expired_sessions = AsyncMock(return_value=[])

        handler = _get_route_handler(controller, "/timeslots/expired")
        result = await handler()

        assert result["tracked_expired_ids"] == ["sess-3"]

    @pytest.mark.asyncio
    async def test_empty_when_no_expired(self, controller, mock_timeslot_manager):
        """Should return empty list when no sessions are expired."""
        mock_timeslot_manager.expired_session_ids = set()
        mock_timeslot_manager.get_expired_sessions = AsyncMock(return_value=[])

        handler = _get_route_handler(controller, "/timeslots/expired")
        result = await handler()

        assert result["total"] == 0
        assert result["sessions"] == []
        assert result["tracked_expired_ids"] == []

    @pytest.mark.asyncio
    async def test_disabled_when_no_timeslot_manager(self, controller_no_timeslot):
        """Should return disabled message when TimeslotManager not configured."""
        handler = _get_route_handler(controller_no_timeslot, "/timeslots/expired")
        result = await handler()

        assert result["enabled"] is False


# =============================================================================
# Tests: /admin/timeslots/landscape
# =============================================================================


class TestTimeslotLandscape:
    """Tests for GET /admin/timeslots/landscape."""

    @pytest.mark.asyncio
    async def test_returns_24h_distribution(self, controller, mock_scheduler):
        """Should return a 24-hour hourly distribution."""
        mock_scheduler._api.get_lablet_sessions = AsyncMock(return_value=[])

        handler = _get_route_handler(controller, "/timeslots/landscape")
        result = await handler()

        assert "hourly_distribution" in result
        assert len(result["hourly_distribution"]) == 24
        assert result["total_in_window"] == 0

    @pytest.mark.asyncio
    async def test_sessions_bucketed_by_hour(self, controller, mock_scheduler):
        """Should bucket sessions by their timeslot_start hour."""
        now = datetime.now(timezone.utc)
        two_hours = now + timedelta(hours=2)
        bucket_key = two_hours.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00Z")

        pending = [
            {"id": "sess-A", "status": "PENDING", "timeslot_start": two_hours.isoformat()},
        ]
        scheduled = [
            {"id": "sess-B", "status": "SCHEDULED", "timeslot_start": two_hours.isoformat()},
        ]

        mock_scheduler._api.get_lablet_sessions = AsyncMock(side_effect=[pending, scheduled])

        handler = _get_route_handler(controller, "/timeslots/landscape")
        result = await handler()

        assert result["total_in_window"] == 2
        assert result["hourly_distribution"][bucket_key] == 2
        assert len(result["hourly_sessions"][bucket_key]) == 2

    @pytest.mark.asyncio
    async def test_sessions_without_timeslot_counted(self, controller, mock_scheduler):
        """Sessions with no timeslot_start should be counted separately."""
        pending = [{"id": "sess-no-ts", "status": "PENDING"}]
        mock_scheduler._api.get_lablet_sessions = AsyncMock(side_effect=[pending, []])

        handler = _get_route_handler(controller, "/timeslots/landscape")
        result = await handler()

        assert result["no_timeslot"] == 1
        assert result["total_in_window"] == 0

    @pytest.mark.asyncio
    async def test_sessions_outside_window_counted(self, controller, mock_scheduler):
        """Sessions with timeslot_start outside 24h window should be counted separately."""
        far_future = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
        pending = [{"id": "sess-far", "status": "PENDING", "timeslot_start": far_future}]
        mock_scheduler._api.get_lablet_sessions = AsyncMock(side_effect=[pending, []])

        handler = _get_route_handler(controller, "/timeslots/landscape")
        result = await handler()

        assert result["outside_window"] == 1
        assert result["total_in_window"] == 0

    @pytest.mark.asyncio
    async def test_disabled_when_no_timeslot_manager(self, controller_no_timeslot):
        """Should return disabled message when TimeslotManager not configured."""
        handler = _get_route_handler(controller_no_timeslot, "/timeslots/landscape")
        result = await handler()

        assert result["enabled"] is False

    @pytest.mark.asyncio
    async def test_window_metadata(self, controller, mock_scheduler):
        """Should include window start/end metadata."""
        mock_scheduler._api.get_lablet_sessions = AsyncMock(return_value=[])

        handler = _get_route_handler(controller, "/timeslots/landscape")
        result = await handler()

        assert "window_start" in result
        assert "window_end" in result
        # Verify 24h window
        start = datetime.fromisoformat(result["window_start"])
        end = datetime.fromisoformat(result["window_end"])
        assert (end - start).total_seconds() == pytest.approx(24 * 3600, abs=60)
