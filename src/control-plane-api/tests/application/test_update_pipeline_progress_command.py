"""Unit tests for UpdatePipelineProgressCommandHandler.

ADR-034 Sprint E: Tests for the generic pipeline progress command that
supports all pipeline types (instantiate, teardown, collect_evidence, compute_grading).

Tests cover:
- Input validation (pipeline_name, step_status)
- Session not found → 404
- Step auto-initialization for unknown steps
- Step status transitions (completed, failed, skipped)
- Pipeline completion detection (all steps done)
- Backward compatibility via aggregate domain event
- Result data and error propagation

Pattern: pytest fixtures + MagicMock + AsyncMock, matching test_lablet_session_commands.py style.
"""

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from application.commands.lablet_session.update_pipeline_progress_command import (
    VALID_PIPELINE_NAMES,
    VALID_STEP_STATUSES,
    UpdatePipelineProgressCommand,
    UpdatePipelineProgressCommandHandler,
)
from domain.entities.lablet_session import LabletSession, LabletSessionState
from domain.enums import LabletSessionStatus
from domain.repositories.lablet_session_repository import LabletSessionRepository
from domain.repositories.pipeline_execution_repository import PipelineExecutionRepository
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator


# =============================================================================
# Shared fixtures
# =============================================================================


@pytest.fixture
def mock_mediator() -> MagicMock:
    mock = MagicMock(spec=Mediator)
    mock.execute_async = AsyncMock()
    return mock


@pytest.fixture
def mock_mapper() -> MagicMock:
    return MagicMock(spec=Mapper)


@pytest.fixture
def mock_cloud_event_bus() -> MagicMock:
    return MagicMock(spec=CloudEventBus)


@pytest.fixture
def mock_cloud_event_publishing_options() -> MagicMock:
    return MagicMock()


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
    mock.get_by_session_and_pipeline_async = AsyncMock(return_value=[])
    mock.get_latest_by_session_and_pipeline_async = AsyncMock(return_value=None)
    return mock


def _make_session(
    session_id: str = "session-001",
    status: LabletSessionStatus = LabletSessionStatus.INSTANTIATING,
    pipeline_progress: dict | None = None,
) -> MagicMock:
    """Create a mock LabletSession with configurable pipeline_progress."""
    session = MagicMock(spec=LabletSession)
    session.id.return_value = session_id

    state = MagicMock(spec=LabletSessionState)
    state.status = status
    state.pipeline_progress = pipeline_progress
    session.state = state

    # Mock the domain method
    session.update_pipeline_progress = MagicMock()

    return session


