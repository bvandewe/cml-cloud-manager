"""Unit tests for etcd state projectors.

These tests verify that domain events are correctly projected to etcd
for watch-based reconciliation (ADR-006, ADR-015).

Tests mock the EtcdStateStore to avoid requiring a running etcd instance.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.events.domain.etcd_state_projector import (
    CMLWorkerCreatedEtcdProjector,
    CMLWorkerDesiredStatusUpdatedEtcdProjector,
    CMLWorkerLicenseDeregistrationCompletedEtcdProjector,
    CMLWorkerLicenseDeregistrationRequestedEtcdProjector,
    CMLWorkerLicenseRegistrationCompletedEtcdProjector,
    CMLWorkerLicenseRegistrationRequestedEtcdProjector,
    CMLWorkerStatusUpdatedEtcdProjector,
    CMLWorkerTerminatedEtcdProjector,
)
from domain.enums import CMLWorkerStatus
from domain.events.cml_worker import (
    CMLWorkerCreatedDomainEvent,
    CMLWorkerDesiredStatusUpdatedDomainEvent,
    CMLWorkerLicenseDeregistrationCompletedDomainEvent,
    CMLWorkerLicenseDeregistrationRequestedDomainEvent,
    CMLWorkerLicenseRegistrationCompletedDomainEvent,
    CMLWorkerLicenseRegistrationRequestedDomainEvent,
    CMLWorkerStatusUpdatedDomainEvent,
    CMLWorkerTerminatedDomainEvent,
)


@pytest.fixture
def mock_etcd_store() -> MagicMock:
    """Create a mock EtcdStateStore."""
    store = MagicMock()
    store.set_worker_state = AsyncMock()
    store.set_worker_desired_state = AsyncMock()
    store.set_worker_license_pending = AsyncMock()
    store.delete_worker_state = AsyncMock()
    store.delete_worker_license_pending = AsyncMock()
    return store


# =============================================================================
# CMLWorkerCreatedEtcdProjector Tests
# =============================================================================


@pytest.mark.unit
class TestCMLWorkerCreatedEtcdProjector:
    """Test worker creation projection to etcd."""

    async def test_projects_status_and_desired_status_on_creation(self, mock_etcd_store: MagicMock) -> None:
        """Verify both status and desired_status are published on creation."""
        projector = CMLWorkerCreatedEtcdProjector(mock_etcd_store)

        event = CMLWorkerCreatedDomainEvent(
            aggregate_id="worker-123",
            name="Test Worker",
            aws_region="us-east-1",
            aws_instance_id="i-1234567890",
            instance_type="m5.xlarge",
            ami_id="ami-123",
            ami_name="CML-AMI",
            ami_description="CML Worker AMI",
            ami_creation_date="2024-01-01",
            status=CMLWorkerStatus.PENDING,
            desired_status=CMLWorkerStatus.RUNNING,
            cml_version="2.5.0",
            created_at=datetime.now(timezone.utc),
            created_by="user-123",
        )

        await projector.handle_async(event)

        # Verify both calls were made (note: enum values are lowercase)
        mock_etcd_store.set_worker_state.assert_called_once_with("worker-123", "pending")
        mock_etcd_store.set_worker_desired_state.assert_called_once_with("worker-123", "running")

    async def test_projects_with_same_status_and_desired_status(self, mock_etcd_store: MagicMock) -> None:
        """Verify projection works when status equals desired_status."""
        projector = CMLWorkerCreatedEtcdProjector(mock_etcd_store)

        event = CMLWorkerCreatedDomainEvent(
            aggregate_id="worker-456",
            name="Stopped Worker",
            aws_region="us-west-2",
            aws_instance_id=None,
            instance_type="m5.xlarge",
            ami_id=None,
            ami_name=None,
            ami_description=None,
            ami_creation_date=None,
            status=CMLWorkerStatus.STOPPED,
            desired_status=CMLWorkerStatus.STOPPED,
            cml_version=None,
            created_at=datetime.now(timezone.utc),
            created_by=None,
        )

        await projector.handle_async(event)

        mock_etcd_store.set_worker_state.assert_called_once_with("worker-456", "stopped")
        mock_etcd_store.set_worker_desired_state.assert_called_once_with("worker-456", "stopped")


# =============================================================================
# CMLWorkerStatusUpdatedEtcdProjector Tests
# =============================================================================


@pytest.mark.unit
class TestCMLWorkerStatusUpdatedEtcdProjector:
    """Test worker status update projection to etcd."""

    async def test_projects_new_status(self, mock_etcd_store: MagicMock) -> None:
        """Verify status changes are projected to etcd."""
        projector = CMLWorkerStatusUpdatedEtcdProjector(mock_etcd_store)

        event = CMLWorkerStatusUpdatedDomainEvent(
            aggregate_id="worker-789",
            old_status=CMLWorkerStatus.PENDING,
            new_status=CMLWorkerStatus.RUNNING,
            updated_at=datetime.now(timezone.utc),
        )

        await projector.handle_async(event)

        mock_etcd_store.set_worker_state.assert_called_once_with("worker-789", "running")


# =============================================================================
# CMLWorkerDesiredStatusUpdatedEtcdProjector Tests (ADR-015)
# =============================================================================


@pytest.mark.unit
class TestCMLWorkerDesiredStatusUpdatedEtcdProjector:
    """Test worker desired_status update projection to etcd.

    ADR-015: This is the key projector for reactive reconciliation.
    When a user requests stop/start/terminate, this projector publishes
    to etcd so worker-controller can immediately start reconciliation.
    """

    async def test_projects_desired_status_for_stop_request(self, mock_etcd_store: MagicMock) -> None:
        """Verify stop request (desired_status=STOPPED) is projected."""
        projector = CMLWorkerDesiredStatusUpdatedEtcdProjector(mock_etcd_store)

        event = CMLWorkerDesiredStatusUpdatedDomainEvent(
            aggregate_id="worker-stop-test",
            old_desired_status=CMLWorkerStatus.RUNNING,
            new_desired_status=CMLWorkerStatus.STOPPED,
            updated_at=datetime.now(timezone.utc),
            requested_by="user-123",
            reason="manual",
        )

        await projector.handle_async(event)

        mock_etcd_store.set_worker_desired_state.assert_called_once_with("worker-stop-test", "stopped")

    async def test_projects_desired_status_for_start_request(self, mock_etcd_store: MagicMock) -> None:
        """Verify start request (desired_status=RUNNING) is projected."""
        projector = CMLWorkerDesiredStatusUpdatedEtcdProjector(mock_etcd_store)

        event = CMLWorkerDesiredStatusUpdatedDomainEvent(
            aggregate_id="worker-start-test",
            old_desired_status=CMLWorkerStatus.STOPPED,
            new_desired_status=CMLWorkerStatus.RUNNING,
            updated_at=datetime.now(timezone.utc),
            requested_by="user-456",
            reason="auto",
        )

        await projector.handle_async(event)

        mock_etcd_store.set_worker_desired_state.assert_called_once_with("worker-start-test", "running")

    async def test_projects_desired_status_for_terminate_request(self, mock_etcd_store: MagicMock) -> None:
        """Verify terminate request (desired_status=TERMINATED) is projected."""
        projector = CMLWorkerDesiredStatusUpdatedEtcdProjector(mock_etcd_store)

        event = CMLWorkerDesiredStatusUpdatedDomainEvent(
            aggregate_id="worker-terminate-test",
            old_desired_status=CMLWorkerStatus.RUNNING,
            new_desired_status=CMLWorkerStatus.TERMINATED,
            updated_at=datetime.now(timezone.utc),
            requested_by="admin-789",
            reason="cleanup",
        )

        await projector.handle_async(event)

        mock_etcd_store.set_worker_desired_state.assert_called_once_with("worker-terminate-test", "terminated")

    async def test_projects_without_optional_fields(self, mock_etcd_store: MagicMock) -> None:
        """Verify projection works with optional fields omitted."""
        projector = CMLWorkerDesiredStatusUpdatedEtcdProjector(mock_etcd_store)

        event = CMLWorkerDesiredStatusUpdatedDomainEvent(
            aggregate_id="worker-no-extras",
            old_desired_status=CMLWorkerStatus.RUNNING,
            new_desired_status=CMLWorkerStatus.STOPPED,
            updated_at=datetime.now(timezone.utc),
            requested_by=None,  # System-triggered
            reason=None,
        )

        await projector.handle_async(event)

        mock_etcd_store.set_worker_desired_state.assert_called_once_with("worker-no-extras", "stopped")


# =============================================================================
# CMLWorkerTerminatedEtcdProjector Tests
# =============================================================================


@pytest.mark.unit
class TestCMLWorkerTerminatedEtcdProjector:
    """Test worker termination projection to etcd."""

    async def test_deletes_worker_state_on_termination(self, mock_etcd_store: MagicMock) -> None:
        """Verify termination deletes all worker state from etcd."""
        projector = CMLWorkerTerminatedEtcdProjector(mock_etcd_store)

        event = CMLWorkerTerminatedDomainEvent(
            aggregate_id="worker-terminated",
            name="Test Worker",
            terminated_at=datetime.now(timezone.utc),
            terminated_by="admin",
        )

        await projector.handle_async(event)

        mock_etcd_store.delete_worker_state.assert_called_once_with("worker-terminated")


# =============================================================================
# CMLWorkerLicenseRegistrationRequestedEtcdProjector Tests (ADR-016)
# =============================================================================


@pytest.mark.unit
class TestCMLWorkerLicenseRegistrationRequestedEtcdProjector:
    """Test license registration request projection to etcd.

    ADR-016: When license registration is requested, this projector publishes
    to etcd so worker-controller can immediately start license reconciliation.
    """

    async def test_projects_license_registration_request(self, mock_etcd_store: MagicMock) -> None:
        """Verify license registration request is projected with token."""
        projector = CMLWorkerLicenseRegistrationRequestedEtcdProjector(mock_etcd_store)

        event = CMLWorkerLicenseRegistrationRequestedDomainEvent(
            aggregate_id="worker-license-reg",
            worker_id="worker-license-reg",
            license_token="license-token-abc123",
            reregister=False,
            requested_at=datetime.now(timezone.utc).isoformat(),
            initiated_by="user-123",
        )

        await projector.handle_async(event)

        mock_etcd_store.set_worker_license_pending.assert_called_once_with(
            worker_id="worker-license-reg",
            operation="register",
            token="license-token-abc123",
            reregister=False,
        )

    async def test_projects_license_reregistration_request(self, mock_etcd_store: MagicMock) -> None:
        """Verify re-registration request sets reregister=True."""
        projector = CMLWorkerLicenseRegistrationRequestedEtcdProjector(mock_etcd_store)

        event = CMLWorkerLicenseRegistrationRequestedDomainEvent(
            aggregate_id="worker-license-rereg",
            worker_id="worker-license-rereg",
            license_token="new-license-token",
            reregister=True,
            requested_at=datetime.now(timezone.utc).isoformat(),
            initiated_by="admin-456",
        )

        await projector.handle_async(event)

        mock_etcd_store.set_worker_license_pending.assert_called_once_with(
            worker_id="worker-license-rereg",
            operation="register",
            token="new-license-token",
            reregister=True,
        )


# =============================================================================
# CMLWorkerLicenseRegistrationCompletedEtcdProjector Tests (ADR-016)
# =============================================================================


@pytest.mark.unit
class TestCMLWorkerLicenseRegistrationCompletedEtcdProjector:
    """Test license registration completion projection to etcd.

    ADR-016: After license registration completes, this projector clears
    the pending operation from etcd.
    """

    async def test_clears_license_pending_on_completion(self, mock_etcd_store: MagicMock) -> None:
        """Verify license pending is deleted after successful registration."""
        projector = CMLWorkerLicenseRegistrationCompletedEtcdProjector(mock_etcd_store)

        event = CMLWorkerLicenseRegistrationCompletedDomainEvent(
            aggregate_id="worker-reg-complete",
            worker_id="worker-reg-complete",
            registration_status="REGISTERED",
            smart_account="my-smart-account",
            virtual_account="my-virtual-account",
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

        await projector.handle_async(event)

        mock_etcd_store.delete_worker_license_pending.assert_called_once_with("worker-reg-complete")


# =============================================================================
# CMLWorkerLicenseDeregistrationRequestedEtcdProjector Tests (ADR-016)
# =============================================================================


@pytest.mark.unit
class TestCMLWorkerLicenseDeregistrationRequestedEtcdProjector:
    """Test license deregistration request projection to etcd.

    ADR-016: When license deregistration is requested, this projector publishes
    to etcd so worker-controller can immediately start license reconciliation.
    """

    async def test_projects_license_deregistration_request(self, mock_etcd_store: MagicMock) -> None:
        """Verify license deregistration request is projected."""
        projector = CMLWorkerLicenseDeregistrationRequestedEtcdProjector(mock_etcd_store)

        event = CMLWorkerLicenseDeregistrationRequestedDomainEvent(
            aggregate_id="worker-license-dereg",
            worker_id="worker-license-dereg",
            requested_at=datetime.now(timezone.utc).isoformat(),
            initiated_by="user-789",
        )

        await projector.handle_async(event)

        mock_etcd_store.set_worker_license_pending.assert_called_once_with(
            worker_id="worker-license-dereg",
            operation="deregister",
        )


# =============================================================================
# CMLWorkerLicenseDeregistrationCompletedEtcdProjector Tests (ADR-016)
# =============================================================================


@pytest.mark.unit
class TestCMLWorkerLicenseDeregistrationCompletedEtcdProjector:
    """Test license deregistration completion projection to etcd.

    ADR-016: After license deregistration completes, this projector clears
    the pending operation from etcd.
    """

    async def test_clears_license_pending_on_deregistration_completion(self, mock_etcd_store: MagicMock) -> None:
        """Verify license pending is deleted after successful deregistration."""
        projector = CMLWorkerLicenseDeregistrationCompletedEtcdProjector(mock_etcd_store)

        event = CMLWorkerLicenseDeregistrationCompletedDomainEvent(
            aggregate_id="worker-dereg-complete",
            worker_id="worker-dereg-complete",
            message="Successfully deregistered from Cisco Smart Licensing",
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

        await projector.handle_async(event)

        mock_etcd_store.delete_worker_license_pending.assert_called_once_with("worker-dereg-complete")
