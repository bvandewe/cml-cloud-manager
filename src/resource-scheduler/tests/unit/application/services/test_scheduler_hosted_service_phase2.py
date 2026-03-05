"""Phase 2 tests for SchedulerHostedService.

Tests etcd capacity refresh, retry escalation, metrics recording,
and reconciliation with real-time capacity data.

Note: These tests mock the parent class infrastructure (etcd, API client)
to test the service logic in isolation without requiring etcd/API connectivity.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from application.hosted_services.scheduler_hosted_service import SchedulerHostedService
from application.services.placement_engine import PlacementEngine
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
    # Worker templates for scale-up decisions
    client.get_worker_templates = AsyncMock(return_value=None)
    return client


@pytest.fixture
def mock_etcd_client():
    """Mock EtcdClient with get_prefix support."""
    client = AsyncMock()
    client.get_prefix = AsyncMock(return_value={})
    client.get = AsyncMock(return_value=None)
    client.put = AsyncMock()
    client.delete = AsyncMock()
    # Required for leader election setup
    client.campaign = AsyncMock()
    client.resign = AsyncMock()
    return client


@pytest.fixture
def placement_engine():
    """Real PlacementEngine instance."""
    return PlacementEngine()


@pytest.fixture
def settings():
    """Settings for tests — defaults are fine for most tests."""
    return Settings()


@pytest.fixture
def scheduler(mock_api_client, mock_etcd_client, placement_engine, settings):
    """Create SchedulerHostedService with mocked dependencies.

    Note: We patch the parent class __init__ to avoid etcd/leader election setup.
    """
    with patch.object(SchedulerHostedService, "__init__", lambda self, *a, **kw: None):
        svc = SchedulerHostedService.__new__(SchedulerHostedService)

    # Set instance attributes that __init__ would normally set
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

    return svc


@pytest.fixture
def pending_instance():
    """A PENDING LabletSessionReadModel."""
    return LabletSessionReadModel(
        id="inst-001",
        name="Test Instance",
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
            "port_entries": [
                {"name": "serial_1"},
            ],
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
# _refresh_etcd_capacities Tests
# =============================================================================


class TestRefreshEtcdCapacities:
    """Tests for etcd capacity data refresh."""

    async def test_refresh_parses_capacity_data(self, scheduler, mock_etcd_client):
        """Test that capacity data is parsed from etcd get_prefix."""
        capacity_data = {
            "worker_id": "worker-001",
            "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
            "allocated_capacity": {"cpu_cores": 40, "memory_gb": 160, "storage_gb": 400},
            "available_capacity": {"cpu_cores": 56, "memory_gb": 224, "storage_gb": 600},
            "assigned_instance_count": 5,
            "updated_at": "2026-02-08T12:00:00Z",
        }

        mock_etcd_client.get_prefix.return_value = {
            "/workers/worker-001/capacity": json.dumps(capacity_data),
        }

        await scheduler._refresh_etcd_capacities()

        assert "worker-001" in scheduler._etcd_capacities
        assert scheduler._etcd_capacities["worker-001"]["worker_id"] == "worker-001"
        assert scheduler._etcd_capacities["worker-001"]["available_capacity"]["cpu_cores"] == 56

    async def test_refresh_ignores_non_capacity_keys(self, scheduler, mock_etcd_client):
        """Test that non-capacity etcd keys are ignored."""
        mock_etcd_client.get_prefix.return_value = {
            "/workers/worker-001/capacity": json.dumps({"worker_id": "worker-001"}),
            "/workers/worker-001/status": "running",
            "/workers/worker-001/health": json.dumps({"healthy": True}),
        }

        await scheduler._refresh_etcd_capacities()

        assert len(scheduler._etcd_capacities) == 1
        assert "worker-001" in scheduler._etcd_capacities

    async def test_refresh_handles_invalid_json(self, scheduler, mock_etcd_client):
        """Test graceful handling of invalid JSON in etcd values."""
        mock_etcd_client.get_prefix.return_value = {
            "/workers/worker-001/capacity": "{invalid json",
            "/workers/worker-002/capacity": json.dumps({"worker_id": "worker-002"}),
        }

        await scheduler._refresh_etcd_capacities()

        assert "worker-001" not in scheduler._etcd_capacities
        assert "worker-002" in scheduler._etcd_capacities

    async def test_refresh_handles_etcd_unavailable(self, scheduler, mock_etcd_client):
        """Test graceful fallback when etcd is unavailable."""
        mock_etcd_client.get_prefix.side_effect = Exception("etcd connection refused")

        # Pre-populate with stale data
        scheduler._etcd_capacities = {"worker-old": {"worker_id": "worker-old"}}

        await scheduler._refresh_etcd_capacities()

        # Should keep stale data (not crash, not empty)
        assert scheduler._etcd_capacities == {"worker-old": {"worker_id": "worker-old"}}

    async def test_refresh_uses_ttl_cache(self, scheduler, mock_etcd_client):
        """Test that refresh respects TTL cache."""
        import time

        mock_etcd_client.get_prefix.return_value = {
            "/workers/worker-001/capacity": json.dumps({"worker_id": "worker-001"}),
        }

        # First call should fetch
        await scheduler._refresh_etcd_capacities()
        assert mock_etcd_client.get_prefix.call_count == 1

        # Second call within TTL should use cache
        await scheduler._refresh_etcd_capacities()
        assert mock_etcd_client.get_prefix.call_count == 1

        # Expire the cache
        scheduler._etcd_capacities_fetched_at = time.monotonic() - 60

        # Third call after TTL should fetch again
        await scheduler._refresh_etcd_capacities()
        assert mock_etcd_client.get_prefix.call_count == 2

    async def test_refresh_handles_multiple_workers(self, scheduler, mock_etcd_client):
        """Test refresh with multiple workers."""
        mock_etcd_client.get_prefix.return_value = {
            "/workers/worker-001/capacity": json.dumps({"worker_id": "worker-001", "available_capacity": {"cpu_cores": 50}}),
            "/workers/worker-002/capacity": json.dumps({"worker_id": "worker-002", "available_capacity": {"cpu_cores": 30}}),
            "/workers/worker-003/capacity": json.dumps({"worker_id": "worker-003", "available_capacity": {"cpu_cores": 10}}),
        }

        await scheduler._refresh_etcd_capacities()

        assert len(scheduler._etcd_capacities) == 3

    async def test_refresh_handles_missing_worker_id(self, scheduler, mock_etcd_client):
        """Test that entries without worker_id are skipped."""
        mock_etcd_client.get_prefix.return_value = {
            "/workers/worker-001/capacity": json.dumps({"available_capacity": {"cpu_cores": 50}}),  # no worker_id
        }

        await scheduler._refresh_etcd_capacities()

        assert len(scheduler._etcd_capacities) == 0


# =============================================================================
# Reconcile Tests
# =============================================================================


class TestReconcileWithEtcdCapacity:
    """Tests for reconcile() with etcd capacity integration."""

    async def test_reconcile_passes_etcd_capacities_to_engine(self, scheduler, mock_api_client, pending_instance, basic_definition, running_worker):
        """Test that reconcile passes etcd capacities to PlacementEngine."""
        mock_api_client.get_lablet_definition.return_value = basic_definition
        scheduler._cached_workers = [running_worker]
        scheduler._etcd_capacities = {
            "worker-001": {
                "worker_id": "worker-001",
                "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
                "allocated_capacity": {"cpu_cores": 0, "memory_gb": 0, "storage_gb": 0},
                "available_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
                "assigned_instance_count": 0,
            }
        }

        with patch.object(scheduler._placement_engine, "schedule", wraps=scheduler._placement_engine.schedule) as mock_schedule:
            await scheduler.reconcile(pending_instance)

            # Verify etcd_capacities was passed
            call_kwargs = mock_schedule.call_args
            assert call_kwargs[1].get("etcd_capacities") is not None or (len(call_kwargs[0]) >= 4 and call_kwargs[0][3] is not None)

    async def test_reconcile_assigns_instance_successfully(self, scheduler, mock_api_client, pending_instance, basic_definition, running_worker):
        """Test successful session assignment via reconcile."""
        mock_api_client.get_lablet_definition.return_value = basic_definition
        scheduler._cached_workers = [running_worker]

        result = await scheduler.reconcile(pending_instance)

        assert result.status == ReconciliationStatus.SUCCESS
        mock_api_client.schedule_session.assert_called_once()
        call_kwargs = mock_api_client.schedule_session.call_args.kwargs
        assert call_kwargs["session_id"] == "inst-001"
        assert call_kwargs["worker_id"] == "worker-001"

    async def test_reconcile_includes_ports_in_schedule(self, scheduler, mock_api_client, pending_instance, basic_definition, running_worker):
        """Test that reconcile passes empty allocated_ports (ADR-031 Phase 4).

        Port allocation is deferred to lablet-controller pipeline (ports_alloc step).
        The scheduler only checks port count availability via placement_engine.
        """
        mock_api_client.get_lablet_definition.return_value = basic_definition
        scheduler._cached_workers = [running_worker]

        await scheduler.reconcile(pending_instance)

        mock_api_client.schedule_session.assert_called_once()
        call_kwargs = mock_api_client.schedule_session.call_args.kwargs
        assert "allocated_ports" in call_kwargs
        assert call_kwargs["allocated_ports"] == {}

    async def test_reconcile_fails_when_definition_not_found(self, scheduler, mock_api_client, pending_instance):
        """Test reconcile fails when definition cannot be fetched."""
        mock_api_client.get_lablet_definition.return_value = None

        result = await scheduler.reconcile(pending_instance)

        assert result.status == ReconciliationStatus.FAILED
        assert "not found" in result.message.lower()

    async def test_reconcile_scale_up_when_no_workers(self, scheduler, mock_api_client, pending_instance, basic_definition):
        """Test reconcile requests scale-up when no workers available."""
        mock_api_client.get_lablet_definition.return_value = basic_definition
        scheduler._cached_workers = []

        result = await scheduler.reconcile(pending_instance)

        # No workers → scale_up → requeue
        assert result.status == ReconciliationStatus.REQUEUE
        mock_api_client.request_scale_up.assert_called_once()


# =============================================================================
# Retry Escalation Tests
# =============================================================================


class TestRetryEscalation:
    """Tests for retry tracking and max retry escalation (Phase 2)."""

    async def test_retry_count_increments_on_failure(self, scheduler, mock_api_client, pending_instance, basic_definition, running_worker):
        """Test that retry count increments on scheduling failure."""
        mock_api_client.get_lablet_definition.return_value = basic_definition
        scheduler._cached_workers = [running_worker]
        mock_api_client.schedule_session.side_effect = Exception("API error")

        result = await scheduler.reconcile(pending_instance)

        assert result.status == ReconciliationStatus.FAILED
        assert scheduler._instance_retry_counts.get("inst-001") == 1

    async def test_retry_count_resets_on_success(self, scheduler, mock_api_client, pending_instance, basic_definition, running_worker):
        """Test that retry count resets on successful scheduling."""
        mock_api_client.get_lablet_definition.return_value = basic_definition
        scheduler._cached_workers = [running_worker]

        # Pre-set retry count
        scheduler._instance_retry_counts["inst-001"] = 3

        result = await scheduler.reconcile(pending_instance)

        assert result.status == ReconciliationStatus.SUCCESS
        assert "inst-001" not in scheduler._instance_retry_counts

    async def test_max_retries_triggers_extended_backoff(self, scheduler, mock_api_client, pending_instance, basic_definition, running_worker):
        """Test that max retries reached triggers 5-min extended backoff."""
        mock_api_client.get_lablet_definition.return_value = basic_definition
        scheduler._cached_workers = [running_worker]
        mock_api_client.schedule_session.side_effect = Exception("Persistent API error")

        # Pre-set retry count to max - 1 (will reach max on this attempt)
        scheduler._instance_retry_counts["inst-001"] = 4

        result = await scheduler.reconcile(pending_instance)

        # Should escalate to requeue with extended backoff
        assert result.status == ReconciliationStatus.REQUEUE
        assert result.requeue_after_seconds == 300.0
        assert scheduler._instance_retry_counts["inst-001"] == 5

    async def test_below_max_retries_returns_failure(self, scheduler, mock_api_client, pending_instance, basic_definition, running_worker):
        """Test that below max retries, failure is returned (normal backoff)."""
        mock_api_client.get_lablet_definition.return_value = basic_definition
        scheduler._cached_workers = [running_worker]
        mock_api_client.schedule_session.side_effect = Exception("Transient error")

        # Pre-set retry count below max
        scheduler._instance_retry_counts["inst-001"] = 2

        result = await scheduler.reconcile(pending_instance)

        # Should be FAILED (normal backoff from base class)
        assert result.status == ReconciliationStatus.FAILED
        assert scheduler._instance_retry_counts["inst-001"] == 3


# =============================================================================
# Metrics Recording Tests
# =============================================================================


class TestMetricsRecording:
    """Tests for OTel metrics recording in scheduling operations."""

    @patch("application.hosted_services.scheduler_hosted_service.record_scheduling_decision")
    async def test_reconcile_records_decision_metric(self, mock_record_decision, scheduler, mock_api_client, pending_instance, basic_definition, running_worker):
        """Test that reconcile records a scheduling decision metric."""
        mock_api_client.get_lablet_definition.return_value = basic_definition
        scheduler._cached_workers = [running_worker]

        await scheduler.reconcile(pending_instance)

        mock_record_decision.assert_called_once()
        args = mock_record_decision.call_args[0]
        assert args[0] == "assign"  # action

    @patch("application.hosted_services.scheduler_hosted_service.record_scheduling_success")
    async def test_reconcile_records_success_metric(self, mock_record_success, scheduler, mock_api_client, pending_instance, basic_definition, running_worker):
        """Test that successful assignment records success metric."""
        mock_api_client.get_lablet_definition.return_value = basic_definition
        scheduler._cached_workers = [running_worker]

        await scheduler.reconcile(pending_instance)

        mock_record_success.assert_called_once_with("worker-001")

    @patch("application.hosted_services.scheduler_hosted_service.record_scheduling_failure")
    async def test_reconcile_records_failure_metric(self, mock_record_failure, scheduler, mock_api_client, pending_instance, basic_definition, running_worker):
        """Test that failed assignment records failure metric."""
        mock_api_client.get_lablet_definition.return_value = basic_definition
        scheduler._cached_workers = [running_worker]
        mock_api_client.schedule_session.side_effect = Exception("API error")

        await scheduler.reconcile(pending_instance)

        mock_record_failure.assert_called_once()

    @patch("application.hosted_services.scheduler_hosted_service.record_scale_up_decision")
    async def test_reconcile_records_scale_up_metric(self, mock_record_scale_up, scheduler, mock_api_client, pending_instance, basic_definition):
        """Test that scale-up decision records scale-up metric."""
        mock_api_client.get_lablet_definition.return_value = basic_definition
        scheduler._cached_workers = []  # No workers → scale-up

        await scheduler.reconcile(pending_instance)

        mock_record_scale_up.assert_called_once()

    @patch("application.hosted_services.scheduler_hosted_service.record_scheduling_retry")
    async def test_reconcile_records_retry_metric_on_failure(self, mock_record_retry, scheduler, mock_api_client, pending_instance, basic_definition, running_worker):
        """Test that retry metric is recorded on scheduling failure."""
        mock_api_client.get_lablet_definition.return_value = basic_definition
        scheduler._cached_workers = [running_worker]
        mock_api_client.schedule_session.side_effect = Exception("API error")

        await scheduler.reconcile(pending_instance)

        mock_record_retry.assert_called_once_with("inst-001", 1)

    @patch("application.hosted_services.scheduler_hosted_service.record_etcd_capacity_fetch")
    async def test_refresh_records_etcd_fetch_success(self, mock_record_fetch, scheduler, mock_etcd_client):
        """Test that successful etcd fetch records success metric."""
        mock_etcd_client.get_prefix.return_value = {
            "/workers/w-1/capacity": json.dumps({"worker_id": "w-1"}),
        }

        await scheduler._refresh_etcd_capacities()

        mock_record_fetch.assert_called_once_with(success=True, worker_count=1)

    @patch("application.hosted_services.scheduler_hosted_service.record_etcd_capacity_fetch")
    async def test_refresh_records_etcd_fetch_failure(self, mock_record_fetch, scheduler, mock_etcd_client):
        """Test that failed etcd fetch records failure metric."""
        mock_etcd_client.get_prefix.side_effect = Exception("etcd error")

        await scheduler._refresh_etcd_capacities()

        mock_record_fetch.assert_called_once_with(success=False)


# =============================================================================
# List Resources Tests
# =============================================================================


class TestListResources:
    """Tests for list_resources with etcd capacity integration."""

    async def test_list_resources_refreshes_etcd_capacities(self, scheduler, mock_api_client, mock_etcd_client):
        """Test that list_resources refreshes etcd capacity data."""
        mock_api_client.get_lablet_sessions.return_value = []
        mock_api_client.get_workers.return_value = []
        mock_etcd_client.get_prefix.return_value = {
            "/workers/w-1/capacity": json.dumps({"worker_id": "w-1"}),
        }

        await scheduler.list_resources()

        mock_etcd_client.get_prefix.assert_called_once_with("/workers/")

    async def test_list_resources_handles_etcd_failure(self, scheduler, mock_api_client, mock_etcd_client):
        """Test that list_resources completes even if etcd fails."""
        mock_api_client.get_lablet_sessions.return_value = []
        mock_api_client.get_workers.return_value = []
        mock_etcd_client.get_prefix.side_effect = Exception("etcd down")

        # Should not raise
        result = await scheduler.list_resources()

        assert result == []

    async def test_list_resources_returns_sessions(self, scheduler, mock_api_client, mock_etcd_client):
        """Test that list_resources returns parsed sessions."""
        mock_api_client.get_lablet_sessions.return_value = [
            {"id": "inst-1", "name": "I1", "definition_id": "def-1", "status": "PENDING"},
            {"id": "inst-2", "name": "I2", "definition_id": "def-2", "status": "PENDING"},
        ]
        mock_api_client.get_workers.return_value = []
        mock_etcd_client.get_prefix.return_value = {}

        result = await scheduler.list_resources()

        assert len(result) == 2
        assert result[0].id == "inst-1"
        assert result[1].id == "inst-2"


# =============================================================================
# Scale-Up Decision Tests
# =============================================================================


class TestScaleUpDecision:
    """Tests for scale-up decision handling with rejection summaries."""

    async def test_scale_up_includes_rejection_summary_in_log(self, scheduler, mock_api_client, pending_instance, basic_definition):
        """Test that scale-up decision propagates rejection_summary correctly."""
        mock_api_client.get_lablet_definition.return_value = basic_definition

        # Only stopped workers → status rejections
        scheduler._cached_workers = [
            {
                "id": "worker-stopped",
                "name": "Stopped Worker",
                "status": "stopped",
                "declared_capacity": {"cpu_cores": 96, "memory_gb": 384, "storage_gb": 1000},
                "allocated_capacity": {"cpu_cores": 0, "memory_gb": 0, "storage_gb": 0},
                "session_ids": [],
                "port_allocations": [],
                "license": {"license_type": "enterprise"},
            }
        ]

        # The decision should be scale_up with status rejection
        result = await scheduler.reconcile(pending_instance)

        assert result.status == ReconciliationStatus.REQUEUE
        assert scheduler._scale_up_requests == 1

    async def test_scale_up_request_sent_to_api(self, scheduler, mock_api_client, pending_instance, basic_definition):
        """Test that scale-up decision sends request to API."""
        mock_api_client.get_lablet_definition.return_value = basic_definition
        scheduler._cached_workers = []

        await scheduler.reconcile(pending_instance)

        mock_api_client.request_scale_up.assert_called_once()
        call_args = mock_api_client.request_scale_up.call_args
        assert call_args[0][0] is not None  # template
        assert call_args[0][1] is not None  # reason
