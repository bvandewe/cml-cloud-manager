# ADR-036 Phase 2: TimedResource Abstraction Extraction — Implementation Plan

| Attribute | Value |
|-----------|-------|
| **ADR Reference** | [ADR-036 §3 Phase 2](../architecture/adr/ADR-036-resource-management-abstraction-layer.md) |
| **Architecture Reference** | [TimedResource Data Model](../architecture/timed-resource-data-model.md) |
| **Target Sprint** | F |
| **Status** | 🔄 In Progress (Phase 2 core ✅, Phase 2.5 Batches A–G ✅, Batch I ⬜) |
| **Author** | Architecture Team |
| **Date** | 2026-03-09 |

---

## 1. Objective

Extract the three-layer `Resource` → `TimedResource` hierarchy into `lcm_core`,
creating the framework-promotable abstraction layer. All new types go into the
shared core package so that every microservice (CPA, worker-controller,
lablet-controller, resource-scheduler) can consume them.

**Key Constraint**: All changes MUST be backward-compatible. Existing aggregates
gain base class inheritance but **no behavioral changes**. MongoDB serialization
unchanged. All existing tests MUST pass without modification.

---

## 2. Context Analysis — Patterns to Follow

### 2.1 Value Object Pattern (from `lcm_core`)

Established by `ResourceObservation`, `NodeObservation`, `InterfaceObservation`:

- `@dataclass(frozen=True)` — immutable
- `to_dict() → dict[str, Any]` — JSON-safe serialization
- `@staticmethod from_dict(data: dict) → Self` — deserialization with sensible defaults
- Tuples for sequences (JSON serialized as lists)
- Explicit type annotations, no Pydantic
- Located in `lcm_core/domain/value_objects/`

### 2.2 Read Model Pattern (from `lcm_core`)

Established by `LabletSessionReadModel`, `CMLWorkerReadModel`, `LabRecordReadModel`:

- `@dataclass` (mutable — populated from API responses)
- `@classmethod from_dict(cls, data: dict) → Self`
- Optional fields with sensible defaults
- `__post_init__` for backward-compatible field mappings
- Located in `lcm_core/domain/entities/read_models/`

### 2.3 Test Pattern (from `lcm_core/tests/`)

Established by `test_resource_observation_value_objects.py`:

- Class-based test grouping: `class TestTimeslot:`
- Round-trip tests: `test_round_trip_full`, `test_round_trip_minimal`
- Edge-case tests: defaults, type coercion, boundary values
- Descriptive docstrings on every test method
- Direct imports from `lcm_core.domain.value_objects`
- No fixtures needed for simple VOs

### 2.4 Aggregate State Pattern (from CPA)

Established by `LabletSessionState`, `CMLWorkerState`, `LabRecordState`:

- Extends `AggregateState[str]` (Neuroglia)
- All fields declared as **class-level annotations** (required for Neuroglia deserialization)
- `__init__` sets defaults (not using dataclass — Neuroglia bypasses `__init__` on deserialization)
- `@dispatch(EventType)` handlers for event sourcing
- Status as type-specific enum (e.g., `CMLWorkerStatus`)

### 2.5 StateTransition — Current Location

Currently lives in **CPA only** (`control-plane-api/domain/value_objects/state_transition.py`)
and is tightly coupled to `LabletSessionStatus` enum. ADR-036 requires a **generic version**
in `lcm_core` that uses `str` for states, while the CPA version can remain for backward
compatibility during migration.

---

## 3. Implementation Plan — Task Breakdown

### Phase 2 Tasks (from ADR-036 §3)

| Task | Description | Component | Files |
|------|-------------|-----------|-------|
| **2.1** | Verify/create `StateTransition` VO in `lcm_core` | lcm_core | §3.1 |
| **2.2** | Create `Timeslot` VO in `lcm_core` | lcm_core | §3.2 |
| **2.3** | Create `LifecyclePhase` + `ManagedLifecycle` VOs | lcm_core | §3.3 |
| **2.4** | Create `ResourceState` abstract base | lcm_core | §3.4 |
| **2.5** | Create `TimedResourceState` abstract base | lcm_core | §3.5 |
| **2.6** | Create `TimedResourceReadModel` base | lcm_core | §3.6 |
| **2.7** | Refactor `LabletSessionState` to extend `TimedResourceState` | CPA | §3.7 |
| **2.8** | Add `state_history` to `CMLWorkerState` | CPA | §3.8 |
| **2.9** | Add `desired_status` to `LabRecordState` | CPA | §3.9 |
| **2.10** | Update `LabletSessionReadModel` to extend `TimedResourceReadModel` | lcm_core | §3.10 |
| **2.11** | Update `CMLWorkerReadModel` to extend `TimedResourceReadModel` | lcm_core | §3.11 |
| **2.12** | Tests for all VOs + base classes (40+ tests) | lcm_core | §3.12 |
| **2.13** | Backward compatibility — all existing tests pass | all | §3.13 |

