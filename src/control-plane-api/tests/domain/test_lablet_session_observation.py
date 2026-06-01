"""Domain tests for LabletSession resource observation (ADR-030).

Tests cover:
- record_resource_observation() — happy path (no drift)
- record_resource_observation() — port drift: added ports
- record_resource_observation() — port drift: removed ports
- record_resource_observation() — port drift: changed port numbers
- record_resource_observation() — no allocated ports (no drift possible)
- record_resource_observation() — increments observation_count
- request_resource_observation() — emits ObserveResourcesRequested event
"""

from datetime import datetime, timedelta, timezone

import pytest

from domain.entities.lablet_session import LabletSession
from domain.enums import LabletSessionStatus
from domain.events.lablet_session_events import (
    LabletSessionObserveResourcesRequestedDomainEvent,
    LabletSessionPortDriftDetectedDomainEvent,
    LabletSessionResourcesObservedDomainEvent,
)

# =============================================================================
# Helpers
# =============================================================================

NOW = datetime.now(timezone.utc)
FUTURE_START = NOW + timedelta(hours=1)
FUTURE_END = NOW + timedelta(hours=2)

DEFAULT_PORTS = {"PC_serial": 5041, "PC_vnc": 5044, "iosv-0_serial": 5042}

SAMPLE_OBSERVATION = {
    "observed_at": NOW.isoformat(),
    "observer": "lablet-controller",
    "total_cpu_cores": 4.0,
    "total_memory_mb": 8192,
    "total_storage_mb": None,
    "nodes": [],
    "actual_node_count": 2,
    "node_definitions_used": ["iosv", "ubuntu-desktop-24-04-v2"],
    "observed_ports": {"PC_serial": 5041, "PC_vnc": 5044, "iosv-0_serial": 5042},
    "simulation_stats": None,
}


def _make_running(allocated_ports: dict[str, int] | None = None) -> LabletSession:
    """Create a LabletSession in RUNNING state with allocated ports."""
    session = LabletSession.create(
        definition_id="def-001",
        definition_name="Test Lablet",
        definition_version="1.0",
        owner_id="user-42",
        timeslot_start=FUTURE_START,
        timeslot_end=FUTURE_END,
        reservation_id="rsv-001",
    )
    session.schedule(
        worker_id="worker-01",
        allocated_ports=DEFAULT_PORTS if allocated_ports is None else allocated_ports,
        lab_record_id="lr-001",
        scheduled_by="scheduler",
    )
    session.start_instantiation()
    session.mark_ready(user_session_id="us-001", cml_lab_id="cml-lab-99")
    session.mark_running()
    return session


# =============================================================================
# Tests — record_resource_observation
# =============================================================================


