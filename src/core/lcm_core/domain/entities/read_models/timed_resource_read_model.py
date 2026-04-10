"""Base read model for time-bounded managed resources.

ADR-036 §2.1.4: Provides shared fields for all timed resource read models.
LabletSessionReadModel and CMLWorkerReadModel extend this base.

Design decisions:
    - ALL fields have defaults (including `id` and `status`) to support
      Python dataclass MRO — child classes may declare fields without defaults
      only if they come before any inherited field with a default. Since that's
      fragile, we give all base fields defaults for safe inheritance.
    - `timeslot_start`/`timeslot_end` remain as flat datetime fields (not a
      Timeslot VO) because read models are DTOs from API responses where the
      timeslot is not yet consolidated into a VO at the API level.
    - No `from_dict` method — each concrete read model has domain-specific
      field mapping logic in its own `from_dict`.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class TimedResourceReadModel:
    """Base read model for time-bounded resources.

    Provides the common field set shared by LabletSessionReadModel,
    CMLWorkerReadModel, and future resource read models.

    Used by controllers and schedulers to represent the current state
    of a managed resource without full aggregate reconstruction.
    """

    # Core identity
    id: str = ""
    resource_type: str = ""
    status: str = ""
    desired_status: str | None = None
    owner_id: str = ""

    # Timeslot fields (flat for backward compat, not Timeslot VO)
    timeslot_start: datetime | None = None
    timeslot_end: datetime | None = None

    # Runtime lifecycle
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: float | None = None
    terminated_at: datetime | None = None

    # Pipeline tracking
    pipeline_progress: dict[str, Any] | None = None

    # Timestamps
    created_at: datetime | None = None
    updated_at: datetime | None = None
