"""ScenarioContext — execution context injected into scenarios.

Provides everything a scenario needs to execute without importing
application-layer services. Follows DDD dependency inversion.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


class AdapterRegistry:
    """Registry of infrastructure adapters available to scenarios.

    Simple dict wrapper with typed access. Adapters are registered by type name
    (e.g. "cml", "aws") and resolved at runtime by scenario code.
    """

    def __init__(self, adapters: dict[str, Any] | None = None) -> None:
        self._adapters: dict[str, Any] = adapters or {}

    def get(self, adapter_type: str) -> Any | None:
        """Get an adapter by type name, or None if not registered."""
        return self._adapters.get(adapter_type)

    def require(self, adapter_type: str) -> Any:
        """Get an adapter by type name, raising if not registered.

        Raises:
            KeyError: If the adapter type is not registered.
        """
        adapter = self._adapters.get(adapter_type)
        if adapter is None:
            raise KeyError(f"Required adapter '{adapter_type}' not registered. Available: {list(self._adapters.keys())}")
        return adapter

    def register(self, adapter_type: str, adapter: Any) -> None:
        """Register an adapter instance."""
        self._adapters[adapter_type] = adapter

    def available_types(self) -> list[str]:
        """Return list of registered adapter type names."""
        return list(self._adapters.keys())


@dataclass(frozen=True)
class ScenarioContext:
    """Execution context injected into scenario.execute().

    Carries input data, job metadata, and typed adapter interfaces.
    Frozen to communicate immutability — scenarios should not mutate context.

    Attributes:
        job_id: Unique identifier for the executing job.
        scenario_name: Name of the scenario being executed.
        scenario_version: Version of the scenario (e.g. "v1").
        input_data: Input parameters from the job submission.
        pod_definition_id: Optional reference to PodDefinition content.
        callback_url: Optional per-job CloudEvents callback URL.
        adapters: Registry of infrastructure adapters (CML, AWS, etc.).
        report_progress: Async callback for reporting execution progress.
        cancellation_event: Event set when cancellation is requested.
        logger: Pre-configured logger with job_id context.
    """

    job_id: str
    scenario_name: str
    scenario_version: str
    input_data: dict[str, Any] = field(default_factory=dict)
    pod_definition_id: str | None = None
    callback_url: str | None = None
    adapters: AdapterRegistry = field(default_factory=AdapterRegistry)
    report_progress: Callable[[int, str, dict[str, Any] | None], Awaitable[None]] = field(default=None)  # type: ignore[assignment]
    cancellation_event: asyncio.Event = field(default_factory=asyncio.Event)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("scenario"))
