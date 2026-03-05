"""Unit tests for Phase 8 LabRecord CQRS command handlers (P8-27).

Tests cover all 14 Phase 8 command handlers:
- P8-1: DiscoverLabRecordsCommandHandler
- P8-2: StartLabRecordCommandHandler
- P8-3: StopLabRecordCommandHandler
- P8-4: WipeLabRecordCommandHandler
- P8-5: DeleteLabRecordCommandHandler
- P8-6: CloneLabRecordCommandHandler
- P8-7: ArchiveLabRecordCommandHandler
- P8-8: BindLabToLabletCommandHandler
- P8-9: UnbindLabFromLabletCommandHandler
- P8-10: UpdateLabRecordStatusCommandHandler
- P8-11: UpdateLabTopologyCommandHandler
- P8-12: RecordLabRunCommandHandler
- P8-13: CompleteLabActionCommandHandler
- P8-14: FailLabActionCommandHandler

Pattern: pytest fixtures + MagicMock + AsyncMock, matching existing test_commands.py style.
"""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from application.commands.lab import (
    ArchiveLabRecordCommand,
    ArchiveLabRecordCommandHandler,
    BindLabToLabletCommand,
    BindLabToLabletCommandHandler,
    CloneLabRecordCommand,
    CloneLabRecordCommandHandler,
    CompleteLabActionCommand,
    CompleteLabActionCommandHandler,
    DeleteLabRecordCommand,
    DeleteLabRecordCommandHandler,
    DiscoverLabRecordsCommand,
    DiscoverLabRecordsCommandHandler,
    FailLabActionCommand,
    FailLabActionCommandHandler,
    RecordLabRunCommand,
    RecordLabRunCommandHandler,
    StartLabRecordCommand,
    StartLabRecordCommandHandler,
    StopLabRecordCommand,
    StopLabRecordCommandHandler,
    UnbindLabFromLabletCommand,
    UnbindLabFromLabletCommandHandler,
    UpdateLabRecordStatusCommand,
    UpdateLabRecordStatusCommandHandler,
    UpdateLabTopologyCommand,
    UpdateLabTopologyCommandHandler,
    WipeLabRecordCommand,
    WipeLabRecordCommandHandler,
)
from domain.entities.lab_record import LabRecord
from domain.entities.lablet_session import LabletSession, LabletSessionState
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from domain.value_objects.lab_run_record import LabRunRecord
from lcm_core.domain.enums import LabRecordStatus
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator

from tests.fixtures.mixins import BaseTestCase

# =============================================================================
# Shared fixtures
# =============================================================================


@pytest.fixture
def mock_mediator() -> MagicMock:
    """Provide a mock Mediator."""
    return MagicMock(spec=Mediator)


@pytest.fixture
def mock_mapper() -> MagicMock:
    """Provide a mock Mapper."""
    return MagicMock(spec=Mapper)


@pytest.fixture
def mock_cloud_event_bus() -> MagicMock:
    """Provide a mock CloudEventBus."""
    return MagicMock(spec=CloudEventBus)


@pytest.fixture
def mock_cloud_event_publishing_options() -> MagicMock:
    """Provide a mock CloudEventPublishingOptions."""
    return MagicMock()


