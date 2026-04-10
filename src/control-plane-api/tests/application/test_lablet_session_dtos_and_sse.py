"""Unit tests for Phase 7D LabletSession DTOs and SSE event handlers.

Tests cover:
- DTO mapping functions (4 tests)
- LabletSession SSE event handlers (4 tests)

Pattern: pytest fixtures + MagicMock + AsyncMock.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from lcm_core.domain.value_objects.state_transition import StateTransition

from application.dtos.lablet_session_dto import (
    LabletSessionDto,
    LabletSessionSummaryDto,
    StateTransitionDto,
    map_lablet_session_to_dto,
    map_lablet_session_to_summary_dto,
    map_state_history_to_dto,
)
from application.events.domain.lablet_session_sse_handlers import (
    LabletSessionCreatedDomainEventHandler,
    LabletSessionRunningDomainEventHandler,
    LabletSessionTerminatedDomainEventHandler,
)
from application.services.sse_event_relay import SSEEventRelay
from domain.entities.lablet_session import LabletSession, LabletSessionState
from domain.enums import LabletSessionStatus
from domain.events.lablet_session_events import (
    LabletSessionCreatedDomainEvent,
    LabletSessionRunningDomainEvent,
    LabletSessionTerminatedDomainEvent,
)

# =============================================================================
# DTO Mapping Tests
# =============================================================================


def _make_session_for_dto(
    session_id: str = "session-001",
    status: LabletSessionStatus = LabletSessionStatus.RUNNING,
) -> MagicMock:
    """Create a mock LabletSession with full state for DTO mapping."""
    session = MagicMock(spec=LabletSession)
    session.id.return_value = session_id

    now = datetime.now(timezone.utc)
    state = MagicMock(spec=LabletSessionState)
    state.status = status
    state.definition_id = "def-001"
    state.definition_name = "Lab 101"
    state.definition_version = "1.0.0"
    state.owner_id = "user-001"
    state.worker_id = "worker-001"
    state.reservation_id = "res-001"
    state.timeslot_start = now
    state.timeslot_end = now + timedelta(hours=2)
    state.created_at = now - timedelta(hours=1)
    state.scheduled_at = now - timedelta(minutes=30)
    state.lab_record_id = "lr-001"
    state.cml_lab_id = "lab-abc"
    state.cml_lab_title = "Lab ABC - Intro to Networking"
    state.allocated_ports = {"serial_1": 5041, "vnc_1": 5044}
    state.user_session_id = "us-001"
    state.grading_session_id = "gs-001"
    state.score_report_id = "sr-001"
    state.grade_result = "pass"
    state.started_at = now
    state.ended_at = None
    state.duration_seconds = None
    state.terminated_at = None
    state.state_history = [
        StateTransition(
            from_state=None,
            to_state="pending",
            transitioned_at=now - timedelta(hours=1),
            triggered_by="system",
            reason="Session created",
        ).to_dict(),
        StateTransition(
            from_state="pending",
            to_state="running",
            transitioned_at=now,
            triggered_by="lablet-controller",
            reason="Started",
        ).to_dict(),
    ]

    # ADR-030 resource observation fields
    state.observed_resources = None
    state.observed_ports = None
    state.port_drift_detected = False
    state.observation_count = 0
    state.observed_at = None

    # ADR-034 Sprint E: multi-pipeline progress + desired status
    state.pipeline_progress = None
    state.desired_status = LabletSessionStatus.RUNNING

    session.state = state
    return session


@pytest.mark.unit
class TestLabletSessionDtoMapping:
    """Tests for DTO mapping functions."""

    def test_map_state_history_to_dto(self) -> None:
        """Verify state history is correctly mapped to DTOs."""
        now = datetime.now(timezone.utc)
        transitions = [
            StateTransition(
                from_state=None,
                to_state="pending",
                transitioned_at=now,
                triggered_by="system",
                reason="Created",
            ).to_dict(),
        ]

        result = map_state_history_to_dto(transitions)
        assert len(result) == 1
        assert isinstance(result[0], StateTransitionDto)
        assert result[0].to_state == "pending"
        assert result[0].triggered_by == "system"

    def test_map_lablet_session_to_summary_dto(self) -> None:
        """Verify session maps to summary DTO correctly."""
        session = _make_session_for_dto()
        dto = map_lablet_session_to_summary_dto(session)

        assert isinstance(dto, LabletSessionSummaryDto)
        assert dto.id == "session-001"
        assert dto.status == "running"
        assert dto.definition_name == "Lab 101"
        assert dto.owner_id == "user-001"
        assert dto.worker_id == "worker-001"
        assert dto.user_session_id == "us-001"
        assert dto.cml_lab_id == "lab-abc"

    def test_map_lablet_session_to_full_dto(self) -> None:
        """Verify session maps to full DTO with all fields."""
        session = _make_session_for_dto()
        dto = map_lablet_session_to_dto(session)

        assert isinstance(dto, LabletSessionDto)
        assert dto.id == "session-001"
        assert dto.status == "running"
        assert dto.lab_record_id == "lr-001"
        assert dto.allocated_ports == {"serial_1": 5041, "vnc_1": 5044}
        assert dto.user_session_id == "us-001"
        assert dto.grading_session_id == "gs-001"
        assert dto.score_report_id == "sr-001"
        assert dto.grade_result == "pass"
        assert len(dto.state_history) == 2

    def test_map_summary_dto_from_pending_session(self) -> None:
        """Verify summary DTO works for a minimal PENDING session."""
        session = _make_session_for_dto(status=LabletSessionStatus.PENDING)
        session.state.worker_id = None
        session.state.user_session_id = None
        session.state.cml_lab_id = None
        session.state.state_history = []

        dto = map_lablet_session_to_summary_dto(session)
        assert dto.status == "pending"
        assert dto.worker_id is None
        assert dto.user_session_id is None


# =============================================================================
# SSE Event Handler Tests
# =============================================================================


@pytest.fixture
def mock_sse_relay() -> MagicMock:
    """Provide a mock SSEEventRelay."""
    mock = MagicMock(spec=SSEEventRelay)
    mock.broadcast_event = AsyncMock()
    return mock


@pytest.mark.unit
class TestLabletSessionSSEHandlers:
    """Tests for SSE event broadcasting on domain events."""

    @pytest.mark.asyncio
    async def test_created_event_broadcasts_sse(self, mock_sse_relay: MagicMock) -> None:
        """Verify LabletSessionCreated broadcasts SSE event."""
        handler = LabletSessionCreatedDomainEventHandler(sse_relay=mock_sse_relay)
        now = datetime.now(timezone.utc)

        event = LabletSessionCreatedDomainEvent(
            aggregate_id="session-001",
            definition_id="def-001",
            definition_name="Lab 101",
            definition_version="1.0.0",
            owner_id="user-001",
            timeslot_start=now,
            timeslot_end=now + timedelta(hours=2),
            reservation_id=None,
            created_at=now,
        )

        await handler.handle_async(event)

        mock_sse_relay.broadcast_event.assert_called_once()
        call_kwargs = mock_sse_relay.broadcast_event.call_args
        assert call_kwargs[1]["event_type"] == "lablet.session.created" or call_kwargs[0][0] == "lablet.session.created"

    @pytest.mark.asyncio
    async def test_running_event_broadcasts_sse(self, mock_sse_relay: MagicMock) -> None:
        """Verify LabletSessionRunning broadcasts SSE event."""
        handler = LabletSessionRunningDomainEventHandler(sse_relay=mock_sse_relay)

        event = LabletSessionRunningDomainEvent(
            aggregate_id="session-001",
            started_at=datetime.now(timezone.utc),
        )

        await handler.handle_async(event)
        mock_sse_relay.broadcast_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_terminated_event_broadcasts_sse(self, mock_sse_relay: MagicMock) -> None:
        """Verify LabletSessionTerminated broadcasts SSE event."""
        handler = LabletSessionTerminatedDomainEventHandler(sse_relay=mock_sse_relay)

        event = LabletSessionTerminatedDomainEvent(
            aggregate_id="session-001",
            terminated_at=datetime.now(timezone.utc),
            terminated_by="admin",
            reason="Manual stop",
            from_state="RUNNING",
            duration_seconds=3600,
        )

        await handler.handle_async(event)
        mock_sse_relay.broadcast_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_sse_handler_includes_session_id_in_data(self, mock_sse_relay: MagicMock) -> None:
        """Verify SSE broadcast data contains session_id field."""
        handler = LabletSessionCreatedDomainEventHandler(sse_relay=mock_sse_relay)
        now = datetime.now(timezone.utc)

        event = LabletSessionCreatedDomainEvent(
            aggregate_id="session-999",
            definition_id="def-001",
            definition_name="Lab 101",
            definition_version="1.0.0",
            owner_id="user-001",
            timeslot_start=now,
            timeslot_end=now + timedelta(hours=2),
            reservation_id=None,
            created_at=now,
        )

        await handler.handle_async(event)

        call_args = mock_sse_relay.broadcast_event.call_args
        # Check that session_id is in the data dict (positional or keyword)
        if call_args[1]:
            data = call_args[1].get("data", call_args[0][1] if len(call_args[0]) > 1 else {})
        else:
            data = call_args[0][1] if len(call_args[0]) > 1 else {}
        assert data.get("session_id") == "session-999"
