"""Job DTOs — data transfer objects for job-related responses."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from domain.entities.job import Job


@dataclass
class JobDto:
    """Full job status representation."""

    id: str
    scenario_name: str
    scenario_version: str
    status: str
    progress: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class JobSubmittedDto:
    """Response after job submission (202 Accepted)."""

    id: str
    status: str
    stream_url: str | None = None


def map_job_to_dto(entity: Job) -> JobDto:
    """Map a Job aggregate to a JobDto."""
    state = entity.state
    return JobDto(
        id=state.id,
        scenario_name=state.scenario_name,
        scenario_version=state.scenario_version,
        status=state.status.value,
        progress=state.progress,
        output_data=state.output_data,
        error=state.error,
        created_at=state.created_at,
        started_at=state.started_at,
        completed_at=state.completed_at,
    )