@pytest.fixture
def mock_lab_repository() -> MagicMock:
    """Provide a mock LabRecordRepository."""
    mock: MagicMock = MagicMock(spec=LabRecordRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    mock.get_all_by_worker_async = AsyncMock(return_value=[])
    mock.add_async = AsyncMock()
    mock.update_async = AsyncMock()
    return mock


@pytest.fixture
def mock_session_repository() -> MagicMock:
    """Provide a mock LabletSessionRepository."""
    mock: MagicMock = MagicMock(spec=LabletSessionRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    mock.get_by_lab_record_async = AsyncMock(return_value=None)
    mock.update_async = AsyncMock()
    return mock


def _make_discovered_lab(
    lab_record_id: str = "lr-001",
    lab_id: str = "lab-001",
    worker_id: str = "worker-001",
    status: LabRecordStatus = LabRecordStatus.DISCOVERED,
    pending_action: str | None = None,
) -> LabRecord:
    """Create a LabRecord via the discover factory and optionally force state."""
    lab = LabRecord.discover(
        lab_id=lab_id,
        worker_id=worker_id,
        title="Test Lab",
        description="A test lab for commands",
        state="DEFINED_ON_CORE",
        owner_username="admin",
        node_count=3,
        link_count=2,
    )
    # Override ID and status for test determinism
    lab.state.id = lab_record_id
    lab.state.status = status
    lab.state.pending_action = pending_action
    return lab


def _make_terminal_lab(lab_record_id: str = "lr-terminal") -> LabRecord:
    """Create a LabRecord in a terminal state (DELETED)."""
    return _make_discovered_lab(lab_record_id=lab_record_id, status=LabRecordStatus.DELETED)


def _make_mock_session(
    session_id: str = "lablet-001",
    lab_record_id: str | None = None,
) -> MagicMock:
    """Create a mock LabletSession with configurable lab_record_id."""
    session = MagicMock(spec=LabletSession)
    session.id.return_value = session_id
    session.state = MagicMock(spec=LabletSessionState)
    session.state.lab_record_id = lab_record_id
    session.is_terminal = False
    return session


# =============================================================================
# P8-2: StartLabRecordCommand
# =============================================================================


class TestStartLabRecordCommand(BaseTestCase):
    """Tests for StartLabRecordCommandHandler."""

    @pytest.fixture
    def handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_repository: MagicMock,
    ) -> StartLabRecordCommandHandler:
        return StartLabRecordCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lab_record_repository=mock_lab_repository,
        )

    @pytest.mark.asyncio
    async def test_start_success(self, handler: StartLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Start a lab in DISCOVERED state succeeds with 202."""
        lab = _make_discovered_lab()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result: OperationResult[Any] = await handler.handle_async(StartLabRecordCommand(lab_record_id="lr-001", started_by="user:admin"))

        assert result.is_success
        assert result.status_code == 202
        assert result.data["action"] == "start"
        mock_lab_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_not_found(self, handler: StartLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Start a nonexistent lab returns 404."""
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(StartLabRecordCommand(lab_record_id="does-not-exist"))

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_start_pending_action_conflict(self, handler: StartLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Start a lab with an existing pending action returns 409."""
        lab = _make_discovered_lab(pending_action="stop")
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(StartLabRecordCommand(lab_record_id="lr-001"))

        assert not result.is_success
        assert result.status_code == 409

    @pytest.mark.asyncio
    async def test_start_terminal_state(self, handler: StartLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Start a lab in terminal state returns 400."""
        lab = _make_terminal_lab()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(StartLabRecordCommand(lab_record_id="lr-terminal"))

        assert not result.is_success
        assert result.status_code == 400


# =============================================================================
# P8-3: StopLabRecordCommand
# =============================================================================


class TestStopLabRecordCommand(BaseTestCase):
    """Tests for StopLabRecordCommandHandler."""

    @pytest.fixture
    def handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_repository: MagicMock,
    ) -> StopLabRecordCommandHandler:
        return StopLabRecordCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lab_record_repository=mock_lab_repository,
        )

    @pytest.mark.asyncio
    async def test_stop_success(self, handler: StopLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Stop a lab succeeds with 202."""
        lab = _make_discovered_lab(status=LabRecordStatus.BOOTED)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(StopLabRecordCommand(lab_record_id="lr-001", stop_reason="user_request"))

        assert result.is_success
        assert result.status_code == 202
        assert result.data["action"] == "stop"
        mock_lab_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_not_found(self, handler: StopLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Stop a nonexistent lab returns 404."""
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(StopLabRecordCommand(lab_record_id="missing"))

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_stop_terminal_state(self, handler: StopLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Stop a lab in terminal state returns 400."""
        lab = _make_terminal_lab()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(StopLabRecordCommand(lab_record_id="lr-terminal"))

        assert not result.is_success
        assert result.status_code == 400


# =============================================================================
# P8-4: WipeLabRecordCommand
# =============================================================================


class TestWipeLabRecordCommand(BaseTestCase):
    """Tests for WipeLabRecordCommandHandler."""

    @pytest.fixture
    def handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_repository: MagicMock,
    ) -> WipeLabRecordCommandHandler:
        return WipeLabRecordCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lab_record_repository=mock_lab_repository,
        )

    @pytest.mark.asyncio
    async def test_wipe_success(self, handler: WipeLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Wipe a lab succeeds with 202."""
        lab = _make_discovered_lab(status=LabRecordStatus.BOOTED)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(WipeLabRecordCommand(lab_record_id="lr-001"))

        assert result.is_success
        assert result.status_code == 202
        assert result.data["action"] == "wipe"

    @pytest.mark.asyncio
    async def test_wipe_not_found(self, handler: WipeLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Wipe a nonexistent lab returns 404."""
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(WipeLabRecordCommand(lab_record_id="missing"))

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_wipe_pending_action_conflict(self, handler: WipeLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Wipe a lab with an existing pending action returns 409."""
        lab = _make_discovered_lab(pending_action="start")
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(WipeLabRecordCommand(lab_record_id="lr-001"))

        assert not result.is_success
        assert result.status_code == 409


# =============================================================================
# P8-5: DeleteLabRecordCommand
# =============================================================================


class TestDeleteLabRecordCommand(BaseTestCase):
    """Tests for DeleteLabRecordCommandHandler."""

    @pytest.fixture
    def handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_repository: MagicMock,
    ) -> DeleteLabRecordCommandHandler:
        return DeleteLabRecordCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lab_record_repository=mock_lab_repository,
        )

    @pytest.mark.asyncio
    async def test_delete_success(self, handler: DeleteLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Delete a lab succeeds with 202."""
        lab = _make_discovered_lab(status=LabRecordStatus.STOPPED)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(DeleteLabRecordCommand(lab_record_id="lr-001", deleted_by="admin"))

        assert result.is_success
        assert result.status_code == 202
        assert result.data["action"] == "delete"

    @pytest.mark.asyncio
    async def test_delete_terminal_state(self, handler: DeleteLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Delete a lab already in terminal state returns 400."""
        lab = _make_terminal_lab()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(DeleteLabRecordCommand(lab_record_id="lr-terminal"))

        assert not result.is_success
        assert result.status_code == 400


# =============================================================================
# P8-6: CloneLabRecordCommand
# =============================================================================


class TestCloneLabRecordCommand(BaseTestCase):
    """Tests for CloneLabRecordCommandHandler."""

    @pytest.fixture
    def handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_repository: MagicMock,
    ) -> CloneLabRecordCommandHandler:
        return CloneLabRecordCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lab_record_repository=mock_lab_repository,
        )

    @pytest.mark.asyncio
    async def test_clone_success(self, handler: CloneLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Clone a lab succeeds with 201."""
        source_lab = _make_discovered_lab(status=LabRecordStatus.DEFINED)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=source_lab)

        result = await handler.handle_async(
            CloneLabRecordCommand(
                source_lab_record_id="lr-001",
                title="My Clone",
                cloned_by="user:tester",
            )
        )

        assert result.is_success
        assert result.status_code == 201
        assert result.data["source"] == "clone"
        assert result.data["title"] == "My Clone"
        mock_lab_repository.add_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_clone_source_not_found(self, handler: CloneLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Clone from nonexistent source returns 404."""
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(CloneLabRecordCommand(source_lab_record_id="missing"))

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_clone_terminal_source(self, handler: CloneLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Clone from terminal source returns 400."""
        lab = _make_terminal_lab()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(CloneLabRecordCommand(source_lab_record_id="lr-terminal"))

        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_clone_default_title(self, handler: CloneLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Clone without title generates default 'Clone of <source_title>'."""
        source_lab = _make_discovered_lab(status=LabRecordStatus.DEFINED)
        source_lab.state.title = "Original Lab"
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=source_lab)

        result = await handler.handle_async(CloneLabRecordCommand(source_lab_record_id="lr-001"))

        assert result.is_success
        assert result.data["title"] == "Clone of Original Lab"


# =============================================================================
# P8-7: ArchiveLabRecordCommand
# =============================================================================


class TestArchiveLabRecordCommand(BaseTestCase):
    """Tests for ArchiveLabRecordCommandHandler."""

    @pytest.fixture
    def handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_repository: MagicMock,
    ) -> ArchiveLabRecordCommandHandler:
        return ArchiveLabRecordCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lab_record_repository=mock_lab_repository,
        )

    @pytest.mark.asyncio
    async def test_archive_success(self, handler: ArchiveLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Archive a lab in STOPPED state succeeds."""
        lab = _make_discovered_lab(status=LabRecordStatus.STOPPED)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(ArchiveLabRecordCommand(lab_record_id="lr-001", archived_by="admin"))

        assert result.is_success
        assert result.status_code == 200
        assert result.data["status"] == "archived"
        mock_lab_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_archive_not_found(self, handler: ArchiveLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Archive a nonexistent lab returns 404."""
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(ArchiveLabRecordCommand(lab_record_id="missing"))

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_archive_pending_action_conflict(self, handler: ArchiveLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Archive a lab with pending action returns 409."""
        lab = _make_discovered_lab(pending_action="start")
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(ArchiveLabRecordCommand(lab_record_id="lr-001"))

        assert not result.is_success
        assert result.status_code == 409

    @pytest.mark.asyncio
    async def test_archive_already_terminal(self, handler: ArchiveLabRecordCommandHandler, mock_lab_repository: MagicMock) -> None:
        """Archive a lab already in terminal state returns 400."""
        lab = _make_terminal_lab()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(ArchiveLabRecordCommand(lab_record_id="lr-terminal"))

        assert not result.is_success
        assert result.status_code == 400


# =============================================================================
# P8-8: BindLabToLabletCommand
# =============================================================================


class TestBindLabToLabletCommand(BaseTestCase):
    """Tests for BindLabToLabletCommandHandler."""

    @pytest.fixture
    def handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_repository: MagicMock,
        mock_session_repository: MagicMock,
    ) -> BindLabToLabletCommandHandler:
        return BindLabToLabletCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lab_record_repository=mock_lab_repository,
            lablet_session_repository=mock_session_repository,
        )

    @pytest.mark.asyncio
    async def test_bind_success(
        self,
        handler: BindLabToLabletCommandHandler,
        mock_lab_repository: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Bind a lab to a lablet succeeds with 201."""
        lab = _make_discovered_lab(status=LabRecordStatus.DEFINED)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)
        session = _make_mock_session(session_id="lablet-001", lab_record_id=None)
        mock_session_repository.get_by_id_async = self.create_async_mock(return_value=session)

        result = await handler.handle_async(
            BindLabToLabletCommand(
                lab_record_id="lr-001",
                lablet_session_id="lablet-001",
                role="primary",
            )
        )

        assert result.is_success
        assert result.status_code == 201
        assert result.data["role"] == "primary"
        mock_session_repository.update_async.assert_called_once()
        mock_lab_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_bind_lab_not_found(
        self,
        handler: BindLabToLabletCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Bind to nonexistent lab returns 404."""
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(BindLabToLabletCommand(lab_record_id="missing", lablet_session_id="lablet-001"))

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_bind_terminal_lab(
        self,
        handler: BindLabToLabletCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Bind a lab in terminal state returns 400."""
        lab = _make_terminal_lab()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(BindLabToLabletCommand(lab_record_id="lr-terminal", lablet_session_id="lablet-001"))

        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_bind_session_not_found(
        self,
        handler: BindLabToLabletCommandHandler,
        mock_lab_repository: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Bind to nonexistent session returns 404."""
        lab = _make_discovered_lab(status=LabRecordStatus.DEFINED)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)
        mock_session_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(BindLabToLabletCommand(lab_record_id="lr-001", lablet_session_id="missing"))

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_bind_duplicate_active_binding(
        self,
        handler: BindLabToLabletCommandHandler,
        mock_lab_repository: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Bind with existing active binding for same pair returns 409."""
        lab = _make_discovered_lab(status=LabRecordStatus.DEFINED)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)
        session = _make_mock_session(session_id="lablet-001", lab_record_id="lr-001")
        mock_session_repository.get_by_id_async = self.create_async_mock(return_value=session)

        result = await handler.handle_async(BindLabToLabletCommand(lab_record_id="lr-001", lablet_session_id="lablet-001"))

        assert not result.is_success
        assert result.status_code == 409

    @pytest.mark.asyncio
    async def test_bind_session_already_bound_to_other_lab(
        self,
        handler: BindLabToLabletCommandHandler,
        mock_lab_repository: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Bind when session is already bound to another lab returns 409."""
        lab = _make_discovered_lab(status=LabRecordStatus.DEFINED)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)
        session = _make_mock_session(session_id="lablet-001", lab_record_id="lr-other")
        mock_session_repository.get_by_id_async = self.create_async_mock(return_value=session)

        result = await handler.handle_async(BindLabToLabletCommand(lab_record_id="lr-001", lablet_session_id="lablet-001"))

        assert not result.is_success
        assert result.status_code == 409

    @pytest.mark.asyncio
    async def test_bind_invalid_role(
        self,
        handler: BindLabToLabletCommandHandler,
        mock_lab_repository: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Bind with invalid role returns 400."""
        lab = _make_discovered_lab(status=LabRecordStatus.DEFINED)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)
        session = _make_mock_session(session_id="lablet-001", lab_record_id=None)
        mock_session_repository.get_by_id_async = self.create_async_mock(return_value=session)

        result = await handler.handle_async(
            BindLabToLabletCommand(
                lab_record_id="lr-001",
                lablet_session_id="lablet-001",
                role="INVALID_ROLE",
            )
        )

        assert not result.is_success
        assert result.status_code == 400


# =============================================================================
# P8-9: UnbindLabFromLabletCommand
# =============================================================================


class TestUnbindLabFromLabletCommand(BaseTestCase):
    """Tests for UnbindLabFromLabletCommandHandler."""

    @pytest.fixture
    def handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_repository: MagicMock,
        mock_session_repository: MagicMock,
    ) -> UnbindLabFromLabletCommandHandler:
        return UnbindLabFromLabletCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lab_record_repository=mock_lab_repository,
            lablet_session_repository=mock_session_repository,
        )

    @pytest.mark.asyncio
    async def test_unbind_success(
        self,
        handler: UnbindLabFromLabletCommandHandler,
        mock_lab_repository: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Unbind a lab from a lablet succeeds with 200."""
        lab = _make_discovered_lab(status=LabRecordStatus.DEFINED)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)
        session = _make_mock_session(session_id="lablet-001", lab_record_id="lr-001")
        mock_session_repository.get_by_id_async = self.create_async_mock(return_value=session)

        result = await handler.handle_async(
            UnbindLabFromLabletCommand(
                lab_record_id="lr-001",
                lablet_session_id="lablet-001",
                reason="user_request",
            )
        )

        assert result.is_success
        assert result.status_code == 200
        assert result.data["status"] == "released"
        mock_session_repository.update_async.assert_called_once()
        mock_lab_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_unbind_lab_not_found(
        self,
        handler: UnbindLabFromLabletCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Unbind from nonexistent lab returns 404."""
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(UnbindLabFromLabletCommand(lab_record_id="missing", lablet_session_id="lablet-001"))

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_unbind_session_not_found(
        self,
        handler: UnbindLabFromLabletCommandHandler,
        mock_lab_repository: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Unbind with nonexistent session returns 404."""
        lab = _make_discovered_lab(status=LabRecordStatus.DEFINED)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)
        mock_session_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(UnbindLabFromLabletCommand(lab_record_id="lr-001", lablet_session_id="lablet-001"))

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_unbind_no_active_binding(
        self,
        handler: UnbindLabFromLabletCommandHandler,
        mock_lab_repository: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Unbind when session is not bound to this lab returns 404."""
        lab = _make_discovered_lab(status=LabRecordStatus.DEFINED)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)
        session = _make_mock_session(session_id="lablet-001", lab_record_id=None)
        mock_session_repository.get_by_id_async = self.create_async_mock(return_value=session)

        result = await handler.handle_async(UnbindLabFromLabletCommand(lab_record_id="lr-001", lablet_session_id="lablet-001"))

        assert not result.is_success
        assert result.status_code == 404


# =============================================================================
# P8-10: UpdateLabRecordStatusCommand
# =============================================================================


class TestUpdateLabRecordStatusCommand(BaseTestCase):
    """Tests for UpdateLabRecordStatusCommandHandler."""

    @pytest.fixture
    def handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_repository: MagicMock,
    ) -> UpdateLabRecordStatusCommandHandler:
        return UpdateLabRecordStatusCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lab_record_repository=mock_lab_repository,
        )

    @pytest.mark.asyncio
    async def test_update_status_via_typed_value(
        self,
        handler: UpdateLabRecordStatusCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Update status with a typed LabRecordStatus value succeeds."""
        lab = _make_discovered_lab(status=LabRecordStatus.STARTING)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(UpdateLabRecordStatusCommand(lab_record_id="lr-001", new_status="booted"))

        assert result.is_success
        assert result.status_code == 200
        mock_lab_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_status_already_at_target(
        self,
        handler: UpdateLabRecordStatusCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Update status when already at target returns 200 with no-change message."""
        lab = _make_discovered_lab(status=LabRecordStatus.BOOTED)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(UpdateLabRecordStatusCommand(lab_record_id="lr-001", new_status="booted"))

        assert result.is_success
        assert "no change" in result.data["message"].lower()

    @pytest.mark.asyncio
    async def test_update_status_not_found(
        self,
        handler: UpdateLabRecordStatusCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Update status for nonexistent lab returns 404."""
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(UpdateLabRecordStatusCommand(lab_record_id="missing", new_status="booted"))

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_update_status_no_status_provided(
        self,
        handler: UpdateLabRecordStatusCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Update status with neither new_status nor cml_state returns 400."""
        lab = _make_discovered_lab()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(UpdateLabRecordStatusCommand(lab_record_id="lr-001"))

        assert not result.is_success
        assert result.status_code == 400


# =============================================================================
# P8-11: UpdateLabTopologyCommand
# =============================================================================


class TestUpdateLabTopologyCommand(BaseTestCase):
    """Tests for UpdateLabTopologyCommandHandler."""

    @pytest.fixture
    def handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_repository: MagicMock,
    ) -> UpdateLabTopologyCommandHandler:
        return UpdateLabTopologyCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lab_record_repository=mock_lab_repository,
        )

    @pytest.mark.asyncio
    async def test_update_topology_success(
        self,
        handler: UpdateLabTopologyCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Update topology with valid data succeeds."""
        lab = _make_discovered_lab(status=LabRecordStatus.DEFINED)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(
            UpdateLabTopologyCommand(
                lab_record_id="lr-001",
                topology_data={
                    "nodes": [{"label": "r1", "node_definition": "iosv", "x": 0, "y": 0}],
                    "links": [],
                },
                change_summary="Added router r1",
            )
        )

        assert result.is_success
        assert result.status_code == 200
        mock_lab_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_topology_not_found(
        self,
        handler: UpdateLabTopologyCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Update topology for nonexistent lab returns 404."""
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(UpdateLabTopologyCommand(lab_record_id="missing", topology_data={}))

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_update_topology_terminal_state(
        self,
        handler: UpdateLabTopologyCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Update topology for terminal lab returns 400."""
        lab = _make_terminal_lab()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(UpdateLabTopologyCommand(lab_record_id="lr-terminal", topology_data={"nodes": []}))

        assert not result.is_success
        assert result.status_code == 400


# =============================================================================
# P8-12: RecordLabRunCommand
# =============================================================================


class TestRecordLabRunCommand(BaseTestCase):
    """Tests for RecordLabRunCommandHandler."""

    @pytest.fixture
    def handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_repository: MagicMock,
    ) -> RecordLabRunCommandHandler:
        return RecordLabRunCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lab_record_repository=mock_lab_repository,
        )

    @pytest.mark.asyncio
    async def test_record_run_success(
        self,
        handler: RecordLabRunCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Record a lab run with timestamps succeeds with 201."""
        lab = _make_discovered_lab(status=LabRecordStatus.STOPPED)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(
            RecordLabRunCommand(
                lab_record_id="lr-001",
                started_at="2025-01-01T10:00:00+00:00",
                stopped_at="2025-01-01T11:30:00+00:00",
                started_by="user:admin",
                stop_reason="timeslot_end",
                final_state="stopped",
            )
        )

        assert result.is_success
        assert result.status_code == 201
        assert result.data["duration_seconds"] == 5400  # 1.5 hours
        mock_lab_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_run_not_found(
        self,
        handler: RecordLabRunCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Record a run for nonexistent lab returns 404."""
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(RecordLabRunCommand(lab_record_id="missing"))

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_record_run_minimal_fields(
        self,
        handler: RecordLabRunCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Record a run with only lab_record_id uses defaults."""
        lab = _make_discovered_lab(status=LabRecordStatus.BOOTED)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(RecordLabRunCommand(lab_record_id="lr-001"))

        assert result.is_success
        assert result.status_code == 201
        assert result.data["started_by"] == "system"


# =============================================================================
# P8-13: CompleteLabActionCommand
# =============================================================================


class TestCompleteLabActionCommand(BaseTestCase):
    """Tests for CompleteLabActionCommandHandler."""

    @pytest.fixture
    def handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_repository: MagicMock,
    ) -> CompleteLabActionCommandHandler:
        return CompleteLabActionCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lab_record_repository=mock_lab_repository,
        )

    @pytest.mark.asyncio
    async def test_complete_start_action(
        self,
        handler: CompleteLabActionCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Complete a 'start' action clears pending and transitions to BOOTED."""
        lab = _make_discovered_lab(status=LabRecordStatus.STARTING, pending_action="start")
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(CompleteLabActionCommand(lab_record_id="lr-001", action="start"))

        assert result.is_success
        assert result.status_code == 200
        mock_lab_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_stop_action(
        self,
        handler: CompleteLabActionCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Complete a 'stop' action clears pending and transitions to STOPPED."""
        lab = _make_discovered_lab(status=LabRecordStatus.STOPPING, pending_action="stop")
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(CompleteLabActionCommand(lab_record_id="lr-001", action="stop"))

        assert result.is_success
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_complete_no_action_and_no_pending(
        self,
        handler: CompleteLabActionCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Complete with no action specified and no pending action returns 400."""
        lab = _make_discovered_lab()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(CompleteLabActionCommand(lab_record_id="lr-001"))

        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_complete_not_found(
        self,
        handler: CompleteLabActionCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Complete action for nonexistent lab returns 404."""
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(CompleteLabActionCommand(lab_record_id="missing", action="start"))

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_start_action_opens_run(
        self,
        handler: CompleteLabActionCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Completing a 'start' action should open a new run in run_history_v2."""
        lab = _make_discovered_lab(status=LabRecordStatus.STARTING, pending_action="start")
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(CompleteLabActionCommand(lab_record_id="lr-001", action="start"))

        assert result.is_success
        assert len(lab.state.run_history_v2) == 1
        run = lab.state.run_history_v2[0]
        assert run["stopped_at"] is None  # Open run — not yet stopped
        assert run["started_by"] == "user"
        assert run["run_id"] is not None
        assert result.data["run_id"] == run["run_id"]

    @pytest.mark.asyncio
    async def test_stop_action_closes_run(
        self,
        handler: CompleteLabActionCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Completing a 'stop' action should close the open run in run_history_v2."""
        lab = _make_discovered_lab(status=LabRecordStatus.STOPPING, pending_action="stop")
        # Simulate an open run from a previous start
        open_run = LabRunRecord(
            run_id="run-existing",
            started_at=datetime.now(timezone.utc),
            stopped_at=None,
            duration_seconds=None,
            started_by="user",
        )
        lab.state.run_history_v2.append(open_run.to_dict())
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(CompleteLabActionCommand(lab_record_id="lr-001", action="stop"))

        assert result.is_success
        assert len(lab.state.run_history_v2) == 1
        closed_run = lab.state.run_history_v2[0]
        assert closed_run["stopped_at"] is not None
        assert closed_run["stop_reason"] == "stop"
        assert closed_run["final_state"] == "stopped"
        assert closed_run["duration_seconds"] is not None
        assert closed_run["duration_seconds"] >= 0
        assert result.data["run_id"] == "run-existing"

    @pytest.mark.asyncio
    async def test_wipe_action_closes_run(
        self,
        handler: CompleteLabActionCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Completing a 'wipe' action should close the open run with final_state=wiped."""
        lab = _make_discovered_lab(status=LabRecordStatus.BOOTED, pending_action="wipe")
        open_run = LabRunRecord(
            run_id="run-wipe",
            started_at=datetime.now(timezone.utc),
            stopped_at=None,
            duration_seconds=None,
            started_by="user",
        )
        lab.state.run_history_v2.append(open_run.to_dict())
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(CompleteLabActionCommand(lab_record_id="lr-001", action="wipe"))

        assert result.is_success
        closed_run = lab.state.run_history_v2[0]
        assert closed_run["stopped_at"] is not None
        assert closed_run["final_state"] == "wiped"
        assert closed_run["stop_reason"] == "wipe"

    @pytest.mark.asyncio
    async def test_stop_no_open_run_graceful(
        self,
        handler: CompleteLabActionCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Completing a 'stop' with no open run should succeed without error."""
        lab = _make_discovered_lab(status=LabRecordStatus.STOPPING, pending_action="stop")
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(CompleteLabActionCommand(lab_record_id="lr-001", action="stop"))

        assert result.is_success
        assert len(lab.state.run_history_v2) == 0  # No runs to close
        assert result.data["run_id"] is None


# =============================================================================
# P8-14: FailLabActionCommand
# =============================================================================


class TestFailLabActionCommand(BaseTestCase):
    """Tests for FailLabActionCommandHandler."""

    @pytest.fixture
    def handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_repository: MagicMock,
    ) -> FailLabActionCommandHandler:
        return FailLabActionCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lab_record_repository=mock_lab_repository,
        )

    @pytest.mark.asyncio
    async def test_fail_action_success(
        self,
        handler: FailLabActionCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Fail a pending action records the error."""
        lab = _make_discovered_lab(pending_action="start")
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(
            FailLabActionCommand(
                lab_record_id="lr-001",
                error_message="CML API returned 500",
                transition_to_error=False,
            )
        )

        assert result.is_success
        assert result.status_code == 200
        assert result.data["action"] == "start"
        mock_lab_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_fail_action_transition_to_error(
        self,
        handler: FailLabActionCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Fail a pending action with transition_to_error marks lab as ERROR."""
        lab = _make_discovered_lab(pending_action="wipe")
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(
            FailLabActionCommand(
                lab_record_id="lr-001",
                error_message="Wipe failed",
                transition_to_error=True,
            )
        )

        assert result.is_success
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_fail_action_no_pending(
        self,
        handler: FailLabActionCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Fail with no pending action returns 400."""
        lab = _make_discovered_lab()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(FailLabActionCommand(lab_record_id="lr-001", error_message="Nothing to fail"))

        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_fail_action_not_found(
        self,
        handler: FailLabActionCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Fail action for nonexistent lab returns 404."""
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(FailLabActionCommand(lab_record_id="missing", error_message="Not found"))

        assert not result.is_success
        assert result.status_code == 404


# =============================================================================
# P8-1: DiscoverLabRecordsCommand
# =============================================================================


class TestDiscoverLabRecordsCommand(BaseTestCase):
    """Tests for DiscoverLabRecordsCommandHandler."""

    @pytest.fixture
    def handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_repository: MagicMock,
    ) -> DiscoverLabRecordsCommandHandler:
        return DiscoverLabRecordsCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lab_record_repository=mock_lab_repository,
        )

    @pytest.mark.asyncio
    async def test_discover_new_labs(
        self,
        handler: DiscoverLabRecordsCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Discover new labs creates records with status DISCOVERED."""
        mock_lab_repository.get_all_by_worker_async = self.create_async_mock(return_value=[])

        labs_data = [
            {"id": "lab-new-1", "title": "New Lab 1", "state": "DEFINED_ON_CORE", "node_count": 2, "link_count": 1},
            {"id": "lab-new-2", "title": "New Lab 2", "state": "STOPPED", "node_count": 4, "link_count": 3},
        ]

        result = await handler.handle_async(
            DiscoverLabRecordsCommand(
                worker_id="worker-001",
                labs=labs_data,
                source="test",
            )
        )

        assert result.is_success
        assert result.data.discovered == 2
        assert result.data.updated == 0
        assert result.data.orphaned == 0
        assert mock_lab_repository.add_async.call_count == 2

    @pytest.mark.asyncio
    async def test_discover_updates_existing_labs(
        self,
        handler: DiscoverLabRecordsCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Discover existing labs updates them."""
        existing = _make_discovered_lab(lab_id="lab-existing", worker_id="worker-001")
        mock_lab_repository.get_all_by_worker_async = self.create_async_mock(return_value=[existing])

        labs_data = [
            {"id": "lab-existing", "title": "Updated Lab", "state": "BOOTED", "node_count": 5, "link_count": 4},
        ]

        result = await handler.handle_async(DiscoverLabRecordsCommand(worker_id="worker-001", labs=labs_data))

        assert result.is_success
        assert result.data.discovered == 0
        assert result.data.updated == 1
        mock_lab_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_discover_orphans_missing_labs(
        self,
        handler: DiscoverLabRecordsCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Discover marks DB labs not in CML scan as ORPHANED."""
        existing = _make_discovered_lab(lab_id="lab-orphan", worker_id="worker-001")
        mock_lab_repository.get_all_by_worker_async = self.create_async_mock(return_value=[existing])

        # CML scan returns empty — existing lab is now orphaned
        result = await handler.handle_async(DiscoverLabRecordsCommand(worker_id="worker-001", labs=[]))

        assert result.is_success
        assert result.data.orphaned == 1
        mock_lab_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_discover_missing_worker_id(
        self,
        handler: DiscoverLabRecordsCommandHandler,
    ) -> None:
        """Discover without worker_id returns 400."""
        result = await handler.handle_async(DiscoverLabRecordsCommand(worker_id="", labs=[]))

        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_discover_handles_lab_missing_id(
        self,
        handler: DiscoverLabRecordsCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Discover gracefully handles labs with missing 'id' field."""
        mock_lab_repository.get_all_by_worker_async = self.create_async_mock(return_value=[])

        labs_data = [
            {"title": "No ID Lab", "state": "BOOTED"},  # Missing 'id'
        ]

        result = await handler.handle_async(DiscoverLabRecordsCommand(worker_id="worker-001", labs=labs_data))

        assert result.is_success
        assert result.data.discovered == 0
        assert len(result.data.errors) == 1  # Error recorded for missing id

    @pytest.mark.asyncio
    async def test_discover_mixed_new_and_existing(
        self,
        handler: DiscoverLabRecordsCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Discover with mix of new and existing labs reports correct stats."""
        existing = _make_discovered_lab(lab_id="lab-old", worker_id="worker-001")
        mock_lab_repository.get_all_by_worker_async = self.create_async_mock(return_value=[existing])

        labs_data = [
            {"id": "lab-old", "title": "Existing", "state": "BOOTED", "node_count": 3, "link_count": 2},
            {"id": "lab-brand-new", "title": "Brand New", "state": "DEFINED_ON_CORE", "node_count": 1, "link_count": 0},
        ]

        result = await handler.handle_async(DiscoverLabRecordsCommand(worker_id="worker-001", labs=labs_data))

        assert result.is_success
        assert result.data.synced == 2
        assert result.data.discovered == 1
        assert result.data.updated == 1
        assert result.data.orphaned == 0
