"""Tests for ADR-036 Timeslot value object.

Validates round-trip serialization, computed properties, query methods,
validation, immutability, and edge cases for the Timeslot VO in lcm_core.
"""

from datetime import UTC, datetime, timedelta

import pytest

from lcm_core.domain.value_objects.timeslot import Timeslot

# =============================================================================
# Timeslot
# =============================================================================


class TestTimeslotRoundTrip:
    """Round-trip serialization for Timeslot."""

    def test_round_trip_full(self):
        """All fields with custom lead_time/teardown — from_dict(to_dict(x)) == x."""
        ts = Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
            lead_time=timedelta(minutes=30),
            teardown_buffer=timedelta(minutes=20),
        )
        restored = Timeslot.from_dict(ts.to_dict())
        assert restored == ts

    def test_round_trip_defaults(self):
        """Default lead_time (15min) and teardown (10min) preserved."""
        ts = Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
        )
        restored = Timeslot.from_dict(ts.to_dict())
        assert restored == ts
        assert restored.lead_time == timedelta(minutes=15)
        assert restored.teardown_buffer == timedelta(minutes=10)

    def test_to_dict_timedelta_as_seconds(self):
        """Timedeltas serialized as float seconds."""
        ts = Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
            lead_time=timedelta(minutes=30),
            teardown_buffer=timedelta(minutes=20),
        )
        d = ts.to_dict()
        assert d["lead_time_seconds"] == 1800.0
        assert d["teardown_buffer_seconds"] == 1200.0

    def test_from_dict_timedelta_from_seconds(self):
        """Timedeltas deserialized from float seconds."""
        data = {
            "start": "2026-03-09T10:00:00+00:00",
            "end": "2026-03-09T12:00:00+00:00",
            "lead_time_seconds": 600.0,
            "teardown_buffer_seconds": 300.0,
        }
        ts = Timeslot.from_dict(data)
        assert ts.lead_time == timedelta(minutes=10)
        assert ts.teardown_buffer == timedelta(minutes=5)

    def test_from_dict_accepts_datetime_objects(self):
        """start/end already datetime objects pass through."""
        start = datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC)
        end = datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC)
        data = {
            "start": start,
            "end": end,
            "lead_time_seconds": 900.0,
            "teardown_buffer_seconds": 600.0,
        }
        ts = Timeslot.from_dict(data)
        assert ts.start == start
        assert ts.end == end

    def test_from_dict_defaults_timedeltas(self):
        """Missing lead_time/teardown defaults to 15min/10min."""
        data = {
            "start": "2026-03-09T10:00:00+00:00",
            "end": "2026-03-09T12:00:00+00:00",
        }
        ts = Timeslot.from_dict(data)
        assert ts.lead_time == timedelta(minutes=15)
        assert ts.teardown_buffer == timedelta(minutes=10)

    def test_to_dict_start_end_isoformat(self):
        """start and end serialized as ISO format strings."""
        ts = Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
        )
        d = ts.to_dict()
        assert isinstance(d["start"], str)
        assert isinstance(d["end"], str)
        assert "2026-03-09" in d["start"]


class TestTimeslotComputedProperties:
    """Computed properties on Timeslot."""

    def _make_timeslot(self) -> Timeslot:
        """Standard test timeslot: 10:00–12:00 with 15min lead, 10min teardown."""
        return Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
        )

    def test_provision_at(self):
        """provision_at == start - lead_time."""
        ts = self._make_timeslot()
        assert ts.provision_at == datetime(2026, 3, 9, 9, 45, 0, tzinfo=UTC)

    def test_cleanup_deadline(self):
        """cleanup_deadline == end + teardown_buffer."""
        ts = self._make_timeslot()
        assert ts.cleanup_deadline == datetime(2026, 3, 9, 12, 10, 0, tzinfo=UTC)

    def test_duration(self):
        """duration == end - start."""
        ts = self._make_timeslot()
        assert ts.duration == timedelta(hours=2)

    def test_total_duration(self):
        """total_duration == cleanup_deadline - provision_at."""
        ts = self._make_timeslot()
        expected = timedelta(hours=2, minutes=25)  # 2h + 15min lead + 10min teardown
        assert ts.total_duration == expected


