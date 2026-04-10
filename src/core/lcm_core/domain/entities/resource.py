"""ResourceState — base aggregate state for all managed resources.

ADR-036 §2.1.4 Layer 1: The foundational state class that every managed
resource in LCM extends. Provides the Kubernetes-like spec/status pattern
with state history tracking.

Hierarchy:
    AggregateState[str]  (Neuroglia)
        └── ResourceState  ← YOU ARE HERE
                └── TimedResourceState  (Layer 2, see timed_resource.py)
                        └── Concrete states (LabletSessionState, CMLWorkerState, …)

Design decisions:
    - `status` and `desired_status` are `str`, NOT enums. Concrete aggregates
      use their own enum types and shadow these fields. The base class stores
      `str` for polymorphism across resource types.
    - `state_history` uses the generic lcm_core `StateTransition` (str-based).
    - NOT a Python ABC — Neuroglia AggregateState doesn't support ABC mixin.
    - Follows the two-phase Neuroglia pattern: class-level type annotations +
      defaults set in __init__().
"""

from datetime import UTC, datetime

from neuroglia.data.abstractions import AggregateState

from lcm_core.domain.value_objects.state_transition import StateTransition


class ResourceState(AggregateState[str]):
    """Base state for all managed resources (Kubernetes-like spec/status).

    Provides:
    - Identity: `id`, `resource_type`, `owner_id`
    - Spec/Status pattern: `status` (actual) + `desired_status` (target)
    - State history: `state_history` list of `StateTransition` records
    - Pipeline tracking: `pipeline_progress` for multi-step operations
    - Timestamps: `created_at`, `updated_at`

    Concrete aggregates (LabletSessionState, CMLWorkerState, LabRecordState)
    shadow these fields with their own typed versions (e.g., enum-typed status)
    and add domain-specific fields.
    """

    # --- Class-level type annotations (Neuroglia serialization pattern) ---
    # No default values here — defaults are set in __init__().
    id: str
    resource_type: str
    status: str
    desired_status: str | None
    owner_id: str

    state_history: list  # list[StateTransition] — generic list for Neuroglia compat
    pipeline_progress: dict | None

    created_at: datetime
    updated_at: datetime

    def __init__(self) -> None:
        """Initialize with safe defaults.

        Neuroglia bypasses __init__ during deserialization (MongoDB → object),
        so these defaults only apply to freshly created aggregates.
        """
        super().__init__()
        self.id = ""
        self.resource_type = ""
        self.status = ""
        self.desired_status = None
        self.owner_id = ""

        self.state_history = []
        self.pipeline_progress = None

        self.created_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)

    def _record_transition(
        self,
        from_state: str | None,
        to_state: str,
        triggered_by: str = "system",
        reason: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Record a state transition in the history.

        Concrete aggregates call this from their @dispatch event handlers
        to maintain a full audit trail.
        """
        transition = StateTransition(
            from_state=from_state,
            to_state=to_state,
            transitioned_at=datetime.now(UTC),
            triggered_by=triggered_by,
            reason=reason,
            metadata=metadata,
        )
        self.state_history.append(transition)
        self.updated_at = datetime.now(UTC)
