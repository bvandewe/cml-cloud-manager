"""TimedResourceState — state for time-bounded managed resources.

ADR-036 §2.1.4 Layer 2: Extends ResourceState with time-bounded execution
window (Timeslot) and managed lifecycle (ManagedLifecycle).

Hierarchy:
    AggregateState[str]  (Neuroglia)
        └── ResourceState  (Layer 1, see resource.py)
                └── TimedResourceState  ← YOU ARE HERE
                        └── Concrete states (LabletSessionState, CMLWorkerState, …)

Every LCM-managed resource is time-bounded:
    - LabletSession: 120min active window, scheduled provisioning
    - CMLWorker: 24h max window, infrastructure lifecycle
    - LabRecord: Derived from parent session timeslot

Design decisions:
    - `timeslot` and `lifecycle` are stored as `dict | None` at the state level
      for Neuroglia serialization compatibility. Concrete aggregates access them
      as Timeslot/ManagedLifecycle VOs via properties or explicit deserialization
      in their @dispatch handlers.
    - `started_at`, `ended_at`, `terminated_at` are lifecycle timestamps that
      exist at this level because ALL timed resources share them.
    - `duration_seconds` is a denormalized field (computed from started_at/ended_at)
      stored for query efficiency.
"""

from datetime import UTC, datetime

from lcm_core.domain.entities.resource import ResourceState
from lcm_core.domain.value_objects.managed_lifecycle import ManagedLifecycle
from lcm_core.domain.value_objects.timeslot import Timeslot


class TimedResourceState(ResourceState):
    """State for time-bounded resources with managed lifecycles.

    Adds:
    - Timeslot: When the resource is active (start/end/lead/teardown)
    - ManagedLifecycle: Phases and their execution strategies
    - Runtime timestamps: started_at, ended_at, terminated_at
    - Duration tracking: duration_seconds (denormalized)

    Concrete aggregates shadow these fields with typed versions where needed
    and add domain-specific fields (e.g., worker_id, lab_record_id).
    """

    # --- Class-level type annotations (Neuroglia serialization pattern) ---
    # Stored as dicts for Neuroglia serialization; accessed as VOs via helpers.
    timeslot: dict | None
    lifecycle: dict | None

    # Runtime lifecycle timestamps
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: float | None
    terminated_at: datetime | None

    def __init__(self) -> None:
        """Initialize with safe defaults.

        Neuroglia bypasses __init__ during deserialization (MongoDB → object),
        so these defaults only apply to freshly created aggregates.
        """
        super().__init__()

        self.timeslot = None
        self.lifecycle = None

        self.started_at = None
        self.ended_at = None
        self.duration_seconds = None
        self.terminated_at = None

    def get_timeslot(self) -> Timeslot | None:
        """Deserialize the stored timeslot dict into a Timeslot VO.

        Returns None if no timeslot is set.
        """
        if self.timeslot is None:
            return None
        return Timeslot.from_dict(self.timeslot)

    def set_timeslot(self, timeslot: Timeslot) -> None:
        """Serialize and store a Timeslot VO.

        Call this from @dispatch event handlers when setting the timeslot.
        """
        self.timeslot = timeslot.to_dict()
        self.updated_at = datetime.now(UTC)

    def get_lifecycle(self) -> ManagedLifecycle | None:
        """Deserialize the stored lifecycle dict into a ManagedLifecycle VO.

        Returns None if no lifecycle is set.
        """
        if self.lifecycle is None:
            return None
        return ManagedLifecycle.from_dict(self.lifecycle)

    def set_lifecycle(self, lifecycle: ManagedLifecycle) -> None:
        """Serialize and store a ManagedLifecycle VO.

        Call this from @dispatch event handlers when setting the lifecycle.
        """
        self.lifecycle = lifecycle.to_dict()
        self.updated_at = datetime.now(UTC)

    def _compute_duration(self) -> None:
        """Compute and store duration_seconds from started_at/ended_at.

        Call this when ended_at is set. Denormalized for query efficiency.

        Normalizes both timestamps to UTC-aware before subtraction to
        handle MongoDB rehydration returning offset-naive datetimes.
        """
        if self.started_at and self.ended_at:
            start = self.started_at if self.started_at.tzinfo else self.started_at.replace(tzinfo=UTC)
            end = self.ended_at if self.ended_at.tzinfo else self.ended_at.replace(tzinfo=UTC)
            self.duration_seconds = (end - start).total_seconds()
