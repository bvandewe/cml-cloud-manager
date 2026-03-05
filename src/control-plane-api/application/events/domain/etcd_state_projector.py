"""etcd State Projector - Domain event handlers for publishing state to etcd.

This module projects domain events to etcd for reactive watch-based notifications.
Controllers subscribe to etcd watch and receive immediate notification of state changes,
enabling faster reconciliation than polling alone.

Pattern: Event Sourcing Projection
- Domain events are the source of truth (in MongoDB via aggregates)
- etcd state is a projection for reactive notifications
- Controllers can watch etcd keys for immediate updates

Key Structure (following ADR-005):
    /lcm/workers/{id}/state       - CMLWorker status (PENDING, RUNNING, etc.)
    /lcm/sessions/{id}/state      - LabletSession status
    /lcm/sessions/{id}/metadata   - LabletSession scheduling metadata

Watch Patterns:
    - worker-controller watches /lcm/workers/ prefix
    - lablet-controller watches /lcm/sessions/ prefix
    - resource-scheduler watches both for scheduling decisions
"""

from __future__ import annotations

import logging
from datetime import datetime

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
from domain.events.lab_record_events import (
    LabActionClearedDomainEvent,
    LabActionCompletedDomainEvent,
    LabActionFailedDomainEvent,
    LabActionRequestedDomainEvent,
)
from domain.events.lablet_definition_events import (
    LabletDefinitionContentSyncedDomainEvent,
    LabletDefinitionSyncRequestedDomainEvent,
)
from domain.events.lablet_session_events import (
    LabletSessionCollectingDomainEvent,
    LabletSessionCreatedDomainEvent,
    LabletSessionGradingDomainEvent,
    LabletSessionInstantiatingDomainEvent,
    LabletSessionObserveResourcesRequestedDomainEvent,
    LabletSessionRequeuedDomainEvent,
    LabletSessionRunningDomainEvent,
    LabletSessionScheduledDomainEvent,
    LabletSessionStoppedDomainEvent,
    LabletSessionStoppingDomainEvent,
    LabletSessionTerminatedDomainEvent,
)
from integration.services.etcd_state_store import EtcdStateStore
from neuroglia.mediation import DomainEventHandler

log = logging.getLogger(__name__)


def _utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat() + "Z" if not dt.isoformat().endswith("Z") else dt.isoformat()


# =============================================================================
# CMLWorker Event Handlers -> etcd Projections
# =============================================================================


class CMLWorkerCreatedEtcdProjector(DomainEventHandler[CMLWorkerCreatedDomainEvent]):
    """Project worker creation to etcd for controller watch.

    Publishes both status and desired_status on creation.
    """

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: CMLWorkerCreatedDomainEvent) -> None:  # type: ignore[override]
        # Publish current status
        await self._etcd.set_worker_state(event.aggregate_id, event.status.value)
        # Publish desired_status (spec) - ADR-015
        await self._etcd.set_worker_desired_state(event.aggregate_id, event.desired_status.value)
        log.debug(f"[etcd] Projected worker.created: {event.aggregate_id} -> status={event.status.value}, desired_status={event.desired_status.value}")
        return None


class CMLWorkerStatusUpdatedEtcdProjector(DomainEventHandler[CMLWorkerStatusUpdatedDomainEvent]):
    """Project worker status changes to etcd for controller watch."""

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: CMLWorkerStatusUpdatedDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.set_worker_state(event.aggregate_id, event.new_status.value)
        log.info(f"[etcd] Projected worker.status.updated: {event.aggregate_id} {event.old_status.value} -> {event.new_status.value}")
        return None


class CMLWorkerDesiredStatusUpdatedEtcdProjector(DomainEventHandler[CMLWorkerDesiredStatusUpdatedDomainEvent]):
    """Project worker desired_status (spec) changes to etcd for controller watch.

    ADR-015: When desired_status changes, worker-controller needs immediate notification
    to start reconciliation. This projector publishes to /workers/{id}/desired_state
    which the worker-controller watches.

    Pattern: Spec (desired_status) vs State (status)
    - desired_status = what user wants (spec)
    - status = actual EC2 state (state)
    - worker-controller reconciles when desired_status != status
    """

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: CMLWorkerDesiredStatusUpdatedDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.set_worker_desired_state(event.aggregate_id, event.new_desired_status.value)
        log.info(
            f"[etcd] Projected worker.desired_status.updated: {event.aggregate_id} "
            f"{event.old_desired_status.value} -> {event.new_desired_status.value} "
            f"(reason={event.reason}, requested_by={event.requested_by})"
        )
        return None


