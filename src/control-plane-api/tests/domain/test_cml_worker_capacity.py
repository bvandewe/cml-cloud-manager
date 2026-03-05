"""Tests for CMLWorker Capacity Extensions (Task 1.5)."""

import pytest
from domain.entities.cml_worker import CMLWorker
from domain.events.cml_worker import (
    CMLWorkerCapacityUpdatedDomainEvent,
    CMLWorkerPortsAllocatedDomainEvent,
    CMLWorkerPortsReleasedDomainEvent,
    LabletSessionAssignedDomainEvent,
)
from domain.value_objects.worker_capacity import WorkerCapacity


class TestCMLWorkerCapacityExtensions:
    """Test CMLWorker capacity management functionality."""

    def test_initial_capacity_state(self):
        """Test worker initializes with zero capacity."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        assert worker.state.template_name is None
        assert worker.state.declared_capacity is None
        assert worker.state.allocated_capacity.cpu_cores == 0
        assert worker.state.allocated_capacity.memory_gb == 0
        assert worker.state.allocated_capacity.storage_gb == 0
        assert worker.state.port_allocations == []
        assert worker.state.session_ids == []

    def test_update_capacity(self):
        """Test updating worker capacity from template."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        worker.update_capacity(
            template_name="m5zn.metal-cml-2.9",
            cpu_cores=96,
            memory_gb=384,
            storage_gb=1000,
            max_nodes=200,
        )

        assert worker.state.template_name == "m5zn.metal-cml-2.9"
        assert worker.state.declared_capacity is not None
        assert worker.state.declared_capacity.cpu_cores == 96
        assert worker.state.declared_capacity.memory_gb == 384
        assert worker.state.declared_capacity.storage_gb == 1000
        assert worker.state.declared_capacity.max_nodes == 200

    def test_update_capacity_emits_event(self):
        """Test update_capacity emits correct domain event."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        worker.update_capacity(
            template_name="m5zn.metal-cml-2.9",
            cpu_cores=96,
            memory_gb=384,
            storage_gb=1000,
            max_nodes=200,
        )

        # Find the capacity event (skip the creation event)
        capacity_events = [e for e in worker.domain_events if isinstance(e, CMLWorkerCapacityUpdatedDomainEvent)]
        assert len(capacity_events) == 1

        event = capacity_events[0]
        assert event.template_name == "m5zn.metal-cml-2.9"
        assert event.declared_capacity_cpu_cores == 96
        assert event.declared_capacity_memory_gb == 384
        assert event.declared_capacity_storage_gb == 1000
        assert event.declared_capacity_max_nodes == 200

    def test_available_capacity_computed(self):
        """Test available_capacity property returns correct value."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        worker.update_capacity(
            template_name="m5zn.metal-cml-2.9",
            cpu_cores=96,
            memory_gb=384,
            storage_gb=1000,
            max_nodes=200,
        )

        # With no allocations, available should equal declared
        available = worker.available_capacity
        assert available is not None
        assert available.cpu_cores == 96
        assert available.memory_gb == 384
        assert available.storage_gb == 1000
        assert available.max_nodes == 200

    def test_available_capacity_none_when_no_declared(self):
        """Test available_capacity returns None when no declared capacity."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        assert worker.available_capacity is None

    def test_assign_lablet_session(self):
        """Test assigning a lablet session to worker."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        worker.update_capacity(
            template_name="m5zn.metal-cml-2.9",
            cpu_cores=96,
            memory_gb=384,
            storage_gb=1000,
            max_nodes=200,
        )

        worker.assign_lablet_session(
            session_id="lablet-inst-001",
            cpu_cores=4,
            memory_gb=16,
            storage_gb=50,
            max_nodes=10,
        )

        # Check session is tracked
        assert "lablet-inst-001" in worker.state.session_ids
        assert worker.has_session("lablet-inst-001") is True

        # Check allocated capacity updated
        assert worker.state.allocated_capacity.cpu_cores == 4
        assert worker.state.allocated_capacity.memory_gb == 16
        assert worker.state.allocated_capacity.storage_gb == 50
        assert worker.state.allocated_capacity.max_nodes == 10

        # Check available capacity reduced
        available = worker.available_capacity
        assert available is not None
        assert available.cpu_cores == 92
        assert available.memory_gb == 368
        assert available.storage_gb == 950
        assert available.max_nodes == 190

    def test_assign_lablet_session_emits_event(self):
        """Test assign_lablet_session emits correct domain event."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        worker.assign_lablet_session(
            session_id="lablet-inst-001",
            cpu_cores=4,
            memory_gb=16,
            storage_gb=50,
            max_nodes=10,
        )

        events = [e for e in worker.domain_events if isinstance(e, LabletSessionAssignedDomainEvent)]
        assert len(events) == 1

        event = events[0]
        assert event.session_id == "lablet-inst-001"
        assert event.allocated_cpu_cores == 4
        assert event.allocated_memory_gb == 16
        assert event.allocated_storage_gb == 50
        assert event.allocated_nodes == 10

    def test_remove_lablet_session(self):
        """Test removing a lablet session from worker."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        worker.update_capacity(
            template_name="m5zn.metal-cml-2.9",
            cpu_cores=96,
            memory_gb=384,
            storage_gb=1000,
            max_nodes=200,
        )

        # Assign then remove
        worker.assign_lablet_session(
            session_id="lablet-inst-001",
            cpu_cores=4,
            memory_gb=16,
            storage_gb=50,
            max_nodes=10,
        )

        worker.remove_lablet_session(
            session_id="lablet-inst-001",
            cpu_cores=4,
            memory_gb=16,
            storage_gb=50,
            max_nodes=10,
        )

        # Check session removed
        assert "lablet-inst-001" not in worker.state.session_ids
        assert worker.has_session("lablet-inst-001") is False

        # Check allocated capacity released
        assert worker.state.allocated_capacity.cpu_cores == 0
        assert worker.state.allocated_capacity.memory_gb == 0
        assert worker.state.allocated_capacity.storage_gb == 0

        # Check available capacity restored
        available = worker.available_capacity
        assert available is not None
        assert available.cpu_cores == 96
        assert available.memory_gb == 384

    def test_can_accommodate_true(self):
        """Test can_accommodate returns True when capacity available."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        worker.update_capacity(
            template_name="m5zn.metal-cml-2.9",
            cpu_cores=96,
            memory_gb=384,
            storage_gb=1000,
            max_nodes=200,
        )

        required = WorkerCapacity(cpu_cores=8, memory_gb=32, storage_gb=100, max_nodes=20)
        assert worker.can_accommodate(required) is True

    def test_can_accommodate_false_insufficient(self):
        """Test can_accommodate returns False when insufficient capacity."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        worker.update_capacity(
            template_name="m5zn.metal-cml-2.9",
            cpu_cores=16,
            memory_gb=32,
            storage_gb=100,
        )

        required = WorkerCapacity(cpu_cores=32, memory_gb=64, storage_gb=200)
        assert worker.can_accommodate(required) is False

    def test_can_accommodate_false_no_declared(self):
        """Test can_accommodate returns False when no declared capacity."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        required = WorkerCapacity(cpu_cores=4, memory_gb=16, storage_gb=50)
        assert worker.can_accommodate(required) is False


class TestCMLWorkerPortAllocation:
    """Test CMLWorker port allocation functionality."""

    def test_initial_ports_state(self):
        """Test worker initializes with no port allocations."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        assert worker.state.port_allocations == []
        assert len(worker.available_ports) == 8000  # 2000-9999

    def test_allocate_ports(self):
        """Test allocating ports for a session."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        worker.allocate_ports(
            session_id="lablet-inst-001",
            ports={"console": 2000, "api": 2001, "vnc": 2002},
        )

        # Check allocation stored
        assert len(worker.state.port_allocations) == 1
        allocation = worker.state.port_allocations[0]
        assert allocation.session_id == "lablet-inst-001"
        assert allocation.ports == {"console": 2000, "api": 2001, "vnc": 2002}

        # Check ports no longer available
        assert 2000 not in worker.available_ports
        assert 2001 not in worker.available_ports
        assert 2002 not in worker.available_ports

    def test_allocate_ports_emits_event(self):
        """Test allocate_ports emits correct domain event."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        worker.allocate_ports(
            session_id="lablet-inst-001",
            ports={"console": 2000, "api": 2001},
        )

        events = [e for e in worker.domain_events if isinstance(e, CMLWorkerPortsAllocatedDomainEvent)]
        assert len(events) == 1

        event = events[0]
        assert event.session_id == "lablet-inst-001"
        assert event.ports == {"console": 2000, "api": 2001}

    def test_release_ports(self):
        """Test releasing ports from a session."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        # Allocate then release
        worker.allocate_ports(
            session_id="lablet-inst-001",
            ports={"console": 2000, "api": 2001},
        )

        worker.release_ports(session_id="lablet-inst-001")

        # Check allocation removed
        assert len(worker.state.port_allocations) == 0

        # Check ports available again
        assert 2000 in worker.available_ports
        assert 2001 in worker.available_ports

    def test_release_ports_emits_event(self):
        """Test release_ports emits correct domain event."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        worker.allocate_ports(
            session_id="lablet-inst-001",
            ports={"console": 2000, "api": 2001},
        )

        worker.release_ports(session_id="lablet-inst-001")

        events = [e for e in worker.domain_events if isinstance(e, CMLWorkerPortsReleasedDomainEvent)]
        assert len(events) == 1

        event = events[0]
        assert event.session_id == "lablet-inst-001"
        assert sorted(event.released_ports) == [2000, 2001]

    def test_release_ports_nonexistent_no_event(self):
        """Test release_ports does nothing for nonexistent allocation."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        worker.release_ports(session_id="nonexistent")

        events = [e for e in worker.domain_events if isinstance(e, CMLWorkerPortsReleasedDomainEvent)]
        assert len(events) == 0

    def test_get_next_available_ports(self):
        """Test getting next available ports."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        ports = worker.get_next_available_ports(3)

        assert len(ports) == 3
        assert ports == [2000, 2001, 2002]

    def test_get_next_available_ports_skips_allocated(self):
        """Test get_next_available_ports skips allocated ports."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        # Allocate first few ports
        worker.allocate_ports(
            session_id="lablet-inst-001",
            ports={"a": 2000, "b": 2001, "c": 2002},
        )

        ports = worker.get_next_available_ports(2)

        assert len(ports) == 2
        assert ports == [2003, 2004]

    def test_get_next_available_ports_insufficient_raises(self):
        """Test get_next_available_ports raises when insufficient ports."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        with pytest.raises(ValueError, match="Not enough available ports"):
            worker.get_next_available_ports(10000)

    def test_get_port_allocation(self):
        """Test getting port allocation for specific session."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        worker.allocate_ports(
            session_id="lablet-inst-001",
            ports={"console": 2000, "api": 2001},
        )

        allocation = worker.get_port_allocation("lablet-inst-001")
        assert allocation is not None
        assert allocation.session_id == "lablet-inst-001"
        assert allocation.ports == {"console": 2000, "api": 2001}

    def test_get_port_allocation_not_found(self):
        """Test get_port_allocation returns None for unknown session."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        allocation = worker.get_port_allocation("nonexistent")
        assert allocation is None

    def test_multiple_allocations(self):
        """Test multiple port allocations tracked correctly."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        worker.allocate_ports(
            session_id="lablet-inst-001",
            ports={"console": 2000, "api": 2001},
        )
        worker.allocate_ports(
            session_id="lablet-inst-002",
            ports={"console": 2002, "api": 2003},
        )

        assert len(worker.state.port_allocations) == 2
        assert 2000 not in worker.available_ports
        assert 2002 not in worker.available_ports

        # Release one
        worker.release_ports("lablet-inst-001")

        assert len(worker.state.port_allocations) == 1
        assert 2000 in worker.available_ports
        assert 2002 not in worker.available_ports


class TestCMLWorkerBackwardCompatibility:
    """Test backward compatibility with existing CMLWorker functionality."""

    def test_existing_functionality_unchanged(self):
        """Test existing CMLWorker functionality still works."""
        worker = CMLWorker(
            name="test-worker",
            aws_region="us-east-1",
            instance_type="m5zn.metal",
            cml_version="2.9.0",
        )

        # Test existing status update
        worker.update_status(worker.state.status)  # No-op
        assert worker.state.name == "test-worker"
        assert worker.state.aws_region == "us-east-1"
        assert worker.state.instance_type == "m5zn.metal"

    def test_capacity_fields_optional(self):
        """Test capacity fields are optional and don't break existing usage."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        # Can use worker without setting capacity
        assert worker.state.declared_capacity is None
        assert worker.available_capacity is None

        # Existing methods still work
        worker.update_endpoint("https://cml.example.com")
        assert worker.state.https_endpoint == "https://cml.example.com"

    def test_mixed_capacity_and_existing_operations(self):
        """Test capacity operations don't interfere with existing operations."""
        worker = CMLWorker(name="test-worker", aws_region="us-east-1", instance_type="m5zn.metal")

        # Set capacity
        worker.update_capacity(
            template_name="m5zn.metal-cml-2.9",
            cpu_cores=96,
            memory_gb=384,
            storage_gb=1000,
        )

        # Existing operations still work
        worker.update_endpoint("https://cml.example.com")
        worker.update_aws_tags({"Name": "CML-Worker", "Environment": "test"})

        # Verify both sets of state
        assert worker.state.https_endpoint == "https://cml.example.com"
        assert worker.state.aws_tags == {"Name": "CML-Worker", "Environment": "test"}
        assert worker.state.declared_capacity is not None
        assert worker.state.declared_capacity.cpu_cores == 96
