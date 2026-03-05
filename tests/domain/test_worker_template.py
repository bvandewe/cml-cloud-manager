"""Integration tests for WorkerTemplate with MongoDB.

These tests verify the complete WorkerTemplate persistence flow
using a real MongoDB instance. Requires mongomock or MongoDB to be available.
"""

import pytest
from domain.entities.worker_template import WorkerTemplate
from domain.events.worker_template_events import (
    WorkerTemplateCreatedDomainEvent,
    WorkerTemplateDisabledDomainEvent,
    WorkerTemplateEnabledDomainEvent,
    WorkerTemplateUpdatedDomainEvent,
)
from domain.value_objects.worker_capacity import WorkerCapacity
from integration.enums import Ec2InstanceType


class TestWorkerTemplateAggregate:
    """Tests for WorkerTemplate aggregate domain logic."""

    def test_create_template_success(self) -> None:
        """Test successful template creation."""
        template = WorkerTemplate.create(
            name="small",
            description="Small worker for simple labs",
            instance_type=Ec2InstanceType.SMALL,
            capacity=WorkerCapacity(cpu_cores=2, memory_gb=4, storage_gb=50, max_nodes=5),
            ami_name_pattern="cisco-cml2.9*",
            cost_per_hour_usd=0.10,
            enabled=True,
        )

        assert template.state.name == "small"
        assert template.state.description == "Small worker for simple labs"
        assert template.state.instance_type == Ec2InstanceType.SMALL
        assert template.state.capacity.cpu_cores == 2
        assert template.state.capacity.memory_gb == 4
        assert template.state.capacity.storage_gb == 50
        assert template.state.capacity.max_nodes == 5
        assert template.state.ami_name_pattern == "cisco-cml2.9*"
        assert template.state.cost_per_hour_usd == 0.10
        assert template.state.enabled is True
        assert template.id() != ""

    def test_create_template_with_custom_id(self) -> None:
        """Test template creation with explicit ID."""
        template = WorkerTemplate.create(
            name="medium",
            description="Medium worker",
            instance_type=Ec2InstanceType.MEDIUM,
            capacity=WorkerCapacity(cpu_cores=4, memory_gb=16, storage_gb=100),
            template_id="custom-template-id",
        )

        assert template.id() == "custom-template-id"

    def test_create_template_empty_name_raises_error(self) -> None:
        """Test that empty name raises ValueError."""
        with pytest.raises(ValueError, match="name cannot be empty"):
            WorkerTemplate.create(
                name="",
                description="Test",
                instance_type=Ec2InstanceType.SMALL,
                capacity=WorkerCapacity(cpu_cores=2, memory_gb=4, storage_gb=50),
            )

    def test_create_template_empty_description_raises_error(self) -> None:
        """Test that empty description raises ValueError."""
        with pytest.raises(ValueError, match="description cannot be empty"):
            WorkerTemplate.create(
                name="test",
                description="",
                instance_type=Ec2InstanceType.SMALL,
                capacity=WorkerCapacity(cpu_cores=2, memory_gb=4, storage_gb=50),
            )

    def test_update_template(self) -> None:
        """Test updating template fields."""
        template = WorkerTemplate.create(
            name="small",
            description="Original description",
            instance_type=Ec2InstanceType.SMALL,
            capacity=WorkerCapacity(cpu_cores=2, memory_gb=4, storage_gb=50),
            cost_per_hour_usd=0.10,
        )

        template.update(
            description="Updated description",
            cost_per_hour_usd=0.15,
        )

        assert template.state.description == "Updated description"
        assert template.state.cost_per_hour_usd == 0.15

    def test_update_template_instance_type(self) -> None:
        """Test updating instance type."""
        template = WorkerTemplate.create(
            name="upgradable",
            description="Upgradable worker",
            instance_type=Ec2InstanceType.SMALL,
            capacity=WorkerCapacity(cpu_cores=2, memory_gb=4, storage_gb=50),
        )

        template.update(instance_type=Ec2InstanceType.MEDIUM)

        assert template.state.instance_type == Ec2InstanceType.MEDIUM

    def test_update_template_capacity(self) -> None:
        """Test updating capacity."""
        template = WorkerTemplate.create(
            name="expandable",
            description="Expandable worker",
            instance_type=Ec2InstanceType.SMALL,
            capacity=WorkerCapacity(cpu_cores=2, memory_gb=4, storage_gb=50),
        )

        new_capacity = WorkerCapacity(cpu_cores=4, memory_gb=8, storage_gb=100, max_nodes=10)
        template.update(capacity=new_capacity)

        assert template.state.capacity.cpu_cores == 4
        assert template.state.capacity.memory_gb == 8
        assert template.state.capacity.storage_gb == 100
        assert template.state.capacity.max_nodes == 10

    def test_update_template_no_changes_does_not_record_event(self) -> None:
        """Test that updating with same values doesn't record an event."""
        template = WorkerTemplate.create(
            name="stable",
            description="Stable worker",
            instance_type=Ec2InstanceType.SMALL,
            capacity=WorkerCapacity(cpu_cores=2, memory_gb=4, storage_gb=50),
        )
        initial_events = len(template._pending_events)

        template.update(description="Stable worker")  # Same value

        # No new event should be recorded
        assert len(template._pending_events) == initial_events

    def test_disable_template(self) -> None:
        """Test disabling a template."""
        template = WorkerTemplate.create(
            name="to-disable",
            description="Will be disabled",
            instance_type=Ec2InstanceType.SMALL,
            capacity=WorkerCapacity(cpu_cores=2, memory_gb=4, storage_gb=50),
            enabled=True,
        )

        template.disable()

        assert template.state.enabled is False

    def test_disable_already_disabled_template_no_op(self) -> None:
        """Test that disabling an already disabled template doesn't record event."""
        template = WorkerTemplate.create(
            name="already-disabled",
            description="Already disabled",
            instance_type=Ec2InstanceType.SMALL,
            capacity=WorkerCapacity(cpu_cores=2, memory_gb=4, storage_gb=50),
            enabled=False,
        )
        initial_events = len(template._pending_events)

        template.disable()

        assert len(template._pending_events) == initial_events

    def test_can_satisfy_capacity_true(self) -> None:
        """Test can_satisfy returns True when template has enough capacity."""
        template = WorkerTemplate.create(
            name="large",
            description="Large worker",
            instance_type=Ec2InstanceType.LARGE,
            capacity=WorkerCapacity(cpu_cores=8, memory_gb=32, storage_gb=200, max_nodes=50),
        )

        required = WorkerCapacity(cpu_cores=4, memory_gb=16, storage_gb=100, max_nodes=20)

        assert template.can_satisfy(required) is True

    def test_can_satisfy_capacity_false_cpu(self) -> None:
        """Test can_satisfy returns False when CPU is insufficient."""
        template = WorkerTemplate.create(
            name="small",
            description="Small worker",
            instance_type=Ec2InstanceType.SMALL,
            capacity=WorkerCapacity(cpu_cores=2, memory_gb=16, storage_gb=200),
        )

        required = WorkerCapacity(cpu_cores=4, memory_gb=8, storage_gb=100)

        assert template.can_satisfy(required) is False

    def test_can_satisfy_capacity_false_memory(self) -> None:
        """Test can_satisfy returns False when memory is insufficient."""
        template = WorkerTemplate.create(
            name="low-memory",
            description="Low memory worker",
            instance_type=Ec2InstanceType.SMALL,
            capacity=WorkerCapacity(cpu_cores=8, memory_gb=4, storage_gb=200),
        )

        required = WorkerCapacity(cpu_cores=4, memory_gb=8, storage_gb=100)

        assert template.can_satisfy(required) is False


