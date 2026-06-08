"""Unit tests for ResumePipelineStepCommandHandler + FailPipelineStepCommandHandler.

Phase 3 / AD-CSI-009: Bridge between Scenario Engine CloudEvents and the
CPA's pipeline progress. Tests cover:

- Resume flips suspended → completed, merges output_data, persists.
- Fail flips suspended → failed, records error.
- Step lookup by step_correlation_id.
- Session not found → 404.
- Pipeline not found → 404.
- Correlation id not found → 404 (idempotency at controller layer).
- Resume on already-completed step → 200 + idempotent=True.
- Fail on completed step → 409 conflict.

Pattern: mirrors ``test_update_pipeline_progress_command.py``.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from application.commands.lablet_session.fail_pipeline_step_command import (
    FailPipelineStepCommand,
    FailPipelineStepCommandHandler,
)
from application.commands.lablet_session.resume_pipeline_step_command import (
    ResumePipelineStepCommand,
    ResumePipelineStepCommandHandler,
)
from domain.entities.lablet_session import LabletSession, LabletSessionState
from domain.repositories.lablet_session_repository import LabletSessionRepository

# =============================================================================
# Shared fixtures
# =============================================================================


@pytest.fixture
def mock_session_repository() -> MagicMock:
    mock = MagicMock(spec=LabletSessionRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    mock.update_async = AsyncMock()
    return mock


def _make_session_with_progress(
    session_id: str = "sess-1",
    pipeline_progress: dict | None = None,
) -> MagicMock:
    session = MagicMock(spec=LabletSession)
    session.id.return_value = session_id
    state = MagicMock(spec=LabletSessionState)
    state.pipeline_progress = pipeline_progress or {}
    session.state = state
    session.update_pipeline_progress = MagicMock()
    return session


# =============================================================================
# ResumePipelineStepCommandHandler
# =============================================================================


@pytest.mark.unit
@pytest.mark.command
class TestResumePipelineStepCommandHandler:
    @pytest.mark.asyncio
    async def test_session_not_found_returns_404(self, mock_session_repository):
        handler = ResumePipelineStepCommandHandler(mock_session_repository)
        command = ResumePipelineStepCommand(
            session_id="missing",
            pipeline_name="instantiate",
            step_correlation_id="abc",
        )
        result = await handler.handle_async(command)
        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_pipeline_not_found_returns_404(self, mock_session_repository):
        session = _make_session_with_progress(pipeline_progress={})
        mock_session_repository.get_by_id_async.return_value = session

        handler = ResumePipelineStepCommandHandler(mock_session_repository)
        command = ResumePipelineStepCommand(
            session_id="sess-1",
            pipeline_name="instantiate",
            step_correlation_id="abc",
        )
        result = await handler.handle_async(command)
        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_correlation_id_not_found_returns_404(self, mock_session_repository):
        session = _make_session_with_progress(
            pipeline_progress={
                "instantiate": {
                    "lab_resolve": {
                        "status": "suspended",
                        "step_correlation_id": "different-id",
                    }
                }
            }
        )
        mock_session_repository.get_by_id_async.return_value = session

        handler = ResumePipelineStepCommandHandler(mock_session_repository)
        command = ResumePipelineStepCommand(
            session_id="sess-1",
            pipeline_name="instantiate",
            step_correlation_id="abc",
        )
        result = await handler.handle_async(command)
        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_resume_flips_suspended_to_completed_and_merges_output(self, mock_session_repository):
        session = _make_session_with_progress(
            pipeline_progress={
                "instantiate": {
                    "lab_resolve": {
                        "status": "suspended",
                        "step_correlation_id": "corr-1",
                        "external_job_id": "job-100",
                        "result_data": {"topology_yaml": "..."},
                    }
                }
            }
        )
        mock_session_repository.get_by_id_async.return_value = session

        handler = ResumePipelineStepCommandHandler(mock_session_repository)
        command = ResumePipelineStepCommand(
            session_id="sess-1",
            pipeline_name="instantiate",
            step_correlation_id="corr-1",
            output_data={"cml_lab_id": "lab-xyz"},
            completed_at="2026-01-01T00:00:00+00:00",
        )

        result = await handler.handle_async(command)
        assert result.is_success
        assert result.data["pipeline_progress"]["lab_resolve"]["status"] == "completed"
        # Merged data
        assert result.data["pipeline_progress"]["lab_resolve"]["result_data"] == {
            "topology_yaml": "...",
            "cml_lab_id": "lab-xyz",
        }
        assert result.data["idempotent"] is False
        # Aggregate event raised
        session.update_pipeline_progress.assert_called_once()
        kwargs = session.update_pipeline_progress.call_args.kwargs
        assert kwargs["step_status"] == "completed"
        assert kwargs["step_name"] == "lab_resolve"
        mock_session_repository.update_async.assert_awaited_once_with(session)

    @pytest.mark.asyncio
    async def test_resume_already_completed_is_idempotent(self, mock_session_repository):
        session = _make_session_with_progress(
            pipeline_progress={
                "instantiate": {
                    "lab_resolve": {
                        "status": "completed",
                        "step_correlation_id": "corr-1",
                        "result_data": {"cml_lab_id": "lab-xyz"},
                    }
                }
            }
        )
        mock_session_repository.get_by_id_async.return_value = session

        handler = ResumePipelineStepCommandHandler(mock_session_repository)
        command = ResumePipelineStepCommand(
            session_id="sess-1",
            pipeline_name="instantiate",
            step_correlation_id="corr-1",
            output_data={"cml_lab_id": "lab-xyz"},
        )

        result = await handler.handle_async(command)
        assert result.is_success
        assert result.data["idempotent"] is True
        # No aggregate event raised, no persistence
        session.update_pipeline_progress.assert_not_called()
        mock_session_repository.update_async.assert_not_called()


# =============================================================================
# FailPipelineStepCommandHandler
# =============================================================================


@pytest.mark.unit
@pytest.mark.command
class TestFailPipelineStepCommandHandler:
    @pytest.mark.asyncio
    async def test_session_not_found_returns_404(self, mock_session_repository):
        handler = FailPipelineStepCommandHandler(mock_session_repository)
        command = FailPipelineStepCommand(
            session_id="missing",
            pipeline_name="instantiate",
            step_correlation_id="abc",
            error="boom",
        )
        result = await handler.handle_async(command)
        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_fail_flips_suspended_to_failed_and_records_error(self, mock_session_repository):
        session = _make_session_with_progress(
            pipeline_progress={
                "instantiate": {
                    "lab_start": {
                        "status": "suspended",
                        "step_correlation_id": "corr-2",
                    }
                }
            }
        )
        mock_session_repository.get_by_id_async.return_value = session

        handler = FailPipelineStepCommandHandler(mock_session_repository)
        command = FailPipelineStepCommand(
            session_id="sess-1",
            pipeline_name="instantiate",
            step_correlation_id="corr-2",
            error="external job timed out",
            details={"timeout_seconds": 1800},
            failed_at="2026-01-01T00:30:00+00:00",
        )

        result = await handler.handle_async(command)
        assert result.is_success
        step = result.data["pipeline_progress"]["lab_start"]
        assert step["status"] == "failed"
        assert step["error"] == "external job timed out"
        assert step["error_details"] == {"timeout_seconds": 1800}
        assert step["failed_at"] == "2026-01-01T00:30:00+00:00"
        session.update_pipeline_progress.assert_called_once()
        kwargs = session.update_pipeline_progress.call_args.kwargs
        assert kwargs["step_status"] == "failed"
        mock_session_repository.update_async.assert_awaited_once_with(session)

    @pytest.mark.asyncio
    async def test_fail_on_completed_step_returns_409(self, mock_session_repository):
        session = _make_session_with_progress(
            pipeline_progress={
                "instantiate": {
                    "lab_start": {
                        "status": "completed",
                        "step_correlation_id": "corr-3",
                    }
                }
            }
        )
        mock_session_repository.get_by_id_async.return_value = session

        handler = FailPipelineStepCommandHandler(mock_session_repository)
        command = FailPipelineStepCommand(
            session_id="sess-1",
            pipeline_name="instantiate",
            step_correlation_id="corr-3",
            error="late failure",
        )

        result = await handler.handle_async(command)
        assert not result.is_success
        assert result.status_code == 409
        session.update_pipeline_progress.assert_not_called()

    @pytest.mark.asyncio
    async def test_fail_idempotent_on_already_failed_step(self, mock_session_repository):
        """Failing a step that's already failed should re-record (overwrite is acceptable)."""
        session = _make_session_with_progress(
            pipeline_progress={
                "instantiate": {
                    "lab_start": {
                        "status": "failed",
                        "step_correlation_id": "corr-4",
                        "error": "old error",
                    }
                }
            }
        )
        mock_session_repository.get_by_id_async.return_value = session

        handler = FailPipelineStepCommandHandler(mock_session_repository)
        command = FailPipelineStepCommand(
            session_id="sess-1",
            pipeline_name="instantiate",
            step_correlation_id="corr-4",
            error="duplicate notification",
        )

        result = await handler.handle_async(command)
        # We allow overwrite-on-failed (the latest error message wins).
        assert result.is_success
        step = result.data["pipeline_progress"]["lab_start"]
        assert step["error"] == "duplicate notification"
