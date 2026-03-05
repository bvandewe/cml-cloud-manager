"""Scheduling metrics for Resource Scheduler service.

OpenTelemetry metrics for monitoring scheduling decisions,
placement performance, capacity utilization, and scale-up events.

Metric naming convention: lcm_scheduler_* prefix for all scheduler metrics.
"""

import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry import metrics

logger = logging.getLogger(__name__)

# Get the meter for scheduling metrics
meter = metrics.get_meter("resource-scheduler", "1.0.0")


# =============================================================================
# Scheduling Decision Metrics
# =============================================================================

# Counter: Scheduling decisions by action (assign, scale_up, wait)
scheduling_decisions_total = meter.create_counter(
    name="lcm_scheduler_decisions_total",
    description="Total scheduling decisions made by the placement engine",
    unit="1",
)

# Counter: Scheduling successes (instance successfully assigned to worker)
scheduling_successes_total = meter.create_counter(
    name="lcm_scheduler_successes_total",
    description="Total successful instance-to-worker assignments",
    unit="1",
)

# Counter: Scheduling failures (assignment or API call failed)
scheduling_failures_total = meter.create_counter(
    name="lcm_scheduler_failures_total",
    description="Total failed scheduling attempts",
    unit="1",
)

# Histogram: Scheduling latency (time to make a placement decision)
scheduling_latency = meter.create_histogram(
    name="lcm_scheduler_decision_duration_seconds",
    description="Duration of placement decision (PlacementEngine.schedule)",
    unit="s",
)

# Histogram: End-to-end scheduling duration (decision + execution)
scheduling_e2e_duration = meter.create_histogram(
    name="lcm_scheduler_e2e_duration_seconds",
    description="End-to-end duration from reconcile start to completion",
    unit="s",
)


# =============================================================================
# Capacity Metrics
# =============================================================================

# Counter: etcd capacity fetches (success/failure)
etcd_capacity_fetches_total = meter.create_counter(
    name="lcm_scheduler_etcd_capacity_fetches_total",
    description="Total etcd capacity data fetch attempts",
    unit="1",
)

# Gauge: Workers with etcd capacity data available
etcd_capacity_workers = meter.create_up_down_counter(
    name="lcm_scheduler_etcd_capacity_workers",
    description="Number of workers with real-time etcd capacity data",
    unit="1",
)


# =============================================================================
# Scale-Up Metrics
# =============================================================================

# Counter: Scale-up requests emitted
scale_up_requests_total = meter.create_counter(
    name="lcm_scheduler_scale_up_requests_total",
    description="Total scale-up requests submitted",
    unit="1",
)


# =============================================================================
# Retry Metrics
# =============================================================================

# Counter: Scheduling retries (per-instance requeues due to failure)
scheduling_retries_total = meter.create_counter(
    name="lcm_scheduler_retries_total",
    description="Total scheduling retry attempts",
    unit="1",
)

# Counter: Max retries reached (escalation events)
scheduling_max_retries_total = meter.create_counter(
    name="lcm_scheduler_max_retries_total",
    description="Total instances that hit max retry limit",
    unit="1",
)


# =============================================================================
# Helper Functions
# =============================================================================


def record_scheduling_decision(action: str, reason: str = "") -> None:
    """Record a scheduling decision metric.

    Args:
        action: Decision action (assign, scale_up, wait).
        reason: Human-readable reason for the decision.
    """
    scheduling_decisions_total.add(1, {"action": action})


def record_scheduling_success(worker_id: str) -> None:
    """Record a successful scheduling assignment.

    Args:
        worker_id: The worker the instance was assigned to.
    """
    scheduling_successes_total.add(1, {"worker_id": worker_id})


def record_scheduling_failure(reason: str = "") -> None:
    """Record a scheduling failure.

    Args:
        reason: Failure reason category.
    """
    scheduling_failures_total.add(1, {"reason": reason})


def record_scale_up_request(template: str) -> None:
    """Record a scale-up request.

    Args:
        template: Worker template requested for scale-up.
    """
    scale_up_requests_total.add(1, {"template": template})


def record_scale_up_decision(template: str, reason: str, instance_id: str = "") -> None:
    """Record a scale-up decision with audit context.

    Phase 3 - Auto-Scaling: Enhanced audit for scale-up decisions
    made by the placement engine.

    Args:
        template: Worker template selected.
        reason: Reason for the scale-up decision.
        instance_id: Lablet instance that triggered the decision.
    """
    scheduling_decisions_total.add(1, {"action": "scale_up"})
    scale_up_requests_total.add(1, {"template": template})


def record_scheduling_retry(instance_id: str, retry_count: int) -> None:
    """Record a scheduling retry.

    Args:
        instance_id: Instance being retried.
        retry_count: Current retry attempt number.
    """
    scheduling_retries_total.add(1)
    if retry_count >= 5:  # Max retries threshold
        scheduling_max_retries_total.add(1)


def record_etcd_capacity_fetch(success: bool, worker_count: int = 0) -> None:
    """Record an etcd capacity fetch attempt.

    Args:
        success: Whether the fetch succeeded.
        worker_count: Number of workers with capacity data (on success).
    """
    etcd_capacity_fetches_total.add(1, {"status": "success" if success else "failure"})


@contextmanager
def measure_scheduling_latency() -> Generator[dict[str, Any], None, None]:
    """Context manager to measure scheduling decision latency.

    Usage:
        with measure_scheduling_latency() as ctx:
            decision = placement_engine.schedule(...)
            ctx["action"] = decision.action

    Yields:
        Dict for caller to annotate with action type.
    """
    ctx: dict[str, Any] = {"action": "unknown"}
    start = time.monotonic()
    try:
        yield ctx
    finally:
        duration = time.monotonic() - start
        scheduling_latency.record(duration, {"action": ctx.get("action", "unknown")})


@contextmanager
def measure_e2e_scheduling() -> Generator[dict[str, Any], None, None]:
    """Context manager to measure end-to-end scheduling duration.

    Usage:
        with measure_e2e_scheduling() as ctx:
            result = await reconcile(instance)
            ctx["status"] = result.status.value

    Yields:
        Dict for caller to annotate with result status.
    """
    ctx: dict[str, Any] = {"status": "unknown"}
    start = time.monotonic()
    try:
        yield ctx
    finally:
        duration = time.monotonic() - start
        scheduling_e2e_duration.record(duration, {"status": ctx.get("status", "unknown")})


__all__ = [
    # Metric instruments
    "scheduling_decisions_total",
    "scheduling_successes_total",
    "scheduling_failures_total",
    "scheduling_latency",
    "scheduling_e2e_duration",
    "etcd_capacity_fetches_total",
    "etcd_capacity_workers",
    "scale_up_requests_total",
    "scheduling_retries_total",
    "scheduling_max_retries_total",
    # Helper functions
    "record_scheduling_decision",
    "record_scheduling_success",
    "record_scheduling_failure",
    "record_scale_up_request",
    "record_scale_up_decision",
    "record_scheduling_retry",
    "record_etcd_capacity_fetch",
    "measure_scheduling_latency",
    "measure_e2e_scheduling",
]
