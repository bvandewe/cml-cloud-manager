"""Business and technical metrics for Lablet Cloud Manager.

This module defines comprehensive OpenTelemetry metrics for monitoring
the LCM system, including:
- Business metrics: lablet instances, workers, scheduling decisions
- Technical metrics: API latencies, instantiation durations
- Operational metrics: resource utilization, background job performance

Sub-modules:
- tracing: Distributed tracing utilities
- logging: Structured logging configuration
"""

from opentelemetry import metrics

# Re-export logging utilities
from .logging import (
    JsonFormatter,
    StructuredLogger,
    clear_context,
    configure_structured_logging,
    get_correlation_id,
    get_logger,
    set_correlation_id,
    set_user_context,
)

# Re-export tracing utilities
from .tracing import (
    add_instance_context,
    add_scheduling_context,
    add_span_attributes,
    add_span_event,
    add_worker_context,
    get_current_span,
    get_lcm_tracer,
    get_tracer,
    record_exception,
    trace_assessment,
    trace_async,
    trace_cloud_event,
    trace_etcd_operation,
    trace_instantiation,
    trace_operation,
    trace_scheduling,
    trace_sync,
    trace_worker_operation,
)

# Get the meter for LCM metrics
meter = metrics.get_meter("lablet-cloud-manager", "1.0.0")

# =============================================================================
# Business Metrics - Lablet Sessions
# =============================================================================

# Counter: Total lablet sessions created (by definition and final state)
lablet_sessions_total = meter.create_counter(
    name="lcm_lablet_sessions_total",
    description="Total LabletSessions created",
    unit="1",
)

# Gauge: Currently active lablet sessions (by state and worker)
lablet_sessions_active = meter.create_up_down_counter(
    name="lcm_lablet_sessions_active",
    description="Currently active LabletSessions",
    unit="1",
)

# Histogram: Lablet session instantiation duration (from PENDING to RUNNING)
instantiation_duration = meter.create_histogram(
    name="lcm_instantiation_duration_seconds",
    description="LabletSession instantiation duration",
    unit="s",
)

# Counter: Session state transitions
instance_state_transitions = meter.create_counter(
    name="lcm_instance_state_transitions_total",
    description="Total state transitions for lablet sessions",
    unit="1",
)

# =============================================================================
# Business Metrics - Workers
# =============================================================================

# Counter: Total workers created (by template)
workers_total = meter.create_counter(
    name="lcm_workers_total",
    description="Total workers created",
    unit="1",
)

# Gauge: Currently active workers (by state and template)
workers_active = meter.create_up_down_counter(
    name="lcm_workers_active",
    description="Currently active workers",
    unit="1",
)

# Counter: Worker state transitions
worker_state_transitions = meter.create_counter(
    name="lcm_worker_state_transitions_total",
    description="Total state transitions for workers",
    unit="1",
)

# =============================================================================
# Business Metrics - Scheduling
# =============================================================================

# Counter: Scheduling decisions made (by action type)
scheduling_decisions = meter.create_counter(
    name="lcm_scheduling_decisions_total",
    description="Scheduling decisions made",
    unit="1",
)

# Counter: Scaling actions taken (by action type and template)
scaling_actions = meter.create_counter(
    name="lcm_scaling_actions_total",
    description="Scaling actions taken",
    unit="1",
)

# Histogram: Scheduling loop duration
scheduler_loop_duration = meter.create_histogram(
    name="lcm_scheduler_loop_duration_seconds",
    description="Scheduler loop execution duration",
    unit="s",
)

# =============================================================================
# Business Metrics - Assessment
# =============================================================================

# Counter: Assessment collections started
collections_started = meter.create_counter(
    name="lcm_collections_started_total",
    description="Total assessment collections started",
    unit="1",
)

# Counter: Assessment gradings completed
gradings_completed = meter.create_counter(
    name="lcm_gradings_completed_total",
    description="Total assessment gradings completed",
    unit="1",
)

