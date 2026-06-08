"""IntegrationEvent definitions for Scenario Engine CloudEvent callbacks.

These events are received from the Scenario Engine via CloudEvents POSTed to
this service. They are decorated with :func:`@cloudevent` so Neuroglia's
:class:`CloudEventIngestor` can map the incoming CloudEvent ``type`` to the
matching class and publish an instance via the Mediator.

The Scenario Engine emits structured-mode CloudEvents
(``Content-Type: application/cloudevents+json``) with the following payload
shape (see ``src/scenario-engine/integration/services/cloud_event_client.py``):

    {
        "specversion": "1.0",
        "type": "scenario_engine.job.completed.v1",
        "source": "scenario-engine",
        "id": "...",
        "subject": "<job_id>",
        "data": {
            "job_id": "...",
            "output_data": {...},
            "artifacts": [...],
            "duration": 12.3,
            "metadata": {                 # AD-CSI-017: round-tripped from job submission
                "lablet_session_id": "...",
                "step_correlation_id": "...",
                "pipeline_name": "instantiate",
                "step_name": "lab_resolve"
            }
        }
    }

Note:
    The ingestor reconstructs the event instance via ``e.__dict__ = data``
    (bypassing ``__init__``). Field annotations below are documentation /
    type-checker hints — the runtime shape is whatever the SE puts in
    ``data``. We give every field a default so the dataclass remains
    constructible from tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from neuroglia.eventing.cloud_events.decorators import cloudevent
from neuroglia.integration.models import IntegrationEvent

# ---------------------------------------------------------------------------
# scenario_engine.job.started.v1 — informational
# ---------------------------------------------------------------------------


@cloudevent("scenario_engine.job.started.v1")
@dataclass
class ScenarioEngineJobStartedIntegrationEventV1(IntegrationEvent[str]):
    """SE job execution has begun. Informational — no CPA write."""

    aggregate_id: str = ""
    created_at: datetime = datetime.min
    job_id: str = ""
    scenario_name: str = ""
    started_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# scenario_engine.job.progress.v1 — informational (throttled by SE)
# ---------------------------------------------------------------------------


@cloudevent("scenario_engine.job.progress.v1")
@dataclass
class ScenarioEngineJobProgressIntegrationEventV1(IntegrationEvent[str]):
    """SE job progress update. Informational — no CPA write."""

    aggregate_id: str = ""
    created_at: datetime = datetime.min
    job_id: str = ""
    percentage: int = 0
    message: str = ""
    details: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# scenario_engine.job.completed.v1 — flips suspended pipeline step → completed
# ---------------------------------------------------------------------------


@cloudevent("scenario_engine.job.completed.v1")
@dataclass
class ScenarioEngineJobCompletedIntegrationEventV1(IntegrationEvent[str]):
    """SE job finished successfully. Triggers CPA ``resume_pipeline_step``
    and signals the in-process :class:`LifecyclePhaseHandler` (AD-CSI-016)."""

    aggregate_id: str = ""
    created_at: datetime = datetime.min
    job_id: str = ""
    output_data: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    duration: float | None = None
    # Tolerated for backward / forward compatibility (SE currently omits).
    completed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# scenario_engine.job.failed.v1 — flips suspended pipeline step → failed
# ---------------------------------------------------------------------------


@cloudevent("scenario_engine.job.failed.v1")
@dataclass
class ScenarioEngineJobFailedIntegrationEventV1(IntegrationEvent[str]):
    """SE job failed. Triggers CPA ``fail_pipeline_step`` and signals the
    in-process :class:`LifecyclePhaseHandler`."""

    aggregate_id: str = ""
    created_at: datetime = datetime.min
    job_id: str = ""
    error: str = ""
    # ``error_message`` is tolerated as a synonym for ``error``; ``details`` /
    # ``error_details`` and ``failed_at`` are also tolerated when present.
    error_message: str | None = None
    error_details: dict[str, Any] | None = None
    details: dict[str, Any] | None = None
    duration: float | None = None
    failed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# scenario_engine.job.cancelled.v1 — treated identically to failed (with marker)
# ---------------------------------------------------------------------------


@cloudevent("scenario_engine.job.cancelled.v1")
@dataclass
class ScenarioEngineJobCancelledIntegrationEventV1(IntegrationEvent[str]):
    """SE job cancelled. Treated as :class:`...JobFailed...` with a
    ``cancelled:`` prefix and ``details.cancelled = True`` marker so
    downstream lifecycle handlers can distinguish operator cancellation
    from genuine job failure."""

    aggregate_id: str = ""
    created_at: datetime = datetime.min
    job_id: str = ""
    reason: str | None = None
    cancelled_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