---

### 3.1 Task 2.1: `StateTransition` Value Object in `lcm_core`

**Goal**: Create a **generic** `StateTransition` VO that uses `str` for states
(not `LabletSessionStatus`), making it usable by CMLWorker and LabRecord too.

**File**: `src/core/lcm_core/domain/value_objects/state_transition.py` (NEW)

**Design**:

```python
@dataclass(frozen=True)
class StateTransition:
    from_state: str | None        # None for initial creation
    to_state: str
    transitioned_at: datetime
    triggered_by: str             # User ID, component, or "system"
    reason: str | None = None
    metadata: dict[str, Any] | None = None

    def to_dict() → dict
    @staticmethod from_dict(data) → StateTransition
```

**Pattern alignment**:

- Follows `ResourceObservation` pattern: frozen dataclass, `to_dict`/`from_dict`
- Uses `str` for states (not enum) — enum-specific conversion handled by concrete aggregates
- The existing CPA `StateTransition` (uses `LabletSessionStatus`) will be updated to
  delegate to or wrap this generic version in a later migration step

**Backward compatibility**: The CPA `StateTransition` continues to work unchanged.
The lcm_core version is a NEW parallel class used by the new base classes.

**Update required**: `lcm_core/domain/value_objects/__init__.py` — add export

---

### 3.2 Task 2.2: `Timeslot` Value Object

**File**: `src/core/lcm_core/domain/value_objects/timeslot.py` (NEW)

**Design** (from ADR-036 §2.1.4):

```python
@dataclass(frozen=True)
class Timeslot:
    start: datetime
    end: datetime
    lead_time: timedelta = timedelta(minutes=15)
    teardown_buffer: timedelta = timedelta(minutes=10)

    # Computed properties
    @property provision_at → datetime       # start - lead_time
    @property cleanup_deadline → datetime   # end + teardown_buffer
    @property duration → timedelta          # end - start
    @property total_duration → timedelta    # cleanup_deadline - provision_at

    # Query methods
    def is_active(now=None) → bool          # start <= now <= end
    def is_expired(now=None) → bool         # now > end
    def remaining(now=None) → timedelta     # max(0, end - now)

    # Factory
    def extend(new_end) → Timeslot          # Returns new Timeslot with extended end

    def to_dict() → dict
    @staticmethod from_dict(data) → Timeslot
```

**Validation in `__post_init__`**:

- `end` must be after `start`
- `lead_time` must be non-negative
- `teardown_buffer` must be non-negative

**Pattern alignment**: Follows `ResourceObservation` pattern exactly.

**Update required**: `lcm_core/domain/value_objects/__init__.py` — add export

---

### 3.3 Task 2.3: `LifecyclePhase` + `ManagedLifecycle` Value Objects

**File**: `src/core/lcm_core/domain/value_objects/managed_lifecycle.py` (NEW)

**Design** (from ADR-036 §2.1.4):

```python
@dataclass(frozen=True)
class LifecyclePhase:
    name: str
    engine: str = "pipeline"                   # "pipeline" | "workflow"
    trigger_on_status: str | None = None
    pipeline_def: dict | None = None           # Step definitions for PipelineExecutor
    workflow_ref: dict | None = None           # {namespace, name, version}
    is_required: bool = True

    def to_dict() → dict
    @staticmethod from_dict(data) → LifecyclePhase

@dataclass(frozen=True)
class ManagedLifecycle:
    phases: tuple[LifecyclePhase, ...]         # Ordered, immutable sequence
    current_phase: str | None = None

    def get_phase(name: str) → LifecyclePhase | None
    def get_active_phases() → list[LifecyclePhase]  # where is_required=True
    def phase_names() → list[str]

    def to_dict() → dict
    @staticmethod from_dict(data) → ManagedLifecycle
```

**Design decision — `phases` field type**:

