"""Managed lifecycle value objects — lifecycle phases and their execution strategies.

ADR-036 §2.1.4: Part of the TimedResource abstraction layer (Layer 2).

Defines which pipelines/workflows execute during each lifecycle transition.
A LabletSession might have:
    instantiate → monitor_resources → collect_evidence → compute_grading → teardown.
A CMLWorker might have:
    provision → license_register → monitor_resources → teardown → terminate.

Each phase maps to either a PipelineExecutor (internal DAG) or a
WorkflowExecutor (external Synapse delegation). See ADR-036 §2.3.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LifecyclePhase:
    """A single lifecycle phase with its execution strategy.

    Each phase maps to either a PipelineExecutor (internal DAG) or a
    WorkflowExecutor (external Synapse delegation).

    Examples:
    - LifecyclePhase("instantiate", engine="pipeline", trigger_on_status="instantiating")
    - LifecyclePhase("collect_evidence", engine="workflow", workflow_ref={...})
    """

    name: str  # e.g., "instantiate", "teardown", "collect_evidence"
    engine: str = "pipeline"  # "pipeline" | "workflow"
    trigger_on_status: str | None = None  # Status that triggers this phase
    pipeline_def: dict[str, Any] | None = None  # Step definitions for PipelineExecutor
    workflow_ref: dict[str, Any] | None = None  # {namespace, name, version} for WorkflowExecutor
    is_required: bool = True  # If False, phase can be skipped per resource type

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "engine": self.engine,
            "trigger_on_status": self.trigger_on_status,
            "pipeline_def": self.pipeline_def,
            "workflow_ref": self.workflow_ref,
            "is_required": self.is_required,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "LifecyclePhase":
        """Create from dictionary.

        Missing optional fields default to their dataclass defaults.
        """
        return LifecyclePhase(
            name=data["name"],
            engine=data.get("engine", "pipeline"),
            trigger_on_status=data.get("trigger_on_status"),
            pipeline_def=data.get("pipeline_def"),
            workflow_ref=data.get("workflow_ref"),
            is_required=data.get("is_required", True),
        )


@dataclass(frozen=True)
class ManagedLifecycle:
    """Ordered set of lifecycle phases for a resource type.

    Defines which pipelines/workflows execute during each lifecycle
    transition. Phases are stored as an immutable tuple for consistency
    with the lcm_core VO pattern (see ResourceObservation.nodes).

    Serialization: Phases are serialized as a dict keyed by phase name
    for YAML/JSON readability (matching LabletDefinition seed format).

    Examples:
    - LabletSession lifecycle: instantiate → collect_evidence → compute_grading → teardown
    - CMLWorker lifecycle: provision → license_register → monitor_resources → teardown → terminate
    - LabRecord lifecycle: import → boot → wipe → teardown
    """

    phases: tuple[LifecyclePhase, ...]  # Ordered, immutable sequence
    current_phase: str | None = None  # Currently executing phase name

    def get_phase(self, name: str) -> LifecyclePhase | None:
        """Get a phase by name, or None if not found."""
        for phase in self.phases:
            if phase.name == name:
                return phase
        return None

    def get_active_phases(self) -> list[LifecyclePhase]:
        """Get all required (non-skippable) phases."""
        return [p for p in self.phases if p.is_required]

    def phase_names(self) -> list[str]:
        """Get ordered list of phase names."""
        return [p.name for p in self.phases]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Phases are serialized as a dict keyed by phase name for
        YAML/JSON readability, matching the seed file format.
        """
        return {
            "phases": {p.name: p.to_dict() for p in self.phases},
            "current_phase": self.current_phase,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ManagedLifecycle":
        """Create from dictionary.

        Phases are deserialized from a dict keyed by phase name.
        Each phase dict must include a 'name' field (or it is inferred
        from the dict key).
        """
        raw_phases = data.get("phases", {})
        phases: list[LifecyclePhase] = []
        for key, phase_data in raw_phases.items():
            # Ensure 'name' is set — use dict key if not present in data
            if "name" not in phase_data:
                phase_data = {**phase_data, "name": key}
            phases.append(LifecyclePhase.from_dict(phase_data))
        return ManagedLifecycle(
            phases=tuple(phases),
            current_phase=data.get("current_phase"),
        )

    def __str__(self) -> str:
        """Human-readable representation."""
        names = " → ".join(self.phase_names())
        current = f" [current: {self.current_phase}]" if self.current_phase else ""
        return f"ManagedLifecycle({names}{current})"
