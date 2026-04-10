# LCM UI/UX Enhancement — Bootstrap Prompt

> **Date:** 2026-03-10
> **Scope:** Extend `lcm_ui` core library + all CPA datatables for richer resource visualization
> **Audience:** AI coding agent implementing the changes

---

## 1. MISSION

Evolve the LCM frontend from status-display-only tables into **resource-aware dashboards** where every managed resource (Worker, LabletSession, LabRecord, LabletDefinition) exposes its full lifecycle, pipeline execution state, desired-vs-current reconciliation status, state history with transitions, and revision tracking — all driven by the resource's state schema rather than hardcoded column lists.

---

## 2. CURRENT STATE (What Exists Today)

### 2.1 Architecture

```
lcm_ui (core lib)          → @neuroglia/ui-core, TypeScript, Rollup → ESM+UMD
  ├── core/                → EventBus, StateStore, SSEClient, EventBuffer
  ├── session/             → SessionManager (auth lifecycle)
  ├── middleware/           → Logger, DevTools, Persistence, Throttle
  ├── components/          → BaseComponent, DataTable, StatusBadge, DashboardCard,
  │                          TabView, Modal, ActionBar, FilterBar
  └── types/               → EventBus, Store, Component type definitions

CPA UI (consumer)          → Parcel 2, Bootstrap 5, Vanilla JS
  ├── core/                → LcmDataTable (extends DataTable), LcmStatusBadge,
  │                          LcmModal, LcmTabView, LcmActionBar, LcmGrafanaPanel
  ├── store/               → StateStore slices: workers, sessions, definitions, templates
  ├── sse/                 → SSE adapter (wire→EventBus→Store), ~65 domain events
  └── components/          → Domain: WorkerList, SessionList, DefinitionList,
                              SessionDetailPage, PipelineProgressPanel, etc.
```

### 2.2 Datatable Columns Today (Hardcoded)

Each list component defines its own `columns` array with hardcoded field names:

| Resource | Table Component | Current Columns | Missing from State Schema |
|----------|----------------|-----------------|--------------------------|
| **Worker** | `WorkerList.js` | name, region, status, instance_type, cpu%, mem%, labs_count, created | desired_status, state_history, lifecycle phases, port_utilization, idle state, pause/resume tracking, revision |
| **LabletSession** | `LabletSessionList.js` | definition, owner, status, worker, topology, timeslot, form_qn, pipeline_dots, actions | desired_status, state_history, lifecycle phases, pipeline detail, resource_observation, revision, grading result |
| **LabletDefinition** | `LabletDefinitionList.js` | name, form_qn, status, sync_status, nodes, links, updated | desired_status, state_history, timeslot, lifecycle, owner_id, content_versions, pipelines config, deprecation info, warm_pool_depth, revision |
| **LabRecord** | `WorkerDetailsModal` (inline) | title, worker, status, nodes, links, source, updated | desired_status, state_history, pending_action detail, runtime_binding, revision |

### 2.3 What Exists in lcm_ui Core Components

| Component | Tag | What It Does | What's Missing |
|-----------|-----|-------------|----------------|
| `DataTable` | `<ui-data-table>` | Sort, filter, paginate, select, bulk/row actions | Column visibility toggle, column groups, column presets, schema-driven column generation, expandable rows, nested detail panels |
| `StatusBadge` | `<ui-status-badge>` | Maps ~35 statuses to Bootstrap color+icon | No desired-vs-current dual display, no transition arrow, no "reconciling" animation |
| `TabView` | `<ui-tab-view>` | Tabbed navigation | No lifecycle-phase-aware tabs, no phase completion indicators |
| `BaseComponent` | — | Web Component base with EventBus/Store | Good foundation, no resource-aware lifecycle hooks |

### 2.4 Backend State Schemas (Source of Truth)

```
AggregateState[str]
  └── ResourceState                    ← All managed resources
  │     ├── id, resource_type, status, desired_status, owner_id
  │     ├── state_history: list[StateTransition]
  │     ├── annotations: dict | None
  │     ├── created_at, updated_at
  │     └── state_version: int         ← Revision counter
  │
  └── TimedResourceState               ← LabletSession, LabletDefinition, scheduled resources
        ├── (inherits all ResourceState fields)
        ├── timeslot: Timeslot | None   ← start, end, lead_time, teardown_buffer
        ├── managed_lifecycle: ManagedLifecycle | None
        │     └── phases: tuple[LifecyclePhase, ...]
        │           └── name, phase_type ("pipeline"|"workflow"),
        │               status, started_at, completed_at
        ├── resource_observation: ResourceObservation | None
        │     └── status, nodes[].name/state/cpu/memory/interfaces[]
        ├── started_at, ended_at
        └── duration_seconds
```

**Key Value Objects:**

| Object | Fields | Purpose |
|--------|--------|---------|
| `StateTransition` | from_state, to_state, transitioned_at, triggered_by, reason, metadata | Full audit trail of every status change |
| `Timeslot` | start, end, lead_time_minutes, teardown_buffer_minutes + computed: duration, is_active, is_expired, window_phase | Time-bounded resource reservation |
| `ManagedLifecycle` | phases: tuple[LifecyclePhase, ...], current_phase | Ordered pipeline/workflow execution tracking |
| `LifecyclePhase` | name, phase_type, status, started_at, completed_at | Individual pipeline execution record |
| `ResourceObservation` | status, cpu_usage, memory_usage, storage_usage, nodes[] | Live CML resource telemetry |
| `NodeObservation` | label, state, cpu_usage, memory_usage_mb, interfaces[] | Per-node resource telemetry |

