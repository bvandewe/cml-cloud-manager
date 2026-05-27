"""Worker Controller observability metrics.

OpenTelemetry metrics for monitoring worker provisioning,
scale-down decisions, and reconciliation lifecycle.

Metric naming convention: lcm_worker_controller_* prefix.
"""

import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry import metrics

logger = logging.getLogger(__name__)

# Get the meter for worker-controller metrics
meter = metrics.get_meter("worker-controller", "1.0.0")


# =============================================================================
# Scaling Lifecycle Metrics
# =============================================================================

# Counter: Scaling events by action and outcome
scaling_events_total = meter.create_counter(
    name="lcm_worker_controller_scaling_events_total",
    description="Total scaling lifecycle events in worker-controller",
    unit="1",
)

# Histogram: EC2 provisioning duration (PENDING → RUNNING transition)
provisioning_duration = meter.create_histogram(
    name="lcm_worker_controller_provisioning_duration_seconds",
    description="Duration of EC2 instance provisioning",
    unit="s",
)

# Counter: Scale-down evaluations (how often we check)
scale_down_evaluations_total = meter.create_counter(
    name="lcm_worker_controller_scale_down_evaluations_total",
    description="Total scale-down evaluations performed",
    unit="1",
)

# Counter: Scale-down drains initiated
scale_down_drains_total = meter.create_counter(
    name="lcm_worker_controller_scale_down_drains_total",
    description="Total scale-down drain requests initiated",
    unit="1",
)

# Counter: Scale-down skipped (by reason)
scale_down_skipped_total = meter.create_counter(
    name="lcm_worker_controller_scale_down_skipped_total",
    description="Total scale-down evaluations skipped",
    unit="1",
)


# =============================================================================
# WebSocket Monitoring Metrics (ADR-041)
# =============================================================================

# Gauge: Active WebSocket connections to CML workers
ws_connections_active = meter.create_up_down_counter(
    name="lcm_worker_controller_ws_connections_active",
    description="Number of active WebSocket connections to CML workers",
    unit="1",
)

# Counter: Total WebSocket messages received
ws_messages_total = meter.create_counter(
    name="lcm_worker_controller_ws_messages_total",
    description="Total WebSocket messages received from CML workers",
    unit="1",
)

# Counter: WebSocket reconnection attempts
ws_reconnections_total = meter.create_counter(
    name="lcm_worker_controller_ws_reconnections_total",
    description="Total WebSocket reconnection attempts",
    unit="1",
)

# Histogram: Message processing latency (receipt to callback completion)
ws_message_latency_seconds = meter.create_histogram(
    name="lcm_worker_controller_ws_message_latency_seconds",
    description="Time from WS message receipt to callback completion",
    unit="s",
)


# =============================================================================
# Reconciliation Metrics
# =============================================================================

# Counter: Reconciliation cycles by status handled
reconciliation_cycles_total = meter.create_counter(
    name="lcm_worker_controller_reconciliation_total",
    description="Total reconciliation cycles by worker status",
    unit="1",
)

# Histogram: Reconciliation cycle duration
reconciliation_duration = meter.create_histogram(
    name="lcm_worker_controller_reconciliation_duration_seconds",
    description="Duration of a single worker reconciliation cycle",
    unit="s",
)


# =============================================================================
# Helper Functions
# =============================================================================


def record_scaling_event(
    action: str,
    worker_id: str = "",
    template: str = "",
    reason: str = "",
    success: bool = True,
) -> None:
    """Record a scaling lifecycle event.

    Args:
        action: Event type (ec2_provisioned, scale_down_initiated,
                scale_down_skipped, ec2_provision_failed).
        worker_id: ID of the affected worker.
        template: Worker template name.
        reason: Human-readable reason.
        success: Whether the action succeeded.
    """
    scaling_events_total.add(
        1,
        {
            "action": action,
            "success": str(success).lower(),
        },
    )


