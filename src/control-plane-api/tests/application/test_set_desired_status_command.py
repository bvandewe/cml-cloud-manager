"""Unit tests for SetDesiredStatusCommandHandler.

ADR-034 Sprint E / ADR-015 pattern: Tests for the desired_status (spec)
command that follows the Kubernetes-like reconciliation model established
for CMLWorker.

Tests cover:
- Input validation (valid/invalid desired_status values)
- Session not found → 404
- No-op when already at target desired_status
- Successful status change (calls aggregate + persists)
- All valid target statuses (running, stopped, terminated)

Pattern: pytest fixtures + MagicMock + AsyncMock, matching test_lablet_session_commands.py style.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from application.commands.lablet_session.set_desired_status_command import VALID_DESIRED_STATUSES, SetDesiredStatusCommand, SetDesiredStatusCommandHandler
from domain.entities.lablet_session import LabletSession, LabletSessionState
from domain.enums import LabletSessionStatus
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


def _make_session(session_id: str = "session-001", status: LabletSessionStatus = LabletSessionStatus.RUNNING, desired_status: LabletSessionStatus = LabletSessionStatus.RUNNING) -> MagicMock:
    """Create a mock LabletSession with configurable desired_status."""
    session = MagicMock(spec=LabletSession)
    session.id.return_value = session_id

    state = MagicMock(spec=LabletSessionState)
    state.status = status
    state.desired_status = desired_status
    session.state = state

    # Default: update_desired_status returns True (changed)
    session.update_desired_status = MagicMock(return_value=True)

    return session


# =============================================================================
# SetDesiredStatusCommandHandler Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.command
class TestSetDesiredStatusCommandHandler:
    """Tests for session desired_status (spec) updates."""

    def _make_handler(self, mock_session_repository: MagicMock) -> SetDesiredStatusCommandHandler:
        return SetDesiredStatusCommandHandler(lablet_session_repository=mock_session_repository)

    # ─── Validation ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_rejects_invalid_desired_status(self, mock_session_repository):
        """Unrecognized status string → 400 Bad Request."""
        handler = self._make_handler(mock_session_repository)
        command = SetDesiredStatusCommand(session_id="session-001", desired_status="bogus_status")

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400
        mock_session_repository.get_by_id_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_non_target_status(self, mock_session_repository):
        """Valid enum value but not a valid target (e.g., 'instantiating') → 400."""
        handler = self._make_handler(mock_session_repository)
        command = SetDesiredStatusCommand(session_id="session-001", desired_status="instantiating")

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 400
        assert "instantiating" in str(result.detail)

    @pytest.mark.asyncio
    async def test_accepts_all_valid_target_statuses(self, mock_session_repository):
        """All 3 valid targets (running, stopped, terminated) are accepted."""
        handler = self._make_handler(mock_session_repository)

        for target in VALID_DESIRED_STATUSES:
            session = _make_session(desired_status=LabletSessionStatus.RUNNING)
            mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

            command = SetDesiredStatusCommand(session_id="session-001", desired_status=target.value)
            result = await handler.handle_async(command)
            assert result.is_success, f"desired_status '{target.value}' should be accepted"

    # ─── Session not found ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_session_not_found_returns_404(self, mock_session_repository):
        """Non-existent session_id → 404."""
        mock_session_repository.get_by_id_async = AsyncMock(return_value=None)
        handler = self._make_handler(mock_session_repository)
        command = SetDesiredStatusCommand(session_id="nonexistent", desired_status="stopped")

        result = await handler.handle_async(command)

        assert not result.is_success
        assert result.status_code == 404

    # ─── No-op when already at target ────────────────────────────────

    @pytest.mark.asyncio
    async def test_noop_when_already_at_target(self, mock_session_repository):
        """Returns success with changed=False when already at target."""
        session = _make_session(desired_status=LabletSessionStatus.RUNNING)
        session.update_desired_status = MagicMock(return_value=False)  # No-op
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = self._make_handler(mock_session_repository)
        command = SetDesiredStatusCommand(session_id="session-001", desired_status="running")

        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["changed"] is False
        # Should NOT persist if nothing changed
        mock_session_repository.update_async.assert_not_called()

    # ─── Successful change ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_successful_change_persists(self, mock_session_repository):
        """Successful change calls update_desired_status and persists."""
        session = _make_session(desired_status=LabletSessionStatus.RUNNING)
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = self._make_handler(mock_session_repository)
        command = SetDesiredStatusCommand(session_id="session-001", desired_status="stopped", requested_by="admin@test.com", reason="User requested stop")

        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["changed"] is True
        assert result.data["desired_status"] == "stopped"
        session.update_desired_status.assert_called_once_with(new_desired_status=LabletSessionStatus.STOPPED, requested_by="admin@test.com", reason="User requested stop")
        mock_session_repository.update_async.assert_called_once_with(session)

    @pytest.mark.asyncio
    async def test_terminated_desired_status(self, mock_session_repository):
        """Setting desired_status to 'terminated' is valid."""
        session = _make_session(desired_status=LabletSessionStatus.RUNNING)
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = self._make_handler(mock_session_repository)
        command = SetDesiredStatusCommand(session_id="session-001", desired_status="terminated", requested_by="system", reason="Admin force-kill")

        result = await handler.handle_async(command)

        assert result.is_success
        assert result.data["desired_status"] == "terminated"
        session.update_desired_status.assert_called_once_with(new_desired_status=LabletSessionStatus.TERMINATED, requested_by="system", reason="Admin force-kill")
