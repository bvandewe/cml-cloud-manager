"""WorkerTemplate aggregate definition using the AggregateState pattern.

A WorkerTemplate represents a predefined EC2 instance configuration for CML workers.
Templates are seeded from YAML configuration on startup and stored in MongoDB
for consistent worker provisioning.

Per ADR-007: Templates are managed as configuration, not user-created entities.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from multipledispatch import dispatch
from neuroglia.data.abstractions import AggregateRoot, AggregateState

from domain.events.worker_template_events import (
    WorkerTemplateCreatedDomainEvent,
    WorkerTemplateDeletedDomainEvent,
    WorkerTemplateDisabledDomainEvent,
    WorkerTemplateEnabledDomainEvent,
    WorkerTemplateUpdatedDomainEvent,
)
from domain.value_objects.worker_capacity import WorkerCapacity
from integration.enums import Ec2InstanceType

# -------------------------------------------------------------------------
# Aggregate State
# -------------------------------------------------------------------------


class WorkerTemplateState(AggregateState[str]):
    """Encapsulates the persisted state for the WorkerTemplate aggregate.

    Templates define the compute capacity and configuration for worker provisioning.
    Event handlers are defined on the State class using @dispatch.
    """

    id: str
    name: str  # Unique template name (e.g., "small", "medium", "large", "metal")
    description: str

    # EC2 configuration
    instance_type: Ec2InstanceType
    ami_name_pattern: str  # AMI name pattern for lookup (e.g., "CML-2.*-Ubuntu-*")

    # Compute capacity
    capacity: WorkerCapacity

    # Cost tracking (for scheduling optimization)
    cost_per_hour_usd: float

    # Status
    enabled: bool  # Whether this template can be used for new workers
    deleted: bool
    deleted_at: datetime | None

    # Metadata
    created_at: datetime
    updated_at: datetime

    def __init__(self) -> None:
        super().__init__()
        self.id = ""
        self.name = ""
        self.description = ""
        self.instance_type = Ec2InstanceType.SMALL
        self.ami_name_pattern = ""
        self.capacity = WorkerCapacity.zero()
        self.cost_per_hour_usd = 0.0
        self.enabled = True
        self.deleted = False
        self.deleted_at = None
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    # -------------------------------------------------------------------------
    # Event Handlers (using @dispatch pattern on State class)
    # -------------------------------------------------------------------------

    @dispatch(WorkerTemplateCreatedDomainEvent)
    def on(self, event: WorkerTemplateCreatedDomainEvent) -> None:  # type: ignore[override]
        """Handle WorkerTemplateCreatedDomainEvent."""
        self.id = event.aggregate_id
        self.name = event.name
        # Deserialize from CloudEvent-compatible format
        self.instance_type = Ec2InstanceType(event.instance_type)
        self.capacity = WorkerCapacity.from_dict(event.capacity)
        self.cost_per_hour_usd = event.cost_per_hour_usd
        self.created_at = event.created_at
        self.updated_at = event.created_at

    @dispatch(WorkerTemplateUpdatedDomainEvent)
    def on(self, event: WorkerTemplateUpdatedDomainEvent) -> None:  # type: ignore[override]
        """Handle WorkerTemplateUpdatedDomainEvent."""
        for field, change in event.changes.items():
            if field == "description":
                self.description = change["to"]
            elif field == "instance_type":
                self.instance_type = Ec2InstanceType(change["to"])
            elif field == "capacity":
                self.capacity = WorkerCapacity.from_dict(change["to"])
            elif field == "ami_name_pattern":
                self.ami_name_pattern = change["to"]
            elif field == "cost_per_hour_usd":
                self.cost_per_hour_usd = change["to"]
            elif field == "enabled":
                self.enabled = change["to"]
        self.updated_at = event.updated_at

    @dispatch(WorkerTemplateDisabledDomainEvent)
    def on(self, event: WorkerTemplateDisabledDomainEvent) -> None:  # type: ignore[override]
        """Handle WorkerTemplateDisabledDomainEvent."""
        self.enabled = False
        self.updated_at = event.disabled_at

    @dispatch(WorkerTemplateEnabledDomainEvent)
    def on(self, event: WorkerTemplateEnabledDomainEvent) -> None:  # type: ignore[override]
        """Handle WorkerTemplateEnabledDomainEvent."""
        self.enabled = True
        self.updated_at = event.enabled_at

    @dispatch(WorkerTemplateDeletedDomainEvent)
    def on(self, event: WorkerTemplateDeletedDomainEvent) -> None:
        """Handle WorkerTemplateDeletedDomainEvent (soft delete)."""
        self.deleted = True
        self.enabled = False
        self.deleted_at = event.deleted_at
        self.updated_at = event.deleted_at


# -------------------------------------------------------------------------
# Aggregate Root
# -------------------------------------------------------------------------


class WorkerTemplate(AggregateRoot[WorkerTemplateState, str]):
    """WorkerTemplate aggregate root.

    Represents a predefined worker configuration template for provisioning
    CML workers with consistent capacity and settings.

    Templates are typically seeded from YAML configuration and stored in MongoDB.
    They are referenced when creating new workers to determine instance type,
    capacity, and other provisioning parameters.
    """

    def __init__(self) -> None:
        super().__init__()

    def id(self) -> str:
        return self.state.id

    @staticmethod
    def create(
        name: str,
        description: str,
        instance_type: Ec2InstanceType,
        capacity: WorkerCapacity,
        ami_name_pattern: str = "cisco-cml2.9*",
        cost_per_hour_usd: float = 0.0,
        enabled: bool = True,
        template_id: str | None = None,
    ) -> "WorkerTemplate":
        """Create a new WorkerTemplate.

        Args:
            name: Unique template name (e.g., "small", "medium", "large")
            description: Human-readable description
            instance_type: AWS EC2 instance type
            capacity: Compute capacity specification
            ami_name_pattern: AMI name pattern for lookup
            cost_per_hour_usd: Estimated hourly cost for scheduling optimization
            enabled: Whether template can be used for new workers
            template_id: Optional specific ID (for seeding)

        Returns:
            New WorkerTemplate aggregate
        """
        if not name:
            raise ValueError("name cannot be empty")
        if not description:
            raise ValueError("description cannot be empty")

        template = WorkerTemplate()
        now = datetime.now(timezone.utc)
        event = WorkerTemplateCreatedDomainEvent(
            aggregate_id=template_id or str(uuid4()),
            name=name,
            instance_type=instance_type.value,  # Serialize enum to string for CloudEvent
            capacity=capacity.to_dict(),  # Serialize to dict for CloudEvent
            cost_per_hour_usd=cost_per_hour_usd,
            created_at=now,
        )
        # Register event and apply to state (following LabletDefinition pattern)
        template.state.on(template.register_event(event))

        # Set additional fields not in event
        template.state.description = description
        template.state.ami_name_pattern = ami_name_pattern
        template.state.enabled = enabled

        return template

    def update(
        self,
        description: str | None = None,
        instance_type: Ec2InstanceType | None = None,
        capacity: WorkerCapacity | None = None,
        ami_name_pattern: str | None = None,
        cost_per_hour_usd: float | None = None,
        enabled: bool | None = None,
    ) -> None:
        """Update template configuration.

        Args:
            description: New description (optional)
            instance_type: New instance type (optional)
            capacity: New capacity specification (optional)
            ami_name_pattern: New AMI pattern (optional)
            cost_per_hour_usd: New cost estimate (optional)
            enabled: New enabled status (optional)
        """
        changes: dict[str, Any] = {}

        if description is not None and description != self.state.description:
            changes["description"] = {"from": self.state.description, "to": description}
        if instance_type is not None and instance_type != self.state.instance_type:
            changes["instance_type"] = {"from": self.state.instance_type.value, "to": instance_type.value}
        if capacity is not None and capacity != self.state.capacity:
            changes["capacity"] = {"from": self.state.capacity.to_dict(), "to": capacity.to_dict()}
        if ami_name_pattern is not None and ami_name_pattern != self.state.ami_name_pattern:
            changes["ami_name_pattern"] = {"from": self.state.ami_name_pattern, "to": ami_name_pattern}
        if cost_per_hour_usd is not None and cost_per_hour_usd != self.state.cost_per_hour_usd:
            changes["cost_per_hour_usd"] = {"from": self.state.cost_per_hour_usd, "to": cost_per_hour_usd}
        if enabled is not None and enabled != self.state.enabled:
            changes["enabled"] = {"from": self.state.enabled, "to": enabled}

        if changes:
            event = WorkerTemplateUpdatedDomainEvent(
                aggregate_id=self.state.id,
                name=self.state.name,
                changes=changes,
                updated_at=datetime.now(timezone.utc),
            )
            self.state.on(self.register_event(event))

    def disable(self) -> None:
        """Disable this template for new worker provisioning."""
        if self.state.enabled:
            event = WorkerTemplateDisabledDomainEvent(
                aggregate_id=self.state.id,
                name=self.state.name,
                disabled_at=datetime.now(timezone.utc),
            )
            self.state.on(self.register_event(event))

    def enable(self) -> None:
        """Enable this template for new worker provisioning."""
        if not self.state.enabled:
            event = WorkerTemplateEnabledDomainEvent(
                aggregate_id=self.state.id,
                name=self.state.name,
                enabled_at=datetime.now(timezone.utc),
            )
            self.state.on(self.register_event(event))

    def delete(self) -> None:
        """Soft-delete this template. Sets deleted=True and enabled=False."""
        if self.state.deleted:
            return  # Already deleted
        event = WorkerTemplateDeletedDomainEvent(
            aggregate_id=self.state.id,
            name=self.state.name,
            deleted_at=datetime.now(timezone.utc),
        )
        self.state.on(self.register_event(event))

    def can_satisfy(self, required: WorkerCapacity) -> bool:
        """Check if this template can satisfy required capacity.

        Args:
            required: Required capacity specification

        Returns:
            True if template capacity can satisfy requirements
        """
        return self.state.capacity.can_fit(required)
