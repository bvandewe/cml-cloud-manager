"""Unit tests for Phase 7D LabletSession query handlers.

Tests cover:
- GetLabletSessionQueryHandler (6 tests: original 4 + 2 enrichment)
- ListLabletSessionsQueryHandler (6 tests: original 4 + 2 enrichment)

Pattern: pytest fixtures + MagicMock + AsyncMock, matching test_lab_queries.py style.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from lcm_core.domain.enums import LabRecordStatus

from application.queries.lablet_session.get_lablet_session_query import (
    GetLabletSessionQuery,
    GetLabletSessionQueryHandler,
)
from application.queries.lablet_session.list_lablet_sessions_query import (
    ListLabletSessionsQuery,
    ListLabletSessionsQueryHandler,
)
from domain.entities.cml_worker import CMLWorker, CMLWorkerState
from domain.entities.lab_record import LabRecord, LabRecordState
from domain.entities.lablet_definition import LabletDefinition, LabletDefinitionState
from domain.entities.lablet_session import LabletSession, LabletSessionState
from domain.enums import LabletSessionStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from domain.repositories.user_session_repository import UserSessionRepository

# =============================================================================
# Shared fixtures
# =============================================================================


@pytest.fixture
def mock_session_repository() -> MagicMock:
    mock = MagicMock(spec=LabletSessionRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    mock.get_by_reservation_id_async = AsyncMock(return_value=None)
    mock.list_by_status_async = AsyncMock(return_value=[])
    mock.list_by_worker_async = AsyncMock(return_value=[])
    mock.list_by_owner_async = AsyncMock(return_value=[])
    mock.list_by_definition_async = AsyncMock(return_value=[])
    mock.list_pending_async = AsyncMock(return_value=[])
    mock.list_active_async = AsyncMock(return_value=[])
    mock.list_by_statuses_async = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def mock_definition_repository() -> MagicMock:
    mock = MagicMock(spec=LabletDefinitionRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def mock_worker_repository() -> MagicMock:
    mock = MagicMock(spec=CMLWorkerRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def mock_lab_record_repository() -> MagicMock:
    mock = MagicMock(spec=LabRecordRepository)
    mock.get_by_id_async = AsyncMock(return_value=None)
    return mock


def _make_session(
    session_id: str = "session-001",
    status: LabletSessionStatus = LabletSessionStatus.PENDING,
    definition_id: str = "def-001",
    owner_id: str = "user-001",
    worker_id: str | None = None,
) -> MagicMock:
    """Create a mock LabletSession with state."""
    session = MagicMock(spec=LabletSession)
    session.id.return_value = session_id

    state = MagicMock(spec=LabletSessionState)
    state.status = status
    state.definition_id = definition_id
    state.definition_name = "Lab 101"
    state.definition_version = "1.0.0"
    state.owner_id = owner_id
    state.worker_id = worker_id
    state.reservation_id = None
    state.timeslot_start = datetime.now(timezone.utc) + timedelta(hours=1)
    state.timeslot_end = datetime.now(timezone.utc) + timedelta(hours=2)
    state.created_at = datetime.now(timezone.utc)
    state.lab_record_id = None
    state.cml_lab_id = None
    state.cml_lab_title = None
    state.allocated_ports = None
    state.user_session_id = None
    state.grading_session_id = None
    state.score_report_id = None
    state.grade_result = None
    state.started_at = None
    state.ended_at = None
    state.duration_seconds = None
    state.scheduled_at = None
    state.terminated_at = None
    state.state_history = []

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


def _make_definition(
    definition_id: str = "def-001",
    form_qualified_name: str = "CCNA 200-301 Routing Basics",
    node_count: int = 5,
) -> MagicMock:
    """Create a mock LabletDefinition with state."""
    defn = MagicMock(spec=LabletDefinition)
    defn_state = MagicMock(spec=LabletDefinitionState)
    defn_state.form_qualified_name = form_qualified_name
    defn_state.node_count = node_count
    defn_state.upstream_sync_status = {"cml": "synced", "lds": "synced"}
    defn_state.upstream_version = "2.1.0"
    defn_state.content_package_hash = "sha256:abc123"
    defn_state.resource_requirements = MagicMock()
    defn_state.resource_requirements.to_dict.return_value = {"cpu_cores": 2, "memory_gb": 4, "storage_gb": 10}
    defn_state.port_template = MagicMock()
    defn_state.port_template.to_dict.return_value = {"ports": [{"name": "serial_1", "protocol": "tcp"}]}
    defn.state = defn_state
    return defn


def _make_worker(
    worker_id: str = "worker-001",
    name: str = "cml-worker-east-1",
    aws_region: str = "us-east-1",
) -> MagicMock:
    """Create a mock CMLWorker with state."""
    worker = MagicMock(spec=CMLWorker)
    worker_state = MagicMock(spec=CMLWorkerState)
    worker_state.name = name
    worker_state.aws_region = aws_region
    worker_state.https_endpoint = f"https://{name}.example.com"
    worker.state = worker_state
    return worker


def _make_lab_record(
    record_id: str = "lab-001",
    node_count: int = 5,
    link_count: int = 4,
) -> MagicMock:
    """Create a mock LabRecord with state."""
    record = MagicMock(spec=LabRecord)
    record_state = MagicMock(spec=LabRecordState)
    record_state.status = LabRecordStatus.BOOTED
    record_state.node_count = node_count
    record_state.link_count = link_count
    record.state = record_state
    return record


# =============================================================================
# GetLabletSessionQueryHandler Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.query
class TestGetLabletSessionQueryHandler:
    """Tests for retrieving a single LabletSession."""

    @pytest.mark.asyncio
    async def test_retrieves_session_by_id(self, mock_session_repository: MagicMock) -> None:
        """Verify session retrieval by aggregate ID."""
        session = _make_session()
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        handler = GetLabletSessionQueryHandler(
            lablet_session_repository=mock_session_repository,
            lablet_definition_repository=MagicMock(spec=LabletDefinitionRepository, get_by_id_async=AsyncMock(return_value=None)),
            cml_worker_repository=MagicMock(spec=CMLWorkerRepository, get_by_id_async=AsyncMock(return_value=None)),
            lab_record_repository=MagicMock(spec=LabRecordRepository, get_by_id_async=AsyncMock(return_value=None)),
            user_session_repository=MagicMock(spec=UserSessionRepository, get_by_id_async=AsyncMock(return_value=None)),
        )

        query = GetLabletSessionQuery(id="session-001")
        result = await handler.handle_async(query)

        assert result.is_success
        assert result.data is not None
        mock_session_repository.get_by_id_async.assert_called_once_with("session-001")

    @pytest.mark.asyncio
    async def test_retrieves_session_by_reservation_id(self, mock_session_repository: MagicMock) -> None:
        """Verify session retrieval by reservation_id."""
        session = _make_session()
        session.state.reservation_id = "res-001"
        mock_session_repository.get_by_reservation_id_async = AsyncMock(return_value=session)

        handler = GetLabletSessionQueryHandler(
            lablet_session_repository=mock_session_repository,
            lablet_definition_repository=MagicMock(spec=LabletDefinitionRepository, get_by_id_async=AsyncMock(return_value=None)),
            cml_worker_repository=MagicMock(spec=CMLWorkerRepository, get_by_id_async=AsyncMock(return_value=None)),
            lab_record_repository=MagicMock(spec=LabRecordRepository, get_by_id_async=AsyncMock(return_value=None)),
            user_session_repository=MagicMock(spec=UserSessionRepository, get_by_id_async=AsyncMock(return_value=None)),
        )

        query = GetLabletSessionQuery(reservation_id="res-001")
        result = await handler.handle_async(query)

        assert result.is_success
        mock_session_repository.get_by_reservation_id_async.assert_called_once_with("res-001")

    @pytest.mark.asyncio
    async def test_returns_not_found_for_missing_session(self, mock_session_repository: MagicMock) -> None:
        """Verify not_found when session doesn't exist."""
        handler = GetLabletSessionQueryHandler(
            lablet_session_repository=mock_session_repository,
            lablet_definition_repository=MagicMock(spec=LabletDefinitionRepository, get_by_id_async=AsyncMock(return_value=None)),
            cml_worker_repository=MagicMock(spec=CMLWorkerRepository, get_by_id_async=AsyncMock(return_value=None)),
            lab_record_repository=MagicMock(spec=LabRecordRepository, get_by_id_async=AsyncMock(return_value=None)),
            user_session_repository=MagicMock(spec=UserSessionRepository, get_by_id_async=AsyncMock(return_value=None)),
        )

        query = GetLabletSessionQuery(id="nonexistent")
        result = await handler.handle_async(query)

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_rejects_query_with_no_params(self, mock_session_repository: MagicMock) -> None:
        """Verify bad_request when no lookup parameter provided."""
        handler = GetLabletSessionQueryHandler(
            lablet_session_repository=mock_session_repository,
            lablet_definition_repository=MagicMock(spec=LabletDefinitionRepository, get_by_id_async=AsyncMock(return_value=None)),
            cml_worker_repository=MagicMock(spec=CMLWorkerRepository, get_by_id_async=AsyncMock(return_value=None)),
            lab_record_repository=MagicMock(spec=LabRecordRepository, get_by_id_async=AsyncMock(return_value=None)),
            user_session_repository=MagicMock(spec=UserSessionRepository, get_by_id_async=AsyncMock(return_value=None)),
        )

        query = GetLabletSessionQuery()
        result = await handler.handle_async(query)

        assert not result.is_success
        assert result.status_code == 400