The ADR shows `dict[str, LifecyclePhase]` but the established VO pattern in lcm_core
uses **tuples for sequences** (see `ResourceObservation.nodes: tuple[NodeObservation, ...]`).
However, phases need key-based lookup by name, so we use `tuple[LifecyclePhase, ...]`
for immutability with a lookup-by-name method. The `to_dict` serializes phases as a
dict keyed by `name` for YAML/JSON readability.

**Update required**: `lcm_core/domain/value_objects/__init__.py` — add exports

---

### 3.4 Task 2.4: `ResourceState` Abstract Base

**File**: `src/core/lcm_core/domain/entities/resource.py` (NEW)

**Design** (from ADR-036 §2.1.4 Layer 1):

```python
class ResourceState(AggregateState[str]):
    """Base state for all managed resources (Kubernetes-like spec/status)."""

    id: str
    resource_type: str
    status: str
    desired_status: str | None
    owner_id: str

    state_history: list[StateTransition]
    pipeline_progress: dict | None

    created_at: datetime
    updated_at: datetime

    def __init__(self):
        # Set defaults following the established AggregateState pattern
```

**Critical design decisions**:

1. **`status` and `desired_status` as `str`** — NOT enums at this level. Each concrete
   aggregate uses its own enum type. The base class stores `str` for polymorphism.
   Concrete aggregates continue to use typed enums in their `__init__` and `@dispatch`
   handlers — they coerce to `str` when the base class needs it (or the base class
   simply declares `str` annotations and the Neuroglia serializer handles enum→str).

2. **`state_history: list[StateTransition]`** — Uses the new lcm_core `StateTransition`
   (str-based). Concrete aggregates can wrap with type-specific transitions if needed.

3. **NOT a Python ABC** — `AggregateState` is a Neuroglia class that doesn't support
   `ABC`/`abstractmethod`. We use documentation and type annotations to signal "abstract".

**Update required**: `lcm_core/domain/entities/__init__.py` — add export

---

### 3.5 Task 2.5: `TimedResourceState` Abstract Base

**File**: `src/core/lcm_core/domain/entities/timed_resource.py` (NEW)

**Design** (from ADR-036 §2.1.4 Layer 2):

```python
class TimedResourceState(ResourceState):
    """State for time-bounded resources with managed lifecycles."""

    timeslot: Timeslot | None            # When this resource is active
    lifecycle: ManagedLifecycle | None    # Phases and their execution strategies

    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: float | None
    terminated_at: datetime | None

    def __init__(self):
        super().__init__()
        # Set timed-resource specific defaults
```

**Design note on Neuroglia serialization**: The Neuroglia `MotorRepository` serializes
aggregate state using `get_type_hints()` and walks the class hierarchy. Adding a base
class with type-annotated fields is safe as long as:

- All new fields have defaults in `__init__`
- No required constructor args are added
- Field names don't conflict with existing aggregate fields

**Timeslot storage**: The `Timeslot` VO is stored as a serialized dict in MongoDB.
Concrete aggregates that currently use `timeslot_start`/`timeslot_end` as separate
fields will **keep those fields** during migration (Phase 2) and derive the `Timeslot`
VO from them. The full migration to `Timeslot`-only storage happens in a later phase.

**Update required**: `lcm_core/domain/entities/__init__.py` — add export

---

### 3.6 Task 2.6: `TimedResourceReadModel` Base

**File**: `src/core/lcm_core/domain/entities/read_models/timed_resource_read_model.py` (NEW)

**Design**:

