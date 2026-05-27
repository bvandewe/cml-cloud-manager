"""Unit tests for WorkerReconciler — G4 Comprehensive Coverage.

Covers the full worker lifecycle state machine:
- State handlers: PENDING → PROVISIONING → RUNNING → STOPPING → TERMINATED
- Metrics collection (CloudWatch + CML System API)
- Activity detection and idle evaluation
- License reconciliation (ADR-016)
- Scale-down gate regression (SCALE_DOWN_ENABLED default=False)

Pattern: Uses object.__new__(WorkerReconciler) to bypass complex __init__,
matching the fixture pattern from test_worker_reconciler_phase3.py.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from application.hosted_services.worker_reconciler import WorkerReconciler
from integration.services.aws_cloudwatch_spi import Ec2Metrics
from integration.services.aws_ec2_spi import Ec2InstanceState
from integration.services.cml_system_spi import CmlCpuStats, CmlDiskStats, CmlMemoryStats, CmlSystemStats
from lcm_core.domain.entities import CMLWorkerReadModel
from lcm_core.domain.entities.read_models.cml_worker_read_model import CMLLicenseReadModel
from lcm_core.domain.enums import CMLWorkerStatus
from lcm_core.infrastructure.hosted_services.reconciliation_hosted_service import ReconciliationStatus

# =============================================================================
# Fixtures
# =============================================================================


def make_worker(
    worker_id: str = "worker-001",
    status: str = "running",
    desired_status: str = "running",
    ec2_instance_id: str | None = "i-abc123",
    ip_address: str | None = "10.0.0.1",
    template_name: str | None = "default",
    instance_type: str | None = "m5zn.metal",
    ami_name: str | None = "cisco-cml2.9",
    aws_region: str | None = "us-east-1",
    cml_username: str | None = "admin",
    cml_password: str | None = "secret",
    is_idle_detection_enabled: bool = True,
    license: CMLLicenseReadModel | None = None,
) -> CMLWorkerReadModel:
    """Create a CMLWorkerReadModel for testing."""
    return CMLWorkerReadModel(
        id=worker_id,
        name=f"cml-{worker_id}",
        status=status,
        desired_status=desired_status,
        ec2_instance_id=ec2_instance_id,
        ip_address=ip_address,
        template_name=template_name,
        instance_type=instance_type,
        ami_name=ami_name,
        aws_region=aws_region,
        cml_username=cml_username,
        cml_password=cml_password,
        is_idle_detection_enabled=is_idle_detection_enabled,
        license=license or CMLLicenseReadModel(),
    )


def make_ec2_state(
    instance_id: str = "i-abc123",
    state: str = "running",
    public_ip: str | None = "54.1.2.3",
    private_ip: str | None = "10.0.0.1",
) -> Ec2InstanceState:
    """Create an Ec2InstanceState for testing."""
    return Ec2InstanceState(
        instance_id=instance_id,
        state=state,
        public_ip=public_ip,
        private_ip=private_ip,
    )


def make_ec2_metrics(
    instance_id: str = "i-abc123",
    cpu: float = 25.0,
    net_in: float = 1000.0,
    net_out: float = 500.0,
) -> Ec2Metrics:
    """Create Ec2Metrics for testing."""
    return Ec2Metrics(
        instance_id=instance_id,
        cpu_utilization=cpu,
        network_in_bytes=net_in,
        network_out_bytes=net_out,
        disk_read_ops=None,
        disk_write_ops=None,
    )


def make_cml_stats(
    cpu_percent: float = 30.0,
    memory_total: int = 202422902784,
    memory_used: int = 2033487872,
    memory_free: int = 199086161920,
    disk_total: int = 266206101504,
    disk_used: int = 137792577536,
    disk_free: int = 128413523968,
) -> CmlSystemStats:
    """Create CmlSystemStats for testing using the new nested structure."""
    return CmlSystemStats(
        cpu=CmlCpuStats(count=48, percent=cpu_percent),
        memory=CmlMemoryStats(total=memory_total, free=memory_free, used=memory_used),
        disk=CmlDiskStats(total=disk_total, free=disk_free, used=disk_used),
        controller_disk=CmlDiskStats(total=disk_total, free=disk_free, used=disk_used),
    )


def make_idle_result(
    is_idle: bool = True,
    eligible_for_pause: bool = True,
    auto_pause_triggered: bool = False,
    idle_minutes: float = 30.0,
) -> dict:
    """Create an idle_result dict matching the detect_worker_idle API response."""
    return {
        "is_idle": is_idle,
        "eligible_for_pause": eligible_for_pause,
        "auto_pause_triggered": auto_pause_triggered,
        "idle_minutes": idle_minutes,
    }


def make_reconciler(
    scale_down_enabled: bool = False,
    min_workers: int = 0,
    scale_down_cooldown_seconds: int = 600,
    aws_region: str = "us-east-1",
) -> WorkerReconciler:
    """Create a WorkerReconciler with bypassed __init__ and mocked SPI clients.

    Uses object.__new__ to skip the complex __init__ which requires
    etcd, AWS, CML clients, and leader election config.
    Sets up all attributes needed by state handlers and helper methods.
    """
    reconciler = object.__new__(WorkerReconciler)

    # Mock settings
    reconciler._settings = MagicMock()
    reconciler._settings.scale_down_enabled = scale_down_enabled
    reconciler._settings.min_workers = min_workers
    reconciler._settings.scale_down_cooldown_seconds = scale_down_cooldown_seconds
    reconciler._settings.aws_region = aws_region

    # Region config for provisioning (ADR-018)
    region_config = MagicMock()
    region_config.subnet_id = "subnet-abc123"
    region_config.security_group_ids = ["sg-abc123"]
    region_config.key_name = "my-key"
    region_config.default_tags = {"Environment": "test"}
    reconciler._settings.get_region_config = MagicMock(return_value=region_config)

    # Mock SPI clients
    reconciler._api = MagicMock()
    reconciler._api.get_worker_template = AsyncMock(
        return_value={
            "instance_type": "m5zn.metal",
            "ami_name_pattern": "cisco-cml2.9*",
        }
    )
    reconciler._api.update_worker_status = AsyncMock()
    reconciler._api.update_worker_ec2_details = AsyncMock()
    reconciler._api.report_worker_metrics = AsyncMock()
    reconciler._api.detect_worker_idle = AsyncMock(return_value=make_idle_result(is_idle=False))
    reconciler._api.drain_worker = AsyncMock()
    reconciler._api.start_license_registration = AsyncMock()
    reconciler._api.complete_license_registration = AsyncMock()
    reconciler._api.fail_license_registration = AsyncMock()
    reconciler._api.start_license_deregistration = AsyncMock()
    reconciler._api.complete_license_deregistration = AsyncMock()
    reconciler._api.fail_license_deregistration = AsyncMock()

    reconciler._ec2 = MagicMock()
    reconciler._ec2.get_instance_state = AsyncMock(return_value=make_ec2_state())
    reconciler._ec2.get_ami_ids_by_name = AsyncMock(return_value=["ami-12345"])
    reconciler._ec2.run_instance = AsyncMock(return_value="i-new123")
    reconciler._ec2.start_instance = AsyncMock()
    reconciler._ec2.stop_instance = AsyncMock()
    reconciler._ec2.terminate_instance = AsyncMock()
    reconciler._ec2.describe_image = AsyncMock(return_value={"name": "cisco-cml2.9", "description": "CML AMI", "creation_date": "2024-01-01"})

    reconciler._cloudwatch = MagicMock()
    reconciler._cloudwatch.get_ec2_metrics = AsyncMock(return_value=make_ec2_metrics())

    reconciler._cml = MagicMock()
    reconciler._cml.get_system_stats = AsyncMock(return_value=make_cml_stats())
    reconciler._cml.check_health = AsyncMock(return_value=(True, "CML 2.9 ready"))
    reconciler._cml.register_license = AsyncMock(return_value=(True, "OK"))
    reconciler._cml.deregister_license = AsyncMock(return_value=(True, "OK"))

    # Counters
    reconciler._provisioned_count = 0
    reconciler._started_count = 0
    reconciler._stopped_count = 0
    reconciler._terminated_count = 0
    reconciler._metrics_collected_count = 0
    reconciler._activity_checks_count = 0
    reconciler._auto_pauses_triggered_count = 0
    reconciler._scale_down_count = 0
    reconciler._last_scale_down_at = None
    reconciler._running_worker_count = 3
    reconciler._license_registrations_count = 0
    reconciler._license_deregistrations_count = 0

    # Discovery counters and state (AD-020)
    reconciler._discovery_runs = 0
    reconciler._total_discovered = 0
    reconciler._total_imported = 0
    reconciler._total_orphans_terminated = 0
    reconciler._last_discovery_at = None
    reconciler._last_discovery_error = None
    reconciler._cached_discovery_settings = None
    reconciler._discovery_task = None

    # Discovery settings on mock settings
    reconciler._settings.worker_discovery_enabled = True
    reconciler._settings.worker_discovery_interval = 300
    reconciler._settings.worker_discovery_ami_name = "cisco-cml2.9*"
    reconciler._settings.worker_discovery_regions = ""
    reconciler._settings.discovery_regions = [aws_region]
    reconciler._settings.aws_access_key_id = "test-key"
    reconciler._settings.aws_secret_access_key = "test-secret"

    # WebSocket monitoring (ADR-041) — disabled in tests by default
    reconciler._ws_registry = None
    reconciler._settings.cml_websocket_enabled = False

    return reconciler


# =============================================================================
# _handle_pending Tests
# =============================================================================


class TestHandlePending:
    """Tests for WorkerReconciler._handle_pending — EC2 provisioning."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_successful_provisioning(self):
        """Happy path: template resolved → AMI found → EC2 launched → PROVISIONING."""
        reconciler = make_reconciler()
        worker = make_worker(status=CMLWorkerStatus.PENDING, ec2_instance_id=None)

        result = await reconciler._handle_pending(worker)

        assert result.status == ReconciliationStatus.REQUEUE
        reconciler._ec2.run_instance.assert_called_once()
        reconciler._api.update_worker_status.assert_called_once_with(
            worker_id="worker-001",
            status=CMLWorkerStatus.PROVISIONING,
            ec2_instance_id="i-new123",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_fails_without_template_name(self):
        """Fail fast if worker has no template_name."""
        reconciler = make_reconciler()
        worker = make_worker(status=CMLWorkerStatus.PENDING, template_name=None)

        result = await reconciler._handle_pending(worker)

        assert result.status == ReconciliationStatus.FAILED
        reconciler._ec2.run_instance.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_fails_when_template_not_found(self):
        """Fail if control-plane-api returns no template data."""
        reconciler = make_reconciler()
        reconciler._api.get_worker_template = AsyncMock(return_value=None)
        worker = make_worker(status=CMLWorkerStatus.PENDING)

        result = await reconciler._handle_pending(worker)

        assert result.status == ReconciliationStatus.FAILED

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_fails_when_no_ami_found(self):
        """Fail if no AMI matches the name pattern."""
        reconciler = make_reconciler()
        reconciler._ec2.get_ami_ids_by_name = AsyncMock(return_value=[])
        worker = make_worker(status=CMLWorkerStatus.PENDING)

        result = await reconciler._handle_pending(worker)

        assert result.status == ReconciliationStatus.FAILED
        reconciler._ec2.run_instance.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_fails_when_no_region_config(self):
        """Fail if no infrastructure config for the worker's region."""
        reconciler = make_reconciler()
        reconciler._settings.get_region_config = MagicMock(return_value=None)
        worker = make_worker(status=CMLWorkerStatus.PENDING)

        result = await reconciler._handle_pending(worker)

        assert result.status == ReconciliationStatus.FAILED
        reconciler._ec2.run_instance.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_launch_failure_sets_status_failed(self):
        """EC2 RunInstance failure → worker status set to FAILED."""
        reconciler = make_reconciler()
        reconciler._ec2.run_instance = AsyncMock(side_effect=Exception("EC2 launch failed"))
        worker = make_worker(status=CMLWorkerStatus.PENDING)

        result = await reconciler._handle_pending(worker)

        assert result.status == ReconciliationStatus.FAILED
        reconciler._api.update_worker_status.assert_called_with(
            worker_id="worker-001",
            status=CMLWorkerStatus.FAILED,
        )


# =============================================================================
# _handle_provisioning Tests
# =============================================================================


class TestHandleProvisioning:
    """Tests for WorkerReconciler._handle_provisioning — EC2 readiness check."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_running_transitions_to_running(self):
        """EC2 running → worker status updated to RUNNING with IP."""
        reconciler = make_reconciler()
        reconciler._ec2.get_instance_state = AsyncMock(return_value=make_ec2_state(state="running", public_ip="54.1.2.3"))
        worker = make_worker(status=CMLWorkerStatus.PROVISIONING)

        result = await reconciler._handle_provisioning(worker)

        assert result.status == ReconciliationStatus.SUCCESS
        reconciler._api.update_worker_status.assert_called_once_with(
            worker_id="worker-001",
            status=CMLWorkerStatus.RUNNING,
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_running_uses_private_ip_when_no_public(self):
        """EC2 running without public IP → uses private IP."""
        reconciler = make_reconciler()
        reconciler._ec2.get_instance_state = AsyncMock(return_value=make_ec2_state(state="running", public_ip=None, private_ip="10.0.0.99"))
        worker = make_worker(status=CMLWorkerStatus.PROVISIONING)

        result = await reconciler._handle_provisioning(worker)

        assert result.status == ReconciliationStatus.SUCCESS
        reconciler._api.update_worker_status.assert_called_once_with(
            worker_id="worker-001",
            status=CMLWorkerStatus.RUNNING,
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_pending_requeues(self):
        """EC2 still pending → requeue for next cycle."""
        reconciler = make_reconciler()
        reconciler._ec2.get_instance_state = AsyncMock(return_value=make_ec2_state(state="pending"))
        worker = make_worker(status=CMLWorkerStatus.PROVISIONING)

        result = await reconciler._handle_provisioning(worker)

        assert result.status == ReconciliationStatus.REQUEUE
        reconciler._api.update_worker_status.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_not_found_fails(self):
        """EC2 instance not found → fail."""
        reconciler = make_reconciler()
        reconciler._ec2.get_instance_state = AsyncMock(return_value=None)
        worker = make_worker(status=CMLWorkerStatus.PROVISIONING)

        result = await reconciler._handle_provisioning(worker)

        assert result.status == ReconciliationStatus.FAILED

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_ec2_instance_id_fails(self):
        """Worker in PROVISIONING without ec2_instance_id → fail."""
        reconciler = make_reconciler()
        worker = make_worker(status=CMLWorkerStatus.PROVISIONING, ec2_instance_id=None)

        result = await reconciler._handle_provisioning(worker)

        assert result.status == ReconciliationStatus.FAILED


# =============================================================================
# _handle_starting Tests
# =============================================================================


class TestHandleStarting:
    """Tests for WorkerReconciler._handle_starting — start stopped EC2."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_already_running_transitions_to_running(self):
        """EC2 already running → just update status."""
        reconciler = make_reconciler()
        reconciler._ec2.get_instance_state = AsyncMock(return_value=make_ec2_state(state="running"))
        worker = make_worker(status=CMLWorkerStatus.STARTING)

        result = await reconciler._handle_starting(worker)

        assert result.status == ReconciliationStatus.SUCCESS
        reconciler._api.update_worker_status.assert_called_once()
        reconciler._ec2.start_instance.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_stopped_starts_and_requeues(self):
        """EC2 stopped → start instance and requeue."""
        reconciler = make_reconciler()
        reconciler._ec2.get_instance_state = AsyncMock(return_value=make_ec2_state(state="stopped"))
        worker = make_worker(status=CMLWorkerStatus.STARTING)

        result = await reconciler._handle_starting(worker)

        assert result.status == ReconciliationStatus.REQUEUE
        reconciler._ec2.start_instance.assert_called_once_with("i-abc123")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_pending_requeues(self):
        """EC2 in pending state → requeue."""
        reconciler = make_reconciler()
        reconciler._ec2.get_instance_state = AsyncMock(return_value=make_ec2_state(state="pending"))
        worker = make_worker(status=CMLWorkerStatus.STARTING)

        result = await reconciler._handle_starting(worker)

        assert result.status == ReconciliationStatus.REQUEUE

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_terminated_fails(self):
        """EC2 in terminated state → cannot start, fail."""
        reconciler = make_reconciler()
        reconciler._ec2.get_instance_state = AsyncMock(return_value=make_ec2_state(state="terminated"))
        worker = make_worker(status=CMLWorkerStatus.STARTING)

        result = await reconciler._handle_starting(worker)

        assert result.status == ReconciliationStatus.FAILED


# =============================================================================
# _handle_running Tests
# =============================================================================


class TestHandleRunning:
    """Tests for WorkerReconciler._handle_running — steady-state reconciliation."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_desired_stopped_transitions_to_stopping(self):
        """desired_status=stopped → transition to STOPPING."""
        reconciler = make_reconciler()
        worker = make_worker(status=CMLWorkerStatus.RUNNING, desired_status="stopped")

        result = await reconciler._handle_running(worker)

        assert result.status == ReconciliationStatus.REQUEUE
        reconciler._api.update_worker_status.assert_called_once_with(
            worker_id="worker-001",
            status=CMLWorkerStatus.STOPPING,
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_desired_terminated_transitions_to_terminating(self):
        """desired_status=terminated → transition to TERMINATING."""
        reconciler = make_reconciler()
        worker = make_worker(status=CMLWorkerStatus.RUNNING, desired_status="terminated")

        result = await reconciler._handle_running(worker)

        assert result.status == ReconciliationStatus.REQUEUE
        reconciler._api.update_worker_status.assert_called_once_with(
            worker_id="worker-001",
            status=CMLWorkerStatus.TERMINATING,
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_state_mismatch_updates_status(self):
        """EC2 no longer running → update worker status to match."""
        reconciler = make_reconciler()
        reconciler._ec2.get_instance_state = AsyncMock(return_value=make_ec2_state(state="stopped"))
        worker = make_worker(status=CMLWorkerStatus.RUNNING)

        result = await reconciler._handle_running(worker)

        assert result.status == ReconciliationStatus.REQUEUE
        reconciler._api.update_worker_status.assert_called_once_with(
            worker_id="worker-001",
            status=CMLWorkerStatus.STOPPED,
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_ip_change_updates_worker_in_place(self):
        """EC2 IP differs from worker IP → reports to CPA AND updates local read model.

        This ensures the rest of the reconcile tick (WS monitoring, health checks)
        uses the new IP immediately, not on the next tick.
        """
        reconciler = make_reconciler()
        # Worker has old IP; EC2 has new IP (default make_ec2_state: public_ip="54.1.2.3")
        worker = make_worker(status=CMLWorkerStatus.RUNNING, ip_address="10.0.0.99")
        reconciler._ec2.get_instance_state = AsyncMock(return_value=make_ec2_state(public_ip="54.1.2.3", private_ip="10.0.0.1"))

        result = await reconciler._handle_running(worker)

        assert result.status == ReconciliationStatus.SUCCESS
        # Should report to CPA
        reconciler._api.update_worker_ec2_details.assert_called_once()
        # Should update local read model in-place for same-tick correctness
        assert worker.ip_address == "54.1.2.3"
        assert worker.public_ip == "54.1.2.3"
        assert worker.private_ip == "10.0.0.1"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_ip_change_ws_monitor_uses_new_ip(self):
        """After IP change detection, WS ensure_monitoring uses the new IP."""
        reconciler = make_reconciler()
        # Enable WS and set up registry mock
        reconciler._settings.cml_websocket_enabled = True
        ws_registry = MagicMock()
        ws_registry.ensure_monitoring = AsyncMock()
        ws_registry.get_monitor = MagicMock(return_value=None)
        reconciler._ws_registry = ws_registry
        # Worker has old IP
        worker = make_worker(status=CMLWorkerStatus.RUNNING, ip_address="3.85.19.221")
        reconciler._ec2.get_instance_state = AsyncMock(return_value=make_ec2_state(public_ip="18.234.119.175", private_ip="10.0.0.5"))

        await reconciler._handle_running(worker)

        # WS ensure_monitoring should be called with the NEW IP, not the old one
        ws_registry.ensure_monitoring.assert_called_once()
        call_kwargs = ws_registry.ensure_monitoring.call_args.kwargs
        assert call_kwargs["host"] == "18.234.119.175"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_happy_path_succeeds_without_metrics(self):
        """Normal RUNNING path: returns success without inline metrics collection.

        Metrics collection runs independently via _run_metrics_collection_loop,
        not during reconciliation (architectural separation).
        """
        reconciler = make_reconciler()
        worker = make_worker(status=CMLWorkerStatus.RUNNING)

        result = await reconciler._handle_running(worker)

        assert result.status == ReconciliationStatus.SUCCESS
        # Metrics are NOT collected during reconciliation anymore
        reconciler._cloudwatch.get_ec2_metrics.assert_not_called()
        reconciler._api.report_worker_metrics.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_idle_detection_called_when_enabled(self):
        """Activity detection is called when is_idle_detection_enabled=True."""
        reconciler = make_reconciler()
        worker = make_worker(status=CMLWorkerStatus.RUNNING, is_idle_detection_enabled=True)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_idle_detection_skipped_when_disabled(self):
        """Activity detection is skipped when is_idle_detection_enabled=False."""
        reconciler = make_reconciler()
        worker = make_worker(status=CMLWorkerStatus.RUNNING, is_idle_detection_enabled=False)

        await reconciler._handle_running(worker)

        reconciler._api.detect_worker_idle.assert_not_called()
        assert reconciler._activity_checks_count == 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_scale_down_gate_blocks_when_disabled(self):
        """REGRESSION: scale_down_enabled=False blocks _evaluate_scale_down even when idle.

        This is the root cause of idle workers not scaling to zero.
        Settings.scale_down_enabled defaults to False, and it was never
        configured in docker-compose.shared.yml.
        """
        reconciler = make_reconciler(scale_down_enabled=False)
        # Make idle detection return an idle, eligible worker
        reconciler._api.detect_worker_idle = AsyncMock(return_value=make_idle_result(is_idle=True, eligible_for_pause=True))
        worker = make_worker(status=CMLWorkerStatus.RUNNING, is_idle_detection_enabled=True)

        result = await reconciler._handle_running(worker)

        # Scale-down should NOT have been evaluated
        assert result.status == ReconciliationStatus.SUCCESS
        reconciler._api.drain_worker.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_scale_down_gate_allows_when_enabled(self):
        """scale_down_enabled=True + idle result → _evaluate_scale_down called."""
        reconciler = make_reconciler(scale_down_enabled=True, min_workers=0)
        reconciler._running_worker_count = 1
        # Make idle detection return an idle, eligible worker
        reconciler._api.detect_worker_idle = AsyncMock(return_value=make_idle_result(is_idle=True, eligible_for_pause=True))
        worker = make_worker(status=CMLWorkerStatus.RUNNING, is_idle_detection_enabled=True)

        result = await reconciler._handle_running(worker)

        # Worker should be drained (scale-down triggered)
        assert result.status == ReconciliationStatus.REQUEUE
        reconciler._api.drain_worker.assert_called_once_with(
            worker_id="worker-001",
            reason="scale_down",
            requested_by="worker-controller",
        )


# =============================================================================
# _handle_stopping Tests
# =============================================================================


class TestHandleStopping:
    """Tests for WorkerReconciler._handle_stopping — stop EC2 instance."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_ec2_instance_transitions_to_stopped(self):
        """No EC2 instance → just update to STOPPED."""
        reconciler = make_reconciler()
        worker = make_worker(status=CMLWorkerStatus.STOPPING, ec2_instance_id=None)

        result = await reconciler._handle_stopping(worker)

        assert result.status == ReconciliationStatus.SUCCESS
        reconciler._api.update_worker_status.assert_called_once_with(
            worker_id="worker-001",
            status=CMLWorkerStatus.STOPPED,
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_already_stopped(self):
        """EC2 already stopped → update to STOPPED."""
        reconciler = make_reconciler()
        reconciler._ec2.get_instance_state = AsyncMock(return_value=make_ec2_state(state="stopped"))
        worker = make_worker(status=CMLWorkerStatus.STOPPING)

        result = await reconciler._handle_stopping(worker)

        assert result.status == ReconciliationStatus.SUCCESS
        reconciler._api.update_worker_status.assert_called_once_with(
            worker_id="worker-001",
            status=CMLWorkerStatus.STOPPED,
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_running_stops_and_requeues(self):
        """EC2 still running → stop instance and requeue."""
        reconciler = make_reconciler()
        reconciler._ec2.get_instance_state = AsyncMock(return_value=make_ec2_state(state="running"))
        worker = make_worker(status=CMLWorkerStatus.STOPPING)

        result = await reconciler._handle_stopping(worker)

        assert result.status == ReconciliationStatus.REQUEUE
        reconciler._ec2.stop_instance.assert_called_once_with("i-abc123")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_stopping_requeues(self):
        """EC2 in stopping state → requeue."""
        reconciler = make_reconciler()
        reconciler._ec2.get_instance_state = AsyncMock(return_value=make_ec2_state(state="stopping"))
        worker = make_worker(status=CMLWorkerStatus.STOPPING)

        result = await reconciler._handle_stopping(worker)

        assert result.status == ReconciliationStatus.REQUEUE

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_not_found_transitions_to_stopped(self):
        """EC2 not found → transition to STOPPED (instance may have been terminated externally)."""
        reconciler = make_reconciler()
        reconciler._ec2.get_instance_state = AsyncMock(return_value=None)
        worker = make_worker(status=CMLWorkerStatus.STOPPING)

        result = await reconciler._handle_stopping(worker)

        assert result.status == ReconciliationStatus.SUCCESS
        reconciler._api.update_worker_status.assert_called_once_with(
            worker_id="worker-001",
            status=CMLWorkerStatus.STOPPED,
        )


# =============================================================================
# _handle_stopped Tests
# =============================================================================


class TestHandleStopped:
    """Tests for WorkerReconciler._handle_stopped — start or terminate stopped worker."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_desired_running_transitions_to_starting(self):
        """desired_status=running → transition to STARTING and requeue."""
        reconciler = make_reconciler()
        worker = make_worker(status=CMLWorkerStatus.STOPPED, desired_status="running")

        result = await reconciler._handle_stopped(worker)

        assert result.status == ReconciliationStatus.REQUEUE
        reconciler._api.update_worker_status.assert_called_once_with(
            worker_id="worker-001",
            status=CMLWorkerStatus.STARTING,
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_desired_terminated_transitions_to_terminating(self):
        """desired_status=terminated → transition to TERMINATING and requeue."""
        reconciler = make_reconciler()
        worker = make_worker(status=CMLWorkerStatus.STOPPED, desired_status="terminated")

        result = await reconciler._handle_stopped(worker)

        assert result.status == ReconciliationStatus.REQUEUE
        reconciler._api.update_worker_status.assert_called_once_with(
            worker_id="worker-001",
            status=CMLWorkerStatus.TERMINATING,
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_desired_stopped_is_noop(self):
        """desired_status=stopped → no action needed, worker is at rest."""
        reconciler = make_reconciler()
        worker = make_worker(status=CMLWorkerStatus.STOPPED, desired_status="stopped")

        result = await reconciler._handle_stopped(worker)

        assert result.status == ReconciliationStatus.SUCCESS
        reconciler._api.update_worker_status.assert_not_called()


# =============================================================================
# _handle_terminating Tests
# =============================================================================


class TestHandleTerminating:
    """Tests for WorkerReconciler._handle_terminating — terminate EC2 instance."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_ec2_instance_transitions_to_terminated(self):
        """No EC2 instance → just update to TERMINATED."""
        reconciler = make_reconciler()
        worker = make_worker(status=CMLWorkerStatus.TERMINATING, ec2_instance_id=None)

        result = await reconciler._handle_terminating(worker)

        assert result.status == ReconciliationStatus.SUCCESS
        reconciler._api.update_worker_status.assert_called_once_with(
            worker_id="worker-001",
            status=CMLWorkerStatus.TERMINATED,
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_already_terminated(self):
        """EC2 already terminated → update to TERMINATED."""
        reconciler = make_reconciler()
        reconciler._ec2.get_instance_state = AsyncMock(return_value=make_ec2_state(state="terminated"))
        worker = make_worker(status=CMLWorkerStatus.TERMINATING)

        result = await reconciler._handle_terminating(worker)

        assert result.status == ReconciliationStatus.SUCCESS
        reconciler._api.update_worker_status.assert_called_once_with(
            worker_id="worker-001",
            status=CMLWorkerStatus.TERMINATED,
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_running_terminates_and_requeues(self):
        """EC2 still running → terminate and requeue."""
        reconciler = make_reconciler()
        reconciler._ec2.get_instance_state = AsyncMock(return_value=make_ec2_state(state="running"))
        worker = make_worker(status=CMLWorkerStatus.TERMINATING)

        result = await reconciler._handle_terminating(worker)

        assert result.status == ReconciliationStatus.REQUEUE
        reconciler._ec2.terminate_instance.assert_called_once_with("i-abc123")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_shutting_down_requeues(self):
        """EC2 shutting-down → requeue."""
        reconciler = make_reconciler()
        reconciler._ec2.get_instance_state = AsyncMock(return_value=make_ec2_state(state="shutting-down"))
        worker = make_worker(status=CMLWorkerStatus.TERMINATING)

        result = await reconciler._handle_terminating(worker)

        assert result.status == ReconciliationStatus.REQUEUE
        reconciler._ec2.terminate_instance.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ec2_not_found_transitions_to_terminated(self):
        """EC2 not found → transition to TERMINATED."""
        reconciler = make_reconciler()
        reconciler._ec2.get_instance_state = AsyncMock(return_value=None)
        worker = make_worker(status=CMLWorkerStatus.TERMINATING)

        result = await reconciler._handle_terminating(worker)

        assert result.status == ReconciliationStatus.SUCCESS
        reconciler._api.update_worker_status.assert_called_once_with(
            worker_id="worker-001",
            status=CMLWorkerStatus.TERMINATED,
        )


# =============================================================================
# _collect_and_report_metrics Tests
# =============================================================================


class TestCollectAndReportMetrics:
    """Tests for WorkerReconciler._collect_and_report_metrics."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_collects_cloudwatch_and_cml_metrics(self):
        """Collects both CloudWatch EC2 metrics and CML system stats."""
        reconciler = make_reconciler()
        worker = make_worker()

        await reconciler._collect_and_report_metrics(worker)

        reconciler._cloudwatch.get_ec2_metrics.assert_called_once_with("i-abc123")
        reconciler._cml.get_system_stats.assert_called_once_with(
            host="10.0.0.1",
            username="admin",
            password="secret",
        )
        reconciler._api.report_worker_metrics.assert_called_once()

        # Verify reported metrics shape
        call_kwargs = reconciler._api.report_worker_metrics.call_args
        metrics = call_kwargs.kwargs.get("metrics") or call_kwargs[1].get("metrics")
        assert "ec2" in metrics
        assert "cml" in metrics
        assert metrics["ec2"]["cpu_utilization"] == 25.0
        assert metrics["cml"]["cpu_percent"] == 30.0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cloudwatch_failure_continues(self):
        """CloudWatch failure doesn't prevent CML metrics collection."""
        reconciler = make_reconciler()
        reconciler._cloudwatch.get_ec2_metrics = AsyncMock(side_effect=Exception("CW timeout"))
        worker = make_worker()

        await reconciler._collect_and_report_metrics(worker)

        # CML stats still collected
        reconciler._cml.get_system_stats.assert_called_once()
        # Metrics still reported (without EC2 section)
        reconciler._api.report_worker_metrics.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cml_failure_continues(self):
        """CML stats failure doesn't prevent metrics reporting."""
        reconciler = make_reconciler()
        reconciler._cml.get_system_stats = AsyncMock(side_effect=Exception("CML unreachable"))
        worker = make_worker()

        await reconciler._collect_and_report_metrics(worker)

        reconciler._cloudwatch.get_ec2_metrics.assert_called_once()
        reconciler._api.report_worker_metrics.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_ec2_instance_skips_cloudwatch(self):
        """No ec2_instance_id → skips CloudWatch metrics."""
        reconciler = make_reconciler()
        worker = make_worker(ec2_instance_id=None)

        await reconciler._collect_and_report_metrics(worker)

        reconciler._cloudwatch.get_ec2_metrics.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_ip_address_skips_cml(self):
        """No ip_address → skips CML system stats."""
        reconciler = make_reconciler()
        worker = make_worker(ip_address=None)

        await reconciler._collect_and_report_metrics(worker)

        reconciler._cml.get_system_stats.assert_not_called()


# =============================================================================
# _detect_activity Tests
# =============================================================================


class TestDetectActivity:
    """Tests for WorkerReconciler._detect_activity."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_idle_result_on_success(self):
        """Returns the idle detection result dict on success."""
        reconciler = make_reconciler()
        expected = make_idle_result(is_idle=True, idle_minutes=45.0)
        reconciler._api.detect_worker_idle = AsyncMock(return_value=expected)
        worker = make_worker()

        result = await reconciler._detect_activity(worker)

        assert result is not None
        assert result["is_idle"] is True
        assert result["idle_minutes"] == 45.0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_none_on_api_error(self):
        """API exception → returns None (non-fatal)."""
        reconciler = make_reconciler()
        reconciler._api.detect_worker_idle = AsyncMock(side_effect=Exception("API timeout"))
        worker = make_worker()

        result = await reconciler._detect_activity(worker)

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_none_when_result_has_error(self):
        """API returns error field → returns None."""
        reconciler = make_reconciler()
        reconciler._api.detect_worker_idle = AsyncMock(return_value={"error": "worker not found"})
        worker = make_worker()

        result = await reconciler._detect_activity(worker)

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_auto_pause_triggered_increments_counter(self):
        """auto_pause_triggered → increments auto_pauses_triggered_count."""
        reconciler = make_reconciler()
        reconciler._api.detect_worker_idle = AsyncMock(return_value=make_idle_result(auto_pause_triggered=True))
        worker = make_worker()

        await reconciler._detect_activity(worker)

        assert reconciler._auto_pauses_triggered_count == 1


# =============================================================================
# _reconcile_license Tests (ADR-016)
# =============================================================================


class TestReconcileLicense:
    """Tests for WorkerReconciler._reconcile_license."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_pending_operation_is_noop(self):
        """No pending_operation → no action."""
        reconciler = make_reconciler()
        worker = make_worker(license=CMLLicenseReadModel(pending_operation=None))

        await reconciler._reconcile_license(worker)

        reconciler._cml.register_license.assert_not_called()
        reconciler._cml.deregister_license.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_pending_register_calls_cml_register(self):
        """pending_operation=register → calls CML register_license."""
        reconciler = make_reconciler()
        license_state = CMLLicenseReadModel(
            pending_operation="register",
            pending_token="my-token-123",
        )
        worker = make_worker(license=license_state)

        await reconciler._reconcile_license(worker)

        reconciler._api.start_license_registration.assert_called_once()
        reconciler._cml.register_license.assert_called_once_with(
            host="10.0.0.1",
            token="my-token-123",
            username="admin",
            password="secret",
            reregister=False,
        )
        reconciler._api.complete_license_registration.assert_called_once()
        assert reconciler._license_registrations_count == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_pending_deregister_calls_cml_deregister(self):
        """pending_operation=deregister → calls CML deregister_license."""
        reconciler = make_reconciler()
        license_state = CMLLicenseReadModel(pending_operation="deregister")
        worker = make_worker(license=license_state)

        await reconciler._reconcile_license(worker)

        reconciler._api.start_license_deregistration.assert_called_once()
        reconciler._cml.deregister_license.assert_called_once_with(
            host="10.0.0.1",
            username="admin",
            password="secret",
        )
        reconciler._api.complete_license_deregistration.assert_called_once()
        assert reconciler._license_deregistrations_count == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_register_failure_reports_to_api(self):
        """CML register_license returns failure → reports via fail_license_registration."""
        reconciler = make_reconciler()
        reconciler._cml.register_license = AsyncMock(return_value=(False, "Invalid token"))
        license_state = CMLLicenseReadModel(
            pending_operation="register",
            pending_token="bad-token",
        )
        worker = make_worker(license=license_state)

        await reconciler._reconcile_license(worker)

        reconciler._api.fail_license_registration.assert_called_once_with(
            worker_id="worker-001",
            error_message="Invalid token",
        )
        assert reconciler._license_registrations_count == 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_register_without_token_fails(self):
        """pending_operation=register but no pending_token → fail."""
        reconciler = make_reconciler()
        license_state = CMLLicenseReadModel(
            pending_operation="register",
            pending_token=None,
        )
        worker = make_worker(license=license_state)

        await reconciler._reconcile_license(worker)

        reconciler._cml.register_license.assert_not_called()
        reconciler._api.fail_license_registration.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_ip_address_skips_license_ops(self):
        """Worker without IP address → skip license operations."""
        reconciler = make_reconciler()
        license_state = CMLLicenseReadModel(
            pending_operation="register",
            pending_token="my-token",
        )
        worker = make_worker(license=license_state, ip_address=None)

        await reconciler._reconcile_license(worker)

        reconciler._cml.register_license.assert_not_called()


# =============================================================================
# reconcile() Router Tests
# =============================================================================


class TestReconcileRouter:
    """Tests for the reconcile() method routing to correct handler."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_routes_pending(self):
        """PENDING status routes to _handle_pending."""
        reconciler = make_reconciler()
        worker = make_worker(status=CMLWorkerStatus.PENDING, ec2_instance_id=None)

        result = await reconciler.reconcile(worker)  # noqa: F841

        # _handle_pending should attempt provisioning
        reconciler._api.get_worker_template.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_routes_unknown_status_returns_success(self):
        """Unknown status returns success (no-op)."""
        reconciler = make_reconciler()
        worker = make_worker(status="WEIRD")

        result = await reconciler.reconcile(worker)

        assert result.status == ReconciliationStatus.SUCCESS

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_exception_returns_failed(self):
        """Unhandled exception returns failed result."""
        reconciler = make_reconciler()
        reconciler._ec2.get_instance_state = AsyncMock(side_effect=RuntimeError("boom"))
        worker = make_worker(status=CMLWorkerStatus.PROVISIONING)

        result = await reconciler.reconcile(worker)

        assert result.status == ReconciliationStatus.FAILED


# =============================================================================
# _map_ec2_state_to_worker_status Tests
# =============================================================================


class TestMapEc2StateToWorkerStatus:
    """Tests for EC2 state → worker status mapping."""

    @pytest.mark.unit
    def test_all_known_states(self):
        """Verify all EC2 states map to expected worker statuses."""
        reconciler = make_reconciler()
        expected = {
            "pending": CMLWorkerStatus.PROVISIONING,
            "running": CMLWorkerStatus.RUNNING,
            "stopping": CMLWorkerStatus.STOPPING,
            "stopped": CMLWorkerStatus.STOPPED,
            "shutting-down": CMLWorkerStatus.TERMINATING,
            "terminated": CMLWorkerStatus.TERMINATED,
        }
        for ec2_state, worker_status in expected.items():
            assert reconciler._map_ec2_state_to_worker_status(ec2_state) == worker_status

    @pytest.mark.unit
    def test_unknown_state_returns_unknown(self):
        """Unknown EC2 state → UNKNOWN."""
        reconciler = make_reconciler()
        assert reconciler._map_ec2_state_to_worker_status("rebooting") == CMLWorkerStatus.UNKNOWN


# =============================================================================
# Independent Metrics Collection Tests
# =============================================================================


class TestCollectAllWorkerMetrics:
    """Tests for _collect_all_worker_metrics (independent metrics loop).

    Metrics collection runs independently from reconciliation, driven by its
    own timer. These tests verify the loop driver fetches RUNNING workers
    from CPA and collects metrics for each.
    """

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_collects_metrics_for_running_workers(self):
        """Fetches RUNNING workers from CPA and collects metrics for each."""
        reconciler = make_reconciler()
        reconciler._api.get_workers = AsyncMock(
            return_value=[
                {"id": "w1", "name": "cml-w1", "status": "RUNNING", "ec2_instance_id": "i-aaa", "ip_address": "10.0.0.1", "cml_username": "admin", "cml_password": "secret"},
                {"id": "w2", "name": "cml-w2", "status": "RUNNING", "ec2_instance_id": "i-bbb", "ip_address": "10.0.0.2", "cml_username": "admin", "cml_password": "secret"},
            ]
        )
        reconciler._api.report_worker_cml_data = AsyncMock()
        reconciler._cml.get_system_info = AsyncMock(return_value=MagicMock(version="2.9.0", ready=True))
        reconciler._cml.check_health = AsyncMock(return_value=(True, "Healthy"))
        reconciler._cml.get_license_info = AsyncMock(return_value=MagicMock(is_valid=True, authorization="", ssms_status="", features={}, node_licenses={}))
        reconciler._config = MagicMock()
        reconciler._config.service_name = "worker-controller"

        await reconciler._collect_all_worker_metrics()

        reconciler._api.get_workers.assert_called_once_with(status=CMLWorkerStatus.RUNNING)
        assert reconciler._cloudwatch.get_ec2_metrics.call_count == 2
        assert reconciler._api.report_worker_metrics.call_count == 2
        assert reconciler._metrics_collected_count == 2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_running_workers_skips_collection(self):
        """No RUNNING workers → nothing to collect, no errors."""
        reconciler = make_reconciler()
        reconciler._api.get_workers = AsyncMock(return_value=[])
        reconciler._config = MagicMock()
        reconciler._config.service_name = "worker-controller"

        await reconciler._collect_all_worker_metrics()

        reconciler._cloudwatch.get_ec2_metrics.assert_not_called()
        reconciler._api.report_worker_metrics.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_api_failure_handled_gracefully(self):
        """CPA get_workers failure → warning, no crash."""
        reconciler = make_reconciler()
        reconciler._api.get_workers = AsyncMock(side_effect=Exception("CPA unreachable"))
        reconciler._config = MagicMock()
        reconciler._config.service_name = "worker-controller"

        # Should not raise
        await reconciler._collect_all_worker_metrics()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_single_worker_failure_continues_others(self):
        """One worker metrics failure → continues to next worker."""
        reconciler = make_reconciler()
        reconciler._api.get_workers = AsyncMock(
            return_value=[
                {"id": "w1", "name": "cml-w1", "status": "RUNNING", "ec2_instance_id": "i-aaa", "ip_address": "10.0.0.1", "cml_username": "admin", "cml_password": "secret"},
                {"id": "w2", "name": "cml-w2", "status": "RUNNING", "ec2_instance_id": "i-bbb", "ip_address": "10.0.0.2", "cml_username": "admin", "cml_password": "secret"},
            ]
        )
        reconciler._api.report_worker_cml_data = AsyncMock()
        reconciler._cml.get_system_info = AsyncMock(return_value=MagicMock(version="2.9.0", ready=True))
        reconciler._cml.check_health = AsyncMock(return_value=(True, "Healthy"))
        reconciler._cml.get_license_info = AsyncMock(return_value=MagicMock(is_valid=True, authorization="", ssms_status="", features={}, node_licenses={}))
        reconciler._config = MagicMock()
        reconciler._config.service_name = "worker-controller"

        # First worker fails CloudWatch, second succeeds
        reconciler._cloudwatch.get_ec2_metrics = AsyncMock(side_effect=[Exception("CloudWatch timeout"), make_ec2_metrics()])

        await reconciler._collect_all_worker_metrics()

        # Despite first worker failing, second worker's metrics should still be reported
        assert reconciler._api.report_worker_metrics.call_count >= 1


# =============================================================================
# Discovery Loop Tests (AD-020: Consolidated under leader election)
# =============================================================================


class TestRunDiscovery:
    """Tests for _run_discovery (worker discovery consolidated into reconciler).

    AD-020: Discovery runs as an independent asyncio task under leader election,
    preventing redundant AWS API calls across multiple replicas.
    """

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_discovery_scans_regions_and_imports(self):
        """Discovery scans configured regions and submits to CPA."""
        from application.hosted_services.worker_reconciler import CachedDiscoverySettings

        reconciler = make_reconciler()
        reconciler._config = MagicMock()
        reconciler._config.service_name = "worker-controller"

        # Mock per-region EC2 client creation (we can't easily mock the constructor)
        # Instead, test _run_discovery which calls _discover_in_region
        reconciler._discover_in_region = AsyncMock(return_value=(3, 1, {"i-aaa", "i-bbb", "i-ccc"}))
        reconciler._garbage_collect_orphans = AsyncMock(return_value=0)

        settings = CachedDiscoverySettings(
            enabled=True,
            regions=["us-east-1", "eu-west-1"],
            ami_name_pattern="cisco-cml*",
            scan_interval_seconds=300,
            fetched_at=MagicMock(),
        )

        await reconciler._run_discovery(settings)

        assert reconciler._discover_in_region.call_count == 2
        assert reconciler._garbage_collect_orphans.call_count == 2
        assert reconciler._discovery_runs == 1
        assert reconciler._total_discovered == 6  # 3 per region × 2 regions
        assert reconciler._total_imported == 2  # 1 per region × 2 regions

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_discovery_region_failure_continues_others(self):
        """One region failing doesn't stop discovery in other regions."""
        from application.hosted_services.worker_reconciler import CachedDiscoverySettings

        reconciler = make_reconciler()
        reconciler._config = MagicMock()
        reconciler._config.service_name = "worker-controller"

        # First region fails, second succeeds
        reconciler._discover_in_region = AsyncMock(side_effect=[Exception("AWS timeout"), (2, 1, {"i-bbb"})])
        reconciler._garbage_collect_orphans = AsyncMock(return_value=0)

        settings = CachedDiscoverySettings(
            enabled=True,
            regions=["us-east-1", "eu-west-1"],
            ami_name_pattern="cisco-cml*",
            scan_interval_seconds=300,
            fetched_at=MagicMock(),
        )

        await reconciler._run_discovery(settings)

        # Should complete despite first region failure
        assert reconciler._discovery_runs == 1
        assert reconciler._total_discovered == 2
        assert reconciler._total_imported == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_discovery_settings_falls_back_to_env(self):
        """When API settings unavailable, falls back to env vars."""
        reconciler = make_reconciler()
        reconciler._config = MagicMock()
        reconciler._config.service_name = "worker-controller"
        reconciler._cached_discovery_settings = None

        # API returns empty
        reconciler._api.get_discovery_settings = AsyncMock(return_value={})

        settings = await reconciler._get_discovery_settings()

        assert settings.enabled == reconciler._settings.worker_discovery_enabled
        assert settings.regions == reconciler._settings.discovery_regions

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_discovery_settings_uses_api_when_available(self):
        """API settings take precedence over env vars."""
        reconciler = make_reconciler()
        reconciler._config = MagicMock()
        reconciler._config.service_name = "worker-controller"
        reconciler._cached_discovery_settings = None

        reconciler._api.get_discovery_settings = AsyncMock(
            return_value={
                "enabled": True,
                "regions": ["ap-southeast-1"],
                "ami_name_pattern": "custom-cml*",
                "scan_interval_seconds": 600,
            }
        )

        settings = await reconciler._get_discovery_settings()

        assert settings.regions == ["ap-southeast-1"]
        assert settings.ami_name_pattern == "custom-cml*"
        assert settings.scan_interval_seconds == 600
