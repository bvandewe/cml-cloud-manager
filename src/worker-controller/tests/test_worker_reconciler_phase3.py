"""Unit tests for WorkerReconciler Phase 3 - Scale-Down Evaluation.

Tests cover _evaluate_scale_down() safety guards:
1. Auto-pause already triggered → skip (avoid double-action)
2. Worker not idle → skip
3. Worker not eligible for pause → skip
4. Running count ≤ min_workers → skip
5. Scale-down cooldown active → skip
6. All checks pass → drain initiated
7. API drain failure → returns False

These tests validate the five safety guards that prevent
unnecessary or harmful scale-down operations.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from application.hosted_services.worker_reconciler import WorkerReconciler
from lcm_core.domain.entities import CMLWorkerReadModel

# =============================================================================
# Fixtures
# =============================================================================


def make_worker(worker_id: str = "worker-001", status: str = "running") -> CMLWorkerReadModel:
    """Create a CMLWorkerReadModel for testing."""
    return CMLWorkerReadModel(
        id=worker_id,
        name=f"cml-{worker_id}",
        status=status,
        desired_status="running",
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
    running_worker_count: int = 3,
    min_workers: int = 1,
    scale_down_cooldown_seconds: int = 600,
    last_scale_down_at: datetime | None = None,
) -> WorkerReconciler:
    """Create a WorkerReconciler with bypassed __init__ and mocked attributes.

    Uses object.__new__ to skip the complex __init__ (which requires
    etcd, AWS, CML clients, and leader election config).
    Only sets the attributes used by _evaluate_scale_down.
    """
    reconciler = object.__new__(WorkerReconciler)

    # Mock settings
    reconciler._settings = MagicMock()
    reconciler._settings.min_workers = min_workers
    reconciler._settings.scale_down_cooldown_seconds = scale_down_cooldown_seconds

    # Scale-down tracking
    reconciler._running_worker_count = running_worker_count
    reconciler._last_scale_down_at = last_scale_down_at
    reconciler._scale_down_count = 0

    # Mock API client for drain calls
    reconciler._api = MagicMock()
    reconciler._api.drain_worker = AsyncMock()

    return reconciler


# =============================================================================
# Scale-Down Safety Guard Tests
# =============================================================================


class TestEvaluateScaleDown:
    """Tests for WorkerReconciler._evaluate_scale_down."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_skips_when_auto_pause_triggered(self):
        """Guard 1: Skip scale-down if auto-pause already handled this worker."""
        # Arrange
        reconciler = make_reconciler(running_worker_count=5, min_workers=1)
        worker = make_worker()
        idle_result = make_idle_result(auto_pause_triggered=True)

        # Act
        result = await reconciler._evaluate_scale_down(worker, idle_result)

        # Assert
        assert result is False
        reconciler._api.drain_worker.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_skips_when_not_idle(self):
        """Guard 2: Skip scale-down if worker is not idle."""
        # Arrange
        reconciler = make_reconciler(running_worker_count=5, min_workers=1)
        worker = make_worker()
        idle_result = make_idle_result(is_idle=False)

        # Act
        result = await reconciler._evaluate_scale_down(worker, idle_result)

        # Assert
        assert result is False
        reconciler._api.drain_worker.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_skips_when_not_eligible_for_pause(self):
        """Guard 3: Skip scale-down if worker is not eligible for pause."""
        # Arrange
        reconciler = make_reconciler(running_worker_count=5, min_workers=1)
        worker = make_worker()
        idle_result = make_idle_result(eligible_for_pause=False)

        # Act
        result = await reconciler._evaluate_scale_down(worker, idle_result)

        # Assert
        assert result is False
        reconciler._api.drain_worker.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_skips_when_at_min_workers(self):
        """Guard 4: Skip scale-down when running count <= min_workers."""
        # Arrange — 2 running workers with min_workers=2
        reconciler = make_reconciler(running_worker_count=2, min_workers=2)
        worker = make_worker()
        idle_result = make_idle_result()

        # Act
        result = await reconciler._evaluate_scale_down(worker, idle_result)

        # Assert
        assert result is False
        reconciler._api.drain_worker.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_skips_when_below_min_workers(self):
        """Guard 4b: Skip scale-down when running count < min_workers."""
        # Arrange — 1 running worker with min_workers=2
        reconciler = make_reconciler(running_worker_count=1, min_workers=2)
        worker = make_worker()
        idle_result = make_idle_result()

        # Act
        result = await reconciler._evaluate_scale_down(worker, idle_result)

        # Assert
        assert result is False
        reconciler._api.drain_worker.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_skips_when_cooldown_active(self):
        """Guard 5: Skip scale-down when cooldown hasn't elapsed."""
        # Arrange — last scale-down was 60 seconds ago, cooldown is 600s
        recent_drain = datetime.now(timezone.utc) - timedelta(seconds=60)
        reconciler = make_reconciler(
            running_worker_count=5,
            min_workers=1,
            scale_down_cooldown_seconds=600,
            last_scale_down_at=recent_drain,
        )
        worker = make_worker()
        idle_result = make_idle_result()

        # Act
        result = await reconciler._evaluate_scale_down(worker, idle_result)

        # Assert
        assert result is False
        reconciler._api.drain_worker.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_allows_when_cooldown_expired(self):
        """Cooldown elapsed → drain should proceed."""
        # Arrange — last scale-down was 700 seconds ago, cooldown is 600s
        old_drain = datetime.now(timezone.utc) - timedelta(seconds=700)
        reconciler = make_reconciler(
            running_worker_count=5,
            min_workers=1,
            scale_down_cooldown_seconds=600,
            last_scale_down_at=old_drain,
        )
        worker = make_worker()
        idle_result = make_idle_result()

        # Act
        result = await reconciler._evaluate_scale_down(worker, idle_result)

        # Assert
        assert result is True
        reconciler._api.drain_worker.assert_called_once_with(
            worker_id="worker-001",
            reason="scale_down",
            requested_by="worker-controller",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_drain_success_all_checks_pass(self):
        """All guards pass → drain should be initiated."""
        # Arrange
        reconciler = make_reconciler(
            running_worker_count=3,
            min_workers=1,
            last_scale_down_at=None,  # No previous drain
        )
        worker = make_worker("worker-abc")
        idle_result = make_idle_result(idle_minutes=45.0)

        # Act
        result = await reconciler._evaluate_scale_down(worker, idle_result)

        # Assert
        assert result is True
        reconciler._api.drain_worker.assert_called_once_with(
            worker_id="worker-abc",
            reason="scale_down",
            requested_by="worker-controller",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_drain_updates_tracking_state(self):
        """After successful drain, tracking state is updated."""
        # Arrange
        reconciler = make_reconciler(
            running_worker_count=4,
            min_workers=1,
        )
        worker = make_worker()
        idle_result = make_idle_result()

        # Act
        await reconciler._evaluate_scale_down(worker, idle_result)

        # Assert
        assert reconciler._scale_down_count == 1
        assert reconciler._last_scale_down_at is not None
        # Running count decremented for subsequent cycle accuracy
        assert reconciler._running_worker_count == 3

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_drain_failure_returns_false(self):
        """API drain failure returns False without updating tracking."""
        # Arrange
        reconciler = make_reconciler(
            running_worker_count=3,
            min_workers=1,
        )
        reconciler._api.drain_worker = AsyncMock(side_effect=Exception("API error"))
        worker = make_worker()
        idle_result = make_idle_result()

        # Act
        result = await reconciler._evaluate_scale_down(worker, idle_result)

        # Assert
        assert result is False
        assert reconciler._scale_down_count == 0
        assert reconciler._last_scale_down_at is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_min_workers_zero_allows_scale_to_zero(self):
        """min_workers=0 allows draining even with only 1 running worker."""
        # Arrange
        reconciler = make_reconciler(
            running_worker_count=1,
            min_workers=0,
        )
        worker = make_worker()
        idle_result = make_idle_result()

        # Act
        result = await reconciler._evaluate_scale_down(worker, idle_result)

        # Assert
        assert result is True
        reconciler._api.drain_worker.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_multiple_drains_decrement_running_count(self):
        """Draining multiple workers in one cycle decrements running count each time."""
        # Arrange — set cooldown to 0 so sequential drains aren't blocked
        reconciler = make_reconciler(
            running_worker_count=4,
            min_workers=1,
            scale_down_cooldown_seconds=0,
        )
        idle_result = make_idle_result()

        # Act — drain 3 workers in sequence (simulating reconciliation cycle)
        r1 = await reconciler._evaluate_scale_down(make_worker("w-1"), idle_result)
        r2 = await reconciler._evaluate_scale_down(make_worker("w-2"), idle_result)
        r3 = await reconciler._evaluate_scale_down(make_worker("w-3"), idle_result)

        # Assert — first 3 drained, running count should be 1 (at min_workers)
        assert r1 is True
        assert r2 is True
        assert r3 is True
        assert reconciler._running_worker_count == 1
        assert reconciler._scale_down_count == 3

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_fourth_drain_blocked_by_min_workers(self):
        """After draining to min_workers, next drain is blocked."""
        # Arrange — set cooldown to 0 so sequential drains aren't blocked by cooldown
        reconciler = make_reconciler(
            running_worker_count=3,
            min_workers=2,
            scale_down_cooldown_seconds=0,
        )
        idle_result = make_idle_result()

        # Act — drain first worker succeeds
        r1 = await reconciler._evaluate_scale_down(make_worker("w-1"), idle_result)
        # Second drain blocked (2 running == min_workers)
        r2 = await reconciler._evaluate_scale_down(make_worker("w-2"), idle_result)

        # Assert
        assert r1 is True
        assert r2 is False
        assert reconciler._running_worker_count == 2
        assert reconciler._scale_down_count == 1
