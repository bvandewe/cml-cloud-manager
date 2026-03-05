"""Domain events for WorkerTemplate aggregate operations.

These events are raised when WorkerTemplate aggregates change state.
Templates are managed as configuration (not user-created) per ADR-007.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from neuroglia.data.abstractions import DomainEvent
from neuroglia.eventing.cloud_events.decorators import cloudevent


@cloudevent("worker_template.created.v1")
@dataclass
class WorkerTemplateCreatedDomainEvent(DomainEvent):
    """Event raised when a new WorkerTemplate is created."""

    aggregate_id: str
    name: str
    instance_type: str  # Serialized as string for CloudEvent compatibility
    capacity: dict[str, Any]  # Serialized WorkerCapacity
    cost_per_hour_usd: float
    created_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        name: str,
        instance_type: str,
        capacity: dict[str, Any],
        cost_per_hour_usd: float,
        created_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.name = name
        self.instance_type = instance_type
        self.capacity = capacity
        self.cost_per_hour_usd = cost_per_hour_usd
        self.created_at = created_at


@cloudevent("worker_template.updated.v1")
@dataclass
class WorkerTemplateUpdatedDomainEvent(DomainEvent):
    """Event raised when a WorkerTemplate is updated.

    The changes dict captures which fields were modified.
    """

    aggregate_id: str
    name: str
    changes: dict[str, Any]
    updated_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        name: str,
        changes: dict[str, Any],
        updated_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.name = name
        self.changes = changes
        self.updated_at = updated_at


@cloudevent("worker_template.disabled.v1")
@dataclass
class WorkerTemplateDisabledDomainEvent(DomainEvent):
    """Event raised when a WorkerTemplate is disabled.

    Disabled templates cannot be used for new worker provisioning.
    """

    aggregate_id: str
    name: str
    disabled_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        name: str,
        disabled_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.name = name
        self.disabled_at = disabled_at


@cloudevent("worker_template.enabled.v1")
@dataclass
class WorkerTemplateEnabledDomainEvent(DomainEvent):
    """Event raised when a WorkerTemplate is re-enabled."""

    aggregate_id: str
    name: str
    enabled_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        name: str,
        enabled_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.name = name
        self.enabled_at = enabled_at


@cloudevent("worker_template.deleted.v1")
@dataclass
class WorkerTemplateDeletedDomainEvent(DomainEvent):
    """Event raised when a WorkerTemplate is soft-deleted."""

    aggregate_id: str
    name: str
    deleted_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        name: str,
        deleted_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.name = name
        self.deleted_at = deleted_at