class CMLWorkerTerminatedEtcdProjector(DomainEventHandler[CMLWorkerTerminatedDomainEvent]):
    """Project worker termination to etcd (delete state) for controller watch."""

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: CMLWorkerTerminatedDomainEvent) -> None:  # type: ignore[override]
        # Delete worker state from etcd (controllers will see DELETE event)
        await self._etcd.delete_worker_state(event.aggregate_id)
        log.info(f"[etcd] Projected worker.terminated: {event.aggregate_id} (state deleted)")
        return None


# =============================================================================
# CMLWorker License Event Handlers -> etcd Projections (ADR-016)
# =============================================================================


class CMLWorkerLicenseRegistrationRequestedEtcdProjector(DomainEventHandler[CMLWorkerLicenseRegistrationRequestedDomainEvent]):
    """Project license registration request to etcd for controller watch.

    ADR-016: When license registration is requested, worker-controller needs
    immediate notification to start reconciliation. This projector publishes
    to /workers/{id}/license which the worker-controller watches.

    Pattern: Pending Operation
    - User requests license registration via control-plane-api
    - control-plane-api stores intent (pending_operation="register") in DB
    - This projector publishes to etcd for reactive notification
    - worker-controller watches and reconciles by calling CML API
    """

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: CMLWorkerLicenseRegistrationRequestedDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.set_worker_license_pending(
            worker_id=event.aggregate_id,
            operation="register",
            token=event.license_token,
            reregister=event.reregister,
        )
        log.info(f"[etcd] Projected worker.license.registration.requested: {event.aggregate_id} (reregister={event.reregister}, initiated_by={event.initiated_by})")
        return None


class CMLWorkerLicenseRegistrationCompletedEtcdProjector(DomainEventHandler[CMLWorkerLicenseRegistrationCompletedDomainEvent]):
    """Project license registration completion to etcd (clear pending).

    ADR-016: After license registration completes successfully, clear the
    pending operation from etcd. This allows the controller to see that
    the operation is complete.
    """

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: CMLWorkerLicenseRegistrationCompletedDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.delete_worker_license_pending(event.aggregate_id)
        log.info(f"[etcd] Projected worker.license.registration.completed: {event.aggregate_id} (status={event.registration_status})")
        return None


class CMLWorkerLicenseDeregistrationRequestedEtcdProjector(DomainEventHandler[CMLWorkerLicenseDeregistrationRequestedDomainEvent]):
    """Project license deregistration request to etcd for controller watch.

    ADR-016: When license deregistration is requested, worker-controller needs
    immediate notification to start reconciliation. This projector publishes
    to /workers/{id}/license which the worker-controller watches.

    Pattern: Pending Operation
    - User requests license deregistration via control-plane-api
    - control-plane-api stores intent (pending_operation="deregister") in DB
    - This projector publishes to etcd for reactive notification
    - worker-controller watches and reconciles by calling CML API
    """

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: CMLWorkerLicenseDeregistrationRequestedDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.set_worker_license_pending(
            worker_id=event.aggregate_id,
            operation="deregister",
        )
        log.info(f"[etcd] Projected worker.license.deregistration.requested: {event.aggregate_id} (initiated_by={event.initiated_by})")
        return None


class CMLWorkerLicenseDeregistrationCompletedEtcdProjector(DomainEventHandler[CMLWorkerLicenseDeregistrationCompletedDomainEvent]):
    """Project license deregistration completion to etcd (clear pending).

    ADR-016: After license deregistration completes successfully, clear the
    pending operation from etcd. This allows the controller to see that
    the operation is complete.
    """

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: CMLWorkerLicenseDeregistrationCompletedDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.delete_worker_license_pending(event.aggregate_id)
        log.info(f"[etcd] Projected worker.license.deregistration.completed: {event.aggregate_id} (message={event.message})")
        return None


# =============================================================================
# LabletSession Event Handlers -> etcd Projections (Phase 7E)
# =============================================================================


