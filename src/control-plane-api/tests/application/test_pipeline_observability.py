"""Unit tests for Sprint G pipeline query handlers and handler observability.

Tests cover:
G2 — GetPipelineProgressQuery:
- Missing session_id → bad_request
- Session not found → not_found
- Returns all pipelines with step summaries
- Filters by pipeline_name when provided
- Returns found=False for unknown pipeline_name

G2 — ListPipelineExecutionsQuery:
- Missing session_id → bad_request
- Returns empty list for no records
- Returns execution summaries with step counts
- Filters by pipeline_name
- Filters by status
- Applies pagination

G1+G5 — UpdatePipelineProgressCommandHandler observability:
- Emits PipelineStepStartedEventV1 on step_status=pending
- Emits PipelineStepCompletedEventV1 on step_status=completed
- Emits PipelineStepFailedEventV1 on step_status=failed
- Emits PipelineCompletedEventV1 when all_done=True
- Creates PipelineExecutionRecord on first step (pending)
- Finalizes PipelineExecutionRecord on pipeline completion
- CloudEvent emission failure does not break handler

Pattern: pytest fixtures + MagicMock + AsyncMock.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from application.commands.lablet_session.update_pipeline_progress_command import UpdatePipelineProgressCommand, UpdatePipelineProgressCommandHandler
from application.events.integration.pipeline_events import PipelineCompletedEventV1, PipelineStepCompletedEventV1, PipelineStepFailedEventV1, PipelineStepStartedEventV1
from application.queries.lablet_session.get_pipeline_progress_query import GetPipelineProgressQuery, GetPipelineProgressQueryHandler
from application.queries.lablet_session.list_pipeline_executions_query import ListPipelineExecutionsQuery, ListPipelineExecutionsQueryHandler, _map_execution_summary
from domain.entities.lablet_session import LabletSession, LabletSessionState
from domain.entities.pipeline_execution_record import PipelineExecutionRecord
from domain.enums import LabletSessionStatus
from domain.repositories.lablet_session_repository import LabletSessionRepository
from domain.repositories.pipeline_execution_repository import PipelineExecutionRepository

# =============================================================================
# Shared fixtures
# =============================================================================


@pytest.fixture
def mock_session_repository() -> MagicMock:
    mock = MagicMock(spec=LabletSessionRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    mock.update_async = AsyncMock()
    return mock


@pytest.fixture
def mock_execution_repository() -> MagicMock:
    mock = MagicMock(spec=PipelineExecutionRepository)
    mock.add_async = AsyncMock()
    mock.update_async = AsyncMock()
    mock.get_by_session_async = AsyncMock(return_value=[])
    mock.get_by_session_and_pipeline_async = AsyncMock(return_value=[])
    mock.get_latest_by_session_and_pipeline_async = AsyncMock(return_value=None)
    return mock


def _make_session(session_id: str = "session-001", status: LabletSessionStatus = LabletSessionStatus.INSTANTIATING, pipeline_progress: dict | None = None) -> MagicMock:
    """Create a mock LabletSession with configurable pipeline_progress."""
    session = MagicMock(spec=LabletSession)
    session.id.return_value = session_id

    state = MagicMock(spec=LabletSessionState)
    state.status = status
    state.pipeline_progress = pipeline_progress
    session.state = state

    session.update_pipeline_progress = MagicMock()
    return session


# =============================================================================
# G2: GetPipelineProgressQueryHandler Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.query
class TestGetPipelineProgressQueryHandler:
    """Tests for pipeline progress retrieval from LabletSession aggregate."""

    def _make_handler(self, mock_session_repository: MagicMock) -> GetPipelineProgressQueryHandler:
        return GetPipelineProgressQueryHandler(lablet_session_repository=mock_session_repository)

    @pytest.mark.asyncio
    async def test_missing_session_id_returns_bad_request(self, mock_session_repository):
        """Empty session_id → 400."""
        handler = self._make_handler(mock_session_repository)
        result = await handler.handle_async(GetPipelineProgressQuery(session_id=""))
        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_session_not_found_returns_404(self, mock_session_repository):
        """Non-existent session → 404."""
        mock_session_repository.get_by_id_async = AsyncMock(return_value=None)
        handler = self._make_handler(mock_session_repository)
        result = await handler.handle_async(GetPipelineProgressQuery(session_id="nonexistent"))
        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_all_pipelines_with_summaries(self, mock_session_repository):
        """Returns pipeline dict with step summaries."""
        session = _make_session(
            pipeline_progress={
                "instantiate": {
                    "resolve_lab": {"status": "completed", "order": 0},
                    "start_lab": {"status": "in_progress", "order": 1},
                    "wait_converge": {"status": "pending", "order": 2},
                },
            }
        )
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)
        handler = self._make_handler(mock_session_repository)

        result = await handler.handle_async(GetPipelineProgressQuery(session_id="session-001"))

        assert result.is_success
        data = result.data
        assert "pipelines" in data
        assert "instantiate" in data["pipelines"]
        summary = data["pipelines"]["instantiate"]["summary"]
        assert summary["total"] == 3
        assert summary["completed"] == 1
        assert summary["in_progress"] == 1
        assert summary["pending"] == 1

    @pytest.mark.asyncio
    async def test_filters_by_pipeline_name(self, mock_session_repository):
        """Returns single pipeline when pipeline_name provided."""
        session = _make_session(
            pipeline_progress={
                "instantiate": {"resolve_lab": {"status": "completed", "order": 0}},
                "teardown": {"stop_lab": {"status": "pending", "order": 0}},
            }
        )
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)
        handler = self._make_handler(mock_session_repository)

        result = await handler.handle_async(GetPipelineProgressQuery(session_id="session-001", pipeline_name="instantiate"))

        assert result.is_success
        assert result.data["found"] is True
        assert result.data["pipeline_name"] == "instantiate"
        assert "resolve_lab" in result.data["steps"]

    @pytest.mark.asyncio
    async def test_unknown_pipeline_name_returns_empty(self, mock_session_repository):
        """Unknown pipeline_name → found=False, empty steps."""
        session = _make_session(pipeline_progress={})
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)
        handler = self._make_handler(mock_session_repository)

        result = await handler.handle_async(GetPipelineProgressQuery(session_id="session-001", pipeline_name="bogus"))

        assert result.is_success
        assert result.data["found"] is False
        assert result.data["steps"] == {}


# =============================================================================
# G2: ListPipelineExecutionsQueryHandler Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.query
class TestListPipelineExecutionsQueryHandler:
    """Tests for pipeline execution history listing."""

    def _make_handler(self, mock_execution_repository: MagicMock) -> ListPipelineExecutionsQueryHandler:
        return ListPipelineExecutionsQueryHandler(pipeline_execution_repository=mock_execution_repository)

    @pytest.mark.asyncio
    async def test_missing_session_id_returns_bad_request(self, mock_execution_repository):
        """Empty session_id → 400."""
        handler = self._make_handler(mock_execution_repository)
        result = await handler.handle_async(ListPipelineExecutionsQuery(session_id=""))
        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_no_records(self, mock_execution_repository):
        """No records → empty list."""
        mock_execution_repository.get_by_session_async = AsyncMock(return_value=[])
        handler = self._make_handler(mock_execution_repository)

        result = await handler.handle_async(ListPipelineExecutionsQuery(session_id="session-001"))

        assert result.is_success
        assert result.data == []

    @pytest.mark.asyncio
    async def test_returns_execution_summaries(self, mock_execution_repository):
        """Returns mapped execution summaries."""
        record = PipelineExecutionRecord.create(
            session_id="session-001",
            pipeline_name="instantiate",
            attempt=1,
            steps=[
                {"name": "resolve_lab", "status": "completed", "order": 0},
                {"name": "start_lab", "status": "failed", "order": 1},
            ],
        )
        record.mark_failed(error="Step failed", duration_seconds=42.5)

        mock_execution_repository.get_by_session_async = AsyncMock(return_value=[record])
        handler = self._make_handler(mock_execution_repository)

        result = await handler.handle_async(ListPipelineExecutionsQuery(session_id="session-001"))

        assert result.is_success
        assert len(result.data) == 1
        summary = result.data[0]
        assert summary["pipeline_name"] == "instantiate"
        assert summary["status"] == "failed"
        assert summary["steps_total"] == 2
        assert summary["steps_completed"] == 1
        assert summary["steps_failed"] == 1
        assert summary["error"] == "Step failed"

    @pytest.mark.asyncio
    async def test_filters_by_pipeline_name(self, mock_execution_repository):
        """Delegates pipeline_name filter to repository."""
        mock_execution_repository.get_by_session_and_pipeline_async = AsyncMock(return_value=[])
        handler = self._make_handler(mock_execution_repository)

        result = await handler.handle_async(ListPipelineExecutionsQuery(session_id="session-001", pipeline_name="teardown"))

        assert result.is_success
        mock_execution_repository.get_by_session_and_pipeline_async.assert_called_once_with("session-001", "teardown")
        mock_execution_repository.get_by_session_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_filters_by_status(self, mock_execution_repository):
        """Filters records by status in-memory."""
        running = PipelineExecutionRecord.create(session_id="s1", pipeline_name="instantiate", attempt=1)
        completed = PipelineExecutionRecord.create(session_id="s1", pipeline_name="instantiate", attempt=2)
        completed.mark_completed()

        mock_execution_repository.get_by_session_async = AsyncMock(return_value=[running, completed])
        handler = self._make_handler(mock_execution_repository)

        result = await handler.handle_async(ListPipelineExecutionsQuery(session_id="s1", status="completed"))

        assert result.is_success
        assert len(result.data) == 1
        assert result.data[0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_applies_pagination(self, mock_execution_repository):
        """Skip/limit applied correctly."""
        records = [PipelineExecutionRecord.create(session_id="s1", pipeline_name="instantiate", attempt=i) for i in range(1, 6)]
        mock_execution_repository.get_by_session_async = AsyncMock(return_value=records)
        handler = self._make_handler(mock_execution_repository)

        result = await handler.handle_async(ListPipelineExecutionsQuery(session_id="s1", skip=1, limit=2))

        assert result.is_success
        assert len(result.data) == 2


# =============================================================================
# G1+G5: UpdatePipelineProgressCommandHandler Observability Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.command
class TestPipelineObservability:
    """Tests for G1 (execution record upsert) and G5 (CloudEvent emission)."""

    def _make_handler(self, mock_session_repository, mock_execution_repository, mock_publisher=None) -> UpdatePipelineProgressCommandHandler:
        if mock_publisher is None:
            mock_publisher = AsyncMock()
        return UpdatePipelineProgressCommandHandler(cloud_event_publisher=mock_publisher, lablet_session_repository=mock_session_repository, pipeline_execution_repository=mock_execution_repository)

    # ─── G5: CloudEvent emission ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_emits_step_started_on_pending(self, mock_session_repository, mock_execution_repository):
        """step_status=pending → PipelineStepStartedEventV1 CloudEvent."""
        session = _make_session(
            pipeline_progress={
                "instantiate": {"resolve_lab": {"status": "pending", "order": 0}},
            }
        )
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        mock_publisher = AsyncMock()
        handler = self._make_handler(mock_session_repository, mock_execution_repository, mock_publisher)

        command = UpdatePipelineProgressCommand(session_id="session-001", pipeline_name="instantiate", step_name="resolve_lab", step_status="pending")
        result = await handler.handle_async(command)

        assert result.is_success
        # Verify CloudEvent was published via the publisher
        assert mock_publisher.publish_async.call_count >= 1
        # The first CloudEvent should be a step.started event
        cloud_event = mock_publisher.publish_async.call_args_list[0][0][0]
        assert isinstance(cloud_event, PipelineStepStartedEventV1)

    @pytest.mark.asyncio
    async def test_emits_step_completed_on_completed(self, mock_session_repository, mock_execution_repository):
        """step_status=completed → PipelineStepCompletedEventV1."""
        session = _make_session(
            pipeline_progress={
                "instantiate": {
                    "resolve_lab": {"status": "pending", "order": 0},
                    "start_lab": {"status": "pending", "order": 1},
                },
            }
        )
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        mock_publisher = AsyncMock()
        handler = self._make_handler(mock_session_repository, mock_execution_repository, mock_publisher)

        command = UpdatePipelineProgressCommand(session_id="session-001", pipeline_name="instantiate", step_name="resolve_lab", step_status="completed", result_data={"lab_id": "lab-123"})
        result = await handler.handle_async(command)

        assert result.is_success
        assert mock_publisher.publish_async.call_count >= 1
        ce = mock_publisher.publish_async.call_args_list[0][0][0]
        assert isinstance(ce, PipelineStepCompletedEventV1)

    @pytest.mark.asyncio
    async def test_emits_step_failed_on_failed(self, mock_session_repository, mock_execution_repository):
        """step_status=failed → PipelineStepFailedEventV1."""
        session = _make_session(
            pipeline_progress={
                "teardown": {"stop_lab": {"status": "pending", "order": 0}},
            }
        )
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        mock_publisher = AsyncMock()
        handler = self._make_handler(mock_session_repository, mock_execution_repository, mock_publisher)

        command = UpdatePipelineProgressCommand(session_id="session-001", pipeline_name="teardown", step_name="stop_lab", step_status="failed", error="CML API timeout")
        result = await handler.handle_async(command)

        assert result.is_success
        assert mock_publisher.publish_async.call_count >= 1
        ce = mock_publisher.publish_async.call_args_list[0][0][0]
        assert isinstance(ce, PipelineStepFailedEventV1)

    @pytest.mark.asyncio
    async def test_emits_pipeline_completed_when_all_done(self, mock_session_repository, mock_execution_repository):
        """All steps done → PipelineCompletedEventV1."""
        session = _make_session(
            pipeline_progress={
                "teardown": {
                    "stop_lab": {"status": "completed", "order": 0},
                    "wipe_lab": {"status": "pending", "order": 1},
                },
            }
        )
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)
        # Provide a running record for G1 finalization
        running_record = PipelineExecutionRecord.create(session_id="session-001", pipeline_name="teardown", attempt=1)
        mock_execution_repository.get_latest_by_session_and_pipeline_async = AsyncMock(return_value=running_record)

        mock_publisher = AsyncMock()
        handler = self._make_handler(mock_session_repository, mock_execution_repository, mock_publisher)

        command = UpdatePipelineProgressCommand(session_id="session-001", pipeline_name="teardown", step_name="wipe_lab", step_status="completed")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["pipeline_complete"] is True
        # Should have 2 CloudEvents: step.completed + pipeline.completed
        assert mock_publisher.publish_async.call_count == 2
        published_events = [c[0][0] for c in mock_publisher.publish_async.call_args_list]
        assert any(isinstance(e, PipelineStepCompletedEventV1) for e in published_events)
        assert any(isinstance(e, PipelineCompletedEventV1) for e in published_events)

    # ─── G1: Execution record upsert ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_creates_execution_record_on_first_step(self, mock_session_repository, mock_execution_repository):
        """step_status=pending (first step) → creates PipelineExecutionRecord."""
        session = _make_session(
            pipeline_progress={
                "instantiate": {"resolve_lab": {"status": "pending", "order": 0}},
            }
        )
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)
        # No existing records → attempt 1
        mock_execution_repository.get_by_session_and_pipeline_async = AsyncMock(return_value=[])

        handler = self._make_handler(mock_session_repository, mock_execution_repository)

        command = UpdatePipelineProgressCommand(session_id="session-001", pipeline_name="instantiate", step_name="resolve_lab", step_status="pending")
        result = await handler.handle_async(command)

        assert result.is_success
        mock_execution_repository.add_async.assert_called_once()
        added_record = mock_execution_repository.add_async.call_args[0][0]
        assert isinstance(added_record, PipelineExecutionRecord)
        assert added_record.session_id == "session-001"
        assert added_record.pipeline_name == "instantiate"
        assert added_record.status == "running"
        assert added_record.attempt == 1

    @pytest.mark.asyncio
    async def test_finalizes_execution_record_on_completion(self, mock_session_repository, mock_execution_repository):
        """All steps done → finalizes existing PipelineExecutionRecord."""
        session = _make_session(
            pipeline_progress={
                "instantiate": {
                    "resolve_lab": {"status": "completed", "order": 0},
                    "start_lab": {"status": "pending", "order": 1},
                },
            }
        )
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        running_record = PipelineExecutionRecord.create(session_id="session-001", pipeline_name="instantiate", attempt=1)
        mock_execution_repository.get_latest_by_session_and_pipeline_async = AsyncMock(return_value=running_record)

        handler = self._make_handler(mock_session_repository, mock_execution_repository)

        command = UpdatePipelineProgressCommand(session_id="session-001", pipeline_name="instantiate", step_name="start_lab", step_status="completed")
        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["pipeline_complete"] is True
        mock_execution_repository.update_async.assert_called_once()
        updated_record = mock_execution_repository.update_async.call_args[0][0]
        assert updated_record.status == "completed"
        assert updated_record.duration_seconds > 0 or updated_record.duration_seconds == 0.0

    @pytest.mark.asyncio
    async def test_cloud_event_failure_does_not_break_handler(self, mock_session_repository, mock_execution_repository):
        """CloudEvent emission error is logged but handler still succeeds."""
        session = _make_session(
            pipeline_progress={
                "instantiate": {"resolve_lab": {"status": "pending", "order": 0}},
            }
        )
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        # Make CloudEvent emission fail
        mock_publisher = AsyncMock()
        mock_publisher.publish_async.side_effect = RuntimeError("Bus crash")

        handler = self._make_handler(mock_session_repository, mock_execution_repository, mock_publisher)

        command = UpdatePipelineProgressCommand(session_id="session-001", pipeline_name="instantiate", step_name="resolve_lab", step_status="pending")
        result = await handler.handle_async(command)

        # Handler should still succeed despite CloudEvent failure
        assert result.is_success
        assert result.data["step_status"] == "pending"


# =============================================================================
# Mapping helper tests
# =============================================================================


@pytest.mark.unit
class TestExecutionSummaryMapping:
    """Tests for _map_execution_summary helper."""

    def test_maps_all_fields(self):
        """Maps entity to summary dict with all expected fields."""
        record = PipelineExecutionRecord.create(
            session_id="s1",
            pipeline_name="instantiate",
            attempt=2,
            steps=[
                {"name": "resolve_lab", "status": "completed", "order": 0},
                {"name": "start_lab", "status": "failed", "order": 1},
                {"name": "wait_converge", "status": "pending", "order": 2},
            ],
        )
        record.mark_failed(error="Step failed", duration_seconds=30.5)

        result = _map_execution_summary(record)

        assert result["session_id"] == "s1"
        assert result["pipeline_name"] == "instantiate"
        assert result["status"] == "failed"
        assert result["attempt"] == 2
        assert result["steps_total"] == 3
        assert result["steps_completed"] == 1
        assert result["steps_failed"] == 1
        assert result["error"] == "Step failed"
        assert result["duration_seconds"] == 30.5
        assert result["started_at"] is not None
        assert result["completed_at"] is not None