def record_scale_down_evaluation(
    worker_id: str,
    result: str,
    idle_minutes: float = 0,
    running_count: int = 0,
    min_workers: int = 0,
) -> None:
    """Record a scale-down evaluation result.

    Args:
        worker_id: Worker being evaluated.
        result: Evaluation outcome (drained, skipped_auto_pause,
                skipped_not_idle, skipped_min_workers, skipped_cooldown).
        idle_minutes: How long the worker was idle.
        running_count: Current running worker count.
        min_workers: Minimum worker threshold.
    """
    scale_down_evaluations_total.add(1, {"result": result})

    if result == "drained":
        scale_down_drains_total.add(1, {"worker_id": worker_id})
    elif result.startswith("skipped"):
        scale_down_skipped_total.add(1, {"reason": result})


def record_provisioning_complete(
    worker_id: str,
    template: str,
    duration_seconds: float,
    success: bool = True,
) -> None:
    """Record EC2 provisioning completion.

    Args:
        worker_id: Worker that was provisioned.
        template: Worker template name.
        duration_seconds: How long provisioning took.
        success: Whether provisioning succeeded.
    """
    provisioning_duration.record(
        duration_seconds,
        {"template": template, "success": str(success).lower()},
    )
    record_scaling_event(
        action="ec2_provisioned" if success else "ec2_provision_failed",
        worker_id=worker_id,
        template=template,
        success=success,
    )


def record_reconciliation(status: str) -> None:
    """Record a reconciliation cycle for a worker status.

    Args:
        status: The worker status being reconciled (PENDING, RUNNING, etc.).
    """
    reconciliation_cycles_total.add(1, {"status": status})


@contextmanager
def measure_reconciliation(status: str) -> Generator[dict[str, Any], None, None]:
    """Context manager to measure reconciliation cycle duration.

    Usage:
        with measure_reconciliation("PENDING") as ctx:
            await self._handle_pending(worker)
            ctx["result"] = "success"

    Args:
        status: Worker status being reconciled.

    Yields:
        Dict for caller to annotate with result.
    """
    ctx: dict[str, Any] = {"result": "unknown"}
    start = time.monotonic()
    try:
        yield ctx
    finally:
        duration = time.monotonic() - start
        reconciliation_duration.record(
            duration,
            {"status": status, "result": ctx.get("result", "unknown")},
        )
        reconciliation_cycles_total.add(1, {"status": status})


# =============================================================================
# WebSocket Monitoring Helpers (ADR-041)
# =============================================================================


def record_ws_connection_opened(worker_id: str) -> None:
    """Record a WebSocket connection becoming active."""
    ws_connections_active.add(1, {"worker_id": worker_id})


def record_ws_connection_closed(worker_id: str) -> None:
    """Record a WebSocket connection being closed."""
    ws_connections_active.add(-1, {"worker_id": worker_id})


def record_ws_message(worker_id: str, event_type: str) -> None:
    """Record a WebSocket message received.

    Args:
        worker_id: Worker the message came from.
        event_type: CML event type (system_stats, lab_stats, state_change, lab_event).
    """
    ws_messages_total.add(1, {"worker_id": worker_id, "event_type": event_type})


def record_ws_reconnection(worker_id: str, reason: str) -> None:
    """Record a WebSocket reconnection attempt.

    Args:
        worker_id: Worker being reconnected.
        reason: Why reconnection was triggered.
    """
    ws_reconnections_total.add(1, {"worker_id": worker_id, "reason": reason})


def record_ws_message_latency(event_type: str, duration_seconds: float) -> None:
    """Record the processing latency for a WebSocket message.

    Args:
        event_type: CML event type.
        duration_seconds: Time from message receipt to callback completion.
    """
    ws_message_latency_seconds.record(duration_seconds, {"event_type": event_type})


__all__ = [
    # Metric instruments
    "scaling_events_total",
    "provisioning_duration",
    "scale_down_evaluations_total",
    "scale_down_drains_total",
    "scale_down_skipped_total",
    "reconciliation_cycles_total",
    "reconciliation_duration",
    "ws_connections_active",
    "ws_messages_total",
    "ws_reconnections_total",
    "ws_message_latency_seconds",
    # Helper functions
    "record_scaling_event",
    "record_scale_down_evaluation",
    "record_provisioning_complete",
    "record_reconciliation",
    "measure_reconciliation",
    "record_ws_connection_opened",
    "record_ws_connection_closed",
    "record_ws_message",
    "record_ws_reconnection",
    "record_ws_message_latency",
]