class LabletSessionCreatedEtcdProjector(DomainEventHandler[LabletSessionCreatedDomainEvent]):
    """Project session creation to etcd for controller/scheduler watch."""

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: LabletSessionCreatedDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.set_session_state(event.aggregate_id, "PENDING")
        log.debug(f"[etcd] Projected session.created: {event.aggregate_id} -> PENDING")
        return None


class LabletSessionScheduledEtcdProjector(DomainEventHandler[LabletSessionScheduledDomainEvent]):
    """Project session scheduling to etcd for controller watch."""

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: LabletSessionScheduledDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.set_session_state(event.aggregate_id, "SCHEDULED")

        # Also store scheduling metadata for lablet-controller to read
        import json

        metadata = json.dumps(
            {
                "worker_id": event.worker_id,
                "allocated_ports": event.allocated_ports,
                "scheduled_at": _utc_iso(event.scheduled_at),
            }
        )
        await self._etcd._etcd.put(f"/sessions/{event.aggregate_id}/metadata", metadata)

        log.info(f"[etcd] Projected session.scheduled: {event.aggregate_id} -> SCHEDULED (worker={event.worker_id})")
        return None


class LabletSessionInstantiatingEtcdProjector(DomainEventHandler[LabletSessionInstantiatingDomainEvent]):
    """Project session instantiation start to etcd."""

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: LabletSessionInstantiatingDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.set_session_state(event.aggregate_id, "INSTANTIATING")
        log.debug(f"[etcd] Projected session.instantiating: {event.aggregate_id} -> INSTANTIATING")
        return None


class LabletSessionRunningEtcdProjector(DomainEventHandler[LabletSessionRunningDomainEvent]):
    """Project session running state to etcd."""

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: LabletSessionRunningDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.set_session_state(event.aggregate_id, "RUNNING")
        log.info(f"[etcd] Projected session.running: {event.aggregate_id} -> RUNNING")
        return None


class LabletSessionCollectingEtcdProjector(DomainEventHandler[LabletSessionCollectingDomainEvent]):
    """Project session collecting state to etcd."""

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: LabletSessionCollectingDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.set_session_state(event.aggregate_id, "COLLECTING")
        log.debug(f"[etcd] Projected session.collecting: {event.aggregate_id} -> COLLECTING")
        return None


class LabletSessionGradingEtcdProjector(DomainEventHandler[LabletSessionGradingDomainEvent]):
    """Project session grading state to etcd."""

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: LabletSessionGradingDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.set_session_state(event.aggregate_id, "GRADING")
        log.debug(f"[etcd] Projected session.grading: {event.aggregate_id} -> GRADING")
        return None


class LabletSessionStoppingEtcdProjector(DomainEventHandler[LabletSessionStoppingDomainEvent]):
    """Project session stopping state to etcd."""

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: LabletSessionStoppingDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.set_session_state(event.aggregate_id, "STOPPING")
        log.debug(f"[etcd] Projected session.stopping: {event.aggregate_id} -> STOPPING")
        return None


class LabletSessionStoppedEtcdProjector(DomainEventHandler[LabletSessionStoppedDomainEvent]):
    """Project session stopped state to etcd."""

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: LabletSessionStoppedDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.set_session_state(event.aggregate_id, "STOPPED")
        log.info(f"[etcd] Projected session.stopped: {event.aggregate_id} -> STOPPED")
        return None


class LabletSessionRequeuedEtcdProjector(DomainEventHandler[LabletSessionRequeuedDomainEvent]):
    """Project session requeue to etcd for controller watch.

    Re-writes the current state to etcd. Even though the value may be the same,
    etcd fires a watch event on every PUT (revision increments), which triggers
    immediate reconciliation in lablet-controller.
    """

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: LabletSessionRequeuedDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.set_session_state(event.aggregate_id, event.current_status.upper())
        log.info(f"[etcd] Projected session.requeued: {event.aggregate_id} (re-wrote state={event.current_status}, by={event.requeued_by}, reason={event.reason})")
        return None


class LabletSessionTerminatedEtcdProjector(DomainEventHandler[LabletSessionTerminatedDomainEvent]):
    """Project session termination to etcd (delete state)."""

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: LabletSessionTerminatedDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.delete_session_state(event.aggregate_id)
        log.info(f"[etcd] Projected session.terminated: {event.aggregate_id} (state deleted)")
        return None