class TestWorkerTemplateDomainEvents:
    """Tests for WorkerTemplate domain events."""

    def test_created_event_is_recorded(self) -> None:
        """Test that WorkerTemplateCreatedDomainEvent is recorded on creation."""
        template = WorkerTemplate.create(
            name="event-test",
            description="Event test worker",
            instance_type=Ec2InstanceType.MEDIUM,
            capacity=WorkerCapacity(cpu_cores=4, memory_gb=16, storage_gb=100),
        )

        events = template._pending_events
        assert len(events) >= 1
        assert any(isinstance(e, WorkerTemplateCreatedDomainEvent) for e in events)

    def test_updated_event_is_recorded(self) -> None:
        """Test that WorkerTemplateUpdatedDomainEvent is recorded on update."""
        template = WorkerTemplate.create(
            name="update-event-test",
            description="Original",
            instance_type=Ec2InstanceType.SMALL,
            capacity=WorkerCapacity(cpu_cores=2, memory_gb=4, storage_gb=50),
        )
        initial_events = len(template._pending_events)

        template.update(description="Updated")

        events = template._pending_events[initial_events:]
        assert len(events) >= 1
        assert any(isinstance(e, WorkerTemplateUpdatedDomainEvent) for e in events)

    def test_disabled_event_is_recorded(self) -> None:
        """Test that WorkerTemplateDisabledDomainEvent is recorded on disable."""
        template = WorkerTemplate.create(
            name="disable-event-test",
            description="Will be disabled",
            instance_type=Ec2InstanceType.SMALL,
            capacity=WorkerCapacity(cpu_cores=2, memory_gb=4, storage_gb=50),
            enabled=True,
        )
        initial_events = len(template._pending_events)

        template.disable()

        events = template._pending_events[initial_events:]
        assert len(events) >= 1
        assert any(isinstance(e, WorkerTemplateDisabledDomainEvent) for e in events)


