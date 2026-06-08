"""Job Entity — represents an automation job execution.

Uses Neuroglia AggregateRoot[State, Key] pattern with event-driven state transitions.
Event handlers are defined on the State class using @dispatch.

Lifecycle: SUBMITTED → RUNNING → COMPLETED | FAILED | CANCELLED
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from multipledispatch import dispatch
from neuroglia.data.abstractions import AggregateRoot, AggregateState

from domain.events.job_events import (
    JobCancelledDomainEvent,
    JobCompletedDomainEvent,
    JobCreatedDomainEvent,
    JobFailedDomainEvent,
    JobStartedDomainEvent,
)

logger = logging.getLogger(__name__)


class JobStatus(StrEnum):
    """Job lifecycle status."""

    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# -------------------------------------------------------------------------
# Aggregate State
# -------------------------------------------------------------------------


class JobState(AggregateState[str]):
    """Encapsulates the persisted state for the Job aggregate.

    Event handlers are defined on the State class using @dispatch.
    """

    id: str
    scenario_name: str
    scenario_version: str
    status: JobStatus
    input_data: dict[str, Any]
    output_data: dict[str, Any]
    callback_url: str | None
    pod_definition_id: str | None
    progress: dict[str, Any]
    error: str | None
    created_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    metadata: dict[str, Any] | None  # AD-CSI-017: opaque caller-supplied dict, round-tripped onto CloudEvents

    def __init__(self) -> None:
        super().__init__()
        self.id = ""
        self.scenario_name = ""
        self.scenario_version = "v1"
        self.status = JobStatus.SUBMITTED
        self.input_data = {}
        self.output_data = {}
        self.callback_url = None
        self.pod_definition_id = None
        self.progress = {}
        self.error = None
        self.created_at = None
        self.started_at = None
        self.completed_at = None
        self.metadata = None

    # -------------------------------------------------------------------------
    # Event Handlers
    # -------------------------------------------------------------------------

    @dispatch(JobCreatedDomainEvent)
    def on(self, event: JobCreatedDomainEvent) -> None:  # type: ignore[override]
        self.id = event.aggregate_id
        self.scenario_name = event.scenario_name
        self.scenario_version = event.scenario_version
        self.input_data = event.input_data
        self.callback_url = event.callback_url
        self.pod_definition_id = event.pod_definition_id
        self.status = JobStatus.SUBMITTED
        self.created_at = event.created_at
        self.metadata = event.metadata

    @dispatch(JobStartedDomainEvent)
    def on(self, event: JobStartedDomainEvent) -> None:  # type: ignore[override]
        self.status = JobStatus.RUNNING
        self.started_at = event.started_at

    @dispatch(JobCompletedDomainEvent)
    def on(self, event: JobCompletedDomainEvent) -> None:  # type: ignore[override]
        self.status = JobStatus.COMPLETED
        self.output_data = event.output_data
        self.completed_at = event.completed_at

    @dispatch(JobFailedDomainEvent)
    def on(self, event: JobFailedDomainEvent) -> None:  # type: ignore[override]
        self.status = JobStatus.FAILED
        self.error = event.error
        self.completed_at = event.failed_at

    @dispatch(JobCancelledDomainEvent)
    def on(self, event: JobCancelledDomainEvent) -> None:  # type: ignore[override]
        self.status = JobStatus.CANCELLED
        self.completed_at = event.cancelled_at


# -------------------------------------------------------------------------
# Aggregate Root
# -------------------------------------------------------------------------


class Job(AggregateRoot[JobState, str]):
    """Job aggregate root — automation job execution.

    Represents a submitted automation job that executes a named scenario
    against infrastructure adapters. State transitions driven by domain events.
    """

    def __init__(self) -> None:
        super().__init__()

    def id(self) -> str:
        return self.state.id

    @staticmethod
    def create(
        scenario_name: str,
        scenario_version: str = "v1",
        input_data: dict[str, Any] | None = None,
        callback_url: str | None = None,
        pod_definition_id: str | None = None,
        job_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Job:
        """Create a new Job aggregate.

        Args:
            scenario_name: Name of the scenario to execute.
            scenario_version: Version of the scenario (e.g. "v1").
            input_data: Input parameters for the scenario.
            callback_url: CloudEvents sink URL for notifications.
            pod_definition_id: Reference to the PodDefinition.
            job_id: Optional specific ID (for testing).
            metadata: AD-CSI-017 — opaque caller-supplied dict round-tripped
                onto every emitted CloudEvent payload as ``data.metadata``.

        Returns:
            New Job aggregate with JobCreatedDomainEvent recorded.
        """
        if not scenario_name:
            raise ValueError("scenario_name cannot be empty")

        job = Job()
        now = datetime.now(timezone.utc)
        event = JobCreatedDomainEvent(
            aggregate_id=job_id or str(uuid4()),
            scenario_name=scenario_name,
            scenario_version=scenario_version,
            input_data=input_data or {},
            callback_url=callback_url,
            pod_definition_id=pod_definition_id,
            created_at=now,
            metadata=metadata,
        )
        job.state.on(job.register_event(event))
        return job

    def start(self) -> None:
        """Mark job as running."""
        now = datetime.now(timezone.utc)
        event = JobStartedDomainEvent(aggregate_id=self.state.id, started_at=now)
        self.state.on(self.register_event(event))

    def complete(self, output_data: dict[str, Any] | None = None) -> None:
        """Mark job as completed with output data."""
        now = datetime.now(timezone.utc)
        event = JobCompletedDomainEvent(aggregate_id=self.state.id, output_data=output_data or {}, completed_at=now)
        self.state.on(self.register_event(event))

    def fail(self, error: str) -> None:
        """Mark job as failed with error message."""
        now = datetime.now(timezone.utc)
        event = JobFailedDomainEvent(aggregate_id=self.state.id, error=error, failed_at=now)
        self.state.on(self.register_event(event))

    def cancel(self) -> None:
        """Mark job as cancelled."""
        now = datetime.now(timezone.utc)
        event = JobCancelledDomainEvent(aggregate_id=self.state.id, cancelled_at=now)
        self.state.on(self.register_event(event))