# Histogram: Collection duration (from start to completion)
collection_duration = meter.create_histogram(
    name="lcm_collection_duration_seconds",
    description="Assessment collection duration",
    unit="s",
)

# Histogram: Grading duration
grading_duration = meter.create_histogram(
    name="lcm_grading_duration_seconds",
    description="Assessment grading duration",
    unit="s",
)

# =============================================================================
# Technical Metrics - API
# =============================================================================

# Histogram: API request duration (by method, endpoint, status)
api_request_duration = meter.create_histogram(
    name="lcm_api_request_duration_seconds",
    description="API request duration",
    unit="s",
)

# Counter: API errors (by endpoint and error type)
api_errors = meter.create_counter(
    name="lcm_api_errors_total",
    description="Total API errors",
    unit="1",
)

# =============================================================================
# Technical Metrics - Background Jobs
# =============================================================================

# Counter: Background jobs executed (by job type)
background_jobs_executed = meter.create_counter(
    name="lcm_background_jobs_executed_total",
    description="Total background jobs executed",
    unit="1",
)

# Counter: Background jobs failed (by job type)
background_jobs_failed = meter.create_counter(
    name="lcm_background_jobs_failed_total",
    description="Total background jobs failed",
    unit="1",
)

# Histogram: Background job duration (by job type)
background_job_duration = meter.create_histogram(
    name="lcm_background_job_duration_seconds",
    description="Background job execution duration",
    unit="s",
)

# =============================================================================
# Technical Metrics - etcd
# =============================================================================

# Counter: etcd operations (by operation type)
etcd_operations = meter.create_counter(
    name="lcm_etcd_operations_total",
    description="Total etcd operations",
    unit="1",
)

# Histogram: etcd operation latency
etcd_operation_latency = meter.create_histogram(
    name="lcm_etcd_operation_latency_seconds",
    description="etcd operation latency",
    unit="s",
)

# =============================================================================
# Technical Metrics - CloudEvents
# =============================================================================

# Counter: CloudEvents published (by event type)
cloud_events_published = meter.create_counter(
    name="lcm_cloud_events_published_total",
    description="Total CloudEvents published",
    unit="1",
)

# Counter: CloudEvents consumed (by event type)
cloud_events_consumed = meter.create_counter(
    name="lcm_cloud_events_consumed_total",
    description="Total CloudEvents consumed",
    unit="1",
)

# Counter: CloudEvents failed (by event type)
cloud_events_failed = meter.create_counter(
    name="lcm_cloud_events_failed_total",
    description="Total CloudEvents that failed processing",
    unit="1",
)

# =============================================================================
# Operational Metrics - Resource Utilization
# =============================================================================

# Gauge: Worker resource utilization (CPU, memory, disk)
# These are observable gauges that can be updated by callbacks


def create_worker_resource_gauges():
    """Create observable gauges for worker resource utilization."""
    # Note: These would be populated by a callback function
    # that fetches current worker resource data
    pass


# =============================================================================
# Helper Functions for Recording Metrics
# =============================================================================


def record_instance_created(definition_id: str, instance_id: str):
    """Record that a new lablet session was created."""
    lablet_sessions_total.add(1, {"definition_id": definition_id})
    lablet_sessions_active.add(1, {"state": "pending", "worker_id": "unassigned"})


def record_instance_state_change(instance_id: str, from_state: str, to_state: str, worker_id: str = ""):
    """Record a lablet session state transition."""
    instance_state_transitions.add(1, {"from_state": from_state, "to_state": to_state})
    # Update active gauge
    lablet_sessions_active.add(-1, {"state": from_state, "worker_id": worker_id})
    lablet_sessions_active.add(1, {"state": to_state, "worker_id": worker_id})


def record_instance_terminated(definition_id: str, final_state: str, worker_id: str):
    """Record that a lablet session was terminated."""
    lablet_sessions_active.add(-1, {"state": final_state, "worker_id": worker_id})


