"""Unit tests for GetDefinitionResourceObservationsQuery handler (ADR-030).

Tests cover:
- Aggregation with multiple sessions (max, avg, latest CPU/mem/nodes)
- No observations → empty response
- Port drift count across sessions
- Limit parameter respected
- Storage aggregation (optional field)

Pattern: pytest fixtures + MagicMock + AsyncMock, matching test_lablet_session_queries.py.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from application.queries.lablet_session.get_definition_resource_observations_query import (
    GetDefinitionResourceObservationsQuery,
    GetDefinitionResourceObservationsQueryHandler,
)
from domain.entities.lablet_session import LabletSession, LabletSessionState
from domain.repositories.lablet_session_repository import LabletSessionRepository

# =============================================================================
# Fixtures
# =============================================================================

NOW = datetime.now(timezone.utc)


@pytest.fixture
def mock_session_repository() -> MagicMock:
    mock = MagicMock(spec=LabletSessionRepository)
    mock.find_with_observations_async = AsyncMock(return_value=[])
    return mock


def _make_observed_session(
    session_id: str = "session-001",
    cpu_cores: float = 4.0,
    memory_mb: int = 8192,
    storage_mb: int | None = None,
    node_count: int = 2,
    port_drift: bool = False,
    observation_count: int = 1,
) -> MagicMock:
    """Create a mock session with observation data."""
    session = MagicMock(spec=LabletSession)
    session.id.return_value = session_id

    state = MagicMock(spec=LabletSessionState)
    state.observed_resources = {
        "total_cpu_cores": cpu_cores,
        "total_memory_mb": memory_mb,
        "total_storage_mb": storage_mb,
        "actual_node_count": node_count,
    }
    state.observed_at = NOW
    state.port_drift_detected = port_drift
    state.observation_count = observation_count

    session.state = state
    return session


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.query
class TestGetDefinitionResourceObservationsQueryHandler:
    """Tests for aggregated resource observations query."""

    def _make_handler(self, mock_session_repository: MagicMock) -> GetDefinitionResourceObservationsQueryHandler:
        return GetDefinitionResourceObservationsQueryHandler(
            lablet_session_repository=mock_session_repository,
        )

    @pytest.mark.asyncio
    async def test_no_observations_returns_empty(self, mock_session_repository: MagicMock) -> None:
        """When no sessions have observations, returns empty response."""
        mock_session_repository.find_with_observations_async.return_value = []
        handler = self._make_handler(mock_session_repository)

        query = GetDefinitionResourceObservationsQuery(definition_id="def-001")
        result = await handler.handle_async(query)

        assert result.is_success
        assert result.data["observation_count"] == 0
        assert result.data["sessions"] == []
        assert result.data["aggregate"] is None

    @pytest.mark.asyncio
    async def test_single_session_aggregation(self, mock_session_repository: MagicMock) -> None:
        """Single session: max=avg=latest for all metrics."""
        session = _make_observed_session(cpu_cores=4.0, memory_mb=8192, node_count=3)
        mock_session_repository.find_with_observations_async.return_value = [session]
        handler = self._make_handler(mock_session_repository)

        query = GetDefinitionResourceObservationsQuery(definition_id="def-001")
        result = await handler.handle_async(query)

        assert result.is_success
        assert result.data["observation_count"] == 1
        agg = result.data["aggregate"]
        assert agg["cpu_cores"]["max"] == 4.0
        assert agg["cpu_cores"]["avg"] == 4.0
        assert agg["cpu_cores"]["latest"] == 4.0
        assert agg["memory_mb"]["max"] == 8192
        assert agg["node_count"]["max"] == 3

    @pytest.mark.asyncio
    async def test_multi_session_aggregation(self, mock_session_repository: MagicMock) -> None:
        """Multiple sessions: max, avg, latest computed correctly."""
        sessions = [
            _make_observed_session(session_id="s1", cpu_cores=2.0, memory_mb=4096, node_count=2),
            _make_observed_session(session_id="s2", cpu_cores=8.0, memory_mb=16384, node_count=5),
            _make_observed_session(session_id="s3", cpu_cores=4.0, memory_mb=8192, node_count=3),
        ]
        mock_session_repository.find_with_observations_async.return_value = sessions
        handler = self._make_handler(mock_session_repository)

        query = GetDefinitionResourceObservationsQuery(definition_id="def-001")
        result = await handler.handle_async(query)

        assert result.is_success
        assert result.data["observation_count"] == 3

        agg = result.data["aggregate"]
        # Max
        assert agg["cpu_cores"]["max"] == 8.0
        assert agg["memory_mb"]["max"] == 16384
        assert agg["node_count"]["max"] == 5
        # Avg
        assert agg["cpu_cores"]["avg"] == pytest.approx(4.666, rel=0.01)
        assert agg["memory_mb"]["avg"] == pytest.approx(9557.33, rel=0.01)
        # Latest = last session in list
        assert agg["cpu_cores"]["latest"] == 4.0
        assert agg["node_count"]["latest"] == 3

    @pytest.mark.asyncio
    async def test_port_drift_count(self, mock_session_repository: MagicMock) -> None:
        """Port drift count reflects sessions with drift."""
        sessions = [
            _make_observed_session(session_id="s1", port_drift=True),
            _make_observed_session(session_id="s2", port_drift=False),
            _make_observed_session(session_id="s3", port_drift=True),
        ]
        mock_session_repository.find_with_observations_async.return_value = sessions
        handler = self._make_handler(mock_session_repository)

        query = GetDefinitionResourceObservationsQuery(definition_id="def-001")
        result = await handler.handle_async(query)

        assert result.is_success
        assert result.data["aggregate"]["port_drift_sessions"] == 2

    @pytest.mark.asyncio
    async def test_storage_aggregation(self, mock_session_repository: MagicMock) -> None:
        """Storage aggregation works when storage_mb is provided."""
        sessions = [
            _make_observed_session(session_id="s1", storage_mb=10240),
            _make_observed_session(session_id="s2", storage_mb=20480),
        ]
        mock_session_repository.find_with_observations_async.return_value = sessions
        handler = self._make_handler(mock_session_repository)

        query = GetDefinitionResourceObservationsQuery(definition_id="def-001")
        result = await handler.handle_async(query)

        assert result.is_success
        agg = result.data["aggregate"]
        assert agg["storage_mb"] is not None
        assert agg["storage_mb"]["max"] == 20480
        assert agg["storage_mb"]["avg"] == 15360.0

    @pytest.mark.asyncio
    async def test_storage_none_when_not_reported(self, mock_session_repository: MagicMock) -> None:
        """Storage is None when no session reports storage."""
        sessions = [
            _make_observed_session(session_id="s1", storage_mb=None),
        ]
        mock_session_repository.find_with_observations_async.return_value = sessions
        handler = self._make_handler(mock_session_repository)

        query = GetDefinitionResourceObservationsQuery(definition_id="def-001")
        result = await handler.handle_async(query)

        assert result.is_success
        assert result.data["aggregate"]["storage_mb"] is None

    @pytest.mark.asyncio
    async def test_limit_passed_to_repository(self, mock_session_repository: MagicMock) -> None:
        """Limit parameter is forwarded to repository."""
        handler = self._make_handler(mock_session_repository)

        query = GetDefinitionResourceObservationsQuery(definition_id="def-001", limit=5)
        await handler.handle_async(query)

        mock_session_repository.find_with_observations_async.assert_called_once_with(
            definition_id="def-001",
            limit=5,
        )

    @pytest.mark.asyncio
    async def test_session_summaries_structure(self, mock_session_repository: MagicMock) -> None:
        """Each session summary contains expected fields."""
        session = _make_observed_session(session_id="s1", cpu_cores=6.0, memory_mb=12288, node_count=4, port_drift=True, observation_count=3)
        mock_session_repository.find_with_observations_async.return_value = [session]
        handler = self._make_handler(mock_session_repository)

        query = GetDefinitionResourceObservationsQuery(definition_id="def-001")
        result = await handler.handle_async(query)

        assert result.is_success
        summary = result.data["sessions"][0]
        assert summary["session_id"] == "s1"
        assert summary["total_cpu_cores"] == 6.0
        assert summary["total_memory_mb"] == 12288
        assert summary["actual_node_count"] == 4
        assert summary["port_drift_detected"] is True
        assert summary["observation_count"] == 3
        assert summary["observed_at"] is not None