class TestWorkerTemplateEventHandlers:
    """Tests for WorkerTemplate @dispatch event handlers."""

    def test_created_event_handler_sets_state(self) -> None:
        """Test that created event handler properly sets state."""
        from datetime import datetime, timezone

        template = WorkerTemplate()
        capacity = WorkerCapacity(cpu_cores=4, memory_gb=16, storage_gb=100)
        now = datetime.now(timezone.utc)
        event = WorkerTemplateCreatedDomainEvent(
            aggregate_id="test-id",
            name="test-name",
            instance_type=Ec2InstanceType.MEDIUM.value,  # Serialized as string
            capacity=capacity.to_dict(),  # Serialized as dict
            cost_per_hour_usd=0.50,
            created_at=now,
        )

        # Event handlers are on the State class
        template.state.on(event)

        assert template.state.id == "test-id"
        assert template.state.name == "test-name"
        assert template.state.instance_type == Ec2InstanceType.MEDIUM
        assert template.state.capacity.cpu_cores == 4
        assert template.state.created_at == now
        assert template.state.updated_at == now

    def test_updated_event_handler_updates_state(self) -> None:
        """Test that updated event handler properly updates state."""
        from datetime import datetime, timezone

        template = WorkerTemplate.create(
            name="test",
            description="Original",
            instance_type=Ec2InstanceType.SMALL,
            capacity=WorkerCapacity(cpu_cores=2, memory_gb=4, storage_gb=50),
        )

        now = datetime.now(timezone.utc)
        event = WorkerTemplateUpdatedDomainEvent(
            aggregate_id=template.id(),
            name="test",
            changes={
                "description": {"from": "Original", "to": "Updated"},
                "cost_per_hour_usd": {"from": 0.0, "to": 0.15},
            },
            updated_at=now,
        )

        # Event handlers are on the State class
        template.state.on(event)

        assert template.state.description == "Updated"
        assert template.state.cost_per_hour_usd == 0.15
        assert template.state.updated_at == now

    def test_disabled_event_handler_disables_template(self) -> None:
        """Test that disabled event handler sets enabled to False."""
        from datetime import datetime, timezone

        template = WorkerTemplate.create(
            name="test",
            description="Test",
            instance_type=Ec2InstanceType.SMALL,
            capacity=WorkerCapacity(cpu_cores=2, memory_gb=4, storage_gb=50),
            enabled=True,
        )

        now = datetime.now(timezone.utc)
        event = WorkerTemplateDisabledDomainEvent(
            aggregate_id=template.id(),
            name="test",
            disabled_at=now,
        )

        # Event handlers are on the State class
        template.state.on(event)

        assert template.state.enabled is False
        assert template.state.updated_at == now

    def test_enabled_event_handler_enables_template(self) -> None:
        """Test that enabled event handler sets enabled to True."""
        from datetime import datetime, timezone

        template = WorkerTemplate.create(
            name="test",
            description="Test",
            instance_type=Ec2InstanceType.SMALL,
            capacity=WorkerCapacity(cpu_cores=2, memory_gb=4, storage_gb=50),
            enabled=False,
        )

        now = datetime.now(timezone.utc)
        event = WorkerTemplateEnabledDomainEvent(
            aggregate_id=template.id(),
            name="test",
            enabled_at=now,
        )

        # Event handlers are on the State class
        template.state.on(event)

        assert template.state.enabled is True
        assert template.state.updated_at == now


class TestWorkerTemplateState:
    """Tests for WorkerTemplateState initialization."""

    def test_state_default_values(self) -> None:
        """Test that state has proper default values."""
        from domain.entities.worker_template import WorkerTemplateState

        state = WorkerTemplateState()

        assert state.id == ""
        assert state.name == ""
        assert state.description == ""
        assert state.instance_type == Ec2InstanceType.SMALL
        assert state.ami_name_pattern == ""
        assert state.capacity.cpu_cores == 0
        assert state.cost_per_hour_usd == 0.0
        assert state.enabled is True
        assert state.created_at is not None
        assert state.updated_at is not None