### 2.5 DTOs Exposed to Frontend (via SSE + REST)

**WorkerDetailDto** (~80 fields): identity, status, **desired_status**, AMI, network, AWS tags, license, CML metrics, EC2 metrics, CloudWatch, utilization, timing, activity/idle, pause/resume, capacity, port usage

**LabletSessionDetailDto** (~40 fields): identity, definition refs, worker refs, status, **desired_status**, timeslot, allocated_ports, **state_history** (list[StateTransitionDto]), pipeline_progress, resource_observation, user_session, grading_session, score_report

**LabRecordReadModel** (~30 fields): identity, worker_id, lab_id, status, title, state, owner, node/link counts, **pending_action** fields, last_error, runtime_binding

**LabletDefinitionDetailDto** (~25+ fields): identity, topology, resource_requirements, port_template, assessment config, **pipelines**, content metadata, deprecation, sync_status. _After Batch I:_ + **desired_status**, **state_history**, **timeslot**, **managed_lifecycle**, **owner_id**

**StateTransitionDto**: from_state, to_state, transitioned_at, triggered_by, reason, metadata

### 2.6 SSE Events Already Wired

~65 domain events flow through SSE → EventBus → Store slices, including:

- `pipeline_step_started/completed/failed` → updates `pipeline_progress` in session store
- `status_changed` → updates status on all resources
- `desired_status_changed` → updates desired_status on sessions
- `snapshot` events → full state refresh for workers/sessions/definitions
- `resource_observation` data embedded in session events

---

## 3. TARGET STATE (What We're Building)

### 3.1 New lcm_ui Core Components

#### 3.1.1 `<ui-resource-status>` — Desired vs Current Status Display

**Purpose:** Replace simple `<ui-status-badge>` when a resource has both `status` and `desired_status`.

```
┌─────────────────────────────────┐
│ RUNNING  ──→  STOPPING          │  ← current status badge + arrow + desired status badge
│ ◐ Reconciling...                │  ← animated indicator when current ≠ desired
└─────────────────────────────────┘
```

**Attributes:**

- `status` — current resource status (string)
- `desired-status` — target status (string, optional)
- `resource-type` — for status color mapping ("worker"|"session"|"lab"|"definition")
- `show-arrow` — whether to show transition arrow (boolean, default: true when desired ≠ current)
- `compact` — single-line mode for table cells (boolean)

**Behavior:**

- When `desired_status === null || desired_status === status` → renders single `<ui-status-badge>`
- When they differ → renders dual badges with animated `→` and "Reconciling..." subtext
- Pulse animation on the desired badge when reconciliation is in progress

#### 3.1.2 `<ui-state-history>` — Transition Timeline

**Purpose:** Render a resource's `state_history: StateTransition[]` as a visual timeline.

```
┌──────────────────────────────────────────────────────────────┐
│ State History (7 transitions)                    [Collapse ▲]│
│                                                              │
│  ● PENDING ──→ SCHEDULED    2m ago    by: scheduler          │
│  │                          reason: Timeslot approaching     │
│  ● SCHEDULED ──→ INSTANTIATING  1m ago  by: lablet-controller│
│  │                          reason: Worker assigned           │
│  ● INSTANTIATING ──→ READY  30s ago   by: pipeline           │
│  │                          reason: Instantiation complete    │
│  ◉ READY (current)                                           │
└──────────────────────────────────────────────────────────────┘
```

**Attributes:**

- `transitions` — JSON string or JS array of `StateTransition` objects
- `resource-type` — for status color mapping
- `max-visible` — how many to show before "Show more" (default: 5)
- `compact` — single-line summary mode ("PENDING → SCHEDULED → ... → READY")
- `show-metadata` — expand metadata JSON in each transition (default: false)

**Behavior:**

- Chronological (newest first) or reverse-chronological toggle
- Each transition shows: from → to status badges, relative time, triggered_by, reason
- Expandable metadata section per transition
- Compact mode: renders as breadcrumb-style chain (for table cells)

#### 3.1.3 `<ui-lifecycle-tracker>` — Phase/Pipeline Progress

**Purpose:** Visualize a `ManagedLifecycle` with its ordered phases and their status.

```
┌────────────────────────────────────────────────────────────────┐
│ Lifecycle Progress                                             │
│                                                                │
│  [✅ Upstream Sync] → [✅ Storage] → [⏳ POD Setup] → [⬜ LDS] → [⬜ Score] │
│       0.3s              1.2s          Running...                │
│                                                                │
│  Current Phase: POD Setup (pipeline)                           │
│  Started: 10s ago                                              │
└────────────────────────────────────────────────────────────────┘
```

**Attributes:**

