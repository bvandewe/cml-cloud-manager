"""Unit tests for PortAllocationService.

Tests cover:
- Port allocation with various templates
- Port release
- Conflict detection
- Port exhaustion
- Validation logic
- Edge cases

Uses mocked EtcdStateStore to isolate unit tests from etcd.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from application.services.port_allocation_service import (
    PORT_RANGE_MAX,
    PORT_RANGE_MIN,
    PortAllocationResult,
    PortAllocationService,
)
from domain.value_objects.port_template import PortDefinition, PortTemplate
from integration.services.etcd_state_store import WorkerPortAllocation


class TestPortAllocationService:
    """Tests for PortAllocationService."""

    @pytest.fixture
    def mock_etcd_store(self) -> MagicMock:
        """Create a mock EtcdStateStore."""
        store = MagicMock()
        store.get_allocated_ports_for_worker = AsyncMock(return_value=set())
        store.allocate_session_ports = AsyncMock(return_value=True)
        store.release_session_ports = AsyncMock(return_value={"serial_1": 2000})
        store.get_worker_ports = AsyncMock(return_value=None)
        return store

    @pytest.fixture
    def service(self, mock_etcd_store: MagicMock) -> PortAllocationService:
        """Create a PortAllocationService with mocked etcd."""
        return PortAllocationService(
            etcd_store=mock_etcd_store,
            port_range_min=PORT_RANGE_MIN,
            port_range_max=PORT_RANGE_MAX,
        )

    @pytest.fixture
    def simple_template(self) -> PortTemplate:
        """Create a simple port template with one port."""
        return PortTemplate(ports=(PortDefinition(name="serial_1", protocol="tcp", description="Serial console"),))

    @pytest.fixture
    def multi_port_template(self) -> PortTemplate:
        """Create a port template with multiple ports."""
        return PortTemplate(
            ports=(
                PortDefinition(name="serial_1", protocol="tcp", description="Serial console"),
                PortDefinition(name="vnc_1", protocol="tcp", description="VNC display"),
                PortDefinition(name="http", protocol="tcp", description="HTTP service"),
            )
        )

    # -------------------------------------------------------------------------
    # allocate_ports tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_allocate_ports_success(
        self,
        service: PortAllocationService,
        mock_etcd_store: MagicMock,
        simple_template: PortTemplate,
    ) -> None:
        """Test successful port allocation."""
        result = await service.allocate_ports(
            worker_id="worker-123",
            session_id="instance-456",
            port_template=simple_template,
        )

        assert result.success is True
        assert result.allocation is not None
        assert result.allocation.session_id == "instance-456"
        assert result.allocated_ports == {"serial_1": 2000}
        assert result.error is None

        # Verify etcd was called
        mock_etcd_store.get_allocated_ports_for_worker.assert_called_once_with("worker-123")
        mock_etcd_store.allocate_session_ports.assert_called_once_with(
            worker_id="worker-123",
            session_id="instance-456",
            ports={"serial_1": 2000},
        )

    @pytest.mark.asyncio
    async def test_allocate_multiple_ports(
        self,
        service: PortAllocationService,
        mock_etcd_store: MagicMock,
        multi_port_template: PortTemplate,
    ) -> None:
        """Test allocating multiple ports."""
        result = await service.allocate_ports(
            worker_id="worker-123",
            session_id="instance-456",
            port_template=multi_port_template,
        )

        assert result.success is True
        assert result.allocated_ports == {
            "serial_1": 2000,
            "vnc_1": 2001,
            "http": 2002,
        }

    @pytest.mark.asyncio
    async def test_allocate_ports_with_existing_allocations(
        self,
        service: PortAllocationService,
        mock_etcd_store: MagicMock,
        simple_template: PortTemplate,
    ) -> None:
        """Test allocation skips already-allocated ports."""
        # Some ports already allocated
        mock_etcd_store.get_allocated_ports_for_worker = AsyncMock(return_value={2000, 2001, 2002})

        result = await service.allocate_ports(
            worker_id="worker-123",
            session_id="instance-456",
            port_template=simple_template,
        )

        assert result.success is True
        assert result.allocated_ports == {"serial_1": 2003}

    @pytest.mark.asyncio
    async def test_allocate_empty_template(
        self,
        service: PortAllocationService,
        mock_etcd_store: MagicMock,
    ) -> None:
        """Test allocation with empty template succeeds with no ports."""
        empty_template = PortTemplate.empty()

        result = await service.allocate_ports(
            worker_id="worker-123",
            session_id="instance-456",
            port_template=empty_template,
        )

        assert result.success is True
        assert result.allocated_ports == {}
        assert result.allocation is not None
        assert result.allocation.ports == {}

        # Should not call etcd for empty template
        mock_etcd_store.get_allocated_ports_for_worker.assert_not_called()
        mock_etcd_store.allocate_session_ports.assert_not_called()

    @pytest.mark.asyncio
    async def test_allocate_ports_empty_worker_id(
        self,
        service: PortAllocationService,
        simple_template: PortTemplate,
    ) -> None:
        """Test allocation fails with empty worker_id."""
        result = await service.allocate_ports(
            worker_id="",
            session_id="instance-456",
            port_template=simple_template,
        )

        assert result.success is False
        assert "worker_id is required" in result.error

    @pytest.mark.asyncio
    async def test_allocate_ports_empty_session_id(
        self,
        service: PortAllocationService,
        simple_template: PortTemplate,
    ) -> None:
        """Test allocation fails with empty session_id."""
        result = await service.allocate_ports(
            worker_id="worker-123",
            session_id="",
            port_template=simple_template,
        )

        assert result.success is False
        assert "session_id is required" in result.error

    @pytest.mark.asyncio
    async def test_allocate_ports_conflict(
        self,
        service: PortAllocationService,
        mock_etcd_store: MagicMock,
        simple_template: PortTemplate,
    ) -> None:
        """Test allocation fails when etcd reports conflict."""
        mock_etcd_store.allocate_session_ports = AsyncMock(return_value=False)

        result = await service.allocate_ports(
            worker_id="worker-123",
            session_id="instance-456",
            port_template=simple_template,
        )

        assert result.success is False
        assert "conflict" in result.error.lower()

    @pytest.mark.asyncio
    async def test_allocate_ports_exhaustion(
        self,
        mock_etcd_store: MagicMock,
        multi_port_template: PortTemplate,
    ) -> None:
        """Test allocation fails when port range is exhausted."""
        # Very small port range
        service = PortAllocationService(
            etcd_store=mock_etcd_store,
            port_range_min=2000,
            port_range_max=2001,  # Only 2 ports available
        )
        # 1 already allocated
        mock_etcd_store.get_allocated_ports_for_worker = AsyncMock(return_value={2000})

        # Try to allocate 3 ports
        result = await service.allocate_ports(
            worker_id="worker-123",
            session_id="instance-456",
            port_template=multi_port_template,
        )

        assert result.success is False
        assert "Not enough ports" in result.error

    @pytest.mark.asyncio
    async def test_allocate_ports_invalid_range(
        self,
        mock_etcd_store: MagicMock,
        simple_template: PortTemplate,
    ) -> None:
        """Test allocation fails with invalid port range."""
        service = PortAllocationService(
            etcd_store=mock_etcd_store,
            port_range_min=5000,
            port_range_max=4000,  # Invalid: min > max
        )

        result = await service.allocate_ports(
            worker_id="worker-123",
            session_id="instance-456",
            port_template=simple_template,
        )

        assert result.success is False
        assert "Invalid port range" in result.error

    @pytest.mark.asyncio
    async def test_allocate_ports_etcd_exception(
        self,
        service: PortAllocationService,
        mock_etcd_store: MagicMock,
        simple_template: PortTemplate,
    ) -> None:
        """Test allocation handles etcd exceptions gracefully."""
        mock_etcd_store.get_allocated_ports_for_worker = AsyncMock(side_effect=Exception("etcd connection failed"))

        result = await service.allocate_ports(
            worker_id="worker-123",
            session_id="instance-456",
            port_template=simple_template,
        )

        assert result.success is False
        assert "etcd connection failed" in result.error

    # -------------------------------------------------------------------------
    # release_ports tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_release_ports_success(
        self,
        service: PortAllocationService,
        mock_etcd_store: MagicMock,
    ) -> None:
        """Test successful port release."""
        mock_etcd_store.release_session_ports = AsyncMock(return_value={"serial_1": 2000, "vnc_1": 2001})

        released = await service.release_ports(
            worker_id="worker-123",
            session_id="instance-456",
        )

        assert released == {"serial_1": 2000, "vnc_1": 2001}
        mock_etcd_store.release_session_ports.assert_called_once_with("worker-123", "instance-456")

    @pytest.mark.asyncio
    async def test_release_ports_no_allocation(
        self,
        service: PortAllocationService,
        mock_etcd_store: MagicMock,
    ) -> None:
        """Test release when instance has no allocations."""
        mock_etcd_store.release_session_ports = AsyncMock(return_value=None)

        released = await service.release_ports(
            worker_id="worker-123",
            session_id="unknown-instance",
        )

        assert released is None

    @pytest.mark.asyncio
    async def test_release_ports_empty_ids(
        self,
        service: PortAllocationService,
    ) -> None:
        """Test release returns None for empty IDs."""
        assert await service.release_ports("", "instance-456") is None
        assert await service.release_ports("worker-123", "") is None

    @pytest.mark.asyncio
    async def test_release_ports_exception_propagates(
        self,
        service: PortAllocationService,
        mock_etcd_store: MagicMock,
    ) -> None:
        """Test that etcd exceptions propagate from release."""
        mock_etcd_store.release_session_ports = AsyncMock(side_effect=Exception("etcd error"))

        with pytest.raises(Exception, match="etcd error"):
            await service.release_ports("worker-123", "instance-456")

    # -------------------------------------------------------------------------
    # get_allocated_ports tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_allocated_ports_success(
        self,
        service: PortAllocationService,
        mock_etcd_store: MagicMock,
    ) -> None:
        """Test getting ports for an instance."""
        mock_etcd_store.get_worker_ports = AsyncMock(
            return_value=WorkerPortAllocation(
                worker_id="worker-123",
                allocations={
                    "instance-456": {"serial_1": 2000, "vnc_1": 2001},
                    "instance-789": {"http": 3000},
                },
                revision=1,
            )
        )

        ports = await service.get_allocated_ports(
            worker_id="worker-123",
            session_id="instance-456",
        )

        assert ports == {"serial_1": 2000, "vnc_1": 2001}

    @pytest.mark.asyncio
    async def test_get_allocated_ports_not_found(
        self,
        service: PortAllocationService,
        mock_etcd_store: MagicMock,
    ) -> None:
        """Test getting ports for non-existent instance."""
        mock_etcd_store.get_worker_ports = AsyncMock(return_value=None)

        ports = await service.get_allocated_ports(
            worker_id="worker-123",
            session_id="unknown-instance",
        )

        assert ports is None

    # -------------------------------------------------------------------------
    # get_all_allocated_ports tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_all_allocated_ports(
        self,
        service: PortAllocationService,
        mock_etcd_store: MagicMock,
    ) -> None:
        """Test getting all ports for a worker."""
        mock_etcd_store.get_worker_ports = AsyncMock(
            return_value=WorkerPortAllocation(
                worker_id="worker-123",
                allocations={
                    "instance-1": {"serial": 2000},
                    "instance-2": {"http": 3000},
                },
                revision=1,
            )
        )

        all_ports = await service.get_all_allocated_ports("worker-123")

        assert all_ports == {
            "instance-1": {"serial": 2000},
            "instance-2": {"http": 3000},
        }

    @pytest.mark.asyncio
    async def test_get_all_allocated_ports_empty(
        self,
        service: PortAllocationService,
        mock_etcd_store: MagicMock,
    ) -> None:
        """Test getting all ports when none allocated."""
        mock_etcd_store.get_worker_ports = AsyncMock(return_value=None)

        all_ports = await service.get_all_allocated_ports("worker-123")

        assert all_ports == {}

    # -------------------------------------------------------------------------
    # get_port_usage_stats tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_port_usage_stats(
        self,
        service: PortAllocationService,
        mock_etcd_store: MagicMock,
    ) -> None:
        """Test port usage statistics."""
        mock_etcd_store.get_allocated_ports_for_worker = AsyncMock(return_value={2000, 2001, 2002})
        mock_etcd_store.get_worker_ports = AsyncMock(
            return_value=WorkerPortAllocation(
                worker_id="worker-123",
                allocations={
                    "instance-1": {"a": 2000, "b": 2001},
                    "instance-2": {"c": 2002},
                },
                revision=1,
            )
        )

        stats = await service.get_port_usage_stats("worker-123")

        assert stats["total_range"] == 8000  # 9999 - 2000 + 1
        assert stats["allocated"] == 3
        assert stats["available"] == 7997
        assert stats["instance_count"] == 2
        assert stats["port_range"] == {"min": 2000, "max": 9999}

    @pytest.mark.asyncio
    async def test_get_port_usage_stats_error(
        self,
        service: PortAllocationService,
        mock_etcd_store: MagicMock,
    ) -> None:
        """Test port usage stats handles errors gracefully."""
        mock_etcd_store.get_allocated_ports_for_worker = AsyncMock(side_effect=Exception("etcd error"))

        stats = await service.get_port_usage_stats("worker-123")

        assert "error" in stats
        assert stats["allocated"] == 0

    # -------------------------------------------------------------------------
    # validate_port_availability tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_validate_port_availability_success(
        self,
        service: PortAllocationService,
        mock_etcd_store: MagicMock,
        multi_port_template: PortTemplate,
    ) -> None:
        """Test validation when ports are available."""
        mock_etcd_store.get_allocated_ports_for_worker = AsyncMock(return_value=set())

        available, error = await service.validate_port_availability(
            worker_id="worker-123",
            port_template=multi_port_template,
        )

        assert available is True
        assert error is None

    @pytest.mark.asyncio
    async def test_validate_port_availability_insufficient(
        self,
        mock_etcd_store: MagicMock,
        multi_port_template: PortTemplate,
    ) -> None:
        """Test validation when not enough ports."""
        # Small range service
        service = PortAllocationService(
            etcd_store=mock_etcd_store,
            port_range_min=2000,
            port_range_max=2001,
        )
        mock_etcd_store.get_allocated_ports_for_worker = AsyncMock(return_value={2000})

        available, error = await service.validate_port_availability(
            worker_id="worker-123",
            port_template=multi_port_template,
        )

        assert available is False
        assert "Need 3 ports" in error

    @pytest.mark.asyncio
    async def test_validate_empty_template(
        self,
        service: PortAllocationService,
    ) -> None:
        """Test validation always passes for empty template."""
        available, error = await service.validate_port_availability(
            worker_id="worker-123",
            port_template=PortTemplate.empty(),
        )

        assert available is True
        assert error is None

    # -------------------------------------------------------------------------
    # _find_available_ports tests
    # -------------------------------------------------------------------------

    def test_find_available_ports_sequential(
        self,
        service: PortAllocationService,
    ) -> None:
        """Test finding available ports from beginning of range."""
        available = service._find_available_ports(set(), 3)
        assert available == [2000, 2001, 2002]

    def test_find_available_ports_with_gaps(
        self,
        service: PortAllocationService,
    ) -> None:
        """Test finding available ports with some already allocated."""
        allocated = {2000, 2002, 2004}
        available = service._find_available_ports(allocated, 3)
        assert available == [2001, 2003, 2005]

    def test_find_available_ports_insufficient(
        self,
        mock_etcd_store: MagicMock,
    ) -> None:
        """Test when not enough ports in range."""
        service = PortAllocationService(
            etcd_store=mock_etcd_store,
            port_range_min=2000,
            port_range_max=2002,
        )
        # All but one allocated
        allocated = {2000, 2002}
        available = service._find_available_ports(allocated, 3)
        # Should return only what's available
        assert available == [2001]

    # -------------------------------------------------------------------------
    # configure tests
    # -------------------------------------------------------------------------

    def test_configure_registers_service(self) -> None:
        """Test that configure registers the service correctly."""
        builder = MagicMock()

        with patch("application.settings.app_settings") as mock_settings:
            mock_settings.port_allocation_min = 3000
            mock_settings.port_allocation_max = 8000

            PortAllocationService.configure(builder)

            builder.services.add_singleton.assert_called_once()
            call_args = builder.services.add_singleton.call_args
            assert call_args[0][0] == PortAllocationService
            assert "implementation_factory" in call_args[1]


class TestPortAllocationResult:
    """Tests for PortAllocationResult dataclass."""

    def test_success_result(self) -> None:
        """Test creating a success result."""
        from domain.value_objects.port_allocation import PortAllocation

        allocation = PortAllocation(
            session_id="test-instance",
            ports={"http": 8080},
        )
        result = PortAllocationResult(
            success=True,
            allocation=allocation,
            allocated_ports={"http": 8080},
        )

        assert result.success is True
        assert result.allocation == allocation
        assert result.error is None

    def test_failure_result(self) -> None:
        """Test creating a failure result."""
        result = PortAllocationResult(
            success=False,
            error="Port exhaustion",
        )

        assert result.success is False
        assert result.allocation is None
        assert result.error == "Port exhaustion"
