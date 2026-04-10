"""Timeslot value object — time-bounded execution window for managed resources.

ADR-036 §2.1.4: Part of the TimedResource abstraction layer (Layer 2).

Timeslots define both the user-visible window (start → end) and the
operational margins needed for preparation and teardown. Every LCM-managed
resource (CMLWorker, LabRecord, LabletSession) is time-bounded.

Timeline:
    |--lead_time--|------- active window -------|--teardown_buffer--|
    ^             ^                             ^                   ^
  provision     start                          end              cleanup
  begins       (ready)                       (user done)       complete
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class Timeslot:
    """Time window during which a resource is active.

    Timeslots capture not just "when is this resource active?" but also the
    operational reality that resources need **lead time** to become ready
    and **teardown time** after the user is done.

    Examples:
    - LabletSession: 120min active window, 15min lead time, 10min teardown
    - CMLWorker: 24h max window, 30min lead time (EC2 launch), 15min teardown
    - LabRecord: Derived from parent session timeslot
    """

    start: datetime  # When the resource should be ready
    end: datetime  # When the user session ends
    lead_time: timedelta = timedelta(minutes=15)  # Provisioning lead time
    teardown_buffer: timedelta = timedelta(minutes=10)  # Cleanup buffer after end

    def __post_init__(self) -> None:
        """Validate timeslot constraints."""
        if self.end <= self.start:
            raise ValueError(f"end ({self.end}) must be after start ({self.start})")
        if self.lead_time < timedelta(0):
            raise ValueError(f"lead_time must be non-negative, got {self.lead_time}")
        if self.teardown_buffer < timedelta(0):
            raise ValueError(f"teardown_buffer must be non-negative, got {self.teardown_buffer}")

    @property
    def provision_at(self) -> datetime:
        """When provisioning must begin to be ready by start."""
        return self.start - self.lead_time

    @property
    def cleanup_deadline(self) -> datetime:
        """Hard deadline by which teardown must complete."""
        return self.end + self.teardown_buffer

    @property
    def duration(self) -> timedelta:
        """Active window duration (start → end)."""
        return self.end - self.start

    @property
    def total_duration(self) -> timedelta:
        """Total time including lead-time and teardown."""
        return self.cleanup_deadline - self.provision_at

    def is_approaching(self, now: datetime | None = None) -> bool:
        """True if in the provisioning window (between provision_at and start).

        This is the period when infrastructure should be spinning up:
        provision_at <= now < start.
        """
        now = now or datetime.now(UTC)
        return self.provision_at <= now < self.start

    def is_active(self, now: datetime | None = None) -> bool:
        """True if within the active window."""
        now = now or datetime.now(UTC)
        return self.start <= now <= self.end

    def is_expired(self, now: datetime | None = None) -> bool:
        """True if past the active window end."""
        now = now or datetime.now(UTC)
        return now > self.end

    def is_in_teardown(self, now: datetime | None = None) -> bool:
        """True if in the teardown window (between end and cleanup_deadline).

        This is the period when resources are being cleaned up:
        end < now <= cleanup_deadline.
        """
        now = now or datetime.now(UTC)
        return self.end < now <= self.cleanup_deadline

    def remaining(self, now: datetime | None = None) -> timedelta:
        """Time remaining in the active window."""
        now = now or datetime.now(UTC)
        return max(timedelta(0), self.end - now)

    def extend(self, new_end: datetime) -> "Timeslot":
        """Return new Timeslot with extended end time.

        Raises ValueError if new_end is not after current end.
        """
        if new_end <= self.end:
            raise ValueError(f"new_end ({new_end}) must be after current end ({self.end})")
        return Timeslot(
            start=self.start,
            end=new_end,
            lead_time=self.lead_time,
            teardown_buffer=self.teardown_buffer,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Timedeltas are serialized as float seconds for JSON compatibility.
        """
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "lead_time_seconds": self.lead_time.total_seconds(),
            "teardown_buffer_seconds": self.teardown_buffer.total_seconds(),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Timeslot":
        """Create from dictionary.

        Handles both ISO-format strings and datetime objects for start/end.
        Timedeltas deserialized from float seconds.
        """
        start = data["start"]
        if isinstance(start, str):
            start = datetime.fromisoformat(start)
        end = data["end"]
        if isinstance(end, str):
            end = datetime.fromisoformat(end)
        return Timeslot(
            start=start,
            end=end,
            lead_time=timedelta(seconds=data.get("lead_time_seconds", 900.0)),
            teardown_buffer=timedelta(seconds=data.get("teardown_buffer_seconds", 600.0)),
        )

    def __str__(self) -> str:
        """Human-readable representation."""
        return f"Timeslot({self.start.isoformat()} → {self.end.isoformat()}, " f"lead={self.lead_time}, teardown={self.teardown_buffer})"

    def phase(self, now: datetime | None = None) -> str:
        """Return the current temporal phase as a string.

        Returns one of: 'before', 'approaching', 'active', 'teardown', 'expired'.
        """
        now = now or datetime.now(UTC)
        if now < self.provision_at:
            return "before"
        if self.is_approaching(now):
            return "approaching"
        if self.is_active(now):
            return "active"
        if self.is_in_teardown(now):
            return "teardown"
        return "expired"
