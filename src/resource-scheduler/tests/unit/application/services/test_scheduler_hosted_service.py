"""Phase 1 (foundational) tests for SchedulerHostedService.

Tests core methods: watch event parsing, resource fetching, definition caching,
decision execution, assignment/scale-up handling, readiness checks, and stats.

Phase 2 tests (in test_scheduler_hosted_service_phase2.py) cover:
- etcd capacity refresh and TTL
- Reconcile with etcd capacity integration
- Retry escalation and max retry backoff
- OTel metrics recording
- list_resources with etcd
- Scale-up rejection summaries
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from application.hosted_services.scheduler_hosted_service import SchedulerHostedService
from application.services.placement_engine import PlacementEngine, SchedulingDecision
from application.settings import Settings
from lcm_core.domain.entities import LabletSessionReadModel
from lcm_core.infrastructure.hosted_services import ReconciliationStatus


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_api_client():
    """Mock ControlPlaneApiClient."""
    client = AsyncMock()
    client.get_lablet_sessions = AsyncMock(return_value=[])
    client.get_workers = AsyncMock(return_value=[])
    client.get_lablet_definition = AsyncMock(return_value=None)
    client.get_lablet_session = AsyncMock(return_value=None)
    client.schedule_session = AsyncMock()
    client.request_scale_up = AsyncMock()
    client.health_check = AsyncMock(return_value=True)
    client.get_worker_templates = AsyncMock(return_value=None)
    return client


@pytest.fixture
def mock_etcd_client():
    """Mock EtcdClient."""
    client = AsyncMock()
    client.get_prefix = AsyncMock(return_value={})
    client.get = AsyncMock(return_value=None)
    client.put = AsyncMock()
    client.delete = AsyncMock()
    client.campaign = AsyncMock()
    client.resign = AsyncMock()
    return client


@pytest.fixture
def placement_engine():
    """Real PlacementEngine instance."""
    return PlacementEngine()


@pytest.fixture
def settings():
    """Settings with defaults."""
    return Settings()


@pytest.fixture
def scheduler(mock_api_client, mock_etcd_client, placement_engine, settings):
    """Create SchedulerHostedService with mocked dependencies.

    Patches parent class __init__ to avoid etcd/leader election setup.
    """
    with patch.object(SchedulerHostedService, "__init__", lambda self, *a, **kw: None):
        svc = SchedulerHostedService.__new__(SchedulerHostedService)

    svc._api = mock_api_client
    svc._etcd = mock_etcd_client
    svc._placement_engine = placement_engine
    svc._settings = settings
    svc._cached_workers = None
    svc._cached_templates = None
    svc._definition_cache = {}
    svc._etcd_capacities = {}
    svc._etcd_capacities_fetched_at = 0.0
    svc._etcd_capacity_ttl = 30.0
    svc._instance_retry_counts = {}
    svc._max_scheduling_retries = 5
    svc._successful_placements = 0
    svc._failed_placements = 0
    svc._scale_up_requests = 0

    # Parent class attributes needed by stats property
    svc._started = False
    svc._stopping = False
    svc._reconcile_count = 0
    svc._reconcile_success_count = 0
    svc._reconcile_failure_count = 0
    svc._last_reconcile_at = None
    svc._is_leader = False
    svc._leader_id = None
    svc._instance_id = "test-instance"
    svc._watch_events_processed = 0

    return svc


@pytest.fixture
def pending_session():
    """A PENDING LabletSessionReadModel."""
    return LabletSessionReadModel(
        id="session-001",
        name="Test Session",
        definition_id="def-001",
        status="PENDING",
    )


@pytest.fixture
def basic_definition():
    """Basic lablet definition dict."""
    return {
        "id": "def-001",
        "name": "Basic Lab",
        "resource_requirements": {
            "cpu_cores": 8,
            "memory_gb": 16,
            "storage_gb": 50,
        },
        "license_affinity": [],
        "port_template": {
            "port_entries": [{"name": "serial_1"}],
        },
    }


@pytest.fixture
def running_worker():
    """A running worker with ample capacity."""
    return {
        "id": "worker-001",
        "name": "Worker 1",
        "status": "running",
        "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000, "max_ports": 100},
        "allocated_capacity": {"cpu_cores": 0, "memory_gb": 0, "storage_gb": 0},
        "session_ids": [],
        "port_allocations": [],
        "license": {"license_type": "enterprise"},
        "metrics": {"version": "2.9.0"},
    }


# =============================================================================
# Watch Event Tests
# =============================================================================


class TestOnWatchEvent:
    """Tests for on_watch_event — etcd event parsing."""

    @pytest.fixture
    def make_event(self):
        """Factory for EtcdEvent-like objects."""

        def _make(key: str, value: str = "PENDING", event_type: str = "PUT"):
            from lcm_core.integration.clients.etcd_client import EtcdEvent

            return EtcdEvent(key=key, value=value, type=event_type)

        return _make

    @pytest.mark.asyncio
    async def test_pending_session_triggers_scheduling(self, scheduler, make_event):
        """Test that a PENDING session state change returns session ID."""
        event = make_event("/lcm/sessions/session-123/state", "PENDING")
        result = await scheduler.on_watch_event(event)
        assert result == "session-123"

    @pytest.mark.asyncio
    async def test_non_pending_status_ignored(self, scheduler, make_event):
        """Test that non-PENDING states are ignored."""
        event = make_event("/lcm/sessions/session-123/state", "SCHEDULED")
        result = await scheduler.on_watch_event(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_event_ignored(self, scheduler, make_event):
        """Test that DELETE events are ignored."""
        event = make_event("/lcm/sessions/session-123/state", "PENDING", event_type="DELETE")
        result = await scheduler.on_watch_event(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_state_key_ignored(self, scheduler, make_event):
        """Test that non-state keys are ignored."""
        event = make_event("/lcm/sessions/session-123/metadata", "PENDING")
        result = await scheduler.on_watch_event(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_short_key_ignored(self, scheduler, make_event):
        """Test that keys with insufficient parts are ignored."""
        event = make_event("/lcm/sessions/session-123", "PENDING")
        result = await scheduler.on_watch_event(event)
        assert result is None


# =============================================================================
# Fetch Resource By ID Tests
# =============================================================================


class TestFetchResourceById:
    """Tests for fetch_resource_by_id — targeted session retrieval."""

    @pytest.mark.asyncio
    async def test_fetch_existing_session(self, scheduler, mock_api_client, mock_etcd_client):
        """Test fetching an existing session refreshes caches and returns model."""
        mock_api_client.get_lablet_session.return_value = {
            "id": "session-001",
            "name": "Test",
            "definition_id": "def-001",
            "status": "PENDING",
        }
        mock_api_client.get_workers.return_value = []
        mock_etcd_client.get_prefix.return_value = {}

        result = await scheduler.fetch_resource_by_id("session-001")

        assert result is not None
        assert result.id == "session-001"
        # Should refresh worker cache
        mock_api_client.get_workers.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_nonexistent_session(self, scheduler, mock_api_client):
        """Test fetching a session that doesn't exist returns None."""
        mock_api_client.get_lablet_session.return_value = None

        result = await scheduler.fetch_resource_by_id("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_handles_api_error(self, scheduler, mock_api_client):
        """Test that API errors return None gracefully."""
        mock_api_client.get_lablet_session.side_effect = Exception("API error")

        result = await scheduler.fetch_resource_by_id("session-001")

        assert result is None


# =============================================================================
# Definition Caching Tests
# =============================================================================


class TestDefinitionCaching:
    """Tests for _get_definition with per-cycle caching."""

    @pytest.mark.asyncio
    async def test_fetches_from_api_on_first_call(self, scheduler, mock_api_client, basic_definition):
        """Test first call fetches from API."""
        mock_api_client.get_lablet_definition.return_value = basic_definition

        result = await scheduler._get_definition("def-001")

        assert result == basic_definition
        mock_api_client.get_lablet_definition.assert_called_once_with("def-001")

    @pytest.mark.asyncio
    async def test_uses_cache_on_second_call(self, scheduler, mock_api_client, basic_definition):
        """Test second call uses cache (no API call)."""
        mock_api_client.get_lablet_definition.return_value = basic_definition

        await scheduler._get_definition("def-001")
        await scheduler._get_definition("def-001")

        # Should only call API once
        mock_api_client.get_lablet_definition.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none_on_api_error(self, scheduler, mock_api_client):
        """Test API error returns None without caching."""
        mock_api_client.get_lablet_definition.side_effect = Exception("API error")

        result = await scheduler._get_definition("def-001")

        assert result is None

    @pytest.mark.asyncio
    async def test_different_definitions_cached_separately(self, scheduler, mock_api_client):
        """Test different definition IDs are cached independently."""
        mock_api_client.get_lablet_definition.side_effect = [
            {"id": "def-001", "name": "Lab A"},
            {"id": "def-002", "name": "Lab B"},
        ]

        result_a = await scheduler._get_definition("def-001")
        result_b = await scheduler._get_definition("def-002")

        assert result_a["name"] == "Lab A"
        assert result_b["name"] == "Lab B"
        assert mock_api_client.get_lablet_definition.call_count == 2


# =============================================================================
# Execute Decision Tests
# =============================================================================


class TestExecuteDecision:
    """Tests for _execute_decision routing."""

    @pytest.mark.asyncio
    async def test_routes_assign_decision(self, scheduler, mock_api_client, basic_definition):
        """Test assign decision is routed to _handle_assign."""
        decision = SchedulingDecision(action="assign", worker_id="worker-001", reason="Best fit")

        result = await scheduler._execute_decision("session-001", decision, basic_definition)

        assert result.status == ReconciliationStatus.SUCCESS
        mock_api_client.schedule_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_scale_up_decision(self, scheduler, mock_api_client, basic_definition):
        """Test scale_up decision is routed to _handle_scale_up."""
        decision = SchedulingDecision(action="scale_up", worker_template="m5zn.metal-cml", reason="No workers")

        result = await scheduler._execute_decision("session-001", decision, basic_definition)

        assert result.status == ReconciliationStatus.REQUEUE
        mock_api_client.request_scale_up.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_wait_decision(self, scheduler, basic_definition):
        """Test wait decision returns REQUEUE."""
        decision = SchedulingDecision(action="wait", reason="Temporary condition")

        result = await scheduler._execute_decision("session-001", decision, basic_definition)

        assert result.status == ReconciliationStatus.REQUEUE
        assert "Temporary condition" in result.message

    @pytest.mark.asyncio
    async def test_unknown_action_fails(self, scheduler, basic_definition):
        """Test unknown action returns FAILED."""
        decision = SchedulingDecision(action="unknown_action", reason="Test")

        result = await scheduler._execute_decision("session-001", decision, basic_definition)

        assert result.status == ReconciliationStatus.FAILED
        assert "Unknown action" in result.message


# =============================================================================
# Handle Assign Tests
# =============================================================================


class TestHandleAssign:
    """Tests for _handle_assign — session-to-worker assignment."""

    @pytest.mark.asyncio
    async def test_successful_assignment(self, scheduler, mock_api_client, basic_definition):
        """Test successful session assignment."""
        decision = SchedulingDecision(action="assign", worker_id="worker-001", reason="Best fit")

        result = await scheduler._handle_assign("session-001", decision, basic_definition)

        assert result.status == ReconciliationStatus.SUCCESS
        assert "worker-001" in result.message
        assert scheduler._successful_placements == 1

    @pytest.mark.asyncio
    async def test_assignment_passes_empty_ports(self, scheduler, mock_api_client, basic_definition):
        """Test that assignment sends empty allocated_ports (ADR-031 Phase 4)."""
        decision = SchedulingDecision(action="assign", worker_id="worker-001", reason="Best fit")

        await scheduler._handle_assign("session-001", decision, basic_definition)

        call_kwargs = mock_api_client.schedule_session.call_args.kwargs
        assert call_kwargs["allocated_ports"] == {}

    @pytest.mark.asyncio
    async def test_assignment_sends_scheduled_by(self, scheduler, mock_api_client, basic_definition):
        """Test that assignment includes scheduler identity."""
        decision = SchedulingDecision(action="assign", worker_id="worker-001", reason="Best fit")

        await scheduler._handle_assign("session-001", decision, basic_definition)

        call_kwargs = mock_api_client.schedule_session.call_args.kwargs
        assert call_kwargs["scheduled_by"] == "resource-scheduler"

    @pytest.mark.asyncio
    async def test_assignment_api_failure(self, scheduler, mock_api_client, basic_definition):
        """Test assignment handles API failure."""
        mock_api_client.schedule_session.side_effect = Exception("API timeout")
        decision = SchedulingDecision(action="assign", worker_id="worker-001", reason="Best fit")

        result = await scheduler._handle_assign("session-001", decision, basic_definition)

        assert result.status == ReconciliationStatus.FAILED
        assert scheduler._failed_placements == 1

    @pytest.mark.asyncio
    async def test_assignment_missing_worker_id(self, scheduler, basic_definition):
        """Test assignment fails when worker_id is missing."""
        decision = SchedulingDecision(action="assign", worker_id=None, reason="No worker")

        result = await scheduler._handle_assign("session-001", decision, basic_definition)

        assert result.status == ReconciliationStatus.FAILED
        assert "missing worker_id" in result.message.lower()

    @pytest.mark.asyncio
    async def test_assignment_uses_lab_record_id(self, scheduler, mock_api_client):
        """Test that lab_record_id from definition is passed through."""
        definition = {"id": "def-001", "lab_record_id": "lab-rec-123"}
        decision = SchedulingDecision(action="assign", worker_id="worker-001", reason="Best fit")

        await scheduler._handle_assign("session-001", decision, definition)

        call_kwargs = mock_api_client.schedule_session.call_args.kwargs
        assert call_kwargs["lab_record_id"] == "lab-rec-123"


# =============================================================================
# Handle Scale-Up Tests
# =============================================================================


class TestHandleScaleUp:
    """Tests for _handle_scale_up — new worker provisioning request."""

    @pytest.mark.asyncio
    async def test_successful_scale_up(self, scheduler, mock_api_client):
        """Test successful scale-up request."""
        decision = SchedulingDecision(action="scale_up", worker_template="m5zn.metal-cml", reason="No workers")

        result = await scheduler._handle_scale_up(decision)

        assert result.status == ReconciliationStatus.REQUEUE
        assert scheduler._scale_up_requests == 1
        mock_api_client.request_scale_up.assert_called_once_with("m5zn.metal-cml", "No workers")

    @pytest.mark.asyncio
    async def test_scale_up_api_failure(self, scheduler, mock_api_client):
        """Test scale-up handles API failure."""
        mock_api_client.request_scale_up.side_effect = Exception("API error")
        decision = SchedulingDecision(action="scale_up", worker_template="m5zn.metal-cml", reason="No workers")

        result = await scheduler._handle_scale_up(decision)

        assert result.status == ReconciliationStatus.FAILED

    @pytest.mark.asyncio
    async def test_scale_up_missing_template(self, scheduler):
        """Test scale-up fails when template is missing."""
        decision = SchedulingDecision(action="scale_up", worker_template=None, reason="No workers")

        result = await scheduler._handle_scale_up(decision)

        assert result.status == ReconciliationStatus.FAILED
        assert "missing worker_template" in result.message.lower()


# =============================================================================
# Readiness Check Tests
# =============================================================================


class TestCheckReadiness:
    """Tests for check_readiness — health probe logic."""

    @pytest.mark.asyncio
    async def test_ready_when_api_healthy(self, scheduler, mock_api_client):
        """Test readiness is True when API is healthy."""
        mock_api_client.health_check.return_value = True

        is_ready, message = await scheduler.check_readiness()

        assert is_ready is True
        assert message == "OK"

    @pytest.mark.asyncio
    async def test_not_ready_when_api_unhealthy(self, scheduler, mock_api_client):
        """Test readiness is False when API is not healthy."""
        mock_api_client.health_check.return_value = False

        is_ready, message = await scheduler.check_readiness()

        assert is_ready is False
        assert "not reachable" in message.lower()

    @pytest.mark.asyncio
    async def test_not_ready_on_api_exception(self, scheduler, mock_api_client):
        """Test readiness is False when API throws."""
        mock_api_client.health_check.side_effect = Exception("Connection refused")

        is_ready, message = await scheduler.check_readiness()

        assert is_ready is False
        assert "failed" in message.lower()


# =============================================================================
# Stats Tests
# =============================================================================


class TestStats:
    """Tests for stats property."""

    def test_stats_includes_placement_counters(self, scheduler):
        """Test stats include placement success/failure/scale-up counters."""
        scheduler._successful_placements = 10
        scheduler._failed_placements = 2
        scheduler._scale_up_requests = 1

        # Mock the parent stats to avoid needing full parent class initialization
        with patch.object(
            SchedulerHostedService.__bases__[0],
            "stats",
            new_callable=lambda: property(lambda self: {"running": False}),
        ):
            stats = scheduler.stats
            assert stats["successful_placements"] == 10
            assert stats["failed_placements"] == 2
            assert stats["scale_up_requests"] == 1


# =============================================================================
# Configure Tests
# =============================================================================


class TestConfigure:
    """Tests for DI configuration."""

    def test_configure_registers_singleton(self):
        """Test that configure registers a singleton."""
        mock_services = MagicMock()
        settings = Settings()

        SchedulerHostedService.configure(mock_services, settings)

        mock_services.add_singleton.assert_called_once()
        call_args = mock_services.add_singleton.call_args
        assert call_args[0][0] is SchedulerHostedService
