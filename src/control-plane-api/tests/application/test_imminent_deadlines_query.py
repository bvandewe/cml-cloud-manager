"""Unit tests for GetSessionsWithImminentDeadlinesQuery handler.

AD-TIMESLOT-001: Server-side filtering for sessions with imminent
timeslot deadlines using MongoDB indexes.

Tests cover:
- Approaching start: SCHEDULED sessions within boot window
- Past end: non-terminal sessions past timeslot_end
- Mixed results: both lists populated
- Empty results: no imminent deadlines
- Error handling: repository exceptions
- DTO mapping: correct field extraction

Pattern: pytest fixtures + MagicMock(spec=...) + AsyncMock, matching
test_lablet_session_queries.py style.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.queries.lablet_session.get_sessions_with_imminent_deadlines_query import (
    GetSessionsWithImminentDeadlinesQuery,
    GetSessionsWithImminentDeadlinesQueryHandler,
    ImminentDeadlinesResult,
    SessionDeadlineInfo,
)
from domain.entities.lablet_session import LabletSession, LabletSessionState
from domain.enums import LabletSessionStatus
from domain.repositories.lablet_session_repository import LabletSessionRepository

# =============================================================================
# Shared fixtures
# =============================================================================


@pytest.fixture
def mock_session_repository() -> MagicMock:
    mock = MagicMock(spec=LabletSessionRepository)
    mock.list_approaching_start_async = AsyncMock(return_value=[])
    mock.list_past_end_async = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def handler(mock_session_repository: MagicMock) -> GetSessionsWithImminentDeadlinesQueryHandler:
    return GetSessionsWithImminentDeadlinesQueryHandler(
        lablet_session_repository=mock_session_repository,
    )


def _make_session(
    session_id: str = "session-001",
    status: LabletSessionStatus = LabletSessionStatus.SCHEDULED,
    definition_id: str = "def-001",
    worker_id: str | None = None,
    timeslot_start: datetime | None = None,
    timeslot_end: datetime | None = None,
) -> MagicMock:
    """Create a mock LabletSession with state for deadline queries."""
    session = MagicMock(spec=LabletSession)
    session.id.return_value = session_id

    state = MagicMock(spec=LabletSessionState)
    state.status = status
    state.definition_id = definition_id
    state.worker_id = worker_id
    state.timeslot_start = timeslot_start or (datetime.now(timezone.utc) + timedelta(minutes=20))
    state.timeslot_end = timeslot_end or (datetime.now(timezone.utc) + timedelta(hours=2))

    session.state = state
    return session


# =============================================================================
# Tests: Approaching Start
# =============================================================================


@pytest.mark.unit
@pytest.mark.query
class TestImminentDeadlinesApproachingStart:
    @pytest.mark.asyncio
    async def test_returns_approaching_sessions(self, handler, mock_session_repository):
        ts_start = datetime.now(timezone.utc) + timedelta(minutes=15)
        session = _make_session(
            session_id="sess-approaching",
            status=LabletSessionStatus.SCHEDULED,
            timeslot_start=ts_start,
        )
        mock_session_repository.list_approaching_start_async.return_value = [session]

        query = GetSessionsWithImminentDeadlinesQuery(boot_window_minutes=35)
        result = await handler.handle_async(query)

        assert result.is_success
        data: ImminentDeadlinesResult = result.data
        assert len(data.approaching_start) == 1
        assert data.approaching_start[0].id == "sess-approaching"
        assert data.approaching_start[0].status == "scheduled"

    @pytest.mark.asyncio
    async def test_approaching_start_uses_boot_window(self, handler, mock_session_repository):
        """Verify that the handler passes the correct threshold to the repository."""
        query = GetSessionsWithImminentDeadlinesQuery(boot_window_minutes=45)
        await handler.handle_async(query)

        # The handler should call with `before = now + 45min`
        call_args = mock_session_repository.list_approaching_start_async.call_args
        before_arg: datetime = call_args.kwargs.get("before") or call_args.args[0]
        now = datetime.now(timezone.utc)
        expected_min = now + timedelta(minutes=44)
        expected_max = now + timedelta(minutes=46)
        assert expected_min <= before_arg <= expected_max

    @pytest.mark.asyncio
    async def test_multiple_approaching_sessions(self, handler, mock_session_repository):
        sessions = [_make_session(session_id=f"sess-{i}", status=LabletSessionStatus.SCHEDULED) for i in range(3)]
        mock_session_repository.list_approaching_start_async.return_value = sessions

        result = await handler.handle_async(GetSessionsWithImminentDeadlinesQuery())

        assert result.is_success
        assert len(result.data.approaching_start) == 3


# =============================================================================
# Tests: Past End
# =============================================================================


@pytest.mark.unit
@pytest.mark.query
class TestImminentDeadlinesPastEnd:
    @pytest.mark.asyncio
    async def test_returns_past_end_sessions(self, handler, mock_session_repository):
        ts_end = datetime.now(timezone.utc) - timedelta(minutes=10)
        session = _make_session(
            session_id="sess-expired",
            status=LabletSessionStatus.RUNNING,
            timeslot_end=ts_end,
        )
        mock_session_repository.list_past_end_async.return_value = [session]

        result = await handler.handle_async(GetSessionsWithImminentDeadlinesQuery())

        assert result.is_success
        data: ImminentDeadlinesResult = result.data
        assert len(data.past_end) == 1
        assert data.past_end[0].id == "sess-expired"
        assert data.past_end[0].status == "running"

    @pytest.mark.asyncio
    async def test_past_end_uses_current_time(self, handler, mock_session_repository):
        """Verify the handler passes ~now to list_past_end_async."""
        await handler.handle_async(GetSessionsWithImminentDeadlinesQuery())

        call_args = mock_session_repository.list_past_end_async.call_args
        as_of_arg: datetime = call_args.kwargs.get("as_of") or call_args.args[0]
        now = datetime.now(timezone.utc)
        # Should be within ~2 seconds of now
        assert abs((as_of_arg - now).total_seconds()) < 2

    @pytest.mark.asyncio
    async def test_past_end_preserves_non_terminal_statuses(self, handler, mock_session_repository):
        """Sessions in various non-terminal statuses should all appear."""
        sessions = [
            _make_session("sess-sched", status=LabletSessionStatus.SCHEDULED),
            _make_session("sess-running", status=LabletSessionStatus.RUNNING),
            _make_session("sess-instantiating", status=LabletSessionStatus.INSTANTIATING),
        ]
        mock_session_repository.list_past_end_async.return_value = sessions

        result = await handler.handle_async(GetSessionsWithImminentDeadlinesQuery())

        assert result.is_success
        statuses = {s.status for s in result.data.past_end}
        assert statuses == {"scheduled", "running", "instantiating"}


# =============================================================================
# Tests: Mixed & Empty
# =============================================================================


@pytest.mark.unit
@pytest.mark.query
class TestImminentDeadlinesMixed:
    @pytest.mark.asyncio
    async def test_both_approaching_and_past_end(self, handler, mock_session_repository):
        approaching = _make_session("sess-A", status=LabletSessionStatus.SCHEDULED)
        past = _make_session("sess-B", status=LabletSessionStatus.RUNNING)

        mock_session_repository.list_approaching_start_async.return_value = [approaching]
        mock_session_repository.list_past_end_async.return_value = [past]

        result = await handler.handle_async(GetSessionsWithImminentDeadlinesQuery())

        assert result.is_success
        assert len(result.data.approaching_start) == 1
        assert len(result.data.past_end) == 1
        assert result.data.approaching_start[0].id == "sess-A"
        assert result.data.past_end[0].id == "sess-B"

    @pytest.mark.asyncio
    async def test_empty_results(self, handler, mock_session_repository):
        result = await handler.handle_async(GetSessionsWithImminentDeadlinesQuery())

        assert result.is_success
        assert len(result.data.approaching_start) == 0
        assert len(result.data.past_end) == 0


# =============================================================================
# Tests: DTO Mapping
# =============================================================================


@pytest.mark.unit
@pytest.mark.query
class TestImminentDeadlinesDtoMapping:
    @pytest.mark.asyncio
    async def test_dto_maps_all_fields_correctly(self, handler, mock_session_repository):
        ts_start = datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
        ts_end = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        session = _make_session(
            session_id="sess-full",
            status=LabletSessionStatus.SCHEDULED,
            definition_id="def-cisco-101",
            worker_id="worker-42",
            timeslot_start=ts_start,
            timeslot_end=ts_end,
        )
        mock_session_repository.list_approaching_start_async.return_value = [session]

        result = await handler.handle_async(GetSessionsWithImminentDeadlinesQuery())

        dto: SessionDeadlineInfo = result.data.approaching_start[0]
        assert dto.id == "sess-full"
        assert dto.status == "scheduled"
        assert dto.timeslot_start == "2025-06-15T10:00:00+00:00"
        assert dto.timeslot_end == "2025-06-15T12:00:00+00:00"
        assert dto.worker_id == "worker-42"
        assert dto.definition_id == "def-cisco-101"

    @pytest.mark.asyncio
    async def test_dto_handles_none_timeslots(self, handler, mock_session_repository):
        session = _make_session(session_id="sess-no-ts")
        session.state.timeslot_start = None
        session.state.timeslot_end = None
        mock_session_repository.list_approaching_start_async.return_value = [session]

        result = await handler.handle_async(GetSessionsWithImminentDeadlinesQuery())

        dto = result.data.approaching_start[0]
        assert dto.timeslot_start is None
        assert dto.timeslot_end is None

    @pytest.mark.asyncio
    async def test_dto_handles_enum_status_value(self, handler, mock_session_repository):
        """Verify status is serialized as string value, not enum repr."""
        session = _make_session(status=LabletSessionStatus.RUNNING)
        mock_session_repository.list_past_end_async.return_value = [session]

        result = await handler.handle_async(GetSessionsWithImminentDeadlinesQuery())

        assert result.data.past_end[0].status == "running"


# =============================================================================
# Tests: Error Handling
# =============================================================================


@pytest.mark.unit
@pytest.mark.query
class TestImminentDeadlinesErrors:
    @pytest.mark.asyncio
    async def test_repository_error_returns_500(self, handler, mock_session_repository):
        mock_session_repository.list_approaching_start_async.side_effect = Exception("MongoDB down")

        result = await handler.handle_async(GetSessionsWithImminentDeadlinesQuery())

        assert not result.is_success
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_partial_repo_error_returns_500(self, handler, mock_session_repository):
        """If one of the two queries fails, the whole request fails."""
        mock_session_repository.list_approaching_start_async.return_value = []
        mock_session_repository.list_past_end_async.side_effect = Exception("timeout")

        result = await handler.handle_async(GetSessionsWithImminentDeadlinesQuery())

        assert not result.is_success
        assert result.status_code == 500