# =============================================================================
# UpdatePipelineProgressCommandHandler Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.command
class TestUpdatePipelineProgressCommandHandler:
    """Tests for generic pipeline progress updates."""

    def _make_handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_session_repository: MagicMock,
        mock_execution_repository: MagicMock,
    ) -> UpdatePipelineProgressCommandHandler:
        return UpdatePipelineProgressCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lablet_session_repository=mock_session_repository,
            pipeline_execution_repository=mock_execution_repository,
        )

    # ─── Validation ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_rejects_invalid_pipeline_name(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_cloud_event_publishing_options,
        mock_session_repository,
        mock_execution_repository,
    ):
        """Invalid pipeline_name → 400 Bad Request."""
        handler = self._make_handler(
            mock_mediator, mock_mapper, mock_cloud_event_bus,
            mock_cloud_event_publishing_options, mock_session_repository, mock_execution_repository,
        )
        command = UpdatePipelineProgressCommand(
            session_id="session-001",
            pipeline_name="bogus_pipeline",
            step_name="step_1",
            step_status="completed",
        )

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400
        assert "bogus_pipeline" in str(result.detail)
        mock_session_repository.get_by_id_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_invalid_step_status(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_cloud_event_publishing_options,
        mock_session_repository,
        mock_execution_repository,
    ):
        """Invalid step_status → 400 Bad Request."""
        handler = self._make_handler(
            mock_mediator, mock_mapper, mock_cloud_event_bus,
            mock_cloud_event_publishing_options, mock_session_repository, mock_execution_repository,
        )
        command = UpdatePipelineProgressCommand(
            session_id="session-001",
            pipeline_name="instantiate",
            step_name="step_1",
            step_status="running",  # Not in VALID_STEP_STATUSES
        )

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400
        assert "running" in str(result.detail)

    @pytest.mark.asyncio
    async def test_accepts_all_valid_pipeline_names(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_cloud_event_publishing_options,
        mock_session_repository,
        mock_execution_repository,
    ):
        """All 4 pipeline names are accepted."""
        handler = self._make_handler(
            mock_mediator, mock_mapper, mock_cloud_event_bus,
            mock_cloud_event_publishing_options, mock_session_repository, mock_execution_repository,
        )

        for pipeline_name in VALID_PIPELINE_NAMES:
            session = _make_session(pipeline_progress={})
            mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

            command = UpdatePipelineProgressCommand(
                session_id="session-001",
                pipeline_name=pipeline_name,
                step_name="step_1",
                step_status="completed",
            )
            result = await handler.handle_async(command)
            assert result.is_success, f"Pipeline '{pipeline_name}' should be accepted"

    # ─── Session not found ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_session_not_found_returns_404(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_cloud_event_publishing_options,
        mock_session_repository,
        mock_execution_repository,
    ):
        """Non-existent session_id → 404."""
        mock_session_repository.get_by_id_async = AsyncMock(return_value=None)
        handler = self._make_handler(
            mock_mediator, mock_mapper, mock_cloud_event_bus,
            mock_cloud_event_publishing_options, mock_session_repository, mock_execution_repository,
        )
        command = UpdatePipelineProgressCommand(
            session_id="nonexistent",
            pipeline_name="teardown",
            step_name="stop_lab",
            step_status="completed",
        )

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 404

    # ─── Step auto-initialization ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_auto_initializes_unknown_step(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_cloud_event_publishing_options,
        mock_session_repository,
        mock_execution_repository,
    ):
        """Steps not in progress dict get auto-created before status update."""
        session = _make_session(pipeline_progress={})
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = self._make_handler(
            mock_mediator, mock_mapper, mock_cloud_event_bus,
            mock_cloud_event_publishing_options, mock_session_repository, mock_execution_repository,
        )
        command = UpdatePipelineProgressCommand(
            session_id="session-001",
            pipeline_name="teardown",
            step_name="new_step",
            step_status="completed",
        )

        result = await handler.handle_async(command)

        assert result.is_success
        # Verify the aggregate method was called with progress containing the step
        session.update_pipeline_progress.assert_called_once()
        call_kwargs = session.update_pipeline_progress.call_args[1]
        assert call_kwargs["pipeline_name"] == "teardown"
        assert call_kwargs["step_name"] == "new_step"
        progress = call_kwargs["progress_data"]
        assert "new_step" in progress
        assert progress["new_step"]["status"] == "completed"

    # ─── Step transitions ────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_marks_step_completed_with_result_data(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_cloud_event_publishing_options,
        mock_session_repository,
        mock_execution_repository,
    ):
        """Completed step stores result_data."""
        session = _make_session(
            pipeline_progress={
                "instantiate": {
                    "resolve_lab": {"status": "pending", "order": 0},
                },
            },
        )
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = self._make_handler(
            mock_mediator, mock_mapper, mock_cloud_event_bus,
            mock_cloud_event_publishing_options, mock_session_repository, mock_execution_repository,
        )
        command = UpdatePipelineProgressCommand(
            session_id="session-001",
            pipeline_name="instantiate",
            step_name="resolve_lab",
            step_status="completed",
            result_data={"lab_id": "lab-123", "node_count": 5},
        )

        result = await handler.handle_async(command)

        assert result.is_success
        assert result.status_code == 200
        call_kwargs = session.update_pipeline_progress.call_args[1]
        progress = call_kwargs["progress_data"]
        assert progress["resolve_lab"]["status"] == "completed"
        assert progress["resolve_lab"]["result_data"]["lab_id"] == "lab-123"

    @pytest.mark.asyncio
    async def test_marks_step_failed_with_error(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_cloud_event_publishing_options,
        mock_session_repository,
        mock_execution_repository,
    ):
        """Failed step stores error message."""
        session = _make_session(
            pipeline_progress={
                "collect_evidence": {
                    "capture_configs": {"status": "pending", "order": 0},
                },
            },
        )
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = self._make_handler(
            mock_mediator, mock_mapper, mock_cloud_event_bus,
            mock_cloud_event_publishing_options, mock_session_repository, mock_execution_repository,
        )
        command = UpdatePipelineProgressCommand(
            session_id="session-001",
            pipeline_name="collect_evidence",
            step_name="capture_configs",
            step_status="failed",
            error="Connection timeout to CML API",
        )

        result = await handler.handle_async(command)

        assert result.is_success  # Command itself succeeds even on step failure
        call_kwargs = session.update_pipeline_progress.call_args[1]
        progress = call_kwargs["progress_data"]
        assert progress["capture_configs"]["status"] == "failed"
        assert "Connection timeout" in progress["capture_configs"]["error"]

    @pytest.mark.asyncio
    async def test_marks_step_skipped_with_reason(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_cloud_event_publishing_options,
        mock_session_repository,
        mock_execution_repository,
    ):
        """Skipped step stores skip_reason."""
        session = _make_session(
            pipeline_progress={
                "compute_grading": {
                    "run_grading_script": {"status": "pending", "order": 0},
                },
            },
        )
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = self._make_handler(
            mock_mediator, mock_mapper, mock_cloud_event_bus,
            mock_cloud_event_publishing_options, mock_session_repository, mock_execution_repository,
        )
        command = UpdatePipelineProgressCommand(
            session_id="session-001",
            pipeline_name="compute_grading",
            step_name="run_grading_script",
            step_status="skipped",
            error="No grading script configured",
        )

        result = await handler.handle_async(command)

        assert result.is_success
        call_kwargs = session.update_pipeline_progress.call_args[1]
        progress = call_kwargs["progress_data"]
        assert progress["run_grading_script"]["status"] == "skipped"
        assert "No grading script" in progress["run_grading_script"]["skip_reason"]

    # ─── Pipeline completion detection ───────────────────────────────

    @pytest.mark.asyncio
    async def test_detects_pipeline_complete_when_all_steps_done(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_cloud_event_publishing_options,
        mock_session_repository,
        mock_execution_repository,
    ):
        """Result includes pipeline_complete=True when all steps are completed/skipped."""
        session = _make_session(
            pipeline_progress={
                "teardown": {
                    "stop_lab": {"status": "completed", "order": 0},
                    "wipe_lab": {"status": "pending", "order": 1},
                },
            },
        )
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = self._make_handler(
            mock_mediator, mock_mapper, mock_cloud_event_bus,
            mock_cloud_event_publishing_options, mock_session_repository, mock_execution_repository,
        )
        # Complete the last pending step
        command = UpdatePipelineProgressCommand(
            session_id="session-001",
            pipeline_name="teardown",
            step_name="wipe_lab",
            step_status="completed",
        )

        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["pipeline_complete"] is True
        assert result.data["pipeline_name"] == "teardown"

    @pytest.mark.asyncio
    async def test_pipeline_not_complete_with_pending_steps(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_cloud_event_publishing_options,
        mock_session_repository,
        mock_execution_repository,
    ):
        """pipeline_complete=False when steps remain pending."""
        session = _make_session(
            pipeline_progress={
                "instantiate": {
                    "resolve_lab": {"status": "pending", "order": 0},
                    "start_lab": {"status": "pending", "order": 1},
                },
            },
        )
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = self._make_handler(
            mock_mediator, mock_mapper, mock_cloud_event_bus,
            mock_cloud_event_publishing_options, mock_session_repository, mock_execution_repository,
        )
        # Complete only the first step
        command = UpdatePipelineProgressCommand(
            session_id="session-001",
            pipeline_name="instantiate",
            step_name="resolve_lab",
            step_status="completed",
        )

        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["pipeline_complete"] is False

    # ─── Aggregate persistence ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_calls_aggregate_update_pipeline_progress(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_cloud_event_publishing_options,
        mock_session_repository,
        mock_execution_repository,
    ):
        """Handler calls session.update_pipeline_progress() and persists."""
        session = _make_session(pipeline_progress={})
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = self._make_handler(
            mock_mediator, mock_mapper, mock_cloud_event_bus,
            mock_cloud_event_publishing_options, mock_session_repository, mock_execution_repository,
        )
        command = UpdatePipelineProgressCommand(
            session_id="session-001",
            pipeline_name="instantiate",
            step_name="apply_configs",
            step_status="completed",
            result_data={"config_count": 3},
        )

        result = await handler.handle_async(command)

        assert result.is_success
        session.update_pipeline_progress.assert_called_once()
        mock_session_repository.update_async.assert_called_once_with(session)

    # ─── Multiple pipelines on same session ──────────────────────────

    @pytest.mark.asyncio
    async def test_maintains_separate_progress_per_pipeline(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_cloud_event_publishing_options,
        mock_session_repository,
        mock_execution_repository,
    ):
        """Different pipeline names store progress independently."""
        session = _make_session(
            pipeline_progress={
                "instantiate": {
                    "resolve_lab": {"status": "completed", "order": 0},
                },
            },
        )
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = self._make_handler(
            mock_mediator, mock_mapper, mock_cloud_event_bus,
            mock_cloud_event_publishing_options, mock_session_repository, mock_execution_repository,
        )
        # Update teardown pipeline — instantiate progress should not be affected
        command = UpdatePipelineProgressCommand(
            session_id="session-001",
            pipeline_name="teardown",
            step_name="stop_lab",
            step_status="completed",
        )

        result = await handler.handle_async(command)

        assert result.is_success
        call_kwargs = session.update_pipeline_progress.call_args[1]
        assert call_kwargs["pipeline_name"] == "teardown"
        # Only teardown progress is in the delta (instantiate was not touched)
        progress = call_kwargs["progress_data"]
        assert "stop_lab" in progress
