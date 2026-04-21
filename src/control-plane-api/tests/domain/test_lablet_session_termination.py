"""Focused tests for LabletSession termination semantics."""

from datetime import datetime, timedelta, timezone

from domain.entities.lablet_session import LabletSession
from domain.enums import LabletSessionStatus


def test_terminate_sets_desired_status_to_terminated() -> None:
    session = LabletSession.create(
        definition_id="def-1",
        definition_name="Definition",
        definition_version="1.0.0",
        owner_id="user-1",
        timeslot_start=datetime.now(timezone.utc) + timedelta(minutes=10),
        timeslot_end=datetime.now(timezone.utc) + timedelta(minutes=70),
    )

    assert session.state.desired_status == LabletSessionStatus.RUNNING

    session.terminate(terminated_by="system", reason="worker_terminated_before_session_start")

    assert session.state.status == LabletSessionStatus.TERMINATED
    assert session.state.desired_status == LabletSessionStatus.TERMINATED