```python
@dataclass
class TimedResourceReadModel:
    """Base read model for time-bounded resources."""

    id: str
    resource_type: str = ""
    status: str = ""
    desired_status: str | None = None
    owner_id: str = ""

    # Timeslot fields (flat for backward compat, not Timeslot VO)
    timeslot_start: datetime | None = None
    timeslot_end: datetime | None = None

    # Runtime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: float | None = None
    terminated_at: datetime | None = None

    # Lifecycle
    pipeline_progress: dict | None = None

    # Timestamps
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

**Design decision**: The read model keeps `timeslot_start`/`timeslot_end` as flat
fields (not a `Timeslot` VO) because read models are DTOs from API responses where
the timeslot is not yet consolidated into a VO at the API level.

**Update required**: `lcm_core/domain/entities/read_models/__init__.py` — add export

---

### 3.7 Task 2.7: Refactor `LabletSessionState` to Extend `TimedResourceState`

**File**: `src/control-plane-api/domain/entities/lablet_session.py` (MODIFY)

**Strategy**: Introduce inheritance WITHOUT changing any behavior.

**Changes**:

1. Add import: `from lcm_core.domain.entities.timed_resource import TimedResourceState`
2. Change: `class LabletSessionState(AggregateState[str]):` → `class LabletSessionState(TimedResourceState):`
3. In `__init__`: Call `super().__init__()` which now chains through `TimedResourceState → ResourceState → AggregateState`
4. **Keep all existing field annotations** — they override/augment base class fields
5. The `status` field remains `LabletSessionStatus` (enum) at the concrete level — the base class declares `str`, Python's MRO resolves to the concrete annotation

**CRITICAL RISK — Field Shadowing**:

Fields declared in `LabletSessionState` that overlap with `ResourceState`/`TimedResourceState`:

- `id` → already in ResourceState. Keep in LabletSessionState (shadows base, same type)
- `status` → ResourceState declares `str`, LabletSessionState declares `LabletSessionStatus`. **Safe**: concrete overrides abstract
- `desired_status` → same pattern as `status`
- `state_history` → ResourceState declares `list[StateTransition]` (lcm_core version). LabletSessionState uses CPA version. **RISK**: Type mismatch. **Mitigation**: During Phase 2, keep the LabletSessionState field as-is; it shadows the base. The base field is only used by NEW aggregates.
- `pipeline_progress` → same type, safe
- `created_at`, `started_at`, `ended_at`, `terminated_at`, `duration_seconds` → safe, same types

**Approach**: Shadow all overlapping fields in the concrete class. This is the
**safest backward-compatible** approach. The base class provides the structural
contract; concrete classes provide the actual implementation.

**Validation**: Run full CPA test suite — zero test modifications expected.

---

### 3.8 Task 2.8: Add `state_history` to `CMLWorkerState`

**File**: `src/control-plane-api/domain/entities/cml_worker.py` (MODIFY)

**Changes**:

1. Add field annotation: `state_history: list` (use generic list for now)
2. In `__init__`: `self.state_history = []`
3. Add `_record_transition()` method (copy pattern from LabletSessionState)
4. In the `on(CMLWorkerStatusUpdatedDomainEvent)` handler: call `_record_transition()`

**Scope**: This task adds the field and recording capability. It does NOT change
CMLWorkerState's base class (that's a later step when all fields are aligned).

**Why not change base class now?**: CMLWorkerState has significantly more fields
and domain-specific behavior. Changing its base class requires careful validation
that Neuroglia deserialization still works. This is lower risk as a standalone field addition.

---

### 3.9 Task 2.9: Add `desired_status` to `LabRecordState`

**File**: `src/control-plane-api/domain/entities/lab_record.py` (MODIFY)

**Changes**:

1. Add field annotation: `desired_status: str | None`
2. In `__init__`: `self.desired_status = None`
3. Add domain event: `LabRecordDesiredStatusSetDomainEvent` in `domain/events/lab_record_events.py`
4. Add `set_desired_status()` method on aggregate
5. Add `@dispatch(LabRecordDesiredStatusSetDomainEvent)` handler on state

**Scope**: Field addition only. No base class change.

---

### 3.10 Task 2.10: Update `LabletSessionReadModel`

**File**: `src/core/lcm_core/domain/entities/read_models/lablet_session_read_model.py` (MODIFY)

**Strategy**: Make `LabletSessionReadModel` extend `TimedResourceReadModel`.

**Changes**:

1. Add import: `from lcm_core.domain.entities.read_models.timed_resource_read_model import TimedResourceReadModel`
2. Change: `class LabletSessionReadModel:` → `class LabletSessionReadModel(TimedResourceReadModel):`
3. Remove fields that are now inherited: `id`, `status`, `desired_status`, `timeslot_start`, `timeslot_end`, `started_at`, `ended_at`, `pipeline_progress`
4. Keep LabletSession-specific fields
5. Update `from_dict` to pass base fields to `TimedResourceReadModel`

**RISK**: Field removal changes `__init__` parameter order for positional args.
**Mitigation**: `LabletSessionReadModel` already uses keyword arguments everywhere
(fields have defaults). The `from_dict` factory is the primary construction path.

**Validation**: All existing tests and consumers use `from_dict()` or keyword construction.

---

### 3.11 Task 2.11: Update `CMLWorkerReadModel`

**File**: `src/core/lcm_core/domain/entities/read_models/cml_worker_read_model.py` (MODIFY)

**Strategy**: Same as 3.10 but for CMLWorkerReadModel.

**Changes**:

1. Add import for `TimedResourceReadModel`
2. Change base class
3. Remove inherited fields: `id`, `status`, `desired_status`
4. **Note**: CMLWorkerReadModel does NOT currently have `timeslot_start`/`timeslot_end` fields (CMLWorker doesn't track timeslots yet). The inherited fields from `TimedResourceReadModel` will default to `None`.

**Validation**: Existing `from_dict` factory method handles all fields explicitly.

---

### 3.12 Task 2.12: Test Suite (40+ Tests)

**Files**: NEW test files in `src/core/tests/`

#### 3.12.1 `test_state_transition_value_object.py`

| # | Test | What it validates |
|---|------|-------------------|
| 1 | `test_round_trip_full` | All fields populated → `from_dict(to_dict(x)) == x` |
| 2 | `test_round_trip_minimal` | `from_state=None`, `reason=None`, `metadata=None` |
| 3 | `test_from_dict_none_from_state` | `from_state` absent in dict → `None` |
| 4 | `test_to_dict_transitioned_at_isoformat` | Datetime serialized as ISO string |
| 5 | `test_from_dict_parses_iso_datetime` | ISO string deserialized to datetime |
| 6 | `test_frozen_immutability` | Cannot mutate fields after creation |
| 7 | `test_metadata_preserved` | Arbitrary dict metadata round-trips |

#### 3.12.2 `test_timeslot_value_object.py`

| # | Test | What it validates |
|---|------|-------------------|
| 1 | `test_round_trip_full` | All fields with custom lead_time/teardown |
| 2 | `test_round_trip_defaults` | Default lead_time (15min) and teardown (10min) |
| 3 | `test_provision_at` | `provision_at == start - lead_time` |
| 4 | `test_cleanup_deadline` | `cleanup_deadline == end + teardown_buffer` |
| 5 | `test_duration` | `duration == end - start` |
| 6 | `test_total_duration` | `total_duration == cleanup_deadline - provision_at` |
| 7 | `test_is_active_within_window` | `is_active(now)` returns True when `start <= now <= end` |
| 8 | `test_is_active_before_start` | `is_active(now)` returns False before start |
| 9 | `test_is_active_after_end` | `is_active(now)` returns False after end |
| 10 | `test_is_expired` | `is_expired(now)` returns True after end |
| 11 | `test_is_not_expired` | `is_expired(now)` returns False before end |
| 12 | `test_remaining_within_window` | Correct remaining time calculation |
| 13 | `test_remaining_after_end` | Returns `timedelta(0)` after expiry |
| 14 | `test_extend_valid` | Returns new Timeslot with extended end |
| 15 | `test_extend_invalid_raises` | Raises ValueError if new_end <= current end |
| 16 | `test_validation_end_before_start` | `__post_init__` raises if `end <= start` |
| 17 | `test_validation_negative_lead_time` | `__post_init__` raises if `lead_time < 0` |
| 18 | `test_frozen_immutability` | Cannot mutate fields |
| 19 | `test_to_dict_timedelta_as_seconds` | Timedeltas serialized as float seconds |
| 20 | `test_from_dict_timedelta_from_seconds` | Timedeltas deserialized from float seconds |

#### 3.12.3 `test_managed_lifecycle_value_objects.py`

| # | Test | What it validates |
|---|------|-------------------|
| 1 | `test_lifecycle_phase_round_trip_full` | LifecyclePhase with all fields |
| 2 | `test_lifecycle_phase_round_trip_minimal` | LifecyclePhase with defaults only |
| 3 | `test_lifecycle_phase_pipeline_engine` | Engine defaults to "pipeline" |
| 4 | `test_lifecycle_phase_workflow_engine` | Engine = "workflow" with workflow_ref |
| 5 | `test_managed_lifecycle_round_trip` | Full ManagedLifecycle round-trip |
| 6 | `test_managed_lifecycle_empty_phases` | Empty phases tuple |
| 7 | `test_get_phase_found` | Returns correct phase by name |
| 8 | `test_get_phase_not_found` | Returns None for unknown name |
| 9 | `test_get_active_phases` | Filters by `is_required=True` |
| 10 | `test_phase_names` | Returns ordered list of phase names |
| 11 | `test_frozen_immutability` | Cannot mutate fields |
| 12 | `test_to_dict_phases_as_dict` | Phases serialized as dict keyed by name |
| 13 | `test_from_dict_phases_from_dict` | Phases deserialized from dict keyed by name |

#### 3.12.4 `test_timed_resource_read_model.py`

| # | Test | What it validates |
|---|------|-------------------|
| 1 | `test_base_fields_accessible` | TimedResourceReadModel instantiation with all fields |
| 2 | `test_defaults` | All optional fields default correctly |
| 3 | `test_lablet_session_inherits_base` | LabletSessionReadModel is instance of TimedResourceReadModel |
| 4 | `test_lablet_session_from_dict_preserves_base_fields` | Base fields populated via from_dict |
| 5 | `test_cml_worker_inherits_base` | CMLWorkerReadModel is instance of TimedResourceReadModel |
| 6 | `test_cml_worker_from_dict_preserves_base_fields` | Base fields populated via from_dict |
| 7 | `test_backward_compat_lablet_session_all_fields` | All existing LabletSessionReadModel fields still work |
| 8 | `test_backward_compat_cml_worker_all_fields` | All existing CMLWorkerReadModel fields still work |

---

### 3.13 Task 2.13: Backward Compatibility Verification

**Actions**:

1. Run `cd src/core && make test` — all lcm_core tests pass
2. Run `cd src/control-plane-api && make test` — all CPA tests pass
3. Run `cd src/lablet-controller && make test` — all lablet-controller tests pass
4. Run `cd src/worker-controller && make test` — all worker-controller tests pass
5. Run `cd src/resource-scheduler && make test` — all resource-scheduler tests pass

**Pass criteria**: Zero test modifications. If any test fails, the change is NOT
backward-compatible and must be redesigned.

---

## 4. File Tree — All New & Modified Files

```
src/core/lcm_core/domain/
├── value_objects/
│   ├── __init__.py                          ← MODIFY: add exports
│   ├── state_transition.py                  ← NEW (Task 2.1)
│   ├── timeslot.py                          ← NEW (Task 2.2)
│   └── managed_lifecycle.py                 ← NEW (Task 2.3)
├── entities/
│   ├── __init__.py                          ← MODIFY: add exports
│   ├── resource.py                          ← NEW (Task 2.4)
│   ├── timed_resource.py                    ← NEW (Task 2.5)
│   └── read_models/
│       ├── __init__.py                      ← MODIFY: add export
│       ├── timed_resource_read_model.py     ← NEW (Task 2.6)
│       ├── lablet_session_read_model.py     ← MODIFY (Task 2.10)
│       └── cml_worker_read_model.py         ← MODIFY (Task 2.11)

