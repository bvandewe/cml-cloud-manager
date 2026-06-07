"""Scenario Registry — decorator-based registration for scenario implementations.

ADR-044: Scenarios are auto-discovered at boot via decorator side-effects.
Follows the same pattern as lablet-controller's @step_handler registry.

Scenarios are classes or functions registered by name + version:

    @scenario(name="lab_resolve", version="v1")
    class LabResolveScenario:
        \"\"\"Resolve a CML lab topology for a pod.\"\"\"

        input_schema = {...}
        output_schema = {...}

        async def execute(self, input_data: dict, context: ScenarioContext) -> ScenarioResult:
            ...

The registry is populated when scenario modules are imported. The main.py
imports the `scenarios` package to trigger registration.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ScenarioResult — standardized return type for scenario execution
# ---------------------------------------------------------------------------


@dataclass
class ScenarioResult:
    """Standardized result from a scenario execution.

    Attributes:
        status: Outcome — "completed", "failed", or "cancelled".
        output_data: Result payload returned to the caller.
        error: Human-readable error message (when status="failed").
        artifacts: List of artifact references produced during execution.
    """

    status: str  # "completed" | "failed" | "cancelled"
    output_data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    artifacts: list[str] = field(default_factory=list)

    @staticmethod
    def completed(output_data: dict[str, Any] | None = None, artifacts: list[str] | None = None) -> ScenarioResult:
        """Create a successful scenario result."""
        return ScenarioResult(status="completed", output_data=output_data or {}, artifacts=artifacts or [])

    @staticmethod
    def failed(error: str) -> ScenarioResult:
        """Create a failed scenario result."""
        return ScenarioResult(status="failed", error=error)

    @staticmethod
    def cancelled() -> ScenarioResult:
        """Create a cancelled scenario result."""
        return ScenarioResult(status="cancelled")


# ---------------------------------------------------------------------------
# ScenarioMetadata — metadata about a registered scenario
# ---------------------------------------------------------------------------


@dataclass
class ScenarioMetadata:
    """Metadata for a registered scenario."""

    name: str
    version: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    implementation: Any = None  # The class or function


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_SCENARIOS: dict[str, ScenarioMetadata] = {}


def scenario(name: str, version: str = "v1", description: str = "") -> Callable:
    """Decorator to register a scenario class or function.

    Usage::

        @scenario(name="lab_resolve", version="v1", description="Resolve CML lab topology")
        class LabResolveScenario:
            input_schema = {"type": "object", "properties": {...}}
            output_schema = {"type": "object", "properties": {...}}

            async def execute(self, input_data, context):
                ...
                return ScenarioResult.completed({"lab_id": "..."})

    Args:
        name: The scenario name (e.g. "lab_resolve", "lab_start").
        version: The scenario version (e.g. "v1", "v2").
        description: Human-readable description.

    Returns:
        Decorator that registers the class/function and returns it unchanged.
    """

    def decorator(cls_or_fn: Any) -> Any:
        key = f"{name}@{version}"
        if key in _SCENARIOS:
            logger.warning("Scenario '%s' registered twice — overwriting previous registration", key)

        input_schema = getattr(cls_or_fn, "input_schema", {})
        output_schema = getattr(cls_or_fn, "output_schema", {})
        desc = description or getattr(cls_or_fn, "__doc__", "") or ""

        _SCENARIOS[key] = ScenarioMetadata(
            name=name,
            version=version,
            description=desc.strip(),
            input_schema=input_schema,
            output_schema=output_schema,
            implementation=cls_or_fn,
        )
        logger.info("Registered scenario: %s", key)
        return cls_or_fn

    return decorator


def get_scenario(name: str, version: str = "v1") -> ScenarioMetadata | None:
    """Look up a registered scenario by name and version.

    Args:
        name: Scenario name (e.g. "lab_resolve").
        version: Scenario version (e.g. "v1").

    Returns:
        The scenario metadata, or None if not registered.
    """
    return _SCENARIOS.get(f"{name}@{version}")


def get_all_scenarios() -> dict[str, dict[str, Any]]:
    """Return all registered scenarios as a dict (for introspection/API).

    Returns:
        Dictionary mapping "name@version" to metadata dict.
    """
    return {
        key: {
            "name": meta.name,
            "version": meta.version,
            "description": meta.description,
            "input_schema": meta.input_schema,
            "output_schema": meta.output_schema,
        }
        for key, meta in _SCENARIOS.items()
    }


def clear_registry() -> None:
    """Clear all registered scenarios (for testing only)."""
    _SCENARIOS.clear()
