"""PodDefinition Domain Events — state transitions for content sync.

Uses Neuroglia DomainEvent base class with @cloudevent decorator for
CloudEvent-compatible event publication.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from neuroglia.data.abstractions import DomainEvent
from neuroglia.eventing.cloud_events.decorators import cloudevent


@cloudevent("scenario_engine.pod_definition.created.v1")
@dataclass
class PodDefinitionCreatedDomainEvent(DomainEvent):
    """Raised when a new PodDefinition is created."""

    aggregate_id: str
    name: str
    version: str
    pod_type: str  # Serialized as string for CloudEvent compatibility
    source_uri: str
    created_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        name: str,
        version: str,
        pod_type: str,
        source_uri: str,
        created_at: datetime | None = None,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.name = name
        self.version = version
        self.pod_type = pod_type
        self.source_uri = source_uri
        self.created_at = created_at or datetime.now()


@cloudevent("scenario_engine.pod_definition.sync_started.v1")
@dataclass
class PodDefinitionSyncStartedDomainEvent(DomainEvent):
    """Raised when content sync begins."""

    aggregate_id: str
    started_at: datetime

    def __init__(self, aggregate_id: str, started_at: datetime | None = None) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.started_at = started_at or datetime.now()


@cloudevent("scenario_engine.pod_definition.ready.v1")
@dataclass
class PodDefinitionReadyDomainEvent(DomainEvent):
    """Raised when content sync completes successfully.

    Phase 0 (AD-CSI-004): carries first-class typed fields extracted from
    the PAv1/ tree alongside the raw ``manifest`` blob. All extracted fields
    are optional so callers that do not yet populate them remain backward
    compatible — existing rehydrated state simply keeps its defaults.
    """

    aggregate_id: str
    local_path: str
    manifest: dict[str, Any]
    synced_at: datetime
    # PAv1 extracted fields (AD-CSI-004 / G-03)
    content_hash: str | None
    topology: dict[str, Any] | None
    devices: list[dict[str, Any]] | None
    lifecycle_phases: dict[str, Any] | None
    scenarios: dict[str, dict[str, Any]] | None
    grading_rules: dict[str, Any] | None
    reports: dict[str, Any] | None
    restore_rules: dict[str, Any] | None

    def __init__(
        self,
        aggregate_id: str,
        local_path: str,
        manifest: dict[str, Any],
        synced_at: datetime | None = None,
        content_hash: str | None = None,
        topology: dict[str, Any] | None = None,
        devices: list[dict[str, Any]] | None = None,
        lifecycle_phases: dict[str, Any] | None = None,
        scenarios: dict[str, dict[str, Any]] | None = None,
        grading_rules: dict[str, Any] | None = None,
        reports: dict[str, Any] | None = None,
        restore_rules: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.local_path = local_path
        self.manifest = manifest
        self.synced_at = synced_at or datetime.now()
        self.content_hash = content_hash
        self.topology = topology
        self.devices = devices
        self.lifecycle_phases = lifecycle_phases
        self.scenarios = scenarios
        self.grading_rules = grading_rules
        self.reports = reports
        self.restore_rules = restore_rules


@cloudevent("scenario_engine.pod_definition.sync_failed.v1")
@dataclass
class PodDefinitionSyncFailedDomainEvent(DomainEvent):
    """Raised when content sync fails (Phase 1, G-01).

    Shipped in Phase 0 so the event class is available to all consumers; the
    aggregate method that emits it lands with Phase 1's ``SyncContentCommand``
    rewrite.
    """

    aggregate_id: str
    reason: str
    error_detail: str | None
    failed_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        reason: str,
        error_detail: str | None = None,
        failed_at: datetime | None = None,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.reason = reason
        self.error_detail = error_detail
        self.failed_at = failed_at or datetime.now()


@cloudevent("scenario_engine.pod_definition.expired.v1")
@dataclass
class PodDefinitionExpiredDomainEvent(DomainEvent):
    """Raised when a PodDefinition expires (content stale)."""

    aggregate_id: str
    expired_at: datetime

    def __init__(self, aggregate_id: str, expired_at: datetime | None = None) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.expired_at = expired_at or datetime.now()


@cloudevent("scenario_engine.pod_definition.superseded.v1")
@dataclass
class PodDefinitionSupersededDomainEvent(DomainEvent):
    """Raised when a PodDefinition is superseded by a newer version."""

    aggregate_id: str
    superseded_by: str
    superseded_at: datetime

    def __init__(self, aggregate_id: str, superseded_by: str, superseded_at: datetime | None = None) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.superseded_by = superseded_by
        self.superseded_at = superseded_at or datetime.now()