- `phases` — JSON string or JS array of `LifecyclePhase` objects
- `current-phase` — name of the active phase (string)
- `layout` — "horizontal" (progress bar) | "vertical" (step list) | "compact" (dots like today's pipeline column)
- `show-timing` — show duration for each completed phase (boolean)
- `interactive` — clicking a phase opens detail (boolean, for use in modals)

**Status Icons per Phase:**

- `pending` → ⬜ (outline circle)
- `running` → ⏳ (spinner)
- `completed` → ✅ (green check)
- `failed` → ❌ (red X)
- `skipped` → ⊘ (grey slash)

**Behavior:**

- Automatically updates via EventBus `pipeline_step_*` events
- Horizontal layout for table cells / compact spaces
- Vertical layout with timing details for modals/detail pages
- Compact layout (colored dots) backward-compatible with today's pipeline column

#### 3.1.4 `<ui-pipeline-log>` — Pipeline Execution Log Viewer

**Purpose:** Detailed execution log for a single pipeline run, showing each step with its output, errors, timing, and retry attempts.

```
┌──────────────────────────────────────────────────────────────┐
│ Pipeline: Instantiation (Attempt #1)     Status: ✅ Complete │
│ Started: 2026-03-10 14:32:01   Duration: 12.4s              │
│──────────────────────────────────────────────────────────────│
│ ▼ Step 1: validate_definition          ✅  0.1s             │
│   Input: { definition_id: "def-123" }                        │
│   Output: { valid: true, node_count: 4 }                     │
│                                                              │
│ ▼ Step 2: check_worker_capacity        ✅  0.3s             │
│   Input: { worker_id: "w-456", required_nodes: 4 }           │
│   Output: { available: true, allocated_ports: [...] }        │
│                                                              │
│ ▼ Step 3: create_cml_lab               ⏳  Running (8.2s)   │
│   Input: { topology_yaml: "..." }                            │
│   └─ Live output stream...                                   │
│                                                              │
│ ▷ Step 4: configure_networking         ⬜  Pending           │
│ ▷ Step 5: register_with_lds            ⬜  Pending           │
└──────────────────────────────────────────────────────────────┘
```

**Attributes:**

- `pipeline-name` — name of the pipeline (string)
- `steps` — JSON array of step execution records
- `status` — overall pipeline status
- `attempt` — attempt number (for retries)
- `auto-scroll` — follow latest output (boolean, default: true)
- `collapsible` — allow collapsing completed steps (boolean, default: true)

**Step Record Shape:**

```typescript
interface PipelineStep {
  name: string;
  label: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  prerequisites: string[];
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  input: Record<string, any> | null;
  output: Record<string, any> | null;
  error: string | null;
  retry_count: number;
}
```

**Behavior:**

- Subscribes to `pipeline_step_started/completed/failed` SSE events for live updates
- Running steps show elapsed timer (auto-updating)
- Failed steps highlight in red with expandable error trace
- Completed steps auto-collapse (show one-line summary)
- JSON input/output rendered with syntax highlighting (or `<ui-code-viewer>`)

#### 3.1.5 `<ui-revision-indicator>` — Version / Revision Display

**Purpose:** Show a resource's `state_version` (revision counter) with change-since-last-view indicator.

```
┌────────────┐
│ v12  △+3   │  ← version 12, 3 changes since last viewed
└────────────┘
```

**Attributes:**

- `version` — current state_version number
- `previous-version` — last-seen version (from localStorage, optional)
- `resource-id` — for tracking last-seen per resource
- `compact` — badge-only mode for table cells

**Behavior:**

- Shows version number
- If `previous-version` is known and differs, shows delta badge ("+N changes")
- Clicking opens state history (emits `revision-clicked` event)
- Stores last-viewed version in localStorage per resource-id

#### 3.1.6 `<ui-timeslot-badge>` — Timeslot Visualization

**Purpose:** Rich timeslot display replacing the current inline date formatting.

```
Active:     [🟢 Active  14:00–15:30  (47m remaining)]
Approaching:[🟡 Starts in 12m  14:00–15:30]
Expired:    [🔴 Ended 5m ago  14:00–15:30]
No timeslot:[⚪ No timeslot]
```

**Attributes:**

- `start` — ISO datetime string
- `end` — ISO datetime string
- `lead-time` — minutes (for "approaching" detection)
- `teardown-buffer` — minutes (for teardown phase detection)
- `compact` — single-line for table cells

**Computed Properties:**

- `window_phase` → 'before' | 'approaching' | 'active' | 'teardown' | 'expired'
- Auto-updates every 30s to keep relative times fresh
- Color coding matches backend `Timeslot.window_phase` logic

#### 3.1.7 `<ui-resource-observation>` — Live Telemetry Display

**Purpose:** Render `ResourceObservation` data from CML telemetry.

```
┌──────────────────────────────────────────┐
│ Resource Observation  (5s ago)           │
│ CPU: ███████░░░ 68%   Mem: █████░░░ 52% │
│ Storage: ██░░░░░░ 23%  Nodes: 4/6 active│
│                                          │
│ ▼ Node Details                           │
│  router-1  BOOTED  CPU 82%  Mem 45%      │
│  switch-1  BOOTED  CPU 12%  Mem 23%      │
│  server-1  BOOTED  CPU 91%  Mem 78%  ⚠   │
│  ext-net   BOOTED  CPU  2%  Mem  5%      │
└──────────────────────────────────────────┘
```

**Attributes:**

- `observation` — JSON ResourceObservation object
- `show-nodes` — expand node details (default: false)
- `compact` — bar-only mode for table cells
- `warn-threshold` — CPU/mem % threshold for warning highlight (default: 80)

---

### 3.2 Extended `<ui-data-table>` / `<lcm-data-table>` Features

#### 3.2.1 Schema-Driven Column Generation

**Goal:** Instead of hardcoded column arrays, datatables should be configurable from the resource state schema.

```typescript
interface SchemaColumn extends ColumnDefinition {
  // Existing
  field: string;
  label: string;
  sortable?: boolean;
  width?: string;
  type?: 'string' | 'number' | 'date' | 'datetime' | 'boolean';
  render?: (value: any, row: any) => string;

  // NEW
  group?: string;              // Column group name for organization
  visible?: boolean;           // Default visibility (some hidden by default)
  pinned?: 'left' | 'right';  // Pin column to edge
  resizable?: boolean;         // Allow column resize
  description?: string;        // Tooltip on column header
  category?: string;           // For column picker grouping: 'identity'|'status'|'timing'|'metrics'|'lifecycle'|'metadata'
  component?: string;          // Custom element tag to render cell (e.g. 'ui-status-badge', 'ui-timeslot-badge')
  componentAttrs?: Record<string, string>; // Attribute mapping: { 'status': 'row.status', 'resource-type': "'worker'" }
}
```

#### 3.2.2 Column Visibility Picker

**New sub-component:** `<ui-column-picker>`

```
┌──────────────────────────────────┐
│ ⚙ Columns                       │
│──────────────────────────────────│
│ Identity                         │
│  ☑ Name    ☑ ID    ☐ Owner      │
│ Status                           │
│  ☑ Status  ☐ Desired Status     │
│  ☐ Reconciliation State         │
│ Timing                           │
│  ☑ Timeslot  ☐ Started  ☐ Ended│
│  ☐ Duration                     │
│ Lifecycle                        │
│  ☑ Pipeline  ☐ Phase Detail     │
│  ☐ State History                │
│ Metrics                          │
│  ☐ CPU  ☐ Memory  ☐ Nodes      │
│ Metadata                         │
│  ☐ Revision  ☐ Annotations     │
│──────────────────────────────────│
│ [Reset to Default] [Save Preset] │
└──────────────────────────────────┘
```

**Behavior:**

- Column visibility persisted to localStorage per table ID
- Categories from column `category` field
- Preset system: users can save/load column configurations
- "Reset to Default" restores the hardcoded default set
- Keyboard accessible (tabbing, space to toggle)

#### 3.2.3 Expandable Row Detail

**New feature on `<ui-data-table>`:** Clicking a row expand icon (▶) reveals an inline detail panel below the row.

```
│ session-abc │ RUNNING │ worker-1 │ Active │ ✅✅⏳⬜⬜ │ ▼ │
├─────────────┴─────────┴──────────┴────────┴───────────┴───┤
│ ┌─ State History ──┐ ┌─ Lifecycle ─────────────────────┐  │
│ │ PENDING→SCHEDULED │ │ [✅ Upstream] → [⏳ POD] → ... │  │
│ │ SCHEDULED→INSTNT  │ │ Current: POD Setup (12s)       │  │
│ │ INSTNT→READY      │ └────────────────────────────────┘  │
│ │ READY→RUNNING     │ ┌─ Resource Observation ──────────┐ │
│ └───────────────────┘ │ CPU: 68%  Mem: 52%  Nodes: 4/6 │  │
│                       └─────────────────────────────────┘  │
├─────────────┬─────────┬──────────┬────────┬───────────┬───┤
│ session-def │ PENDING │   —      │  —     │ ⬜⬜⬜⬜⬜│ ▶ │
```

**Configuration:**

```typescript
interface ExpandableRowConfig {
  enabled: boolean;
  renderDetail: (row: any) => string;  // HTML template for expanded content
  expandOnClick: boolean;              // Row click expands (vs. explicit button)
  singleExpand: boolean;               // Only one row expanded at a time
  lazyLoad: boolean;                   // Fetch detail data on expand
  detailUrl?: string;                  // REST endpoint template for lazy load
}
```

#### 3.2.4 Column Group Headers

Support two-level headers for complex tables:

```
│          Identity          │       Status        │     Lifecycle      │
│ Name │ Definition │ Owner  │ Current │ Desired   │ Phase │ Pipeline   │
│------│------------│--------│---------│-----------│-------│------------│
```

---

### 3.3 CPA LcmDataTable Column Registries

Replace hardcoded column arrays with **column registries** per resource type. Each registry defines ALL possible columns; list components select a default subset.

#### 3.3.1 Worker Column Registry

```javascript
// scripts/columns/workerColumns.js
export const WORKER_COLUMNS = {
  // Identity
  name:           { field: 'name', label: 'Name', category: 'identity', visible: true, sortable: true },
  id:             { field: 'id', label: 'ID', category: 'identity', visible: false, sortable: true },
  ec2_instance_id:{ field: 'ec2_instance_id', label: 'EC2 ID', category: 'identity', visible: false },
  aws_region:     { field: 'aws_region', label: 'Region', category: 'identity', visible: true, sortable: true },

  // Status
  status:         { field: 'status', label: 'Status', category: 'status', visible: true, sortable: true,
                    component: 'ui-resource-status',
                    componentAttrs: { status: 'row.status', 'desired-status': 'row.desired_status', 'resource-type': "'worker'", compact: true } },
  desired_status: { field: 'desired_status', label: 'Desired', category: 'status', visible: false },

  // Infrastructure
  instance_type:  { field: 'instance_type', label: 'Instance Type', category: 'infra', visible: true, sortable: true },
  ip_address:     { field: 'ip_address', label: 'IP Address', category: 'infra', visible: false },
  ami_name:       { field: 'ami_name', label: 'AMI', category: 'infra', visible: false },
  template_name:  { field: 'template_name', label: 'Template', category: 'infra', visible: false },

  // Metrics
  cpu_utilization:{ field: 'cpu_utilization_percent', label: 'CPU %', category: 'metrics', visible: true, sortable: true, type: 'number' },
  memory_util:    { field: 'memory_utilization_percent', label: 'Memory %', category: 'metrics', visible: true, sortable: true, type: 'number' },
  disk_util:      { field: 'disk_utilization_percent', label: 'Disk %', category: 'metrics', visible: false, type: 'number' },
  active_labs:    { field: 'active_labs_count', label: 'Labs', category: 'metrics', visible: true, sortable: true },
  port_util:      { field: 'port_utilization_pct', label: 'Port %', category: 'metrics', visible: false, type: 'number' },

  // Activity
  is_idle:        { field: 'is_idle', label: 'Idle', category: 'activity', visible: false, type: 'boolean' },
  last_activity:  { field: 'last_activity_at', label: 'Last Activity', category: 'activity', visible: false, type: 'datetime' },
  idle_detection: { field: 'is_idle_detection_enabled', label: 'Idle Detection', category: 'activity', visible: false, type: 'boolean' },

  // License
  license_status: { field: 'license.status', label: 'License', category: 'license', visible: false },

  // Timing
  created_at:     { field: 'created_at', label: 'Created', category: 'timing', visible: true, sortable: true, type: 'datetime' },
  updated_at:     { field: 'updated_at', label: 'Updated', category: 'timing', visible: false, type: 'datetime' },

  // Lifecycle
  state_history:  { field: 'state_history', label: 'History', category: 'lifecycle', visible: false,
                    component: 'ui-state-history', componentAttrs: { transitions: 'row.state_history', 'resource-type': "'worker'", compact: true } },

  // Revision
  state_version:  { field: 'state_version', label: 'Rev', category: 'revision', visible: false,
                    component: 'ui-revision-indicator', componentAttrs: { version: 'row.state_version', 'resource-id': 'row.id' } },

  // Actions (always last)
  actions:        { field: '_actions', label: 'Actions', category: 'actions', visible: true, sortable: false, pinned: 'right' },
};

export const WORKER_DEFAULT_COLUMNS = ['name', 'aws_region', 'status', 'instance_type', 'cpu_utilization', 'memory_util', 'active_labs', 'created_at', 'actions'];
```

#### 3.3.2 Session Column Registry

```javascript
// scripts/columns/sessionColumns.js
export const SESSION_COLUMNS = {
  // Identity
  definition_name:{ field: 'definition_name', label: 'Definition', category: 'identity', visible: true, sortable: true },
  id:             { field: 'id', label: 'ID', category: 'identity', visible: false },
  owner_id:       { field: 'owner_id', label: 'Candidate', category: 'identity', visible: true, sortable: true },
  definition_id:  { field: 'definition_id', label: 'Def ID', category: 'identity', visible: false },
  form_qn:        { field: 'form_qualified_name', label: 'Form', category: 'identity', visible: true, sortable: true },

  // Status
  status:         { field: 'status', label: 'Status', category: 'status', visible: true, sortable: true,
                    component: 'ui-resource-status',
                    componentAttrs: { status: 'row.status', 'desired-status': 'row.desired_status', 'resource-type': "'session'", compact: true } },
  desired_status: { field: 'desired_status', label: 'Desired', category: 'status', visible: false },

  // Placement
  worker_name:    { field: 'worker_name', label: 'Worker', category: 'placement', visible: true, sortable: true },
  worker_region:  { field: 'worker_region', label: 'Region', category: 'placement', visible: false },

  // Topology
  topology:       { field: 'node_count', label: 'Topology', category: 'topology', visible: true, sortable: true },

  // Timeslot
  timeslot:       { field: 'timeslot_start', label: 'Timeslot', category: 'timing', visible: true, sortable: true,
                    component: 'ui-timeslot-badge',
                    componentAttrs: { start: 'row.timeslot_start', end: 'row.timeslot_end', compact: true } },
  started_at:     { field: 'started_at', label: 'Started', category: 'timing', visible: false, type: 'datetime' },
  ended_at:       { field: 'ended_at', label: 'Ended', category: 'timing', visible: false, type: 'datetime' },
  duration:       { field: 'duration_seconds', label: 'Duration', category: 'timing', visible: false, type: 'number' },

  // Lifecycle / Pipeline
  pipeline:       { field: 'pipeline_progress', label: 'Pipeline', category: 'lifecycle', visible: true,
                    component: 'ui-lifecycle-tracker',
                    componentAttrs: { phases: 'row.pipeline_progress', layout: "'compact'" } },
  lifecycle_detail:{ field: 'managed_lifecycle', label: 'Phases', category: 'lifecycle', visible: false,
                    component: 'ui-lifecycle-tracker',
                    componentAttrs: { phases: 'row.managed_lifecycle.phases', layout: "'horizontal'" } },
  state_history:  { field: 'state_history', label: 'History', category: 'lifecycle', visible: false,
                    component: 'ui-state-history', componentAttrs: { transitions: 'row.state_history', 'resource-type': "'session'", compact: true } },

  // Observation
  observation:    { field: 'resource_observation', label: 'Resources', category: 'metrics', visible: false,
                    component: 'ui-resource-observation', componentAttrs: { observation: 'row.resource_observation', compact: true } },

  // Grading
  score:          { field: 'score_report', label: 'Score', category: 'grading', visible: false },
  grade_result:   { field: 'grade_result', label: 'Grade', category: 'grading', visible: false },

  // Revision
  state_version:  { field: 'state_version', label: 'Rev', category: 'revision', visible: false,
                    component: 'ui-revision-indicator', componentAttrs: { version: 'row.state_version', 'resource-id': 'row.id' } },

  // Actions
  actions:        { field: '_actions', label: 'Actions', category: 'actions', visible: true, sortable: false, pinned: 'right' },
};

export const SESSION_DEFAULT_COLUMNS = ['definition_name', 'owner_id', 'status', 'worker_name', 'topology', 'timeslot', 'form_qn', 'pipeline', 'actions'];
```

#### 3.3.3 Definition Column Registry

```javascript
// scripts/columns/definitionColumns.js
export const DEFINITION_COLUMNS = {
  // Identity
  name:           { field: 'name', label: 'Name', category: 'identity', visible: true, sortable: true },
  id:             { field: 'id', label: 'ID', category: 'identity', visible: false },
  form_qn:        { field: 'form_qualified_name', label: 'Form QN', category: 'identity', visible: true, sortable: true },
  version:        { field: 'version', label: 'Version', category: 'identity', visible: false },

  // Status
  status:         { field: 'status', label: 'Status', category: 'status', visible: true, sortable: true, component: 'lcm-status-badge' },
  desired_status: { field: 'desired_status', label: 'Desired', category: 'status', visible: false,
                    component: 'ui-resource-status', componentAttrs: { 'resource-type': 'definition' } },
  sync_status:    { field: 'sync_status', label: 'Sync', category: 'status', visible: true, sortable: true, component: 'lcm-status-badge' },

  // Owner
  owner_id:       { field: 'owner_id', label: 'Owner', category: 'identity', visible: false, sortable: true },

  // Content
  node_count:     { field: 'node_count', label: 'Nodes', category: 'content', visible: true, sortable: true, type: 'number' },
  link_count:     { field: 'link_count', label: 'Links', category: 'content', visible: true, sortable: true, type: 'number' },
  warm_pool_depth:{ field: 'warm_pool_depth', label: 'Warm Pool', category: 'content', visible: false, type: 'number' },
  lab_reuse:      { field: 'lab_reuse_enabled', label: 'Reuse', category: 'content', visible: false, type: 'boolean' },

  // Timeslot (Layer 2 — definitions are time-bounded)
  timeslot:       { field: 'timeslot', label: 'Timeslot', category: 'scheduling', visible: false,
                    component: 'ui-timeslot-badge' },
  timeslot_start: { field: 'timeslot.start', label: 'Starts', category: 'scheduling', visible: false, type: 'datetime' },
  timeslot_end:   { field: 'timeslot.end', label: 'Ends', category: 'scheduling', visible: false, type: 'datetime' },

  // Lifecycle
  lifecycle:      { field: 'managed_lifecycle', label: 'Lifecycle', category: 'lifecycle', visible: false,
                    component: 'ui-lifecycle-tracker', componentAttrs: { layout: 'compact' } },

  // State History
  state_history:  { field: 'state_history', label: 'History', category: 'lifecycle', visible: false,
                    component: 'ui-state-history', componentAttrs: { compact: true } },

  // Pipelines
  pipelines:      { field: 'pipelines', label: 'Pipelines', category: 'lifecycle', visible: false },

  // Content Versioning
  content_version:{ field: 'content_metadata.content_version', label: 'Content Ver', category: 'revision', visible: false },
  lab_yaml_hash:  { field: 'lab_yaml_hash', label: 'YAML Hash', category: 'revision', visible: false },

  // Timing
  created_at:     { field: 'created_at', label: 'Created', category: 'timing', visible: false, type: 'datetime' },
  updated_at:     { field: 'updated_at', label: 'Updated', category: 'timing', visible: true, sortable: true, type: 'datetime' },

  // Deprecation
  deprecated:     { field: 'is_deprecated', label: 'Deprecated', category: 'metadata', visible: false, type: 'boolean' },

  // Revision
  state_version:  { field: 'state_version', label: 'Rev', category: 'revision', visible: false,
                    component: 'ui-revision-indicator' },

  // Actions
  actions:        { field: '_actions', label: 'Actions', category: 'actions', visible: true, sortable: false, pinned: 'right' },
};

export const DEFINITION_DEFAULT_COLUMNS = ['name', 'form_qn', 'status', 'sync_status', 'node_count', 'link_count', 'updated_at', 'actions'];
```

#### 3.3.4 Lab Record Column Registry

```javascript
// scripts/columns/labRecordColumns.js
export const LAB_RECORD_COLUMNS = {
  // Identity
  title:          { field: 'title', label: 'Title', category: 'identity', visible: true, sortable: true },
  id:             { field: 'id', label: 'ID', category: 'identity', visible: false },
  cml_lab_id:     { field: 'lab_id', label: 'CML Lab ID', category: 'identity', visible: false },
  worker_id:      { field: 'worker_id', label: 'Worker', category: 'identity', visible: true, sortable: true },
  owner:          { field: 'owner_fullname', label: 'Owner', category: 'identity', visible: false, sortable: true },

  // Status
  status:         { field: 'status', label: 'Status', category: 'status', visible: true, sortable: true, component: 'lcm-status-badge' },
  pending_action: { field: 'pending_action_type', label: 'Pending', category: 'status', visible: false },
  last_error:     { field: 'last_error_message', label: 'Last Error', category: 'status', visible: false },

  // Topology
  node_count:     { field: 'node_count', label: 'Nodes', category: 'topology', visible: true, sortable: true, type: 'number' },
  link_count:     { field: 'link_count', label: 'Links', category: 'topology', visible: true, sortable: true, type: 'number' },
  source:         { field: 'source', label: 'Source', category: 'topology', visible: true, sortable: true },

  // Binding
  runtime_binding:{ field: 'runtime_binding', label: 'Binding', category: 'binding', visible: false },

  // Timing
  created_at:     { field: 'created_at', label: 'Created', category: 'timing', visible: false, type: 'datetime' },
  updated_at:     { field: 'updated_at', label: 'Updated', category: 'timing', visible: true, sortable: true, type: 'datetime' },

  // State history
  state_history:  { field: 'state_history', label: 'History', category: 'lifecycle', visible: false,
                    component: 'ui-state-history', componentAttrs: { compact: true } },

  // Revision
  state_version:  { field: 'state_version', label: 'Rev', category: 'revision', visible: false },

  // Actions
  actions:        { field: '_actions', label: 'Actions', category: 'actions', visible: true, sortable: false, pinned: 'right' },
};

export const LAB_RECORD_DEFAULT_COLUMNS = ['title', 'worker_id', 'status', 'node_count', 'link_count', 'source', 'updated_at', 'actions'];
```

---

## 4. IMPLEMENTATION PLAN

### Phase A: Core Components (lcm_ui library)

**A1.** `<ui-resource-status>` — Desired vs Current status display
**A2.** `<ui-state-history>` — State transition timeline (compact + full)
**A3.** `<ui-lifecycle-tracker>` — Phase/pipeline progress visualization
**A4.** `<ui-pipeline-log>` — Detailed pipeline execution log viewer
**A5.** `<ui-revision-indicator>` — Version badge with change detection
**A6.** `<ui-timeslot-badge>` — Rich timeslot visualization
**A7.** `<ui-resource-observation>` — Live telemetry bars
**A8.** `<ui-column-picker>` — Column visibility manager

### Phase B: DataTable Extensions (lcm_ui library)

**B1.** Extend `ColumnDefinition` type with `group`, `visible`, `pinned`, `category`, `component`, `componentAttrs`
**B2.** Add column visibility toggle to DataTable (uses `<ui-column-picker>`)
**B3.** Add component-based cell rendering (reads `component` + `componentAttrs` from column def)
**B4.** Add expandable row detail support
**B5.** Add column group headers (optional two-level headers)
**B6.** Add localStorage persistence for column visibility per table ID

### Phase C: CPA Integration (control-plane-api UI)

**C1.** Create column registries: `workerColumns.js`, `sessionColumns.js`, `definitionColumns.js`, `labRecordColumns.js`
**C2.** Refactor `WorkerList.js` to use registry + `<ui-column-picker>`
**C3.** Refactor `LabletSessionList.js` to use registry + `<ui-column-picker>`
**C4.** Refactor `LabletDefinitionList.js` to use registry + `<ui-column-picker>`
**C5.** Refactor lab records table in `WorkerDetailsModal.js` to use registry
**C6.** Add `<ui-pipeline-log>` to `SessionDetailsModal.js` (new tab alongside existing pipeline step table)
**C7.** Update `LcmStatusBadge.js` to delegate to `<ui-resource-status>` when desired_status present
**C8.** Wire SSE `pipeline_step_*` events to new `<ui-lifecycle-tracker>` and `<ui-pipeline-log>` components
**C9.** Add state history panel to all detail modals using `<ui-state-history>`

### Phase D: Testing & Polish

**D1.** Vitest unit tests for all new lcm_ui components
**D2.** Visual regression testing (screenshot comparison)
**D3.** Accessibility audit (keyboard nav, ARIA labels, screen reader)
**D4.** Performance: Virtualized rendering for large state histories (100+ transitions)
**D5.** Responsive: Column picker adapts for mobile/tablet

---

## 5. DEPENDENCY GRAPH

```
Phase A (parallel):
  A1 ui-resource-status     ← StatusBadge (existing)
  A2 ui-state-history       ← StatusBadge (existing)
  A3 ui-lifecycle-tracker   ← (new, standalone)
  A4 ui-pipeline-log        ← A3 (uses lifecycle tracker for overview)
  A5 ui-revision-indicator  ← (new, standalone)
  A6 ui-timeslot-badge      ← (new, standalone)
  A7 ui-resource-observation← (new, standalone)
  A8 ui-column-picker       ← (new, standalone)

Phase B (depends on A):
  B1 column type extensions ← (type definitions only)
  B2 column visibility      ← A8 (column picker component)
  B3 component cell render  ← B1 (type extensions)
  B4 expandable rows        ← (DataTable extension)
  B5 column groups          ← B1 (type extensions)
  B6 persistence            ← B2 (column visibility)

Phase C (depends on A + B):
  C1 column registries      ← B1 (type extensions)
  C2-C5 list refactors      ← C1 + B2 + B3
  C6 pipeline log           ← A4 (pipeline log component)
  C7 status badge upgrade   ← A1 (resource status component)
  C8 SSE wiring             ← A3 + A4 (lifecycle + pipeline components)
  C9 state history panels   ← A2 (state history component)
```

---

## 6. BACKEND PREREQUISITES

### 6.1 DTO Enrichment (if not already present)

Verify these fields are populated in DTOs returned by REST and SSE snapshot events:

| Resource | Field | Source | Status |
|----------|-------|--------|--------|
| Worker | `desired_status` | `CMLWorkerState.desired_status` | ✅ In WorkerDetailDto |
| Worker | `state_history` | `CMLWorkerState.state_history` | ⚠️ Check if included in list DTO |
| Worker | `state_version` | `CMLWorkerState.state_version` | ⚠️ Check if included |
| Session | `desired_status` | `LabletSessionState.desired_status` | ✅ In LabletSessionDetailDto |
| Session | `state_history` | `LabletSessionState.state_history` | ✅ In detail DTO |
| Session | `managed_lifecycle` | `LabletSessionState.managed_lifecycle` | ⚠️ Check if serialized to DTO |
| Session | `resource_observation` | `LabletSessionState.resource_observation` | ✅ In detail DTO |
| Session | `state_version` | `LabletSessionState.state_version` | ⚠️ Check if included |
| LabRecord | `state_history` | `LabRecordState.state_history` (ResourceState, Batch G) | ✅ Verify in list DTO |
| Definition | `desired_status` | `LabletDefinitionState.desired_status` (after Batch I) | ❌ Needs Batch I migration |
| Definition | `state_history` | `LabletDefinitionState.state_history` (after Batch I) | ❌ Needs Batch I migration |
| Definition | `timeslot` | `LabletDefinitionState.timeslot` (after Batch I) | ❌ Needs Batch I migration |
| Definition | `managed_lifecycle` | `LabletDefinitionState.managed_lifecycle` (after Batch I) | ❌ Needs Batch I migration |
| Definition | `owner_id` | `LabletDefinitionState.owner_id` (after Batch I) | ❌ Needs Batch I migration |
| Definition | `state_version` | `LabletDefinitionState.state_version` | ⚠️ Check if included |

### 6.2 New REST Endpoints (if needed)

```
GET /api/sessions/{id}/state-history     → list[StateTransitionDto]
GET /api/sessions/{id}/pipeline-log      → ManagedLifecycle with step details
GET /api/workers/{id}/state-history      → list[StateTransitionDto]
```

_These may not be needed if snapshot DTOs already include full state_history._

---

## 7. DESIGN TOKENS / VISUAL LANGUAGE

### Status Colors (extend existing StatusBadge mapping)

```javascript
const RECONCILIATION_COLORS = {
  reconciling: { bg: 'bg-warning-subtle', text: 'text-warning', icon: 'bi-arrow-repeat spin' },
  converged:   { bg: 'bg-success-subtle', text: 'text-success', icon: 'bi-check-circle' },
  diverged:    { bg: 'bg-danger-subtle', text: 'text-danger', icon: 'bi-exclamation-triangle' },
};

const LIFECYCLE_PHASE_COLORS = {
  pending:   { icon: '○', color: 'text-muted' },
  running:   { icon: '◐', color: 'text-primary', animation: 'pulse' },
  completed: { icon: '●', color: 'text-success' },
  failed:    { icon: '●', color: 'text-danger' },
  skipped:   { icon: '◌', color: 'text-muted' },
};

const TIMESLOT_PHASE_COLORS = {
  before:      { badge: 'outline-secondary', icon: 'bi-clock' },
  approaching: { badge: 'warning', icon: 'bi-clock-history' },
  active:      { badge: 'success', icon: 'bi-play-circle' },
  teardown:    { badge: 'info', icon: 'bi-hourglass-split' },
  expired:     { badge: 'outline-danger', icon: 'bi-clock-fill' },
};
```

---

## 8. FILES TO CREATE / MODIFY

### New Files (lcm_ui)

```
src/core/lcm_ui/src/components/
  ├── ResourceStatus.ts        ← A1
  ├── StateHistory.ts          ← A2
  ├── LifecycleTracker.ts      ← A3
  ├── PipelineLog.ts           ← A4
  ├── RevisionIndicator.ts     ← A5
  ├── TimeslotBadge.ts         ← A6
  ├── ResourceObservation.ts   ← A7
  └── ColumnPicker.ts          ← A8

src/core/lcm_ui/src/types/
  └── columns.d.ts             ← B1 (extended ColumnDefinition)
```

### Modified Files (lcm_ui)

```
src/core/lcm_ui/src/components/DataTable.ts    ← B2, B3, B4, B5, B6
src/core/lcm_ui/src/index.ts                   ← Export new components
```

### New Files (CPA UI)

```
src/control-plane-api/ui/src/scripts/columns/
  ├── workerColumns.js         ← C1
  ├── sessionColumns.js        ← C1
  ├── definitionColumns.js     ← C1
  └── labRecordColumns.js      ← C1
```

### Modified Files (CPA UI)

```
scripts/components/WorkerList.js           ← C2
scripts/components/LabletSessionList.js    ← C3
scripts/components/LabletDefinitionList.js ← C4
scripts/components/SessionDetailsModal.js  ← C6, C9
scripts/components/WorkerDetailsModal.js   ← C5, C9
scripts/core/StatusBadge.js                ← C7
scripts/sse/sse-adapter.js                 ← C8
```

### New Tests (lcm_ui)

```
src/core/lcm_ui/tests/
  ├── ResourceStatus.test.ts
  ├── StateHistory.test.ts
  ├── LifecycleTracker.test.ts
  ├── PipelineLog.test.ts
  ├── RevisionIndicator.test.ts
  ├── TimeslotBadge.test.ts
  ├── ResourceObservation.test.ts
  ├── ColumnPicker.test.ts
  └── DataTable.extended.test.ts
```

---

## 9. CONSTRAINTS & GUIDELINES

1. **No framework migration** — Vanilla JS + Web Components. No React/Vue/Angular.
2. **Bootstrap 5 only** — All styling via Bootstrap utility classes. No custom CSS frameworks.
3. **Backward compatible** — Existing `<ui-data-table>` API must not break. New features are opt-in.
4. **Progressive enhancement** — Components work with partial data (e.g., no desired_status → falls back to simple badge).
5. **SSE-first** — All real-time updates flow through existing SSE → EventBus → Store pipeline. No additional WebSocket connections.
6. **Accessibility** — All new components must have ARIA labels, keyboard navigation, and color-blind-safe indicators (icons + color, never color alone).
7. **Performance** — State histories with 100+ entries must use virtual scrolling or pagination. Pipeline logs must not DOM-thrash on rapid SSE updates (batch DOM writes).
8. **Testing** — Every new component needs Vitest tests. Use JSDOM for DOM testing.
9. **Build** — New components must export from `lcm_ui` index and be consumable by CPA's Parcel build.
10. **No inline imports** — All imports at module top level (per project convention).