def record_instantiation_duration(definition_id: str, duration_seconds: float):
    """Record the duration of instance instantiation."""
    instantiation_duration.record(duration_seconds, {"definition_id": definition_id})


def record_worker_created(template_id: str, worker_id: str):
    """Record that a new worker was created."""
    workers_total.add(1, {"template": template_id})
    workers_active.add(1, {"state": "provisioning", "template": template_id})


def record_worker_state_change(worker_id: str, from_state: str, to_state: str, template_id: str = ""):
    """Record a worker state transition."""
    worker_state_transitions.add(1, {"from_state": from_state, "to_state": to_state})
    workers_active.add(-1, {"state": from_state, "template": template_id})
    workers_active.add(1, {"state": to_state, "template": template_id})


def record_worker_terminated(worker_id: str, template_id: str, final_state: str):
    """Record that a worker was terminated."""
    workers_active.add(-1, {"state": final_state, "template": template_id})


def record_scheduling_decision(action: str, definition_id: str = "", worker_id: str = ""):
    """Record a scheduling decision."""
    scheduling_decisions.add(1, {"action": action, "definition_id": definition_id})


def record_scaling_action(action: str, template_id: str, worker_id: str = ""):
    """Record a scaling action."""
    scaling_actions.add(1, {"action": action, "template": template_id})


def record_collection_started(instance_id: str, definition_id: str):
    """Record that collection was started for an instance."""
    collections_started.add(1, {"definition_id": definition_id})


def record_grading_completed(instance_id: str, definition_id: str, passed: bool):
    """Record that grading was completed for an instance."""
    gradings_completed.add(1, {"definition_id": definition_id, "result": "passed" if passed else "failed"})


def record_api_request(method: str, endpoint: str, status_code: int, duration_seconds: float):
    """Record an API request."""
    api_request_duration.record(duration_seconds, {"method": method, "endpoint": endpoint, "status": str(status_code)})
    if status_code >= 400:
        api_errors.add(1, {"endpoint": endpoint, "status": str(status_code)})


def record_background_job(job_type: str, duration_seconds: float, success: bool):
    """Record a background job execution."""
    background_jobs_executed.add(1, {"job_type": job_type})
    background_job_duration.record(duration_seconds, {"job_type": job_type})
    if not success:
        background_jobs_failed.add(1, {"job_type": job_type})


def record_cloud_event_published(event_type: str):
    """Record a CloudEvent that was published."""
    cloud_events_published.add(1, {"event_type": event_type})


def record_cloud_event_consumed(event_type: str):
    """Record a CloudEvent that was consumed."""
    cloud_events_consumed.add(1, {"event_type": event_type})


def record_cloud_event_failed(event_type: str, error: str = ""):
    """Record a CloudEvent that failed processing."""
    cloud_events_failed.add(1, {"event_type": event_type})


# =============================================================================
# Scaling Audit Metrics (Phase 3 - Auto-Scaling)
# =============================================================================

# Counter: Scaling events by action type (scale_up, drain, scale_down_initiated)
scaling_events_total = meter.create_counter(
    name="lcm_scaling_events_total",
    description="Total scaling lifecycle events",
    unit="1",
)


def record_scaling_event(
    action: str,
    worker_id: str = "",
    template: str = "",
    reason: str = "",
    requested_by: str = "",
    success: bool = True,
) -> None:
    """Record a scaling lifecycle event.

    Args:
        action: Scaling action type (scale_up_accepted, scale_up_rejected,
                drain_accepted, drain_rejected).
        worker_id: ID of the affected worker.
        template: Worker template name (for scale-up events).
        reason: Human-readable reason for the action.
        requested_by: System or user that requested the action.
        success: Whether the action succeeded.
    """
    scaling_events_total.add(
        1,
        {
            "action": action,
            "template": template,
            "requested_by": requested_by,
            "success": str(success).lower(),
        },
    )