# =============================================================================
# ListLabletSessionsQueryHandler Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.query
class TestListLabletSessionsQueryHandler:
    """Tests for listing LabletSessions."""

    @pytest.mark.asyncio
    async def test_lists_sessions_by_status(self, mock_session_repository: MagicMock, mock_definition_repository: MagicMock, mock_worker_repository: MagicMock) -> None:
        """Verify filtering by status."""
        sessions = [_make_session(session_id=f"s-{i}") for i in range(3)]
        mock_session_repository.list_by_status_async = AsyncMock(return_value=sessions)

        handler = ListLabletSessionsQueryHandler(
            lablet_session_repository=mock_session_repository,
            lablet_definition_repository=mock_definition_repository,
            cml_worker_repository=mock_worker_repository,
        )

        query = ListLabletSessionsQuery(status="pending")
        result = await handler.handle_async(query)

        assert result.is_success
        assert len(result.data) == 3
        mock_session_repository.list_by_status_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_lists_sessions_by_worker(self, mock_session_repository: MagicMock, mock_definition_repository: MagicMock, mock_worker_repository: MagicMock) -> None:
        """Verify filtering by worker_id."""
        sessions = [_make_session(session_id=f"s-{i}", worker_id="worker-001") for i in range(2)]
        mock_session_repository.list_by_worker_async = AsyncMock(return_value=sessions)

        handler = ListLabletSessionsQueryHandler(
            lablet_session_repository=mock_session_repository,
            lablet_definition_repository=mock_definition_repository,
            cml_worker_repository=mock_worker_repository,
        )

        query = ListLabletSessionsQuery(worker_id="worker-001")
        result = await handler.handle_async(query)

        assert result.is_success
        assert len(result.data) == 2

    @pytest.mark.asyncio
    async def test_lists_sessions_default_no_terminated(self, mock_session_repository: MagicMock, mock_definition_repository: MagicMock, mock_worker_repository: MagicMock) -> None:
        """Verify default listing returns all non-terminal sessions."""
        all_non_terminal = [
            _make_session(session_id="s-1"),
            _make_session(session_id="s-2", status=LabletSessionStatus.RUNNING),
            _make_session(session_id="s-3", status=LabletSessionStatus.READY),
        ]
        mock_session_repository.list_by_statuses_async = AsyncMock(return_value=all_non_terminal)

        handler = ListLabletSessionsQueryHandler(
            lablet_session_repository=mock_session_repository,
            lablet_definition_repository=mock_definition_repository,
            cml_worker_repository=mock_worker_repository,
        )

        query = ListLabletSessionsQuery()
        result = await handler.handle_async(query)

        assert result.is_success
        assert len(result.data) == 3

    @pytest.mark.asyncio
    async def test_rejects_invalid_status_filter(self, mock_session_repository: MagicMock, mock_definition_repository: MagicMock, mock_worker_repository: MagicMock) -> None:
        """Verify bad_request for invalid status value."""
        handler = ListLabletSessionsQueryHandler(
            lablet_session_repository=mock_session_repository,
            lablet_definition_repository=mock_definition_repository,
            cml_worker_repository=mock_worker_repository,
        )

        query = ListLabletSessionsQuery(status="bogus_status")
        result = await handler.handle_async(query)

        assert not result.is_success
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_applies_pagination(self, mock_session_repository: MagicMock, mock_definition_repository: MagicMock, mock_worker_repository: MagicMock) -> None:
        """Verify skip/limit pagination works."""
        sessions = [_make_session(session_id=f"s-{i}") for i in range(10)]
        mock_session_repository.list_by_status_async = AsyncMock(return_value=sessions)

        handler = ListLabletSessionsQueryHandler(
            lablet_session_repository=mock_session_repository,
            lablet_definition_repository=mock_definition_repository,
            cml_worker_repository=mock_worker_repository,
        )

        query = ListLabletSessionsQuery(status="pending", skip=2, limit=3)
        result = await handler.handle_async(query)

        assert result.is_success
        assert len(result.data) == 3


