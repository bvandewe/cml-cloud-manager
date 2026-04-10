"""Pipeline CloudEvents — granular per-step events for SSE reactivity.

Sprint G (G5): Emitted by UpdatePipelineProgressCommandHandler on step
status transitions. These complement the existing bulk
LabletSessionPipelineProgressUpdatedDomainEvent with fine-grained events
for per-step UI updates.

These are integration events (not domain events) because they are
produced for external consumption (SSE broadcast) rather than for
aggregate state mutation.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from neuroglia.eventing.cloud_events.decorators import cloudevent
from neuroglia.integration.models import IntegrationEvent


@cloudevent("pipeline.step.started.v1")
@dataclass
class PipelineStepStartedEventV1(IntegrationEvent[str]):
    """Event emitted when a pipeline step begins execution.

    Published by: UpdatePipelineProgressCommandHandler
    Consumed by: SSE relay → frontend pipeline progress panel

    Attributes:
        created_at: Event timestamp (inherited from IntegrationEvent).
        aggregate_id: LabletSession ID (used as CloudEvent subject).
        session_id: LabletSession ID (explicit for clarity).
        pipeline_name: Pipeline type (e.g. "instantiate").
        step_name: Name of the step that started.
        started_at: Timestamp when the step began.
    """

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    aggregate_id: str = ""
    session_id: str = ""
    pipeline_name: str = ""
    step_name: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@cloudevent("pipeline.step.completed.v1")
@dataclass
class PipelineStepCompletedEventV1(IntegrationEvent[str]):
    """Event emitted when a pipeline step finishes successfully.

    Published by: UpdatePipelineProgressCommandHandler
    Consumed by: SSE relay → frontend pipeline progress panel

    Attributes:
        created_at: Event timestamp (inherited from IntegrationEvent).
        aggregate_id: LabletSession ID.
        session_id: LabletSession ID.
        pipeline_name: Pipeline type.
        step_name: Name of the step that completed.
        result_data: Optional result payload from the step.
        completed_at: Timestamp when the step finished.
    """

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    aggregate_id: str = ""
    session_id: str = ""
    pipeline_name: str = ""
    step_name: str = ""
    result_data: dict[str, Any] = field(default_factory=dict)
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@cloudevent("pipeline.step.failed.v1")
@dataclass
class PipelineStepFailedEventV1(IntegrationEvent[str]):
    """Event emitted when a pipeline step fails.

    Published by: UpdatePipelineProgressCommandHandler
    Consumed by: SSE relay → frontend pipeline progress panel

    Attributes:
        created_at: Event timestamp (inherited from IntegrationEvent).
        aggregate_id: LabletSession ID.
        session_id: LabletSession ID.
        pipeline_name: Pipeline type.
        step_name: Name of the step that failed.
        error: Error message describing the failure.
        failed_at: Timestamp when the step failed.
    """

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    aggregate_id: str = ""
    session_id: str = ""
    pipeline_name: str = ""
    step_name: str = ""
    error: str = ""
    failed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@cloudevent("pipeline.completed.v1")
@dataclass
class PipelineCompletedEventV1(IntegrationEvent[str]):
    """Event emitted when all steps in a pipeline finish.

    Published by: UpdatePipelineProgressCommandHandler
    Consumed by: SSE relay → frontend pipeline progress panel

    Attributes:
        created_at: Event timestamp (inherited from IntegrationEvent).
        aggregate_id: LabletSession ID.
        session_id: LabletSession ID.
        pipeline_name: Pipeline type.
        status: Terminal status (completed, failed, partial).
        steps_completed: Count of completed steps.
        steps_failed: Count of failed steps.
        steps_skipped: Count of skipped steps.
        completed_at: Timestamp when the pipeline finished.
    """

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    aggregate_id: str = ""
    session_id: str = ""
    pipeline_name: str = ""
    status: str = "completed"
    steps_completed: int = 0
    steps_failed: int = 0
    steps_skipped: int = 0
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
