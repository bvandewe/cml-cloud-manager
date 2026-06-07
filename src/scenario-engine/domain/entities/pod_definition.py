"""PodDefinition Entity — represents content synced from BlobStorage.

Uses Neuroglia AggregateRoot[State, Key] pattern with event-driven state transitions.
Event handlers are defined on the State class using @dispatch.
Mirrors lcm_core.domain.enums.PodDefinitionStatus lifecycle.

Lifecycle: DEFINED → SYNCHRONIZING → READY → EXPIRED | SUPERSEDED
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from lcm_core.domain.enums import PodDefinitionStatus, PodType
from multipledispatch import dispatch
from neuroglia.data.abstractions import AggregateRoot, AggregateState

from domain.events.pod_definition_events import (
    PodDefinitionCreatedDomainEvent,
    PodDefinitionExpiredDomainEvent,
    PodDefinitionReadyDomainEvent,
    PodDefinitionSupersededDomainEvent,
    PodDefinitionSyncFailedDomainEvent,
    PodDefinitionSyncStartedDomainEvent,
)

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------------
# Aggregate State
# -------------------------------------------------------------------------


class PodDefinitionState(AggregateState[str]):
    """Encapsulates the persisted state for the PodDefinition aggregate.

    PodDefinitions represent content packages synced from BlobStorage (S3).
    Event handlers are defined on the State class using @dispatch.
    """

    id: str
    name: str
    version: str
    pod_type: PodType
    status: PodDefinitionStatus
    source_uri: str
    local_path: str | None
    manifest: dict[str, Any]
    created_at: datetime | None
    synced_at: datetime | None

    # PAv1 first-class typed fields (AD-CSI-004 / G-03).
    # All optional with safe defaults so Neuroglia rehydration of existing
    # MongoDB docs (which bypass __init__) tolerates missing keys via getattr.
    content_hash: str | None
    topology: dict[str, Any] | None
    devices: list[dict[str, Any]] | None
    lifecycle_phases: dict[str, Any] | None
    scenarios: dict[str, dict[str, Any]] | None
    grading_rules: dict[str, Any] | None
    reports: dict[str, Any] | None
    restore_rules: dict[str, Any] | None

    # Failure diagnostics (AD-CSI-011 / Phase 1 G-01).
    error_message: str | None
    error_detail: str | None
    failed_at: datetime | None

    def __init__(self) -> None:
        super().__init__()
        self.id = ""
        self.name = ""
        self.version = ""
        self.pod_type = PodType.CML_ON_AWS
        self.status = PodDefinitionStatus.DEFINED
        self.source_uri = ""
        self.local_path = None
        self.manifest = {}
        self.created_at = None
        self.synced_at = None
        # PAv1 extracted fields (AD-CSI-004)
        self.content_hash = None
        self.topology = None
        self.devices = None
        self.lifecycle_phases = None
        self.scenarios = None
        self.grading_rules = None
        self.reports = None
        self.restore_rules = None
        # Failure diagnostics (AD-CSI-011)
        self.error_message = None
        self.error_detail = None
        self.failed_at = None

    # -------------------------------------------------------------------------
    # Event Handlers
    # -------------------------------------------------------------------------

    @dispatch(PodDefinitionCreatedDomainEvent)
    def on(self, event: PodDefinitionCreatedDomainEvent) -> None:  # type: ignore[override]
        self.id = event.aggregate_id
        self.name = event.name
        self.version = event.version
        self.pod_type = PodType(event.pod_type)
        self.source_uri = event.source_uri
        self.status = PodDefinitionStatus.DEFINED
        self.created_at = event.created_at

    @dispatch(PodDefinitionSyncStartedDomainEvent)
    def on(self, event: PodDefinitionSyncStartedDomainEvent) -> None:  # type: ignore[override]
        self.status = PodDefinitionStatus.SYNCHRONIZING
        # Clear stale failure diagnostics on retry / force re-sync.
        self.error_message = None
        self.error_detail = None
        self.failed_at = None

    @dispatch(PodDefinitionReadyDomainEvent)
    def on(self, event: PodDefinitionReadyDomainEvent) -> None:  # type: ignore[override]
        self.status = PodDefinitionStatus.READY
        self.local_path = event.local_path
        self.manifest = event.manifest
        self.synced_at = event.synced_at
        # PAv1 extracted fields (AD-CSI-004). Defensive getattr keeps older
        # events that predate G-03 backward-compatible during rehydration.
        self.content_hash = getattr(event, "content_hash", None)
        self.topology = getattr(event, "topology", None)
        self.devices = getattr(event, "devices", None)
        self.lifecycle_phases = getattr(event, "lifecycle_phases", None)
        self.scenarios = getattr(event, "scenarios", None)
        self.grading_rules = getattr(event, "grading_rules", None)
        self.reports = getattr(event, "reports", None)
        self.restore_rules = getattr(event, "restore_rules", None)

    @dispatch(PodDefinitionExpiredDomainEvent)
    def on(self, event: PodDefinitionExpiredDomainEvent) -> None:  # type: ignore[override]
        self.status = PodDefinitionStatus.EXPIRED

    @dispatch(PodDefinitionSupersededDomainEvent)
    def on(self, event: PodDefinitionSupersededDomainEvent) -> None:  # type: ignore[override]
        self.status = PodDefinitionStatus.SUPERSEDED

    @dispatch(PodDefinitionSyncFailedDomainEvent)
    def on(self, event: PodDefinitionSyncFailedDomainEvent) -> None:  # type: ignore[override]
        self.status = PodDefinitionStatus.FAILED
        self.error_message = event.reason
        self.error_detail = event.error_detail
        self.failed_at = event.failed_at


# -------------------------------------------------------------------------
# Aggregate Root
# -------------------------------------------------------------------------


class PodDefinition(AggregateRoot[PodDefinitionState, str]):
    """PodDefinition aggregate root — content package synced from BlobStorage.

    Represents a content package (PAv1/) that has been synced on-demand
    from BlobStorage (S3). Used by scenarios to access lab definitions,
    grading rules, and automation workflows.
    """

    def __init__(self) -> None:
        super().__init__()

    def id(self) -> str:
        return self.state.id

    @staticmethod
    def create(
        name: str,
        version: str,
        pod_type: PodType,
        source_uri: str,
        definition_id: str | None = None,
    ) -> PodDefinition:
        """Create a new PodDefinition aggregate.

        Args:
            name: Content package name.
            version: Content version.
            pod_type: Pod type (CML_ON_AWS, ROC_RADKIT, etc.).
            source_uri: BlobStorage URI for the content package.
            definition_id: Optional specific ID (for testing/seeding).

        Returns:
            New PodDefinition aggregate with PodDefinitionCreatedDomainEvent recorded.
        """
        if not name:
            raise ValueError("name cannot be empty")
        if not source_uri:
            raise ValueError("source_uri cannot be empty")

        pod_def = PodDefinition()
        now = datetime.now(timezone.utc)
        event = PodDefinitionCreatedDomainEvent(
            aggregate_id=definition_id or str(uuid4()),
            name=name,
            version=version,
            pod_type=pod_type.value,  # Serialize enum for CloudEvent
            source_uri=source_uri,
            created_at=now,
        )
        pod_def.state.on(pod_def.register_event(event))
        return pod_def

    def start_sync(self) -> None:
        """Transition to SYNCHRONIZING state."""
        event = PodDefinitionSyncStartedDomainEvent(aggregate_id=self.state.id)
        self.state.on(self.register_event(event))

    def mark_ready(
        self,
        local_path: str,
        manifest: dict[str, Any],
        content_hash: str | None = None,
        topology: dict[str, Any] | None = None,
        devices: list[dict[str, Any]] | None = None,
        lifecycle_phases: dict[str, Any] | None = None,
        scenarios: dict[str, dict[str, Any]] | None = None,
        grading_rules: dict[str, Any] | None = None,
        reports: dict[str, Any] | None = None,
        restore_rules: dict[str, Any] | None = None,
    ) -> None:
        """Transition to READY after successful content sync.

        Args:
            local_path: Local filesystem path where content was extracted.
            manifest: Parsed manifest.yaml contents.
            content_hash: SHA-256 of the source package (AD-CSI-004).
            topology: Parsed topology/<engine>.yaml contents.
            devices: Parsed devices.json / equivalent.
            lifecycle_phases: Parsed lifecycle.yaml phases map.
            scenarios: Parsed scenarios/*.yaml indexed by name@version.
            grading_rules: Parsed grading/*.yaml contents.
            reports: Parsed reports/*.yaml contents.
            restore_rules: Parsed restore/*.yaml contents.
        """
        now = datetime.now(timezone.utc)
        event = PodDefinitionReadyDomainEvent(
            aggregate_id=self.state.id,
            local_path=local_path,
            manifest=manifest,
            synced_at=now,
            content_hash=content_hash,
            topology=topology,
            devices=devices,
            lifecycle_phases=lifecycle_phases,
            scenarios=scenarios,
            grading_rules=grading_rules,
            reports=reports,
            restore_rules=restore_rules,
        )
        self.state.on(self.register_event(event))

    def expire(self) -> None:
        """Transition to EXPIRED (content stale)."""
        event = PodDefinitionExpiredDomainEvent(aggregate_id=self.state.id)
        self.state.on(self.register_event(event))

    def supersede(self, superseded_by: str) -> None:
        """Transition to SUPERSEDED by a newer version.

        Args:
            superseded_by: ID of the newer PodDefinition that replaces this one.
        """
        event = PodDefinitionSupersededDomainEvent(aggregate_id=self.state.id, superseded_by=superseded_by)
        self.state.on(self.register_event(event))

    def mark_failed(self, reason: str, error_detail: str | None = None) -> None:
        """Transition to FAILED after a sync error (AD-CSI-011 / Phase 1 G-01).

        Args:
            reason: Short, human-readable failure summary (e.g. ``"S3 download failed"``).
            error_detail: Optional detailed payload (e.g. traceback or schema errors).
        """
        event = PodDefinitionSyncFailedDomainEvent(
            aggregate_id=self.state.id,
            reason=reason,
            error_detail=error_detail,
        )
        self.state.on(self.register_event(event))
