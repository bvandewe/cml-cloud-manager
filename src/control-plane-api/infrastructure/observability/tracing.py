"""Tracing utilities for Lablet Cloud Manager.

This module provides application-specific tracing utilities that build on
the Neuroglia framework's observability tracing module.
"""

from contextlib import contextmanager
from typing import Any

from neuroglia.observability.tracing import (
    add_span_attributes,
    add_span_event,
    get_current_span,
    get_tracer,
    record_exception,
    trace_async,
    trace_sync,
)
from opentelemetry import trace
from opentelemetry.trace import SpanKind

# Default tracer for LCM
_lcm_tracer = None


def get_lcm_tracer(module_name: str = "lablet-cloud-manager") -> trace.Tracer:
    """Get the default tracer for LCM services.

    Args:
        module_name: Name of the module for the tracer (used for span identification)

    Returns:
        OpenTelemetry tracer instance
    """
    return get_tracer(module_name, "1.0.0")


@contextmanager
def trace_operation(
    name: str,
    attributes: dict[str, Any] | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
):
    """Context manager for tracing operations.

    Args:
        name: Name of the span
        attributes: Optional attributes to add to the span
        kind: Kind of span (INTERNAL, SERVER, CLIENT, etc.)

    Example:
        >>> with trace_operation("schedule_instance", {"instance_id": "abc123"}):
        ...     # Your code here
        ...     pass
    """
    tracer = get_lcm_tracer()
    with tracer.start_as_current_span(name, kind=kind) as span:
        if attributes:
            add_span_attributes(attributes, span)
        try:
            yield span
        except Exception as ex:
            record_exception(ex, span=span)
            raise


@contextmanager
def trace_scheduling(instance_id: str, definition_id: str):
    """Context manager for tracing scheduling operations.

    Args:
        instance_id: ID of the lablet instance being scheduled
        definition_id: ID of the lablet definition

    Example:
        >>> with trace_scheduling("inst-123", "def-456"):
        ...     # Scheduling logic here
        ...     pass
    """
    with trace_operation(
        "lcm.scheduling.schedule_instance",
        attributes={
            "lcm.instance.id": instance_id,
            "lcm.definition.id": definition_id,
            "lcm.operation": "schedule",
        },
    ) as span:
        yield span


@contextmanager
def trace_instantiation(instance_id: str, worker_id: str, definition_id: str):
    """Context manager for tracing instantiation operations.

    Args:
        instance_id: ID of the lablet instance being instantiated
        worker_id: ID of the target worker
        definition_id: ID of the lablet definition

    Example:
        >>> with trace_instantiation("inst-123", "worker-456", "def-789"):
        ...     # Instantiation logic here
        ...     pass
    """
    with trace_operation(
        "lcm.instantiation.instantiate_lab",
        attributes={
            "lcm.instance.id": instance_id,
            "lcm.worker.id": worker_id,
            "lcm.definition.id": definition_id,
            "lcm.operation": "instantiate",
        },
        kind=SpanKind.CLIENT,
    ) as span:
        yield span


@contextmanager
def trace_worker_operation(
    worker_id: str,
    operation: str,
    attributes: dict[str, Any] | None = None,
):
    """Context manager for tracing worker operations.

    Args:
        worker_id: ID of the worker
        operation: Name of the operation (e.g., "start", "stop", "terminate")
        attributes: Additional attributes

    Example:
        >>> with trace_worker_operation("worker-123", "start"):
        ...     await ec2_client.start_instance(worker_id)
    """
    all_attributes = {
        "lcm.worker.id": worker_id,
        "lcm.operation": operation,
    }
    if attributes:
        all_attributes.update(attributes)

    with trace_operation(
        f"lcm.worker.{operation}",
        attributes=all_attributes,
        kind=SpanKind.CLIENT,
    ) as span:
        yield span


@contextmanager
def trace_assessment(
    instance_id: str,
    phase: str,
    definition_id: str = "",
):
    """Context manager for tracing assessment operations.

    Args:
        instance_id: ID of the lablet instance
        phase: Assessment phase (e.g., "collection", "grading")
        definition_id: ID of the lablet definition

    Example:
        >>> with trace_assessment("inst-123", "collection", "def-456"):
        ...     await collect_artifacts(instance_id)
    """
    with trace_operation(
        f"lcm.assessment.{phase}",
        attributes={
            "lcm.instance.id": instance_id,
            "lcm.definition.id": definition_id,
            "lcm.assessment.phase": phase,
            "lcm.operation": "assessment",
        },
    ) as span:
        yield span


