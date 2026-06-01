"""Unit tests for Phase 8 LabRecord CQRS query handlers (P8-28).

Tests cover all 7 new Phase 8 query handlers:
- P8-15: GetLabRecordsQueryHandler
- P8-16: GetLabRecordQueryHandler
- P8-17: GetLabRecordTopologyQueryHandler
- P8-18: GetLabRecordRevisionsQueryHandler
- P8-19: GetLabRecordRunsQueryHandler
- P8-20: GetLabRecordBindingsQueryHandler
- P8-22: GetLabletLabsQueryHandler

Note: P8-21 (GetWorkerLabsQuery) already existed before Phase 8.

Pattern: pytest fixtures + MagicMock + AsyncMock, matching test_lab_commands.py style.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from lcm_core.domain.enums import LabRecordStatus
from neuroglia.core import OperationResult

from application.queries.get_lab_record_bindings_query import (
    GetLabRecordBindingsQuery,
    GetLabRecordBindingsQueryHandler,
)
from application.queries.get_lab_record_query import GetLabRecordQuery, GetLabRecordQueryHandler
from application.queries.get_lab_record_revisions_query import (
    GetLabRecordRevisionsQuery,
    GetLabRecordRevisionsQueryHandler,
)
from application.queries.get_lab_record_runs_query import GetLabRecordRunsQuery, GetLabRecordRunsQueryHandler
from application.queries.get_lab_record_topology_query import (
    GetLabRecordTopologyQuery,
    GetLabRecordTopologyQueryHandler,
)
from application.queries.get_lab_records_query import GetLabRecordsQuery, GetLabRecordsQueryHandler
from domain.entities.lab_record import LabRecord
from domain.entities.lablet_session import LabletSession, LabletSessionState
from domain.enums import LabletSessionStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from domain.value_objects.lab_run_record import LabRunRecord
from tests.fixtures.mixins import BaseTestCase

# =============================================================================
# Shared fixtures
# =============================================================================


@pytest.fixture
def mock_lab_repository() -> MagicMock:
    """Provide a mock LabRecordRepository."""
    mock: MagicMock = MagicMock(spec=LabRecordRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    mock.get_all_async = AsyncMock(return_value=[])
    mock.get_all_by_worker_async = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def mock_session_repository() -> MagicMock:
    """Provide a mock LabletSessionRepository."""
    mock: MagicMock = MagicMock(spec=LabletSessionRepository)
    mock.get_by_lab_record_async = AsyncMock(return_value=None)
    mock.get_by_id_async = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def mock_worker_repository() -> MagicMock:
    """Provide a mock CMLWorkerRepository."""
    mock: MagicMock = MagicMock(spec=CMLWorkerRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    return mock


# =============================================================================
# Factories
# =============================================================================


def _make_discovered_lab(
    lab_record_id: str = "lr-001",
    lab_id: str = "lab-001",
    worker_id: str = "worker-001",
    status: LabRecordStatus = LabRecordStatus.DISCOVERED,
    owner_username: str = "admin",
    title: str = "Test Lab",
) -> LabRecord:
    """Create a LabRecord via the discover factory and optionally force state."""
    lab = LabRecord.discover(
        lab_id=lab_id,
        worker_id=worker_id,
        title=title,
        description="A test lab for queries",
        state="DEFINED_ON_CORE",
        owner_username=owner_username,
        node_count=3,
        link_count=2,
    )
    lab.state.id = lab_record_id
    lab.state.status = status
    return lab


def _make_mock_session(
    session_id: str = "lablet-001",
    lab_record_id: str = "lr-001",
    is_terminal: bool = False,
) -> MagicMock:
    """Create a mock LabletSession for testing bindings."""
    from datetime import datetime, timezone

    session = MagicMock(spec=LabletSession)
    session.id.return_value = session_id
    session.state = MagicMock(spec=LabletSessionState)
    session.state.lab_record_id = lab_record_id
    session.state.definition_name = "test-definition"
    session.state.status = LabletSessionStatus.TERMINATED if is_terminal else LabletSessionStatus.RUNNING
    session.state.scheduled_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    session.state.terminated_at = datetime(2026, 2, 2, tzinfo=timezone.utc) if is_terminal else None
    session.is_terminal = is_terminal
    return session


def _append_run_with_session(lab: LabRecord, session_id: str, run_id: str = "run-001") -> LabRecord:
    """Attach a historical run entry that references a LabletSession."""
    from datetime import datetime, timezone

    lab.state.run_history_v2.append(
        LabRunRecord(
            run_id=run_id,
            started_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            stopped_at=datetime(2026, 2, 2, tzinfo=timezone.utc),
            lablet_session_id=session_id,
            final_state="stopped",
        ).to_dict()
    )
    return lab


# =============================================================================
# P8-15: GetLabRecordsQuery
# =============================================================================


class TestGetLabRecordsQuery(BaseTestCase):
    """Tests for GetLabRecordsQueryHandler."""

    @pytest.fixture
    def handler(
        self,
        mock_lab_repository: MagicMock,
        mock_session_repository: MagicMock,
        mock_worker_repository: MagicMock,
    ) -> GetLabRecordsQueryHandler:
        return GetLabRecordsQueryHandler(
            lab_record_repository=mock_lab_repository,
            lablet_session_repository=mock_session_repository,
            cml_worker_repository=mock_worker_repository,
        )

    @pytest.mark.asyncio
    async def test_list_all_returns_ok(self, handler: GetLabRecordsQueryHandler, mock_lab_repository: MagicMock) -> None:
        """Listing all labs returns 200 with lab data."""
        lab1 = _make_discovered_lab(lab_record_id="lr-001", lab_id="lab-001")
        lab2 = _make_discovered_lab(lab_record_id="lr-002", lab_id="lab-002", status=LabRecordStatus.BOOTED)
        mock_lab_repository.get_all_async = self.create_async_mock(return_value=[lab1, lab2])

        result: OperationResult[Any] = await handler.handle_async(GetLabRecordsQuery())

        assert result.is_success
        assert result.status_code == 200
        assert len(result.data) == 2

    @pytest.mark.asyncio
    async def test_filter_by_worker_id(self, handler: GetLabRecordsQueryHandler, mock_lab_repository: MagicMock) -> None:
        """Filtering by worker_id calls get_all_by_worker_async."""
        lab = _make_discovered_lab()
        mock_lab_repository.get_all_by_worker_async = self.create_async_mock(return_value=[lab])

        result = await handler.handle_async(GetLabRecordsQuery(worker_id="worker-001"))

        assert result.is_success
        assert len(result.data) == 1
        mock_lab_repository.get_all_by_worker_async.assert_called_once_with("worker-001")

    @pytest.mark.asyncio
    async def test_filter_by_status(self, handler: GetLabRecordsQueryHandler, mock_lab_repository: MagicMock) -> None:
        """Filtering by status returns only matching labs."""
        lab1 = _make_discovered_lab(lab_record_id="lr-001", status=LabRecordStatus.DISCOVERED)
        lab2 = _make_discovered_lab(lab_record_id="lr-002", status=LabRecordStatus.BOOTED)
        mock_lab_repository.get_all_async = self.create_async_mock(return_value=[lab1, lab2])

        result = await handler.handle_async(GetLabRecordsQuery(status="booted"))

        assert result.is_success
        assert len(result.data) == 1
        assert result.data[0]["status"] == "booted"

    @pytest.mark.asyncio
    async def test_invalid_status_returns_400(self, handler: GetLabRecordsQueryHandler, mock_lab_repository: MagicMock) -> None:
        """Invalid status filter returns 400."""
        mock_lab_repository.get_all_async = self.create_async_mock(return_value=[])

        result = await handler.handle_async(GetLabRecordsQuery(status="INVALID_STATUS"))

        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_filter_by_owner(self, handler: GetLabRecordsQueryHandler, mock_lab_repository: MagicMock) -> None:
        """Filtering by owner returns only matching labs."""
        lab1 = _make_discovered_lab(lab_record_id="lr-001", owner_username="alice")
        lab2 = _make_discovered_lab(lab_record_id="lr-002", owner_username="bob")
        mock_lab_repository.get_all_async = self.create_async_mock(return_value=[lab1, lab2])

        result = await handler.handle_async(GetLabRecordsQuery(owner="alice"))

        assert result.is_success
        assert len(result.data) == 1
        assert result.data[0]["owner_username"] == "alice"

    @pytest.mark.asyncio
    async def test_excludes_terminal_by_default(self, handler: GetLabRecordsQueryHandler, mock_lab_repository: MagicMock) -> None:
        """Terminal labs (DELETED/ARCHIVED) are excluded by default."""
        lab1 = _make_discovered_lab(lab_record_id="lr-001", status=LabRecordStatus.BOOTED)
        lab2 = _make_discovered_lab(lab_record_id="lr-002", status=LabRecordStatus.DELETED)
        mock_lab_repository.get_all_async = self.create_async_mock(return_value=[lab1, lab2])

        result = await handler.handle_async(GetLabRecordsQuery())

        assert result.is_success
        assert len(result.data) == 1

    @pytest.mark.asyncio
    async def test_include_terminal(self, handler: GetLabRecordsQueryHandler, mock_lab_repository: MagicMock) -> None:
        """include_terminal=True includes DELETED/ARCHIVED labs."""
        lab1 = _make_discovered_lab(lab_record_id="lr-001", status=LabRecordStatus.BOOTED)
        lab2 = _make_discovered_lab(lab_record_id="lr-002", status=LabRecordStatus.DELETED)
        mock_lab_repository.get_all_async = self.create_async_mock(return_value=[lab1, lab2])

        result = await handler.handle_async(GetLabRecordsQuery(include_terminal=True))

        assert result.is_success
        assert len(result.data) == 2

    @pytest.mark.asyncio
    async def test_empty_result(self, handler: GetLabRecordsQueryHandler, mock_lab_repository: MagicMock) -> None:
        """No matching labs returns empty list, not error."""
        mock_lab_repository.get_all_async = self.create_async_mock(return_value=[])

        result = await handler.handle_async(GetLabRecordsQuery())

        assert result.is_success
        assert len(result.data) == 0


# =============================================================================
# P8-16: GetLabRecordQuery
# =============================================================================


class TestGetLabRecordQuery(BaseTestCase):
    """Tests for GetLabRecordQueryHandler."""

    @pytest.fixture
    def handler(
        self,
        mock_lab_repository: MagicMock,
        mock_session_repository: MagicMock,
        mock_worker_repository: MagicMock,
    ) -> GetLabRecordQueryHandler:
        return GetLabRecordQueryHandler(
            lab_record_repository=mock_lab_repository,
            lablet_session_repository=mock_session_repository,
            cml_worker_repository=mock_worker_repository,
        )

    @pytest.mark.asyncio
    async def test_get_existing_lab_returns_ok(self, handler: GetLabRecordQueryHandler, mock_lab_repository: MagicMock) -> None:
        """Getting an existing lab returns 200 with full details."""
        lab = _make_discovered_lab()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result: OperationResult[Any] = await handler.handle_async(GetLabRecordQuery(lab_record_id="lr-001"))

        assert result.is_success
        assert result.status_code == 200
        assert result.data["id"] == "lr-001"
        assert result.data["lab_id"] == "lab-001"
        assert result.data["status"] == "discovered"
        assert result.data["title"] == "Test Lab"
        assert result.data["node_count"] == 3

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self, handler: GetLabRecordQueryHandler, mock_lab_repository: MagicMock) -> None:
        """Getting a non-existent lab returns 404."""
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(GetLabRecordQuery(lab_record_id="nonexistent"))

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_includes_binding_info(
        self,
        handler: GetLabRecordQueryHandler,
        mock_lab_repository: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Lab detail includes active binding information."""
        lab = _make_discovered_lab()
        session = _make_mock_session()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)
        mock_session_repository.get_by_lab_record_async = self.create_async_mock(return_value=session)

        result = await handler.handle_async(GetLabRecordQuery(lab_record_id="lr-001"))

        assert result.is_success
        assert result.data["active_binding_count"] == 1
        assert len(result.data["active_bindings"]) == 1
        assert result.data["active_bindings"][0]["lablet_session_id"] == "lablet-001"

    @pytest.mark.asyncio
    async def test_falls_back_to_last_run_session_when_direct_binding_missing(
        self,
        handler: GetLabRecordQueryHandler,
        mock_lab_repository: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Historical run linkage keeps the related session visible."""
        lab = _append_run_with_session(_make_discovered_lab(), session_id="lablet-123")
        session = _make_mock_session(session_id="lablet-123", is_terminal=True)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)
        mock_session_repository.get_by_lab_record_async = self.create_async_mock(return_value=None)
        mock_session_repository.get_by_id_async = self.create_async_mock(return_value=session)

        result = await handler.handle_async(GetLabRecordQuery(lab_record_id="lr-001"))

        assert result.is_success
        assert result.data["active_binding_count"] == 1
        assert result.data["active_bindings"][0]["lablet_session_id"] == "lablet-123"
        mock_session_repository.get_by_lab_record_async.assert_called_once_with("lr-001")
        mock_session_repository.get_by_id_async.assert_called_once_with("lablet-123")


# =============================================================================
# P8-17: GetLabRecordTopologyQuery
# =============================================================================


class TestGetLabRecordTopologyQuery(BaseTestCase):
    """Tests for GetLabRecordTopologyQueryHandler."""

    @pytest.fixture
    def handler(self, mock_lab_repository: MagicMock) -> GetLabRecordTopologyQueryHandler:
        return GetLabRecordTopologyQueryHandler(lab_record_repository=mock_lab_repository)

    @pytest.mark.asyncio
    async def test_no_topology_returns_empty(self, handler: GetLabRecordTopologyQueryHandler, mock_lab_repository: MagicMock) -> None:
        """Lab without topology returns has_topology=False."""
        lab = _make_discovered_lab()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result: OperationResult[Any] = await handler.handle_async(GetLabRecordTopologyQuery(lab_record_id="lr-001"))

        assert result.is_success
        assert result.data["has_topology"] is False
        assert result.data["topology"] is None

    @pytest.mark.asyncio
    async def test_with_topology_returns_spec(self, handler: GetLabRecordTopologyQueryHandler, mock_lab_repository: MagicMock) -> None:
        """Lab with topology returns the spec."""
        lab = _make_discovered_lab()
        lab.state.topology_spec = {"yaml": "topology: data", "checksum": "abc123"}
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(GetLabRecordTopologyQuery(lab_record_id="lr-001"))

        assert result.is_success
        assert result.data["has_topology"] is True
        assert result.data["topology"]["checksum"] == "abc123"

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self, handler: GetLabRecordTopologyQueryHandler, mock_lab_repository: MagicMock) -> None:
        """Topology query on non-existent lab returns 404."""
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(GetLabRecordTopologyQuery(lab_record_id="nonexistent"))

        assert not result.is_success
        assert result.status_code == 404


# =============================================================================
# P8-18: GetLabRecordRevisionsQuery
# =============================================================================


class TestGetLabRecordRevisionsQuery(BaseTestCase):
    """Tests for GetLabRecordRevisionsQueryHandler."""

    @pytest.fixture
    def handler(self, mock_lab_repository: MagicMock) -> GetLabRecordRevisionsQueryHandler:
        return GetLabRecordRevisionsQueryHandler(lab_record_repository=mock_lab_repository)

    @pytest.mark.asyncio
    async def test_returns_revision_history(self, handler: GetLabRecordRevisionsQueryHandler, mock_lab_repository: MagicMock) -> None:
        """Returns revision history for a lab."""
        lab = _make_discovered_lab()
        lab.state.revision = 2
        lab.state.revision_history = [
            {"revision": 1, "topology_checksum": "aaa", "created_at": "2026-02-01T00:00:00+00:00"},
            {"revision": 2, "topology_checksum": "bbb", "created_at": "2026-02-02T00:00:00+00:00"},
        ]
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result: OperationResult[Any] = await handler.handle_async(GetLabRecordRevisionsQuery(lab_record_id="lr-001"))

        assert result.is_success
        assert result.data["current_revision"] == 2
        assert result.data["revision_count"] == 2
        assert len(result.data["revisions"]) == 2

    @pytest.mark.asyncio
    async def test_empty_revision_history(self, handler: GetLabRecordRevisionsQueryHandler, mock_lab_repository: MagicMock) -> None:
        """Lab with no revisions returns empty list."""
        lab = _make_discovered_lab()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(GetLabRecordRevisionsQuery(lab_record_id="lr-001"))

        assert result.is_success
        assert result.data["revision_count"] == 0
        assert len(result.data["revisions"]) == 0

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self, handler: GetLabRecordRevisionsQueryHandler, mock_lab_repository: MagicMock) -> None:
        """Revisions query on non-existent lab returns 404."""
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(GetLabRecordRevisionsQuery(lab_record_id="nonexistent"))

        assert not result.is_success
        assert result.status_code == 404


# =============================================================================
# P8-19: GetLabRecordRunsQuery
# =============================================================================


class TestGetLabRecordRunsQuery(BaseTestCase):
    """Tests for GetLabRecordRunsQueryHandler."""

    @pytest.fixture
    def handler(self, mock_lab_repository: MagicMock) -> GetLabRecordRunsQueryHandler:
        return GetLabRecordRunsQueryHandler(lab_record_repository=mock_lab_repository)

    @pytest.mark.asyncio
    async def test_returns_run_history(self, handler: GetLabRecordRunsQueryHandler, mock_lab_repository: MagicMock) -> None:
        """Returns run history in reverse chronological order."""
        lab = _make_discovered_lab()
        lab.state.run_history_v2 = [
            {"started_at": "2026-02-01T00:00:00+00:00", "duration_seconds": 3600},
            {"started_at": "2026-02-02T00:00:00+00:00", "duration_seconds": 7200},
        ]
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result: OperationResult[Any] = await handler.handle_async(GetLabRecordRunsQuery(lab_record_id="lr-001"))

        assert result.is_success
        assert result.data["run_count"] == 2
        # Most recent first
        assert result.data["runs"][0]["started_at"] == "2026-02-02T00:00:00+00:00"

    @pytest.mark.asyncio
    async def test_empty_run_history(self, handler: GetLabRecordRunsQueryHandler, mock_lab_repository: MagicMock) -> None:
        """Lab with no runs returns empty list."""
        lab = _make_discovered_lab()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)

        result = await handler.handle_async(GetLabRecordRunsQuery(lab_record_id="lr-001"))

        assert result.is_success
        assert result.data["run_count"] == 0

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self, handler: GetLabRecordRunsQueryHandler, mock_lab_repository: MagicMock) -> None:
        """Runs query on non-existent lab returns 404."""
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(GetLabRecordRunsQuery(lab_record_id="nonexistent"))

        assert not result.is_success
        assert result.status_code == 404


# =============================================================================
# P8-20: GetLabRecordBindingsQuery
# =============================================================================


class TestGetLabRecordBindingsQuery(BaseTestCase):
    """Tests for GetLabRecordBindingsQueryHandler.

    Phase 7F: Refactored from LabletLabBinding stubs to LabletSession-native
    1:1 binding model (ADR-020 §2).
    """

    @pytest.fixture
    def handler(
        self,
        mock_lab_repository: MagicMock,
        mock_session_repository: MagicMock,
    ) -> GetLabRecordBindingsQueryHandler:
        return GetLabRecordBindingsQueryHandler(
            lab_record_repository=mock_lab_repository,
            lablet_session_repository=mock_session_repository,
        )

    @pytest.mark.asyncio
    async def test_returns_active_binding(
        self,
        handler: GetLabRecordBindingsQueryHandler,
        mock_lab_repository: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Returns the bound LabletSession for a lab (1:1 model)."""
        lab = _make_discovered_lab()
        session = _make_mock_session(session_id="lablet-001", lab_record_id="lr-001")
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)
        mock_session_repository.get_by_lab_record_async = self.create_async_mock(return_value=session)

        result: OperationResult[Any] = await handler.handle_async(GetLabRecordBindingsQuery(lab_record_id="lr-001"))

        assert result.is_success
        assert result.data["binding_count"] == 1
        assert result.data["bindings"][0]["binding_id"] == "lablet-001"
        assert result.data["bindings"][0]["lablet_session_id"] == "lablet-001"
        assert result.data["bindings"][0]["is_active"] is True

    @pytest.mark.asyncio
    async def test_no_bindings_returns_empty(
        self,
        handler: GetLabRecordBindingsQueryHandler,
        mock_lab_repository: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Lab with no bound session returns empty list."""
        lab = _make_discovered_lab()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)
        mock_session_repository.get_by_lab_record_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(GetLabRecordBindingsQuery(lab_record_id="lr-001"))

        assert result.is_success
        assert result.data["binding_count"] == 0

    @pytest.mark.asyncio
    async def test_include_released_still_uses_get_by_lab_record(
        self,
        handler: GetLabRecordBindingsQueryHandler,
        mock_lab_repository: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """include_released=True still returns a direct terminal binding."""
        lab = _make_discovered_lab()
        session = _make_mock_session(session_id="lablet-001", lab_record_id="lr-001", is_terminal=True)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)
        mock_session_repository.get_by_lab_record_async = self.create_async_mock(return_value=session)

        result = await handler.handle_async(GetLabRecordBindingsQuery(lab_record_id="lr-001", include_released=True))

        assert result.is_success
        assert result.data["binding_count"] == 1
        assert result.data["bindings"][0]["is_active"] is False
        mock_session_repository.get_by_lab_record_async.assert_called_once_with("lr-001")

    @pytest.mark.asyncio
    async def test_falls_back_to_latest_run_session_when_direct_binding_missing(
        self,
        handler: GetLabRecordBindingsQueryHandler,
        mock_lab_repository: MagicMock,
        mock_session_repository: MagicMock,
    ) -> None:
        """Completed sessions remain visible via LabRecord run history."""
        lab = _append_run_with_session(_make_discovered_lab(), session_id="lablet-789")
        session = _make_mock_session(session_id="lablet-789", is_terminal=True)
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)
        mock_session_repository.get_by_lab_record_async = self.create_async_mock(return_value=None)
        mock_session_repository.get_by_id_async = self.create_async_mock(return_value=session)

        result = await handler.handle_async(GetLabRecordBindingsQuery(lab_record_id="lr-001", include_released=True))

        assert result.is_success
        assert result.data["binding_count"] == 1
        assert result.data["bindings"][0]["lablet_session_id"] == "lablet-789"
        assert result.data["bindings"][0]["is_active"] is False
        mock_session_repository.get_by_lab_record_async.assert_called_once_with("lr-001")
        mock_session_repository.get_by_id_async.assert_called_once_with("lablet-789")

    @pytest.mark.asyncio
    async def test_not_found_returns_404(
        self,
        handler: GetLabRecordBindingsQueryHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Bindings query on non-existent lab returns 404."""
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(GetLabRecordBindingsQuery(lab_record_id="nonexistent"))

        assert not result.is_success
        assert result.status_code == 404
