"""Unit tests for Sprint F: Pipeline Run Recording (ADR-034).

Tests cover:
- F1: PipelineRunRecord value object (construction, serialization, round-trip)
- F1: PipelineRunRecordedDomainEvent dispatch on LabRecordState
- F1: LabRecord.append_pipeline_run() aggregate method
- F2: AppendPipelineRunCommandHandler (success, not-found, error)
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from lcm_core.domain.enums import LabRecordStatus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator

from application.commands.lab import (
    AppendPipelineRunCommand,
    AppendPipelineRunCommandHandler,
)
from domain.entities.lab_record import LabRecord
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.value_objects.pipeline_run_record import PipelineRunRecord
from tests.fixtures.mixins import BaseTestCase

# =============================================================================
# Helpers
# =============================================================================


def _make_pipeline_run(
    run_id: str = "run-001",
    pipeline_name: str = "instantiate",
    status: str = "completed",
    duration_seconds: float = 42.5,
    steps_completed: int = 5,
    steps_failed: int = 0,
    steps_skipped: int = 1,
) -> PipelineRunRecord:
    """Create a PipelineRunRecord for testing."""
    return PipelineRunRecord(
        run_id=run_id,
        pipeline_name=pipeline_name,
        started_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
        completed_at=datetime(2025, 1, 15, 10, 0, 42, 500000, tzinfo=timezone.utc),
        status=status,
        step_results={"import_lab": {"status": "completed", "duration_seconds": 5.0}},
        error_message=None,
        triggered_by="lablet-controller",
        lablet_session_id="session-001",
        duration_seconds=duration_seconds,
        steps_completed=steps_completed,
        steps_failed=steps_failed,
        steps_skipped=steps_skipped,
    )


def _make_discovered_lab(
    lab_record_id: str = "lr-001",
    status: LabRecordStatus = LabRecordStatus.DISCOVERED,
) -> LabRecord:
    """Create a LabRecord via the discover factory."""
    lab = LabRecord.discover(
        lab_id="lab-001",
        worker_id="worker-001",
        title="Test Lab",
        description="A test lab",
        state="DEFINED_ON_CORE",
        owner_username="admin",
        node_count=3,
        link_count=2,
    )
    lab.state.id = lab_record_id
    lab.state.status = status
    return lab


# =============================================================================
# F1: PipelineRunRecord Value Object
# =============================================================================


class TestPipelineRunRecord:
    """Tests for PipelineRunRecord frozen value object."""

    def test_construction(self):
        """PipelineRunRecord should be constructable with required fields."""
        run = _make_pipeline_run()
        assert run.run_id == "run-001"
        assert run.pipeline_name == "instantiate"
        assert run.status == "completed"
        assert run.duration_seconds == 42.5
        assert run.steps_completed == 5
        assert run.steps_failed == 0
        assert run.steps_skipped == 1
        assert run.triggered_by == "lablet-controller"
        assert run.lablet_session_id == "session-001"

    def test_immutability(self):
        """PipelineRunRecord should be frozen (immutable)."""
        run = _make_pipeline_run()
        with pytest.raises(AttributeError):
            run.status = "failed"  # type: ignore[misc]

    def test_validation_empty_run_id(self):
        """PipelineRunRecord should reject empty run_id."""
        with pytest.raises(ValueError, match="run_id"):
            PipelineRunRecord(
                run_id="",
                pipeline_name="instantiate",
                started_at=datetime.now(timezone.utc),
            )

    def test_validation_empty_pipeline_name(self):
        """PipelineRunRecord should reject empty pipeline_name."""
        with pytest.raises(ValueError, match="pipeline_name"):
            PipelineRunRecord(
                run_id="run-001",
                pipeline_name="",
                started_at=datetime.now(timezone.utc),
            )

    def test_to_dict(self):
        """to_dict should serialize all fields including ISO timestamps."""
        run = _make_pipeline_run()
        d = run.to_dict()
        assert d["run_id"] == "run-001"
        assert d["pipeline_name"] == "instantiate"
        assert d["status"] == "completed"
        assert d["duration_seconds"] == 42.5
        assert d["steps_completed"] == 5
        assert d["started_at"] == "2025-01-15T10:00:00+00:00"
        assert d["completed_at"] is not None
        assert d["triggered_by"] == "lablet-controller"
        assert d["lablet_session_id"] == "session-001"

    def test_from_dict(self):
        """from_dict should reconstruct PipelineRunRecord from dict."""
        d = {
            "run_id": "run-002",
            "pipeline_name": "teardown",
            "started_at": "2025-01-15T12:00:00+00:00",
            "completed_at": "2025-01-15T12:05:00+00:00",
            "status": "failed",
            "step_results": {"stop_lab": {"status": "failed", "error": "timeout"}},
            "error_message": "Lab stop timed out",
            "triggered_by": "lablet-controller",
            "lablet_session_id": "session-002",
            "duration_seconds": 300.0,
            "steps_completed": 2,
            "steps_failed": 1,
            "steps_skipped": 0,
        }
        run = PipelineRunRecord.from_dict(d)
        assert run.run_id == "run-002"
        assert run.pipeline_name == "teardown"
        assert run.status == "failed"
        assert run.error_message == "Lab stop timed out"
        assert run.duration_seconds == 300.0
        assert run.steps_failed == 1

    def test_round_trip(self):
        """to_dict → from_dict should produce equivalent object."""
        original = _make_pipeline_run()
        d = original.to_dict()
        restored = PipelineRunRecord.from_dict(d)
        assert restored.run_id == original.run_id
        assert restored.pipeline_name == original.pipeline_name
        assert restored.status == original.status
        assert restored.duration_seconds == original.duration_seconds
        assert restored.steps_completed == original.steps_completed
        assert restored.steps_failed == original.steps_failed
        assert restored.steps_skipped == original.steps_skipped

    def test_from_dict_with_datetime_objects(self):
        """from_dict should handle datetime objects (not just strings)."""
        d = {
            "run_id": "run-003",
            "pipeline_name": "instantiate",
            "started_at": datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            "completed_at": datetime(2025, 1, 15, 10, 5, 0, tzinfo=timezone.utc),
        }
        run = PipelineRunRecord.from_dict(d)
        assert run.started_at.year == 2025


# =============================================================================
# F1: LabRecord.append_pipeline_run() Domain Integration
# =============================================================================


class TestLabRecordPipelineRunHistory:
    """Tests for pipeline run history on the LabRecord aggregate."""

    def test_append_pipeline_run_creates_event(self):
        """append_pipeline_run should emit PipelineRunRecordedDomainEvent."""
        lab = _make_discovered_lab()
        run = _make_pipeline_run()

        lab.append_pipeline_run(run)

        # Should have the event recorded and state updated
        assert len(lab.state.pipeline_run_history) == 1

    def test_append_pipeline_run_state_update(self):
        """append_pipeline_run should add record to state.pipeline_run_history."""
        lab = _make_discovered_lab()
        run = _make_pipeline_run()

        lab.append_pipeline_run(run)

        assert len(lab.state.pipeline_run_history) == 1
        stored = lab.state.pipeline_run_history[0]
        assert stored["run_id"] == "run-001"
        assert stored["pipeline_name"] == "instantiate"
        assert stored["status"] == "completed"
        assert stored["duration_seconds"] == 42.5

    def test_pipeline_run_history_vo_property(self):
        """pipeline_run_history_vo should return deserialized PipelineRunRecord objects."""
        lab = _make_discovered_lab()
        run = _make_pipeline_run()

        lab.append_pipeline_run(run)

        vos = lab.pipeline_run_history_vo
        assert len(vos) == 1
        assert isinstance(vos[0], PipelineRunRecord)
        assert vos[0].run_id == "run-001"

    def test_pipeline_run_history_bounded_list(self):
        """pipeline_run_history should be bounded to max_run_history_size (50)."""
        lab = _make_discovered_lab()

        # Add 55 runs — should be bounded to 50
        for i in range(55):
            run = _make_pipeline_run(run_id=f"run-{i:03d}")
            lab.append_pipeline_run(run)

        assert len(lab.state.pipeline_run_history) == 50
        # Oldest runs should be evicted
        first = lab.state.pipeline_run_history[0]
        assert first["run_id"] == "run-005"  # First 5 evicted

    def test_multiple_pipeline_types(self):
        """Should track runs from different pipeline types."""
        lab = _make_discovered_lab()
        lab.append_pipeline_run(_make_pipeline_run(run_id="r1", pipeline_name="instantiate"))
        lab.append_pipeline_run(_make_pipeline_run(run_id="r2", pipeline_name="teardown", status="failed"))

        assert len(lab.state.pipeline_run_history) == 2
        names = [r["pipeline_name"] for r in lab.state.pipeline_run_history]
        assert "instantiate" in names
        assert "teardown" in names

    def test_empty_history_initially(self):
        """pipeline_run_history should be empty on a fresh LabRecord."""
        lab = _make_discovered_lab()
        assert lab.state.pipeline_run_history == []
        assert lab.pipeline_run_history_vo == []


# =============================================================================
# F2: AppendPipelineRunCommandHandler
# =============================================================================


class TestAppendPipelineRunCommand(BaseTestCase):
    """Tests for AppendPipelineRunCommandHandler."""

    @pytest.fixture
    def mock_mediator(self) -> MagicMock:
        return MagicMock(spec=Mediator)

    @pytest.fixture
    def mock_mapper(self) -> MagicMock:
        return MagicMock(spec=Mapper)

    @pytest.fixture
    def mock_cloud_event_bus(self) -> MagicMock:
        return MagicMock(spec=CloudEventBus)

    @pytest.fixture
    def mock_cloud_event_publishing_options(self) -> MagicMock:
        mock = MagicMock()
        mock.source = "test"
        mock.type_prefix = "test"
        return mock

    @pytest.fixture
    def mock_lab_repository(self) -> MagicMock:
        return MagicMock(spec=LabRecordRepository)

    @pytest.fixture
    def handler(
        self,
        mock_mediator: MagicMock,
        mock_mapper: MagicMock,
        mock_cloud_event_bus: MagicMock,
        mock_cloud_event_publishing_options: MagicMock,
        mock_lab_repository: MagicMock,
    ) -> AppendPipelineRunCommandHandler:
        return AppendPipelineRunCommandHandler(
            mediator=mock_mediator,
            mapper=mock_mapper,
            cloud_event_bus=mock_cloud_event_bus,
            cloud_event_publishing_options=mock_cloud_event_publishing_options,
            lab_record_repository=mock_lab_repository,
        )

    @pytest.mark.asyncio
    async def test_append_pipeline_run_success(
        self,
        handler: AppendPipelineRunCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Append a pipeline run with full data succeeds with 201."""
        lab = _make_discovered_lab()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)
        mock_lab_repository.update_async = self.create_async_mock()

        result = await handler.handle_async(
            AppendPipelineRunCommand(
                lab_record_id="lr-001",
                pipeline_name="instantiate",
                status="completed",
                started_at="2025-01-15T10:00:00+00:00",
                completed_at="2025-01-15T10:00:42+00:00",
                duration_seconds=42.5,
                steps_completed=5,
                steps_failed=0,
                steps_skipped=1,
                triggered_by="lablet-controller",
                lablet_session_id="session-001",
            )
        )

        assert result.is_success
        assert result.status_code == 201
        assert result.data["pipeline_name"] == "instantiate"
        assert result.data["status"] == "completed"
        assert result.data["duration_seconds"] == 42.5
        assert result.data["steps_completed"] == 5
        mock_lab_repository.update_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_append_pipeline_run_not_found(
        self,
        handler: AppendPipelineRunCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Append a pipeline run for nonexistent lab returns 404."""
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=None)

        result = await handler.handle_async(
            AppendPipelineRunCommand(
                lab_record_id="missing",
                pipeline_name="teardown",
            )
        )

        assert not result.is_success
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_append_pipeline_run_failed_status(
        self,
        handler: AppendPipelineRunCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Append a failed pipeline run records the error message."""
        lab = _make_discovered_lab()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)
        mock_lab_repository.update_async = self.create_async_mock()

        result = await handler.handle_async(
            AppendPipelineRunCommand(
                lab_record_id="lr-001",
                pipeline_name="teardown",
                status="failed",
                error_message="Lab stop timed out",
                steps_completed=2,
                steps_failed=1,
            )
        )

        assert result.is_success
        assert result.status_code == 201
        assert result.data["status"] == "failed"
        assert result.data["steps_failed"] == 1
        # Verify the VO was appended to the aggregate
        assert len(lab.state.pipeline_run_history) == 1

    @pytest.mark.asyncio
    async def test_append_pipeline_run_minimal_fields(
        self,
        handler: AppendPipelineRunCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Append a pipeline run with only required fields uses defaults."""
        lab = _make_discovered_lab()
        mock_lab_repository.get_by_id_async = self.create_async_mock(return_value=lab)
        mock_lab_repository.update_async = self.create_async_mock()

        result = await handler.handle_async(
            AppendPipelineRunCommand(
                lab_record_id="lr-001",
                pipeline_name="collect_evidence",
            )
        )

        assert result.is_success
        assert result.status_code == 201
        assert result.data["pipeline_name"] == "collect_evidence"
        assert result.data["status"] == "completed"
        # triggered_by is set on the VO but not in the response dict
        assert len(lab.state.pipeline_run_history) == 1

    @pytest.mark.asyncio
    async def test_append_pipeline_run_repository_error(
        self,
        handler: AppendPipelineRunCommandHandler,
        mock_lab_repository: MagicMock,
    ) -> None:
        """Repository error should return 500."""
        mock_lab_repository.get_by_id_async = AsyncMock(side_effect=Exception("DB connection failed"))

        result = await handler.handle_async(
            AppendPipelineRunCommand(
                lab_record_id="lr-001",
                pipeline_name="instantiate",
            )
        )

        assert not result.is_success
        assert result.status_code == 500
