"""Tests for Worker Capacity and Port Allocation value objects."""

from datetime import datetime, timezone

import pytest

from domain.value_objects.port_allocation import PortAllocation
from domain.value_objects.worker_capacity import WorkerCapacity


class TestWorkerCapacity:
    """Test WorkerCapacity value object."""

    def test_creation_valid(self):
        """Test valid WorkerCapacity creation."""
        capacity = WorkerCapacity(cpu_cores=16, memory_gb=64, storage_gb=500, max_nodes=50)

        assert capacity.cpu_cores == 16
        assert capacity.memory_gb == 64
        assert capacity.storage_gb == 500
        assert capacity.max_nodes == 50

    def test_creation_without_max_nodes(self):
        """Test WorkerCapacity creation without max_nodes."""
        capacity = WorkerCapacity(cpu_cores=8, memory_gb=32, storage_gb=200)

        assert capacity.cpu_cores == 8
        assert capacity.memory_gb == 32
        assert capacity.storage_gb == 200
        assert capacity.max_nodes is None

    def test_creation_negative_cpu_raises(self):
        """Test negative cpu_cores raises ValueError."""
        with pytest.raises(ValueError, match="cpu_cores cannot be negative"):
            WorkerCapacity(cpu_cores=-1, memory_gb=32, storage_gb=200)

    def test_creation_negative_memory_raises(self):
        """Test negative memory_gb raises ValueError."""
        with pytest.raises(ValueError, match="memory_gb cannot be negative"):
            WorkerCapacity(cpu_cores=8, memory_gb=-1, storage_gb=200)

    def test_creation_negative_storage_raises(self):
        """Test negative storage_gb raises ValueError."""
        with pytest.raises(ValueError, match="storage_gb cannot be negative"):
            WorkerCapacity(cpu_cores=8, memory_gb=32, storage_gb=-1)

    def test_creation_negative_max_nodes_raises(self):
        """Test negative max_nodes raises ValueError."""
        with pytest.raises(ValueError, match="max_nodes cannot be negative"):
            WorkerCapacity(cpu_cores=8, memory_gb=32, storage_gb=200, max_nodes=-1)

    def test_zero_factory(self):
        """Test zero() factory method."""
        zero = WorkerCapacity.zero()

        assert zero.cpu_cores == 0
        assert zero.memory_gb == 0
        assert zero.storage_gb == 0
        assert zero.max_nodes == 0

    def test_can_fit_true(self):
        """Test can_fit returns True when capacity is sufficient."""
        available = WorkerCapacity(cpu_cores=16, memory_gb=64, storage_gb=500, max_nodes=50)
        required = WorkerCapacity(cpu_cores=4, memory_gb=16, storage_gb=100, max_nodes=10)

        assert available.can_fit(required) is True

    def test_can_fit_false_cpu(self):
        """Test can_fit returns False when CPU insufficient."""
        available = WorkerCapacity(cpu_cores=4, memory_gb=64, storage_gb=500)
        required = WorkerCapacity(cpu_cores=8, memory_gb=16, storage_gb=100)

        assert available.can_fit(required) is False

    def test_can_fit_false_memory(self):
        """Test can_fit returns False when memory insufficient."""
        available = WorkerCapacity(cpu_cores=16, memory_gb=16, storage_gb=500)
        required = WorkerCapacity(cpu_cores=4, memory_gb=32, storage_gb=100)

        assert available.can_fit(required) is False

    def test_can_fit_false_storage(self):
        """Test can_fit returns False when storage insufficient."""
        available = WorkerCapacity(cpu_cores=16, memory_gb=64, storage_gb=50)
        required = WorkerCapacity(cpu_cores=4, memory_gb=16, storage_gb=100)

        assert available.can_fit(required) is False

    def test_can_fit_false_max_nodes(self):
        """Test can_fit returns False when max_nodes insufficient."""
        available = WorkerCapacity(cpu_cores=16, memory_gb=64, storage_gb=500, max_nodes=5)
        required = WorkerCapacity(cpu_cores=4, memory_gb=16, storage_gb=100, max_nodes=10)

        assert available.can_fit(required) is False

    def test_can_fit_ignores_none_max_nodes(self):
        """Test can_fit ignores max_nodes comparison when either is None."""
        available = WorkerCapacity(cpu_cores=16, memory_gb=64, storage_gb=500)
        required = WorkerCapacity(cpu_cores=4, memory_gb=16, storage_gb=100, max_nodes=100)

        # Available has None max_nodes, so it should not block
        assert available.can_fit(required) is True

    def test_subtract(self):
        """Test subtract method."""
        total = WorkerCapacity(cpu_cores=16, memory_gb=64, storage_gb=500, max_nodes=50)
        used = WorkerCapacity(cpu_cores=4, memory_gb=16, storage_gb=100, max_nodes=10)

        remaining = total.subtract(used)

        assert remaining.cpu_cores == 12
        assert remaining.memory_gb == 48
        assert remaining.storage_gb == 400
        assert remaining.max_nodes == 40

    def test_subtract_clamps_to_zero(self):
        """Test subtract clamps negative values to zero."""
        total = WorkerCapacity(cpu_cores=4, memory_gb=16, storage_gb=100, max_nodes=10)
        used = WorkerCapacity(cpu_cores=8, memory_gb=32, storage_gb=200, max_nodes=20)

        remaining = total.subtract(used)

        assert remaining.cpu_cores == 0
        assert remaining.memory_gb == 0
        assert remaining.storage_gb == 0
        assert remaining.max_nodes == 0

    def test_add(self):
        """Test add method."""
        first = WorkerCapacity(cpu_cores=4, memory_gb=16, storage_gb=100, max_nodes=10)
        second = WorkerCapacity(cpu_cores=2, memory_gb=8, storage_gb=50, max_nodes=5)

        total = first.add(second)

        assert total.cpu_cores == 6
        assert total.memory_gb == 24
        assert total.storage_gb == 150
        assert total.max_nodes == 15

    def test_add_with_none_max_nodes(self):
        """Test add handles None max_nodes correctly."""
        first = WorkerCapacity(cpu_cores=4, memory_gb=16, storage_gb=100)
        second = WorkerCapacity(cpu_cores=2, memory_gb=8, storage_gb=50, max_nodes=5)

        total = first.add(second)

        # When one has None and other has value, result should have value
        assert total.max_nodes == 5

    def test_to_dict(self):
        """Test to_dict serialization."""
        capacity = WorkerCapacity(cpu_cores=16, memory_gb=64, storage_gb=500, max_nodes=50)

        result = capacity.to_dict()

        assert result == {
            "cpu_cores": 16,
            "memory_gb": 64,
            "storage_gb": 500,
            "max_nodes": 50,
        }

    def test_from_dict(self):
        """Test from_dict deserialization."""
        data = {
            "cpu_cores": 16,
            "memory_gb": 64,
            "storage_gb": 500,
            "max_nodes": 50,
        }

        capacity = WorkerCapacity.from_dict(data)

        assert capacity.cpu_cores == 16
        assert capacity.memory_gb == 64
        assert capacity.storage_gb == 500
        assert capacity.max_nodes == 50

    def test_from_dict_with_missing_values(self):
        """Test from_dict with missing values defaults to zero."""
        data = {"cpu_cores": 8}

        capacity = WorkerCapacity.from_dict(data)

        assert capacity.cpu_cores == 8
        assert capacity.memory_gb == 0
        assert capacity.storage_gb == 0
        assert capacity.max_nodes is None

    def test_str_representation(self):
        """Test string representation."""
        capacity = WorkerCapacity(cpu_cores=16, memory_gb=64, storage_gb=500, max_nodes=50)

        assert "cpu=16" in str(capacity)
        assert "mem=64GB" in str(capacity)
        assert "storage=500GB" in str(capacity)
        assert "max_nodes=50" in str(capacity)

    def test_immutability(self):
        """Test that WorkerCapacity is frozen (immutable)."""
        capacity = WorkerCapacity(cpu_cores=16, memory_gb=64, storage_gb=500)

        with pytest.raises(AttributeError):
            capacity.cpu_cores = 32  # type: ignore