# =============================================================================
# Enrichment Tests — GetLabletSessionQueryHandler
# =============================================================================


@pytest.mark.unit
@pytest.mark.query
class TestGetLabletSessionEnrichment:
    """Tests verifying cross-aggregate enrichment on detail query."""

    @pytest.mark.asyncio
    async def test_enriches_dto_with_definition_worker_and_lab_record(
        self,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
        mock_worker_repository: MagicMock,
        mock_lab_record_repository: MagicMock,
    ) -> None:
        """Verify enrichment fields populated when FK aggregates exist."""
        session = _make_session(worker_id="worker-001")
        session.state.lab_record_id = "lab-001"
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)

        defn = _make_definition()
        mock_definition_repository.get_by_id_async = AsyncMock(return_value=defn)

        worker = _make_worker()
        mock_worker_repository.get_by_id_async = AsyncMock(return_value=worker)

        lab_record = _make_lab_record()
        mock_lab_record_repository.get_by_id_async = AsyncMock(return_value=lab_record)

        handler = GetLabletSessionQueryHandler(
            lablet_session_repository=mock_session_repository,
            lablet_definition_repository=mock_definition_repository,
            cml_worker_repository=mock_worker_repository,
            lab_record_repository=mock_lab_record_repository,
            user_session_repository=MagicMock(spec=UserSessionRepository, get_by_id_async=AsyncMock(return_value=None)),
        )

        result = await handler.handle_async(GetLabletSessionQuery(id="session-001"))

        assert result.is_success
        dto = result.data
        # Definition enrichment
        assert dto.form_qualified_name == "CCNA 200-301 Routing Basics"
        assert dto.node_count == 5
        assert dto.upstream_version == "2.1.0"
        assert dto.content_package_hash == "sha256:abc123"
        assert dto.resource_requirements is not None
        assert dto.port_template is not None
        # Worker enrichment
        assert dto.worker_name == "cml-worker-east-1"
        assert dto.worker_region == "us-east-1"
        # Lab record enrichment
        assert dto.lab_record_status == "booted"
        assert dto.lab_record_node_count == 5
        assert dto.lab_record_link_count == 4

    @pytest.mark.asyncio
    async def test_graceful_none_when_fk_aggregates_missing(
        self,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
        mock_worker_repository: MagicMock,
        mock_lab_record_repository: MagicMock,
    ) -> None:
        """Verify enrichment fields are None when FK aggregates not found."""
        session = _make_session()
        mock_session_repository.get_by_id_async = AsyncMock(return_value=session)
        # All enrichment repos return None (default)

        handler = GetLabletSessionQueryHandler(
            lablet_session_repository=mock_session_repository,
            lablet_definition_repository=mock_definition_repository,
            cml_worker_repository=mock_worker_repository,
            lab_record_repository=mock_lab_record_repository,
            user_session_repository=MagicMock(spec=UserSessionRepository, get_by_id_async=AsyncMock(return_value=None)),
        )

        result = await handler.handle_async(GetLabletSessionQuery(id="session-001"))

        assert result.is_success
        dto = result.data
        assert dto.form_qualified_name is None
        assert dto.node_count is None
        assert dto.worker_name is None
        assert dto.worker_region is None
        assert dto.resource_requirements is None
        assert dto.lab_record_status is None