@contextmanager
def trace_cloud_event(event_type: str, event_id: str = "", source: str = ""):
    """Context manager for tracing CloudEvent processing.

    Args:
        event_type: Type of the CloudEvent
        event_id: ID of the CloudEvent
        source: Source of the CloudEvent

    Example:
        >>> with trace_cloud_event("lablet.instance.created", "evt-123"):
        ...     await handle_event(event)
    """
    attributes = {
        "cloudevent.type": event_type,
        "lcm.operation": "cloud_event",
    }
    if event_id:
        attributes["cloudevent.id"] = event_id
    if source:
        attributes["cloudevent.source"] = source

    with trace_operation(
        f"lcm.cloudevent.{event_type.split('.')[-1]}",
        attributes=attributes,
    ) as span:
        yield span


@contextmanager
def trace_etcd_operation(operation: str, key: str = "", success: bool = True):
    """Context manager for tracing etcd operations.

    Args:
        operation: Type of etcd operation (e.g., "get", "put", "delete", "watch")
        key: The etcd key being accessed
        success: Whether the operation was successful

    Example:
        >>> with trace_etcd_operation("put", "/lcm/instances/123/state"):
        ...     await etcd.put(key, value)
    """
    attributes = {
        "db.system": "etcd",
        "db.operation": operation,
        "lcm.operation": "etcd",
    }
    if key:
        attributes["db.key"] = key

    with trace_operation(
        f"etcd.{operation}",
        attributes=attributes,
        kind=SpanKind.CLIENT,
    ) as span:
        yield span


def add_instance_context(
    instance_id: str,
    definition_id: str = "",
    worker_id: str = "",
    state: str = "",
):
    """Add lablet instance context to the current span.

    Args:
        instance_id: ID of the lablet instance
        definition_id: ID of the lablet definition
        worker_id: ID of the assigned worker
        state: Current state of the instance
    """
    attributes = {"lcm.instance.id": instance_id}
    if definition_id:
        attributes["lcm.definition.id"] = definition_id
    if worker_id:
        attributes["lcm.worker.id"] = worker_id
    if state:
        attributes["lcm.instance.state"] = state
    add_span_attributes(attributes)


def add_worker_context(
    worker_id: str,
    template_id: str = "",
    state: str = "",
    instance_id: str = "",
):
    """Add worker context to the current span.

    Args:
        worker_id: ID of the worker
        template_id: ID of the worker template
        state: Current state of the worker
        instance_id: EC2 instance ID if applicable
    """
    attributes = {"lcm.worker.id": worker_id}
    if template_id:
        attributes["lcm.worker.template":template_id]
    if state:
        attributes["lcm.worker.state"] = state
    if instance_id:
        attributes["aws.ec2.instance_id"] = instance_id
    add_span_attributes(attributes)


def add_scheduling_context(
    action: str,
    instance_id: str = "",
    worker_id: str = "",
    reason: str = "",
):
    """Add scheduling context to the current span.

    Args:
        action: Scheduling action taken (e.g., "assign", "scale_up", "wait")
        instance_id: ID of the instance being scheduled
        worker_id: ID of the assigned worker
        reason: Reason for the scheduling decision
    """
    attributes = {"lcm.scheduling.action": action}
    if instance_id:
        attributes["lcm.instance.id"] = instance_id
    if worker_id:
        attributes["lcm.worker.id"] = worker_id
    if reason:
        attributes["lcm.scheduling.reason"] = reason
    add_span_attributes(attributes)


# Re-export framework tracing utilities for convenience
__all__ = [
    # Framework utilities
    "get_tracer",
    "get_current_span",
    "add_span_attributes",
    "add_span_event",
    "record_exception",
    "trace_async",
    "trace_sync",
    # LCM-specific utilities
    "get_lcm_tracer",
    "trace_operation",
    "trace_scheduling",
    "trace_instantiation",
    "trace_worker_operation",
    "trace_assessment",
    "trace_cloud_event",
    "trace_etcd_operation",
    "add_instance_context",
    "add_worker_context",
    "add_scheduling_context",
]