class TestTimeslotQueryMethods:
    """Query methods on Timeslot."""

    def _make_timeslot(self) -> Timeslot:
        """Standard test timeslot: 10:00–12:00."""
        return Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
        )

    def test_is_active_within_window(self):
        """is_active returns True when start <= now <= end."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 11, 0, 0, tzinfo=UTC)
        assert ts.is_active(now) is True

    def test_is_active_at_start(self):
        """is_active returns True at exactly start."""
        ts = self._make_timeslot()
        assert ts.is_active(ts.start) is True

    def test_is_active_at_end(self):
        """is_active returns True at exactly end."""
        ts = self._make_timeslot()
        assert ts.is_active(ts.end) is True

    def test_is_active_before_start(self):
        """is_active returns False before start."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 9, 0, 0, tzinfo=UTC)
        assert ts.is_active(now) is False

    def test_is_active_after_end(self):
        """is_active returns False after end."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 13, 0, 0, tzinfo=UTC)
        assert ts.is_active(now) is False

    def test_is_expired_after_end(self):
        """is_expired returns True after end."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 12, 0, 1, tzinfo=UTC)
        assert ts.is_expired(now) is True

    def test_is_not_expired_before_end(self):
        """is_expired returns False before end."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 11, 59, 59, tzinfo=UTC)
        assert ts.is_expired(now) is False

    def test_is_not_expired_at_end(self):
        """is_expired returns False at exactly end (end is inclusive for active)."""
        ts = self._make_timeslot()
        assert ts.is_expired(ts.end) is False

    def test_remaining_within_window(self):
        """Correct remaining time calculation within active window."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 11, 0, 0, tzinfo=UTC)
        assert ts.remaining(now) == timedelta(hours=1)

    def test_remaining_after_end(self):
        """Returns timedelta(0) after expiry."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 13, 0, 0, tzinfo=UTC)
        assert ts.remaining(now) == timedelta(0)


class TestTimeslotExtend:
    """Timeslot.extend() factory method."""

    def test_extend_valid(self):
        """Returns new Timeslot with extended end time."""
        ts = Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
            lead_time=timedelta(minutes=20),
            teardown_buffer=timedelta(minutes=5),
        )
        new_end = datetime(2026, 3, 9, 14, 0, 0, tzinfo=UTC)
        extended = ts.extend(new_end)

        assert extended.start == ts.start
        assert extended.end == new_end
        assert extended.lead_time == ts.lead_time
        assert extended.teardown_buffer == ts.teardown_buffer

    def test_extend_invalid_raises(self):
        """Raises ValueError if new_end <= current end."""
        ts = Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
        )
        with pytest.raises(ValueError, match="must be after"):
            ts.extend(datetime(2026, 3, 9, 11, 0, 0, tzinfo=UTC))

    def test_extend_equal_end_raises(self):
        """Raises ValueError if new_end == current end (not strictly after)."""
        ts = Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
        )
        with pytest.raises(ValueError, match="must be after"):
            ts.extend(ts.end)


class TestTimeslotValidation:
    """__post_init__ validation on Timeslot."""

    def test_validation_end_before_start(self):
        """Raises ValueError if end <= start."""
        with pytest.raises(ValueError, match="must be after start"):
            Timeslot(
                start=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
                end=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            )

    def test_validation_end_equals_start(self):
        """Raises ValueError if end == start (zero-duration not allowed)."""
        now = datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="must be after start"):
            Timeslot(start=now, end=now)

    def test_validation_negative_lead_time(self):
        """Raises ValueError if lead_time is negative."""
        with pytest.raises(ValueError, match="lead_time must be non-negative"):
            Timeslot(
                start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
                end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
                lead_time=timedelta(minutes=-5),
            )

    def test_validation_negative_teardown_buffer(self):
        """Raises ValueError if teardown_buffer is negative."""
        with pytest.raises(ValueError, match="teardown_buffer must be non-negative"):
            Timeslot(
                start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
                end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
                teardown_buffer=timedelta(minutes=-5),
            )

    def test_validation_zero_lead_time_ok(self):
        """Zero lead_time is valid (no provisioning lead time)."""
        ts = Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
            lead_time=timedelta(0),
        )
        assert ts.provision_at == ts.start

    def test_validation_zero_teardown_buffer_ok(self):
        """Zero teardown_buffer is valid (no cleanup buffer)."""
        ts = Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
            teardown_buffer=timedelta(0),
        )
        assert ts.cleanup_deadline == ts.end


class TestTimeslotImmutability:
    """Frozen dataclass immutability."""

    def test_frozen_immutability(self):
        """Cannot mutate fields after creation."""
        ts = Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
        )
        with pytest.raises(AttributeError):
            ts.end = datetime(2026, 3, 9, 14, 0, 0, tzinfo=UTC)  # type: ignore[misc]


class TestTimeslotStr:
    """String representation."""

    def test_str_representation(self):
        """__str__ produces human-readable output."""
        ts = Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
        )
        s = str(ts)
        assert "Timeslot" in s
        assert "2026-03-09" in s


class TestTimeslotApproaching:
    """is_approaching() — provisioning window before start."""

    def _make_timeslot(self) -> Timeslot:
        """10:00–12:00, 15min lead, 10min teardown."""
        return Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
        )

    def test_approaching_at_provision_at(self):
        """True at exactly provision_at (start of provisioning window)."""
        ts = self._make_timeslot()
        assert ts.is_approaching(ts.provision_at) is True

    def test_approaching_during_lead_time(self):
        """True during the lead_time window."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 9, 50, 0, tzinfo=UTC)  # 10min before start
        assert ts.is_approaching(now) is True

    def test_not_approaching_at_start(self):
        """False at exactly start (that's active, not approaching)."""
        ts = self._make_timeslot()
        assert ts.is_approaching(ts.start) is False

    def test_not_approaching_before_provision(self):
        """False before provision_at."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 9, 0, 0, tzinfo=UTC)  # well before provision
        assert ts.is_approaching(now) is False

    def test_not_approaching_during_active(self):
        """False during the active window."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 11, 0, 0, tzinfo=UTC)
        assert ts.is_approaching(now) is False

    def test_not_approaching_after_end(self):
        """False after the active window."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 13, 0, 0, tzinfo=UTC)
        assert ts.is_approaching(now) is False


class TestTimeslotInTeardown:
    """is_in_teardown() — cleanup window after end."""

    def _make_timeslot(self) -> Timeslot:
        """10:00–12:00, 15min lead, 10min teardown."""
        return Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
        )

    def test_in_teardown_just_after_end(self):
        """True just after end."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 12, 0, 1, tzinfo=UTC)
        assert ts.is_in_teardown(now) is True

    def test_in_teardown_at_cleanup_deadline(self):
        """True at exactly cleanup_deadline."""
        ts = self._make_timeslot()
        assert ts.is_in_teardown(ts.cleanup_deadline) is True

    def test_not_in_teardown_at_end(self):
        """False at exactly end (that's still active)."""
        ts = self._make_timeslot()
        assert ts.is_in_teardown(ts.end) is False

    def test_not_in_teardown_after_cleanup(self):
        """False after cleanup_deadline (that's expired)."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 12, 11, 0, tzinfo=UTC)
        assert ts.is_in_teardown(now) is False

    def test_not_in_teardown_during_active(self):
        """False during the active window."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 11, 0, 0, tzinfo=UTC)
        assert ts.is_in_teardown(now) is False

    def test_not_in_teardown_before_start(self):
        """False before the active window."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 9, 0, 0, tzinfo=UTC)
        assert ts.is_in_teardown(now) is False


class TestTimeslotPhase:
    """phase() — returns the current temporal phase as a string."""

    def _make_timeslot(self) -> Timeslot:
        """10:00–12:00, 15min lead, 10min teardown."""
        return Timeslot(
            start=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
        )

    def test_phase_before(self):
        """'before' when before provision_at."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 9, 0, 0, tzinfo=UTC)
        assert ts.phase(now) == "before"

    def test_phase_approaching(self):
        """'approaching' during lead_time window."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 9, 50, 0, tzinfo=UTC)
        assert ts.phase(now) == "approaching"

    def test_phase_active(self):
        """'active' during start–end window."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 11, 0, 0, tzinfo=UTC)
        assert ts.phase(now) == "active"

    def test_phase_teardown(self):
        """'teardown' between end and cleanup_deadline."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 12, 5, 0, tzinfo=UTC)
        assert ts.phase(now) == "teardown"

    def test_phase_expired(self):
        """'expired' after cleanup_deadline."""
        ts = self._make_timeslot()
        now = datetime(2026, 3, 9, 12, 15, 0, tzinfo=UTC)
        assert ts.phase(now) == "expired"