# =============================================================================
# Enrichment Tests — ListLabletSessionsQueryHandler
# =============================================================================


@pytest.mark.unit
@pytest.mark.query
class TestListLabletSessionsEnrichment:
    """Tests verifying cross-aggregate enrichment on list query."""

    @pytest.mark.asyncio
    async def test_enriches_summary_dtos_with_definition_and_worker(
        self,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
        mock_worker_repository: MagicMock,
    ) -> None:
        """Verify enrichment fields populated on list DTOs when FK aggregates exist."""
        session = _make_session(worker_id="worker-001")
        mock_session_repository.list_by_statuses_async = AsyncMock(return_value=[session])

        defn = _make_definition()
        mock_definition_repository.get_by_id_async = AsyncMock(return_value=defn)

        worker = _make_worker()
        mock_worker_repository.get_by_id_async = AsyncMock(return_value=worker)

        handler = ListLabletSessionsQueryHandler(
            lablet_session_repository=mock_session_repository,
            lablet_definition_repository=mock_definition_repository,
            cml_worker_repository=mock_worker_repository,
        )

        result = await handler.handle_async(ListLabletSessionsQuery())

        assert result.is_success
        assert len(result.data) == 1
        dto = result.data[0]
        assert dto.form_qualified_name == "CCNA 200-301 Routing Basics"
        assert dto.node_count == 5
        assert dto.worker_name == "cml-worker-east-1"
        assert dto.upstream_sync_status == {"cml": "synced", "lds": "synced"}

    @pytest.mark.asyncio
    async def test_list_enrichment_graceful_none(
        self,
        mock_session_repository: MagicMock,
        mock_definition_repository: MagicMock,
        mock_worker_repository: MagicMock,
    ) -> None:
        """Verify enrichment fields are None on list DTOs when FK aggregates missing."""
        session = _make_session()
        mock_session_repository.list_by_statuses_async = AsyncMock(return_value=[session])
        # Enrichment repos return None (default)

        handler = ListLabletSessionsQueryHandler(
            lablet_session_repository=mock_session_repository,
            lablet_definition_repository=mock_definition_repository,
            cml_worker_repository=mock_worker_repository,
        )

        result = await handler.handle_async(ListLabletSessionsQuery())

        assert result.is_success
        dto = result.data[0]
        assert dto.form_qualified_name is None
        assert dto.node_count is None
        assert dto.worker_name is None
        assert dto.upstream_sync_status is None
