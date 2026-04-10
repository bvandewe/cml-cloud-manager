"""Unit tests for LDS CloudEvent integration event handlers.

Tests cover:
- LdsSessionRunningHandler: READY → RUNNING transition
  - Happy path (session in READY → transitions to RUNNING)
  - Session not found
  - Session not in READY state (skips transition)
  - Deduplication (already processed)
  - LDS CloudEvent processing disabled via settings

Pattern: pytest fixtures + MagicMock + AsyncMock (matching assessment_events_handler tests).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from application.events.integration.lds_events import (
    LdsSessionEndedIntegrationEventV1,
    LdsSessionPausedIntegrationEventV1,
    LdsSessionRunningIntegrationEventV1,
)
from application.events.integration.lds_events_handler import (
    LdsSessionEndedHandler,
    LdsSessionPausedHandler,
    LdsSessionRunningHandler,
)
from application.services.event_deduplication_service import EventDeduplicationService
from application.settings import Settings
from domain.entities.lablet_session import InvalidStateTransitionError, LabletSession, LabletSessionState
from domain.enums import LabletSessionStatus

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_settings():
    """Create mock settings with LDS CloudEvent enabled."""
    settings = MagicMock(spec=Settings)
    settings.lds_cloudevent_enabled = True
    settings.lds_cloudevent_source = "https://labs.lcm.io"
    settings.lds_cloudevent_type_prefix = "io.lablet.lds"
    return settings


@pytest.fixture
def mock_session_repository():
    """Create a mock LabletSessionRepository."""
    repo = AsyncMock()
    return repo


@pytest.fixture
def mock_deduplication():
    """Create a mock EventDeduplicationService."""
    dedup = AsyncMock(spec=EventDeduplicationService)
    dedup.is_processed = AsyncMock(return_value=False)
    dedup.mark_processed = AsyncMock()
    return dedup


@pytest.fixture
def mock_mediator():
    return MagicMock()


@pytest.fixture
def mock_mapper():
    return MagicMock()


@pytest.fixture
def mock_cloud_event_bus():
    return MagicMock()


@pytest.fixture
def mock_publishing_options():
    return MagicMock()


def _make_session(
    session_id: str = "session-001",
    status: LabletSessionStatus = LabletSessionStatus.READY,
) -> MagicMock:
    """Create a mock LabletSession in a given status."""
    session = MagicMock(spec=LabletSession)
    session.id.return_value = session_id

    state = MagicMock(spec=LabletSessionState)
    state.status = status
    session.state = state

    session.mark_running = MagicMock()
    return session


def _make_running_handler(
    mock_mediator,
    mock_mapper,
    mock_cloud_event_bus,
    mock_publishing_options,
    mock_session_repository,
    mock_deduplication,
    mock_settings,
) -> LdsSessionRunningHandler:
    """Create a LdsSessionRunningHandler with mocked dependencies."""
    return LdsSessionRunningHandler(
        mediator=mock_mediator,
        mapper=mock_mapper,
        cloud_event_bus=mock_cloud_event_bus,
        cloud_event_publishing_options=mock_publishing_options,
        lablet_session_repository=mock_session_repository,
        deduplication_service=mock_deduplication,
        settings=mock_settings,
    )


# =============================================================================
# LdsSessionRunningHandler Tests
# =============================================================================


class TestLdsSessionRunningHandler:
    """Tests for the READY → RUNNING transition handler."""

    @pytest.mark.asyncio
    async def test_happy_path_ready_to_running(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_publishing_options,
        mock_session_repository,
        mock_deduplication,
        mock_settings,
    ):
        """Session in READY state transitions to RUNNING when LDS event arrives."""
        session = _make_session(session_id="sess-123", status=LabletSessionStatus.READY)
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)
        mock_session_repository.update_async = AsyncMock()

        handler = _make_running_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_publishing_options,
            mock_session_repository,
            mock_deduplication,
            mock_settings,
        )

        event = LdsSessionRunningIntegrationEventV1(
            aggregate_id="sess-123",
            session_id="sess-123",
        )

        await handler.handle_async(event)

        session.mark_running.assert_called_once()
        mock_session_repository.update_async.assert_called_once_with(session)
        mock_deduplication.mark_processed.assert_called_once_with("lds.session.running.sess-123")

    @pytest.mark.asyncio
    async def test_session_not_found(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_publishing_options,
        mock_session_repository,
        mock_deduplication,
        mock_settings,
    ):
        """Handler logs error when session not found."""
        mock_session_repository.get_by_id_async = AsyncMock(return_value=None)

        handler = _make_running_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_publishing_options,
            mock_session_repository,
            mock_deduplication,
            mock_settings,
        )

        event = LdsSessionRunningIntegrationEventV1(
            aggregate_id="nonexistent-id",
            session_id="nonexistent-id",
        )

        await handler.handle_async(event)

        mock_session_repository.update_async.assert_not_called()
        mock_deduplication.mark_processed.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_not_in_ready_state(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_publishing_options,
        mock_session_repository,
        mock_deduplication,
        mock_settings,
    ):
        """Handler skips transition when session is not in READY state."""
        session = _make_session(session_id="sess-456", status=LabletSessionStatus.RUNNING)
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = _make_running_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_publishing_options,
            mock_session_repository,
            mock_deduplication,
            mock_settings,
        )

        event = LdsSessionRunningIntegrationEventV1(
            aggregate_id="sess-456",
            session_id="sess-456",
        )

        await handler.handle_async(event)

        session.mark_running.assert_not_called()
        mock_session_repository.update_async.assert_not_called()
        # Still marks as processed to avoid repeated warnings
        mock_deduplication.mark_processed.assert_called_once()

    @pytest.mark.asyncio
    async def test_deduplication_skips_already_processed(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_publishing_options,
        mock_session_repository,
        mock_deduplication,
        mock_settings,
    ):
        """Handler skips processing when event already handled (idempotency)."""
        mock_deduplication.is_processed = AsyncMock(return_value=True)

        handler = _make_running_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_publishing_options,
            mock_session_repository,
            mock_deduplication,
            mock_settings,
        )

        event = LdsSessionRunningIntegrationEventV1(
            aggregate_id="sess-789",
            session_id="sess-789",
        )

        await handler.handle_async(event)

        mock_session_repository.get_by_id_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabled_via_settings(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_publishing_options,
        mock_session_repository,
        mock_deduplication,
        mock_settings,
    ):
        """Handler skips processing when LDS CloudEvents are disabled."""
        mock_settings.lds_cloudevent_enabled = False

        handler = _make_running_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_publishing_options,
            mock_session_repository,
            mock_deduplication,
            mock_settings,
        )

        event = LdsSessionRunningIntegrationEventV1(
            aggregate_id="sess-disabled",
            session_id="sess-disabled",
        )

        await handler.handle_async(event)

        mock_session_repository.get_by_id_async.assert_not_called()
        mock_deduplication.is_processed.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_state_transition_error(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_publishing_options,
        mock_session_repository,
        mock_deduplication,
        mock_settings,
    ):
        """Handler catches InvalidStateTransitionError gracefully."""
        session = _make_session(session_id="sess-err", status=LabletSessionStatus.READY)
        session.mark_running.side_effect = InvalidStateTransitionError(
            from_state=LabletSessionStatus.READY,
            to_state=LabletSessionStatus.RUNNING,
            message="Cannot transition from READY to RUNNING",
        )
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = _make_running_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_publishing_options,
            mock_session_repository,
            mock_deduplication,
            mock_settings,
        )

        event = LdsSessionRunningIntegrationEventV1(
            aggregate_id="sess-err",
            session_id="sess-err",
        )

        # Should not raise — handler catches the error
        await handler.handle_async(event)

        mock_session_repository.update_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolves_session_id_from_session_id_field(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_publishing_options,
        mock_session_repository,
        mock_deduplication,
        mock_settings,
    ):
        """Handler resolves session ID from session_id when aggregate_id is empty."""
        session = _make_session(session_id="sess-fallback", status=LabletSessionStatus.READY)
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)
        mock_session_repository.update_async = AsyncMock()

        handler = _make_running_handler(
            mock_mediator,
            mock_mapper,
            mock_cloud_event_bus,
            mock_publishing_options,
            mock_session_repository,
            mock_deduplication,
            mock_settings,
        )

        event = LdsSessionRunningIntegrationEventV1(
            aggregate_id="",
            session_id="sess-fallback",
        )

        await handler.handle_async(event)

        mock_session_repository.get_by_id_async.assert_called_once_with("sess-fallback")
        session.mark_running.assert_called_once()


# =============================================================================
# LdsSessionPausedHandler Tests
# =============================================================================


class TestLdsSessionPausedHandler:
    """Tests for the session paused handler (informational)."""

    @pytest.mark.asyncio
    async def test_paused_handler_logs_without_error(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_publishing_options,
        mock_session_repository,
        mock_deduplication,
        mock_settings,
    ):
        """Paused handler completes without errors."""
        handler = LdsSessionPausedHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_publishing_options,
            lablet_session_repository=mock_session_repository,
            deduplication_service=mock_deduplication,
            settings=mock_settings,
        )

        event = LdsSessionPausedIntegrationEventV1(
            aggregate_id="sess-paused",
            session_id="sess-paused",
            reason="idle_timeout",
        )

        # Should not raise
        await handler.handle_async(event)


# =============================================================================
# LdsSessionEndedHandler Tests
# =============================================================================


class TestLdsSessionEndedHandler:
    """Tests for the session ended handler (informational)."""

    @pytest.mark.asyncio
    async def test_ended_handler_logs_without_error(
        self,
        mock_mediator,
        mock_mapper,
        mock_cloud_event_bus,
        mock_publishing_options,
        mock_session_repository,
        mock_deduplication,
        mock_settings,
    ):
        """Ended handler completes without errors."""
        handler = LdsSessionEndedHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_publishing_options,
            lablet_session_repository=mock_session_repository,
            deduplication_service=mock_deduplication,
            settings=mock_settings,
        )

        event = LdsSessionEndedIntegrationEventV1(
            aggregate_id="sess-ended",
            session_id="sess-ended",
            reason="timeout",
            ended_by="system",
        )

        # Should not raise
        await handler.handle_async(event)