class ObserveResourcesRequestedEtcdProjector(DomainEventHandler[LabletSessionObserveResourcesRequestedDomainEvent]):
    """Project observation request to etcd for lablet-controller watch.

    ADR-030 / AD-OLR-007: When an admin requests resource observation,
    write the request to etcd. LabletReconciler in lablet-controller watches
    the /sessions/ prefix and reacts to observe_resources keys immediately.
    """

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: LabletSessionObserveResourcesRequestedDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.set_session_observe_resources(
            session_id=event.aggregate_id,
            requested_by=event.requested_by,
            requested_at=_utc_iso(event.requested_at),
        )
        log.info(f"[etcd] Projected session.observe_resources_requested: {event.aggregate_id} (requested_by={event.requested_by})")
        return None


# =============================================================================
# Lab Record Pending Action Projectors (AD-023)
# =============================================================================


class LabActionRequestedEtcdProjector(DomainEventHandler[LabActionRequestedDomainEvent]):
    """Project lab action request to etcd for lablet-controller watch.

    AD-023: When a lab action is requested (start/stop/wipe/delete), write the
    pending action to etcd. LabRecordReconciler in lablet-controller watches
    the /lab_records/ prefix and reacts immediately.
    """

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: LabActionRequestedDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.set_lab_pending_action(
            lab_record_id=event.aggregate_id,
            action=event.action,
            lab_id=event.lab_id,
            worker_id=event.worker_id,
            requested_at=_utc_iso(event.requested_at),
        )
        log.info(f"[etcd] Projected lab_record.action_requested: {event.aggregate_id} -> {event.action} (lab={event.lab_id}, worker={event.worker_id})")
        return None


class LabActionCompletedEtcdProjector(DomainEventHandler[LabActionCompletedDomainEvent]):
    """Clear lab pending action from etcd after successful completion."""

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: LabActionCompletedDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.delete_lab_pending_action(event.aggregate_id)
        log.info(f"[etcd] Projected lab_record.action_completed: {event.aggregate_id} -> {event.action} (pending action cleared)")
        return None


class LabActionFailedEtcdProjector(DomainEventHandler[LabActionFailedDomainEvent]):
    """Clear lab pending action from etcd after failure."""

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: LabActionFailedDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.delete_lab_pending_action(event.aggregate_id)
        log.info(f"[etcd] Projected lab_record.action_failed: {event.aggregate_id} -> {event.action} (pending action cleared)")
        return None


class LabActionClearedEtcdProjector(DomainEventHandler[LabActionClearedDomainEvent]):
    """Clear lab pending action from etcd when manually cleared."""

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: LabActionClearedDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.delete_lab_pending_action(event.aggregate_id)
        log.info(f"[etcd] Projected lab_record.action_cleared: {event.aggregate_id} (pending action cleared)")
        return None


# =============================================================================
# LabletDefinition Content Sync Projectors (AD-CS-001)
# =============================================================================


class ContentSyncRequestedEtcdProjector(DomainEventHandler[LabletDefinitionSyncRequestedDomainEvent]):
    """Project content sync request to etcd for lablet-controller watch.

    AD-CS-001: When a sync is requested (via SyncLabletDefinitionCommand),
    write the sync request to etcd. ContentSyncService in lablet-controller
    watches the /definitions/ prefix and reacts immediately.
    """

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: LabletDefinitionSyncRequestedDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.set_definition_content_sync(
            definition_id=event.aggregate_id,
            name="",  # Name not in event — lablet-controller fetches full definition via internal API
            version="",
            form_qualified_name=event.form_qualified_name,
            requested_by=event.requested_by,
            requested_at=event.requested_at,
        )
        log.info(f"[etcd] Projected definition.sync_requested: {event.aggregate_id} (fqn={event.form_qualified_name}, bucket={event.bucket_name})")
        return None


class ContentSyncCompletedEtcdProjector(DomainEventHandler[LabletDefinitionContentSyncedDomainEvent]):
    """Clear content sync key from etcd after sync completes.

    AD-CS-001: After lablet-controller reports sync result (success or failure),
    remove the etcd key so the definition is no longer picked up by watch.
    """

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: LabletDefinitionContentSyncedDomainEvent) -> None:  # type: ignore[override]
        await self._etcd.delete_definition_content_sync(event.aggregate_id)
        log.info(f"[etcd] Projected definition.content_synced: {event.aggregate_id} (sync_status={event.sync_status}, pending sync key cleared)")
        return None