class TestPortAllocation:
    """Test PortAllocation value object."""

    def test_creation_valid(self):
        """Test valid PortAllocation creation."""
        now = datetime.now(timezone.utc)
        allocation = PortAllocation(
            session_id="inst-123",
            ports={"console": 2000, "api": 2001, "vnc": 2002},
            allocated_at=now,
        )

        assert allocation.session_id == "inst-123"
        assert allocation.ports == {"console": 2000, "api": 2001, "vnc": 2002}
        assert allocation.allocated_at == now

    def test_creation_with_default_timestamp(self):
        """Test PortAllocation creation with default timestamp."""
        allocation = PortAllocation(
            session_id="inst-123",
            ports={"console": 2000},
        )

        assert allocation.session_id == "inst-123"
        assert allocation.allocated_at is not None

    def test_creation_empty_session_id_raises(self):
        """Test empty instance_id raises ValueError."""
        with pytest.raises(ValueError, match="session_id cannot be empty"):
            PortAllocation(session_id="", ports={"console": 2000})

    def test_creation_invalid_port_low_raises(self):
        """Test port below 2000 raises ValueError."""
        with pytest.raises(ValueError, match="must be between 2000 and 65535"):
            PortAllocation(session_id="inst-123", ports={"console": 1999})

    def test_creation_invalid_port_high_raises(self):
        """Test port above 65535 raises ValueError."""
        with pytest.raises(ValueError, match="must be between 2000 and 65535"):
            PortAllocation(session_id="inst-123", ports={"console": 65536})

    def test_creation_invalid_port_type_raises(self):
        """Test non-integer port raises ValueError."""
        with pytest.raises(ValueError, match="must be an integer"):
            PortAllocation(session_id="inst-123", ports={"console": "2000"})  # type: ignore

    def test_get_port_found(self):
        """Test get_port returns port number when found."""
        allocation = PortAllocation(
            session_id="inst-123",
            ports={"console": 2000, "api": 2001},
        )

        assert allocation.get_port("console") == 2000
        assert allocation.get_port("api") == 2001

    def test_get_port_not_found(self):
        """Test get_port returns None when not found."""
        allocation = PortAllocation(
            session_id="inst-123",
            ports={"console": 2000},
        )

        assert allocation.get_port("vnc") is None

    def test_get_all_ports(self):
        """Test get_all_ports returns all port numbers."""
        allocation = PortAllocation(
            session_id="inst-123",
            ports={"console": 2000, "api": 2001, "vnc": 2002},
        )

        ports = allocation.get_all_ports()

        assert sorted(ports) == [2000, 2001, 2002]

    def test_port_count(self):
        """Test port_count returns correct count."""
        allocation = PortAllocation(
            session_id="inst-123",
            ports={"console": 2000, "api": 2001, "vnc": 2002},
        )

        assert allocation.port_count() == 3

    def test_to_dict(self):
        """Test to_dict serialization."""
        now = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        allocation = PortAllocation(
            session_id="inst-123",
            ports={"console": 2000, "api": 2001},
            allocated_at=now,
        )

        result = allocation.to_dict()

        assert result["session_id"] == "inst-123"
        assert result["ports"] == {"console": 2000, "api": 2001}
        assert result["allocated_at"] == "2024-01-15T12:00:00+00:00"

    def test_from_dict_with_iso_string(self):
        """Test from_dict with ISO timestamp string."""
        data = {
            "session_id": "inst-123",
            "ports": {"console": 2000, "api": 2001},
            "allocated_at": "2024-01-15T12:00:00+00:00",
        }

        allocation = PortAllocation.from_dict(data)

        assert allocation.session_id == "inst-123"
        assert allocation.ports == {"console": 2000, "api": 2001}
        assert allocation.allocated_at == datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    def test_from_dict_with_datetime_object(self):
        """Test from_dict with datetime object."""
        now = datetime.now(timezone.utc)
        data = {
            "session_id": "inst-123",
            "ports": {"console": 2000},
            "allocated_at": now,
        }

        allocation = PortAllocation.from_dict(data)

        assert allocation.allocated_at == now

    def test_str_representation(self):
        """Test string representation."""
        allocation = PortAllocation(
            session_id="inst-123",
            ports={"api": 2001, "console": 2000},
        )

        result = str(allocation)

        assert "inst-123" in result
        assert "api:2001" in result
        assert "console:2000" in result

    def test_immutability(self):
        """Test that PortAllocation is frozen (immutable)."""
        allocation = PortAllocation(
            session_id="inst-123",
            ports={"console": 2000},
        )

        with pytest.raises(AttributeError):
            allocation.session_id = "different"  # type: ignore
