"""Port Allocation Service for managing lablet instance ports on workers.

This service handles dynamic port allocation for lablet instances,
ensuring unique ports per worker while respecting valid port ranges.
Uses etcd for atomic allocation tracking to prevent race conditions.

Architecture follows ADR-005: etcd for state coordination.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from domain.value_objects.port_allocation import PortAllocation
from domain.value_objects.port_template import PortTemplate
from integration.services.etcd_state_store import EtcdStateStore

if TYPE_CHECKING:
    from neuroglia.hosting.web import WebApplicationBuilder

log = logging.getLogger(__name__)


# Port range constants per acceptance criteria
PORT_RANGE_MIN = 2000
PORT_RANGE_MAX = 9999


class PortAllocationError(Exception):
    """Base exception for port allocation errors."""

    pass


class PortExhaustionError(PortAllocationError):
    """Raised when no ports are available in the allowed range."""

    pass


class PortConflictError(PortAllocationError):
    """Raised when requested ports are already allocated."""

    pass


class InvalidPortRangeError(PortAllocationError):
    """Raised when port numbers are outside valid range."""

    pass


@dataclass
class PortAllocationResult:
    """Result of a port allocation operation.

    Attributes:
        success: Whether allocation succeeded
        allocation: The PortAllocation if successful
        error: Error message if failed
        allocated_ports: The mapping of port names to numbers if successful
    """

    success: bool
    allocation: PortAllocation | None = None
    error: str | None = None
    allocated_ports: dict[str, int] | None = None


class PortAllocationService:
    """Service for managing port allocations per worker.

    Responsibilities:
    - Allocate unique ports for LabletSessions based on PortTemplates
    - Track allocations in etcd for distributed coordination
    - Prevent port conflicts via atomic operations
    - Release ports when instances terminate

    Port Range: 2000-9999 (configurable via class constants)

    Example:
        ```python
        service = PortAllocationService(etcd_store)

        # Allocate ports
        template = PortTemplate(ports=(
            PortDefinition(name="serial_1", protocol="tcp"),
            PortDefinition(name="vnc_1", protocol="tcp"),
        ))
        result = await service.allocate_ports(
            worker_id="worker-123",
            session_id="instance-456",
            port_template=template
        )
        if result.success:
            print(f"Allocated: {result.allocated_ports}")
            # {"serial_1": 2000, "vnc_1": 2001}

        # Release ports
        await service.release_ports(worker_id="worker-123", session_id="instance-456")
        ```
    """

    def __init__(
        self,
        etcd_store: EtcdStateStore,
        port_range_min: int = PORT_RANGE_MIN,
        port_range_max: int = PORT_RANGE_MAX,
    ):
        """Initialize the port allocation service.

        Args:
            etcd_store: EtcdStateStore for port allocation tracking
            port_range_min: Minimum port number (default: 2000)
            port_range_max: Maximum port number (default: 9999)
        """
        self._etcd = etcd_store
        self._port_range_min = port_range_min
        self._port_range_max = port_range_max

        log.debug(f"PortAllocationService initialized (range: {port_range_min}-{port_range_max})")

    @staticmethod
    def configure(builder: "WebApplicationBuilder") -> None:
        """Configure the service for dependency injection.

        Args:
            builder: WebApplicationBuilder instance
        """
        from application.settings import app_settings

        log.info("🔧 Configuring PortAllocationService...")

        def _factory(sp) -> PortAllocationService:
            etcd_store = sp.get_required_service(EtcdStateStore)
            return PortAllocationService(
                etcd_store=etcd_store,
                port_range_min=app_settings.port_allocation_min,
                port_range_max=app_settings.port_allocation_max,
            )

        builder.services.add_singleton(PortAllocationService, implementation_factory=_factory)
        log.info("✅ PortAllocationService registered")

    async def allocate_ports(
        self,
        worker_id: str,
        session_id: str,
        port_template: PortTemplate,
    ) -> PortAllocationResult:
        """Allocate ports for an instance based on a port template.

        Finds available ports in the valid range and atomically allocates
        them for the given instance on the specified worker.

        Args:
            worker_id: The CMLWorker ID to allocate ports on
            session_id: The LabletSession ID requesting ports
            port_template: Template defining required port names

        Returns:
            PortAllocationResult with allocation details or error

        Raises:
            PortExhaustionError: If not enough ports available
            PortConflictError: If allocation failed due to race condition
            InvalidPortRangeError: If port range configuration is invalid
        """
        if not worker_id:
            return PortAllocationResult(success=False, error="worker_id is required")

        if not session_id:
            return PortAllocationResult(success=False, error="session_id is required")

        # Handle empty template (no ports needed)
        if port_template.port_count == 0:
            log.debug(f"No ports required for instance {session_id}")
            allocation = PortAllocation(
                session_id=session_id,
                ports={},
                allocated_at=datetime.now(timezone.utc),
            )
            return PortAllocationResult(
                success=True,
                allocation=allocation,
                allocated_ports={},
            )

        # Validate port range
        if self._port_range_min >= self._port_range_max:
            return PortAllocationResult(
                success=False,
                error=f"Invalid port range: {self._port_range_min}-{self._port_range_max}",
            )

        try:
            # Get currently allocated ports for this worker
            allocated_ports = await self._etcd.get_allocated_ports_for_worker(worker_id)

            # Find available ports
            required_count = port_template.port_count
            available_ports = self._find_available_ports(allocated_ports, required_count)

            if len(available_ports) < required_count:
                available_in_range = self._port_range_max - self._port_range_min + 1 - len(allocated_ports)
                return PortAllocationResult(
                    success=False,
                    error=f"Not enough ports available. Need {required_count}, have {available_in_range} free",
                )

            # Map port names to actual port numbers
            port_mapping = {}
            for i, port_def in enumerate(port_template.ports):
                port_mapping[port_def.name] = available_ports[i]

            # Attempt atomic allocation via etcd
            success = await self._etcd.allocate_session_ports(
                worker_id=worker_id,
                session_id=session_id,
                ports=port_mapping,
            )

            if not success:
                return PortAllocationResult(
                    success=False,
                    error="Port allocation conflict - ports already allocated (race condition)",
                )

            # Create the PortAllocation value object
            allocation = PortAllocation(
                session_id=session_id,
                ports=port_mapping,
                allocated_at=datetime.now(timezone.utc),
            )

            log.info(f"✅ Allocated ports for instance {session_id} on worker {worker_id}: {port_mapping}")

            return PortAllocationResult(
                success=True,
                allocation=allocation,
                allocated_ports=port_mapping,
            )

        except Exception as e:
            log.error(f"Port allocation failed: {e}")
            return PortAllocationResult(
                success=False,
                error=f"Allocation failed: {str(e)}",
            )

    async def release_ports(
        self,
        worker_id: str,
        session_id: str,
    ) -> dict[str, int] | None:
        """Release ports allocated to an instance.

        Called when an instance terminates to return ports to the pool.

        Args:
            worker_id: The CMLWorker ID
            session_id: The LabletSession ID

        Returns:
            Dictionary of released port mappings, or None if no allocation existed
        """
        if not worker_id or not session_id:
            log.warning("release_ports called with empty worker_id or session_id")
            return None

        try:
            released = await self._etcd.release_session_ports(worker_id, session_id)

            if released:
                log.info(f"🔓 Released ports for instance {session_id} on worker {worker_id}: {released}")
            else:
                log.debug(f"No ports to release for instance {session_id} on worker {worker_id}")

            return released

        except Exception as e:
            log.error(f"Failed to release ports for instance {session_id}: {e}")
            raise

    async def get_allocated_ports(
        self,
        worker_id: str,
        session_id: str,
    ) -> dict[str, int] | None:
        """Get ports allocated to a specific instance.

        Args:
            worker_id: The CMLWorker ID
            session_id: The LabletSession ID

        Returns:
            Dictionary of port name -> port number, or None if not found
        """
        try:
            worker_ports = await self._etcd.get_worker_ports(worker_id)

            if not worker_ports or session_id not in worker_ports.allocations:
                return None

            return worker_ports.allocations[session_id]

        except Exception as e:
            log.error(f"Failed to get allocated ports: {e}")
            return None

    async def get_all_allocated_ports(self, worker_id: str) -> dict[str, dict[str, int]]:
        """Get all port allocations for a worker.

        Args:
            worker_id: The CMLWorker ID

        Returns:
            Dictionary of session_id -> {port_name: port_number}
        """
        try:
            worker_ports = await self._etcd.get_worker_ports(worker_id)
            return worker_ports.allocations if worker_ports else {}

        except Exception as e:
            log.error(f"Failed to get all allocated ports: {e}")
            return {}

    async def get_port_usage_stats(self, worker_id: str) -> dict:
        """Get port usage statistics for a worker.

        Args:
            worker_id: The CMLWorker ID

        Returns:
            Dictionary with usage statistics:
            - total_range: Total ports in range
            - allocated: Number of allocated ports
            - available: Number of available ports
            - utilization_pct: Percentage of ports in use
            - instance_count: Number of instances with allocations
        """
        try:
            allocated = await self._etcd.get_allocated_ports_for_worker(worker_id)
            allocated_count = len(allocated)
            total_range = self._port_range_max - self._port_range_min + 1
            available = total_range - allocated_count

            # Count instances
            worker_ports = await self._etcd.get_worker_ports(worker_id)
            instance_count = len(worker_ports.allocations) if worker_ports else 0

            return {
                "total_range": total_range,
                "allocated": allocated_count,
                "available": available,
                "utilization_pct": round((allocated_count / total_range) * 100, 2) if total_range > 0 else 0,
                "instance_count": instance_count,
                "port_range": {
                    "min": self._port_range_min,
                    "max": self._port_range_max,
                },
            }

        except Exception as e:
            log.error(f"Failed to get port usage stats: {e}")
            return {
                "error": str(e),
                "total_range": 0,
                "allocated": 0,
                "available": 0,
                "utilization_pct": 0,
                "instance_count": 0,
            }

    async def validate_port_availability(
        self,
        worker_id: str,
        port_template: PortTemplate,
    ) -> tuple[bool, str | None]:
        """Check if enough ports are available for a template without allocating.

        Useful for scheduling decisions before committing to a worker.

        Args:
            worker_id: The CMLWorker ID
            port_template: Template defining required ports

        Returns:
            Tuple of (is_available, error_message)
        """
        if port_template.port_count == 0:
            return True, None

        try:
            allocated = await self._etcd.get_allocated_ports_for_worker(worker_id)
            available_count = self._port_range_max - self._port_range_min + 1 - len(allocated)

            if available_count >= port_template.port_count:
                return True, None
            else:
                return False, f"Need {port_template.port_count} ports, only {available_count} available"

        except Exception as e:
            return False, f"Failed to check availability: {e}"

    def _find_available_ports(
        self,
        allocated_ports: set[int],
        count: int,
    ) -> list[int]:
        """Find available ports in the valid range.

        Implements a simple sequential allocation strategy starting from
        the minimum port. Future enhancement could implement smarter
        allocation strategies (random, spread, etc.).

        Args:
            allocated_ports: Set of currently allocated ports
            count: Number of ports needed

        Returns:
            List of available port numbers
        """
        available = []
        port = self._port_range_min

        while len(available) < count and port <= self._port_range_max:
            if port not in allocated_ports:
                available.append(port)
            port += 1

        return available

    def _validate_ports_in_range(self, ports: dict[str, int]) -> tuple[bool, str | None]:
        """Validate that all ports are within the valid range.

        Args:
            ports: Dictionary of port name -> port number

        Returns:
            Tuple of (is_valid, error_message)
        """
        for name, port in ports.items():
            if port < self._port_range_min or port > self._port_range_max:
                return (
                    False,
                    f"Port {port} for '{name}' is outside valid range {self._port_range_min}-{self._port_range_max}",
                )
        return True, None
