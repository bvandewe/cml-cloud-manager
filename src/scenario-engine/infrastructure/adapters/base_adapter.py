"""Base Adapter — Protocol definition for infrastructure adapters.

ADR-044: All adapters implement this protocol for uniform dispatch.
Adapters handle the actual I/O calls to infrastructure (CML, ROC, Proxmox, VMWare).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AdapterResult:
    """Standardized result from an adapter call.

    Attributes:
        success: Whether the adapter call succeeded.
        data: Result data from the adapter.
        error: Error message if the call failed.
    """

    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @staticmethod
    def ok(data: dict[str, Any] | None = None) -> AdapterResult:
        return AdapterResult(success=True, data=data or {})

    @staticmethod
    def fail(error: str) -> AdapterResult:
        return AdapterResult(success=False, error=error)


class AdapterProtocol(ABC):
    """Abstract base class for infrastructure adapters.

    Each adapter handles a specific pod type (CML/AWS, ROC/RADkit, Proxmox, VMWare).
    The ScenarioEngine dispatches to the appropriate adapter based on PodType.
    """

    @property
    @abstractmethod
    def pod_type(self) -> str:
        """The pod type this adapter handles (e.g. 'CML_ON_AWS')."""
        ...

    @abstractmethod
    async def execute_task(self, task_name: str, params: dict[str, Any]) -> AdapterResult:
        """Execute a named task with parameters.

        Args:
            task_name: The task to execute (e.g. "resolve_lab", "start_lab").
            params: Task parameters.

        Returns:
            AdapterResult with success/failure and data.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the adapter's target infrastructure is reachable.

        Returns:
            True if healthy, False otherwise.
        """
        ...