src/control-plane-api/domain/
├── entities/
│   ├── lablet_session.py                    ← MODIFY (Task 2.7) — NOT in Phase 2
│   ├── cml_worker.py                        ← MODIFY (Task 2.8) — state_history only
│   └── lab_record.py                        ← MODIFY (Task 2.9) — desired_status only
├── events/
│   └── lab_record_events.py                 ← MODIFY (Task 2.9) — add event

src/core/tests/
├── test_state_transition_value_object.py    ← NEW (Task 2.12.1)
├── test_timeslot_value_object.py            ← NEW (Task 2.12.2)
├── test_managed_lifecycle_value_objects.py   ← NEW (Task 2.12.3)
└── test_timed_resource_read_model.py        ← NEW (Task 2.12.4)
```

---

## 5. Implementation Order (Dependency Chain)

Tasks must be implemented in this order due to dependencies:

```
2.1 StateTransition VO ─────────────────────┐
                                             │
2.2 Timeslot VO ─────────────────────────────┤
                                             │
2.3 LifecyclePhase + ManagedLifecycle VOs ───┤
                                             │
                                             ▼
2.4 ResourceState (depends on 2.1) ──────────┤
                                             │
                                             ▼
2.5 TimedResourceState (depends on 2.2, 2.3, 2.4) ──┐
                                                      │
