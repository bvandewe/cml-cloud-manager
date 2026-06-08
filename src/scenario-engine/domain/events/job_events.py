"""Job Domain Events — state transitions for automation jobs.

Uses Neuroglia DomainEvent base class with @cloudevent decorator for
CloudEvent-compatible event publication.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from neuroglia.data.abstractions import DomainEvent
from neuroglia.eventing.cloud_events.decorators import cloudevent


@cloudevent("scenario_engine.job.created.v1")
@dataclass
class JobCreatedDomainEvent(DomainEvent):
    """Raised when a new job is submitted."""

    aggregate_id: str
    scenario_name: str
    scenario_version: str
    input_data: dict[str, Any]
    callback_url: str | None
    pod_definition_id: str | None
    created_at: datetime
    metadata: dict[str, Any] | None

    def __init__(
        self,
        aggregate_id: str,
        scenario_name: str,
        scenario_version: str,
        input_data: dict[str, Any],
        callback_url: str | None = None,
        pod_definition_id: str | None = None,
        created_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.scenario_name = scenario_name
        self.scenario_version = scenario_version
        self.input_data = input_data
        self.callback_url = callback_url
        self.pod_definition_id = pod_definition_id
        self.created_at = created_at or datetime.now()
        self.metadata = metadata


@cloudevent("scenario_engine.job.started.v1")
@dataclass
class JobStartedDomainEvent(DomainEvent):
    """Raised when a job begins execution."""

    aggregate_id: str
    started_at: datetime

    def __init__(self, aggregate_id: str, started_at: datetime) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.started_at = started_at


@cloudevent("scenario_engine.job.completed.v1")
@dataclass
class JobCompletedDomainEvent(DomainEvent):
    """Raised when a job finishes successfully."""

    aggregate_id: str
    output_data: dict[str, Any]
    completed_at: datetime

    def __init__(self, aggregate_id: str, output_data: dict[str, Any], completed_at: datetime) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.output_data = output_data
        self.completed_at = completed_at


@cloudevent("scenario_engine.job.failed.v1")
@dataclass
class JobFailedDomainEvent(DomainEvent):
    """Raised when a job fails."""

    aggregate_id: str
    error: str
    failed_at: datetime

    def __init__(self, aggregate_id: str, error: str, failed_at: datetime) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.error = error
        self.failed_at = failed_at


@cloudevent("scenario_engine.job.cancelled.v1")
@dataclass
class JobCancelledDomainEvent(DomainEvent):
    """Raised when a job is cancelled."""

    aggregate_id: str
    cancelled_at: datetime

    def __init__(self, aggregate_id: str, cancelled_at: datetime) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.cancelled_at = cancelled_at
