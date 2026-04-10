"""Tests for ADR-036 StateTransition value object (generic, str-based).

Validates round-trip serialization (to_dict / from_dict), immutability,
and edge cases for the shared StateTransition in lcm_core.

This is the generic version using `str` for states, distinct from the
CPA-specific StateTransition that uses LabletSessionStatus enum.
"""

from datetime import UTC, datetime

import pytest
from lcm_core.domain.value_objects.state_transition import StateTransition

# =============================================================================
# StateTransition
# =============================================================================


class TestStateTransition:
    """Round-trip serialization and behavior for StateTransition."""

    def test_round_trip_full(self):
        """All fields populated — from_dict(to_dict(x)) == x."""
        transition = StateTransition(
            from_state="PENDING",
            to_state="SCHEDULED",
            transitioned_at=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            triggered_by="resource-scheduler",
            reason="Worker assigned, timeslot confirmed",
            metadata={"worker_id": "w-123", "timeslot_start": "2026-03-09T11:00:00Z"},
        )
        restored = StateTransition.from_dict(transition.to_dict())
        assert restored == transition

    def test_round_trip_minimal(self):
        """Minimal fields — from_state=None, reason=None, metadata=None."""
        transition = StateTransition(
            from_state=None,
            to_state="PENDING",
            transitioned_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
            triggered_by="system",
        )
        restored = StateTransition.from_dict(transition.to_dict())
        assert restored == transition
        assert restored.from_state is None
        assert restored.reason is None
        assert restored.metadata is None

    def test_from_dict_none_from_state(self):
        """from_state absent in dict → None."""
        data = {
            "to_state": "PENDING",
            "transitioned_at": "2026-03-09T10:00:00+00:00",
            "triggered_by": "system",
        }
        transition = StateTransition.from_dict(data)
        assert transition.from_state is None

    def test_to_dict_transitioned_at_isoformat(self):
        """transitioned_at serialized as ISO format string."""
        transition = StateTransition(
            from_state="RUNNING",
            to_state="STOPPING",
            transitioned_at=datetime(2026, 3, 9, 14, 30, 0, tzinfo=UTC),
            triggered_by="admin:user-42",
        )
        d = transition.to_dict()
        assert isinstance(d["transitioned_at"], str)
        assert "2026-03-09" in d["transitioned_at"]

    def test_from_dict_parses_iso_datetime(self):
        """transitioned_at deserialized from ISO format string."""
        data = {
            "from_state": "RUNNING",
            "to_state": "STOPPED",
            "transitioned_at": "2026-03-09T14:30:00+00:00",
            "triggered_by": "worker-controller",
        }
        transition = StateTransition.from_dict(data)
        assert isinstance(transition.transitioned_at, datetime)
        assert transition.transitioned_at.tzinfo is not None

    def test_from_dict_accepts_datetime_object(self):
        """transitioned_at already a datetime passes through."""
        now = datetime(2026, 3, 9, 14, 30, 0, tzinfo=UTC)
        data = {
            "from_state": "PENDING",
            "to_state": "RUNNING",
            "transitioned_at": now,
            "triggered_by": "system",
        }
        transition = StateTransition.from_dict(data)
        assert transition.transitioned_at == now

    def test_frozen_immutability(self):
        """Cannot mutate fields after creation."""
        transition = StateTransition(
            from_state="PENDING",
            to_state="SCHEDULED",
            transitioned_at=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            triggered_by="system",
        )
        with pytest.raises(AttributeError):
            transition.to_state = "RUNNING"  # type: ignore[misc]

    def test_metadata_preserved(self):
        """Arbitrary dict metadata round-trips correctly."""
        metadata = {
            "error": "TimeoutError",
            "retry_count": 3,
            "nested": {"key": "value"},
        }
        transition = StateTransition(
            from_state="INSTANTIATING",
            to_state="PENDING",
            transitioned_at=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            triggered_by="lablet-controller",
            reason="Pipeline step failed, requeued",
            metadata=metadata,
        )
        restored = StateTransition.from_dict(transition.to_dict())
        assert restored.metadata == metadata

    def test_str_representation(self):
        """__str__ produces human-readable output."""
        transition = StateTransition(
            from_state="RUNNING",
            to_state="STOPPING",
            transitioned_at=datetime(2026, 3, 9, 14, 0, 0, tzinfo=UTC),
            triggered_by="system",
        )
        s = str(transition)
        assert "RUNNING" in s
        assert "STOPPING" in s
        assert "→" in s

    def test_str_representation_none_from_state(self):
        """__str__ handles None from_state gracefully."""
        transition = StateTransition(
            from_state=None,
            to_state="PENDING",
            transitioned_at=datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC),
            triggered_by="system",
        )
        s = str(transition)
        assert "None" in s
        assert "PENDING" in s

    def test_from_dict_default_triggered_by(self):
        """Missing triggered_by defaults to 'system'."""
        data = {
            "to_state": "PENDING",
            "transitioned_at": "2026-03-09T10:00:00+00:00",
        }
        transition = StateTransition.from_dict(data)
        assert transition.triggered_by == "system"