2.6 TimedResourceReadModel (independent) ─────────────┤
                                                      │
                                              ┌───────┤
                                              │       │
2.7 LabletSessionState refactor ──────────────┘       │ These 3 are independent
2.8 CMLWorkerState state_history ─────────────────────┤ of each other but
2.9 LabRecordState desired_status ────────────────────┘ depend on 2.4/2.5
                                                      │
2.10 LabletSessionReadModel refactor ─────────────────┤ Depend on 2.6
2.11 CMLWorkerReadModel refactor ─────────────────────┘
                                                      │
2.12 Tests (can start in parallel with each task) ────┘
                                                      │
2.13 Full backward compatibility verification ────────┘
```

### Recommended Implementation Batches

| Batch | Tasks | Rationale | Status |
|-------|-------|-----------|--------|
| **Batch A** | 2.1, 2.2, 2.3 | Value Objects — no dependencies, can be developed and tested independently | ✅ Complete |
| **Batch B** | 2.4, 2.5 | Entity base classes — depend on Batch A VOs | ✅ Complete |
| **Batch C** | 2.6 | Read model base — independent of B but logically follows | ✅ Complete |
| **Batch D** | 2.8, 2.9 | CPA aggregate field additions — low risk, independent of each other | ✅ Complete |
| **Batch E** | 2.7 | LabletSessionState refactor — highest risk, done after D validates patterns | ✅ Complete (original scope: field additions only) |
| **Batch F** | 2.10, 2.11 | Read model refactors — depend on C | ✅ Complete ||
| **Batch G** | 2.12, 2.13 | LabRecordState → ResourceState + testing and validation | ✅ Complete |
| **Batch I** | 2.14 | LabletDefinitionState → TimedResourceState (Layer 2) — last aggregate promotion | ⬜ Not Started |

---

## 6. Risk Assessment

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Neuroglia `get_type_hints()` doesn't walk MRO for inherited fields | High | Low | Test with minimal prototype before full implementation |
| `LabletSessionState` field shadowing causes serialization issues | High | Medium | Shadow ALL overlapping fields in concrete class; test MongoDB round-trip |
| Read model base class changes `__init__` parameter order | Medium | Low | All construction uses keyword args or `from_dict` factory |
| CMLWorkerState `state_history` field breaks existing MongoDB documents | Medium | Low | Default to `[]` in `__init__`; Neuroglia sets missing fields to type default |
| `Timeslot` VO complicates `timeslot_start`/`timeslot_end` migration | Low | Medium | Phase 2 keeps flat fields; `Timeslot` VO is parallel, not replacing |

---

## 7. Acceptance Criteria

1. ✅ All 3 new VOs (`StateTransition`, `Timeslot`, `ManagedLifecycle`) implemented with `to_dict`/`from_dict`
2. ✅ `ResourceState` and `TimedResourceState` base classes in `lcm_core`
3. ✅ `TimedResourceReadModel` base class in `lcm_core`
4. ✅ `LabletSessionReadModel` and `CMLWorkerReadModel` extend `TimedResourceReadModel`
5. ✅ `CMLWorkerState` has `state_history` field
6. ✅ `LabRecordState` has `desired_status` field with domain event
7. ✅ 40+ unit tests covering all new code
8. ✅ All existing tests pass without modification across all 5 microservices
9. ✅ `lcm_core/domain/value_objects/__init__.py` and `lcm_core/domain/entities/__init__.py` updated with exports

---

## 8. Deferred to Later Phases

The following are explicitly **NOT** in Phase 2 scope:

| Item | Deferred to | Reason | Status |
|------|-------------|--------|--------|
| Change `CMLWorkerState` base class to `TimedResourceState` | Phase 2.5 Batch E | High risk; needs dedicated MongoDB round-trip testing | ✅ Complete (AD-P2-E01) |
| Change `LabRecordState` base class to `ResourceState` (Layer 1) | Phase 2.5 Batch G | LabRecords have open-ended lifetimes, no timeslots — ResourceState (not TimedResourceState) per AD-G0 | ✅ Complete (AD-G0) |
| Migrate `LabletSessionState.timeslot_start/end` → `Timeslot` VO | Phase 2.5 Batch F | Requires API-level changes and frontend updates | ✅ Complete (AD-P2-F01) |
| Replace CPA `StateTransition` with lcm_core version | Phase 2.5 Batch F | Requires updating all CPA event handlers | ✅ Complete (AD-P2-F01) |
| Change `LabletDefinitionState` base class to `TimedResourceState` (Layer 2) | Phase 2.5 Batch I | Last remaining aggregate extending raw `AggregateState[str]`. Timeslot-bounded definitions enable automatic expiry and time-windowed availability for instantiation. Per AD-I0. | ⬜ Not Started |
| Frontend pipeline progress components (ADR-036 1.12–1.13) | Phase 1 (frontend sprint) | Independent of backend abstraction | 🔲 Not Started |
| `LabletSessionState` base class change to `TimedResourceState` | Phase 2.5 Batch F | Validate base classes work first, then refactor | ✅ Complete (AD-P2-F01) |

**Note on Task 2.7 (LabletSessionState refactor)**: Upon careful review, changing the
base class of `LabletSessionState` from `AggregateState[str]` to `TimedResourceState`
carried significant risk due to field shadowing with different types (`LabletSessionStatus`
vs `str`). This was deferred to Phase 2.5 after validating the base classes work
correctly with NEW aggregates (like DemoSession in Phase 4). In Phase 2, the base classes
were **created and tested** but not yet inherited by existing aggregates.

> **✅ Phase 2.5 Completion Status (2026-03-09):**
>
> - **Batch E (CMLWorkerState → TimedResourceState):** Complete. CMLWorkerState base class
>   changed, CML_WORKER_LIFECYCLE defined in `domain/lifecycles.py`, all `_record_transition()`
>   handlers updated with `.value` enum-to-str conversion, backward-compatible Timeslot
>   properties added. 1070 CPA tests pass, 263 lcm_core tests pass. (AD-P2-E01, AD-P2-E02)
>
> - **Batch F (LabletSessionState → TimedResourceState):** Complete. LabletSessionState base
>   class changed, LABLET_SESSION_LIFECYCLE (10 phases) defined, `_record_transition()` stores
>   dicts via `StateTransition.to_dict()`, all 22 event handlers updated, CPA-local
>   `StateTransition` imports consolidated to `lcm_core`, backward-compatible `timeslot_start`/
>   `timeslot_end` properties with legacy fallback. 46 new tests, 929 CPA tests pass (+2
>   pre-existing failures), 263 lcm_core tests pass, lint clean. (AD-P2-F01, AD-P2-F02)
>
> - **Batch G (LabRecordState → ResourceState):** Complete. LabRecordState base class changed
>   to ResourceState (Layer 1, not TimedResourceState) per AD-G0 — LabRecords have open-ended
>   lifetimes with no timeslots or lifecycle phases. `_record_transition()` wired into all 13
>   status-changing @dispatch handlers with conditional transitions for idempotent events.
>   CPA-local `state_transition.py` deleted, imports consolidated to `lcm_core`. 38 new tests,
>   1108 CPA tests pass (+2 pre-existing failures), 263 lcm_core tests pass, lint clean.
>   (AD-G0)
>
> - **Key patterns established:** Dict-based state_history (via `StateTransition.to_dict()`),
>   backward-compatible `@property` accessors for Timeslot VO fields, `ManagedLifecycle` wiring
>   in aggregate `Created` event handlers.
>
> - **Batch I (LabletDefinitionState → TimedResourceState):** ⬜ Not Started. Last remaining
>   aggregate extending raw `AggregateState[str]`. Will promote to Layer 2 (TimedResourceState)
>   per AD-I0 — definitions are time-bounded templates that expire when their timeslot ends.
>   Key design decisions:
>   - **Layer 2 (not Layer 1):** Definitions need timeslot (time-bounded availability) and
>     managed lifecycle (content sync pipeline tracking)
>   - **`desired_status`:** Initially unused (None); reserved for future definition reconciliation
>     via a definition controller (similar to worker-controller pattern)
>   - **`created_by` → `owner_id`:** Mapped in DefinitionCreated event handler; future
>     `set-definition-owner` command planned when user profile management is available
>   - **Timeslot semantics:** Definitions are only available for instantiation during their
>     valid timeslot window. Authorized users can extend timeslots via `Timeslot.extend()`.
>     Expired definitions should transition to ARCHIVED or a new EXPIRED status.
>   - **Status enum expansion:** Consider adding EXPIRED to `LabletDefinitionStatus` for
>     timeslot-driven automatic expiry (vs manual DEPRECATED)
>   - **Scope estimate:** ~60% of Batch G effort (fewer event handlers, no pending_action pattern)

---

## P2-FINAL: Documentation Maintenance (Mandatory)

Per AD-DOC-001, every implementation phase includes a final documentation task:

- [x] Update this plan: mark Phase 2 tasks complete, record actual vs planned
- [ ] Update [ADR-036](../architecture/adr/ADR-036-resource-management-abstraction-layer.md): Phase 2 status → DONE
- [ ] Update implementation_status.md if it exists
- [x] Update CHANGELOG.md with Phase 2 changes under "Unreleased"