@pytest.mark.unit
class TestRecordResourceObservation:
    """Tests for LabletSession.record_resource_observation()."""

    def test_happy_path_no_drift(self) -> None:
        """Recording observations with matching ports produces no drift."""
        session = _make_running()
        observed_ports = {"PC_serial": 5041, "PC_vnc": 5044, "iosv-0_serial": 5042}

        session.record_resource_observation(
            observed_resources=SAMPLE_OBSERVATION,
            observed_ports=observed_ports,
        )

        assert session.state.observed_resources == SAMPLE_OBSERVATION
        assert session.state.observed_ports == observed_ports
        assert session.state.port_drift_detected is False
        assert session.state.observation_count == 1
        assert session.state.observed_at is not None

    def test_records_observation_data(self) -> None:
        """Observation data stored on state correctly."""
        session = _make_running()
        session.record_resource_observation(
            observed_resources=SAMPLE_OBSERVATION,
            observed_ports=DEFAULT_PORTS,
        )

        assert session.state.observed_resources["total_cpu_cores"] == 4.0
        assert session.state.observed_resources["total_memory_mb"] == 8192
        assert session.state.observed_resources["actual_node_count"] == 2

    def test_emits_resources_observed_event(self) -> None:
        """Always emits ResourcesObserved event."""
        session = _make_running()
        initial_event_count = len(session._pending_events)

        session.record_resource_observation(
            observed_resources=SAMPLE_OBSERVATION,
            observed_ports=DEFAULT_PORTS,
        )

        new_events = session._pending_events[initial_event_count:]
        obs_events = [e for e in new_events if isinstance(e, LabletSessionResourcesObservedDomainEvent)]
        assert len(obs_events) == 1
        assert obs_events[0].port_drift_detected is False

    def test_drift_added_ports(self) -> None:
        """Detects drift when CML has ports not in allocation."""
        session = _make_running()
        observed_ports = {**DEFAULT_PORTS, "NEW_ssh": 5050}

        session.record_resource_observation(
            observed_resources=SAMPLE_OBSERVATION,
            observed_ports=observed_ports,
        )

        assert session.state.port_drift_detected is True

        # Check drift event emitted
        drift_events = [e for e in session._pending_events if isinstance(e, LabletSessionPortDriftDetectedDomainEvent)]
        assert len(drift_events) == 1
        assert "NEW_ssh" in drift_events[0].drift_details["added"]

    def test_drift_removed_ports(self) -> None:
        """Detects drift when allocated ports are missing in CML."""
        session = _make_running()
        observed_ports = {"PC_serial": 5041, "PC_vnc": 5044}  # Missing iosv-0_serial

        session.record_resource_observation(
            observed_resources=SAMPLE_OBSERVATION,
            observed_ports=observed_ports,
        )

        assert session.state.port_drift_detected is True

        drift_events = [e for e in session._pending_events if isinstance(e, LabletSessionPortDriftDetectedDomainEvent)]
        assert len(drift_events) == 1
        assert "iosv-0_serial" in drift_events[0].drift_details["removed"]

    def test_drift_changed_ports(self) -> None:
        """Detects drift when port numbers differ."""
        session = _make_running()
        observed_ports = {"PC_serial": 9999, "PC_vnc": 5044, "iosv-0_serial": 5042}

        session.record_resource_observation(
            observed_resources=SAMPLE_OBSERVATION,
            observed_ports=observed_ports,
        )

        assert session.state.port_drift_detected is True

        drift_events = [e for e in session._pending_events if isinstance(e, LabletSessionPortDriftDetectedDomainEvent)]
        assert len(drift_events) == 1
        changed = drift_events[0].drift_details["changed"]
        assert "PC_serial" in changed
        assert changed["PC_serial"]["allocated"] == 5041
        assert changed["PC_serial"]["observed"] == 9999

    def test_no_allocated_ports_no_drift(self) -> None:
        """No drift when session has no allocated ports."""
        session = _make_running(allocated_ports={})
        observed_ports = {"PC_serial": 5041}

        session.record_resource_observation(
            observed_resources=SAMPLE_OBSERVATION,
            observed_ports=observed_ports,
        )

        # With empty allocated, no comparison is made
        assert session.state.port_drift_detected is False

    def test_increments_observation_count(self) -> None:
        """Multiple observations increment the count."""
        session = _make_running()

        session.record_resource_observation(
            observed_resources=SAMPLE_OBSERVATION,
            observed_ports=DEFAULT_PORTS,
        )
        assert session.state.observation_count == 1

        session.record_resource_observation(
            observed_resources=SAMPLE_OBSERVATION,
            observed_ports=DEFAULT_PORTS,
        )
        assert session.state.observation_count == 2

    def test_no_drift_event_when_ports_match(self) -> None:
        """PortDriftDetected event NOT emitted when ports match exactly."""
        session = _make_running()
        initial_event_count = len(session._pending_events)

        session.record_resource_observation(
            observed_resources=SAMPLE_OBSERVATION,
            observed_ports=DEFAULT_PORTS,
        )

        new_events = session._pending_events[initial_event_count:]
        drift_events = [e for e in new_events if isinstance(e, LabletSessionPortDriftDetectedDomainEvent)]
        assert len(drift_events) == 0


# =============================================================================
# Tests — request_resource_observation
# =============================================================================


@pytest.mark.unit
class TestRequestResourceObservation:
    """Tests for LabletSession.request_resource_observation()."""

    def test_emits_observe_requested_event(self) -> None:
        """Emits ObserveResourcesRequested event."""
        session = _make_running()
        initial_event_count = len(session._pending_events)

        session.request_resource_observation(requested_by="admin-user")

        new_events = session._pending_events[initial_event_count:]
        req_events = [e for e in new_events if isinstance(e, LabletSessionObserveResourcesRequestedDomainEvent)]
        assert len(req_events) == 1
        assert req_events[0].requested_by == "admin-user"
        assert req_events[0].requested_at is not None

    def test_does_not_change_status(self) -> None:
        """request_resource_observation does not change session status."""
        session = _make_running()
        assert session.state.status == LabletSessionStatus.RUNNING

        session.request_resource_observation(requested_by="admin")

        assert session.state.status == LabletSessionStatus.RUNNING
