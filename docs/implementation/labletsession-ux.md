# LabletSession UX Overhaul — Implementation Plan

**Status**: 🔄 In Progress (Phase 2 Complete)
**Created**: 2026-02-28
**Author**: AI Architect (lcm-senior-architect)
**Depends On**: ADR-030 (Resource Observation), AD-P7-06 (Session Transitions), ADR-029 (Cross-Ref Links), ADR-021 (Child Entities), ADR-025 (Content Sync)
**Scope**: Backend query enrichment + Frontend datatable & detail modal overhaul for `LabletSession`

---

## Executive Summary

The `LabletSession` is the **central aggregate** of the Lablet Cloud Manager — it orchestrates the full lifecycle from reservation through execution, grading, and archival. Currently, the UI under-represents the richness of the domain:

- **Datatable** shows 8 columns with minimal data (no topology, no form name, no pipeline status, no cross-ref links)
- **Detail modal** is a flat `<dl>` with 8 fields, no tabs, no child entity data, no cross-references
- **Sub-entity endpoints are unwired** — `GetUserSessionQuery`, `GetGradingSessionQuery`, `GetScoreReportQuery` handlers exist but have no BFF routes
- **No enrichment** — neither list nor detail queries join with Definition, Worker, or LabRecord data
- **No relative timestamps** — datatable shows raw datetimes; `formatRelativeTime()` and `formatDateTimeWithTooltip()` utilities exist but aren't used

This plan restructures the LabletSession UI into a **rich, tabbed, cross-referenced experience** worthy of the central entity, across 8 incremental phases.

---

## Implementation Progress

| Phase | Scope | Status | Effort | Backend | Frontend |
|-------|-------|--------|--------|---------|----------|
| **Phase 1** | Backend: Enrich DTOs & wire sub-entity endpoints | ✅ Complete | Medium | ✅ | — |
| **Phase 2** | Datatable: Unified columns, dot-indicators, relative time, cross-refs | ✅ Complete | Medium | — | ✅ |
| **Phase 3** | Detail modal: Convert to tabbed `SessionDetailsModal` custom element | ✅ Complete | Large | — | ✅ |
| **Phase 4** | Overview tab: Identity, lifecycle, timeslot, resources, definition cross-ref | ✅ Complete | Medium | — | ✅ |
| **Phase 5** | Pipeline tab: Upstream, Object Storage, POD, UserSession, Grading dot-indicators | 📋 Planned | Medium | — | ✅ |
| **Phase 6** | Reports tab: Instantiation, evidence, score reports with section breakdown | 📋 Planned | Medium | — | ✅ |
| **Phase 7** | Resources tab: Observed vs Required vs Available visualization | 📋 Planned | Medium | ✅ | ✅ |
| **Phase 8** | Cross-ref links on all related modals (Worker, LabRecord, Definition) | 📋 Planned | Small | — | ✅ |

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Phase 1: Backend Enrichment & Sub-Entity Endpoints](#2-phase-1-backend-enrichment--sub-entity-endpoints)
3. [Phase 2: Datatable Column Overhaul](#3-phase-2-datatable-column-overhaul)
4. [Phase 3: Tabbed SessionDetailsModal](#4-phase-3-tabbed-sessiondetailsmodal)
5. [Phase 4: Overview Tab](#5-phase-4-overview-tab)
6. [Phase 5: Pipeline Tab](#6-phase-5-pipeline-tab)
7. [Phase 6: Reports Tab](#7-phase-6-reports-tab)
8. [Phase 7: Resources Tab](#8-phase-7-resources-tab)
9. [Phase 8: Cross-Ref Links on Related Modals](#9-phase-8-cross-ref-links-on-related-modals)
10. [File Index](#10-file-index)
11. [Test Approach](#11-test-approach)

---

## 1. Architecture Overview

### 1.1 Current State

```
┌─────────────────────────────────────────────────────────────────────┐
│  SessionsPage.js                                                     │
│  ├─ _configureLabletSessionsTable() → 8 columns, minimal data       │
│  ├─ _showSessionDetailModal()       → flat <dl> in #labletSession…  │
│  │   └─ _renderObservationSummary() → 4 resource tiles              │
│  └─ API: labletSessionsApi.getLabletSession(id)                      │
│       └─ Returns: LabletSessionDto (no enrichment)                   │
│           ├─ definition_id, definition_name (pinned)                 │
│           ├─ worker_id (FK only, no worker_name)                     │
│           ├─ lab_record_id (FK only)                                 │
│           ├─ user_session_id (FK only)                               │
│           ├─ grading_session_id (FK only)                            │
│           └─ score_report_id (FK only)                               │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 Target State

```
┌─────────────────────────────────────────────────────────────────────┐
│  SessionsPage.js                                                     │
│  ├─ _configureLabletSessionsTable()                                  │
│  │   ├─ Definition (name + form_qualified_name badge)                │
│  │   ├─ Candidate (owner_id)                                         │
│  │   ├─ Status (lcm-status-badge)                                    │
│  │   ├─ Worker (clickable cross-ref → WorkerDetailsModal)            │
│  │   ├─ Topology (nodes/links notation)                              │
│  │   ├─ Timeslot (unified: relative time + conditional format)       │
│  │   ├─ Form (form_qualified_name)                                   │
│  │   ├─ Pipeline (dot-indicators: Upstream, Storage, POD, LDS, …)   │
│  │   └─ Actions (observe / sync / terminate)                         │
│  │                                                                   │
│  └─ SessionDetailsModal (custom element, tabbed)                     │
│      ├─ Overview tab     │ Identity, lifecycle timeline, timeslot,   │
│      │                   │ definition cross-ref, worker cross-ref    │
│      ├─ Pipeline tab     │ Upstream Source, Object Storage,          │
│      │                   │ POD LabRecord, UserSession, Grading       │
│      ├─ Reports tab      │ InstantiationReport, EvidenceReport,      │
│      │                   │ ScoreReport with section breakdown        │
│      └─ Resources tab    │ Observed vs Required vs Available bars    │
│                                                                      │
│  Backend enrichment:                                                 │
│  ├─ EnrichedLabletSessionDto (joins definition + worker fields)      │
│  ├─ BFF routes: /lablet-sessions/{id}/user-session                   │
│  ├─ BFF routes: /lablet-sessions/{id}/grading-session                │
│  ├─ BFF routes: /lablet-sessions/{id}/score-report                   │
│  └─ Enriched list DTO: +form_qualified_name, +node_count,           │
│     +worker_name, +upstream_sync_status                              │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.3 Design Principles

| Principle | Application |
|-----------|-------------|
| **Progressive disclosure** | Datatable shows dot-indicators; details in tooltips and modal tabs |
| **Cross-referencing** | Every FK rendered as clickable link opening the related modal |
| **Relative time** | Use existing `formatRelativeTime()` + `formatDateTimeWithTooltip()` everywhere |
| **Conditional formatting** | Timeslots: green (future/active), amber (about to end), muted (past) |
| **Consistency** | Follow WorkerDetailsModal tab pattern (5-tab, EventBus, BaseComponent) |
| **Lazy loading** | Modal tabs fetch data on activation, cache until invalidated by SSE |
| **No backend duplication** | Reuse existing query handlers; enrich with cross-aggregate lookups in handlers |

### 1.4 Entity Relationship (for reference)

```
LabletDefinition (template, immutable per version)
  ├── form_qualified_name          ← surfaced in datatable "Form" column
  ├── resource_requirements        ← surfaced in Resources tab (required)
  ├── node_count                   ← surfaced in datatable "Topology" column
  ├── port_template                ← surfaced in Resources tab
  ├── upstream_sync_status         ← surfaced in Pipeline dot-indicators
  └── defines → LabletSession(s) via definition_id FK

LabletSession (aggregate root, 11-state lifecycle)
  ├── worker_id FK → CMLWorker     ← clickable cross-ref
  │     ├── name, aws_region       ← shown in datatable + modal
  │     ├── declared_capacity      ← surfaced in Resources tab (available)
  │     └── allocated_capacity     ← surfaced in Resources tab (used)
  ├── lab_record_id FK → LabRecord ← clickable cross-ref
  │     ├── node_count, link_count ← surfaced in datatable "Topology"
  │     ├── status                 ← surfaced in Pipeline POD indicator
  │     └── run_history_v2         ← surfaced in Overview tab
  ├── user_session_id FK → UserSession (child entity)
  │     ├── lds_session_id         ← clickable LDS cross-ref
  │     ├── login_url              ← clickable launch link
  │     ├── devices                ← surfaced in Pipeline tab detail
  │     └── status                 ← surfaced in Pipeline LDS indicator
  ├── grading_session_id FK → GradingSession (child entity)
  │     ├── status                 ← surfaced in Pipeline Grading indicator
  │     └── devices                ← surfaced in Pipeline tab detail
  ├── score_report_id FK → ScoreReport (child entity)
  │     ├── score, max_score, passed  ← surfaced in Reports tab
  │     └── sections[]             ← breakdown table in Reports tab
  ├── observed_resources           ← surfaced in Resources tab (observed)
  └── state_history[]              ← timeline in Overview tab
```

---

## 2. Phase 1: Backend Enrichment & Sub-Entity Endpoints

> **Goal**: Enrich the list and detail DTOs with cross-aggregate data, and wire the existing sub-entity query handlers to BFF routes.

### 2.1 Enrich `ListLabletSessionsQuery` Handler

**File**: `application/queries/lablet_session/list_lablet_sessions_query.py`

**Current**: Straight `entity → DTO` mapping with zero lookups.

**Changes**:

1. Inject `LabletDefinitionRepository` and `CMLWorkerRepository` into the handler
2. Batch-fetch referenced definitions and workers (avoid N+1)
3. Add enrichment fields to `ListLabletSessionDto`

**New fields on `ListLabletSessionDto`** (in `application/dtos/lablet_session_dto.py`):

| Field | Type | Source |
|-------|------|--------|
| `form_qualified_name` | `str \| None` | `LabletDefinitionState.form_qualified_name` via `definition_id` FK lookup |
| `node_count` | `int \| None` | `LabletDefinitionState.node_count` via `definition_id` FK lookup |
| `worker_name` | `str \| None` | `CMLWorkerState.name` via `worker_id` FK lookup |
| `upstream_sync_status` | `dict \| None` | `LabletDefinitionState.upstream_sync_status` (per-service sync dict) |
| `lab_record_id` | `str \| None` | Already on session state but not on list DTO — add it |
| `user_session_id` | `str \| None` | Already on session state but not on list DTO — add it |
| `grade_result` | `str \| None` | Already on session state but not on list DTO — add it |

**Enrichment strategy** (batch, not N+1):

```python
# Collect unique FK IDs from the page of results
definition_ids = {s.state.definition_id for s in sessions if s.state.definition_id}
worker_ids = {s.state.worker_id for s in sessions if s.state.worker_id}

# Batch-fetch aggregates (repository method: get_by_ids_async or iterate)
definitions_map = {}
for def_id in definition_ids:
    defn = await self._definition_repo.get_by_id_async(def_id, cancellation_token)
    if defn:
        definitions_map[def_id] = defn.state

workers_map = {}
for wid in worker_ids:
    worker = await self._worker_repo.get_by_id_async(wid, cancellation_token)
    if worker:
        workers_map[wid] = worker.state

# Enrich each DTO
for dto, session in zip(dtos, sessions):
    defn = definitions_map.get(session.state.definition_id)
    worker = workers_map.get(session.state.worker_id)
    dto.form_qualified_name = defn.form_qualified_name if defn else None
    dto.node_count = defn.node_count if defn else None
    dto.worker_name = worker.name if worker else None
    dto.upstream_sync_status = defn.upstream_sync_status if defn else None
```

> **Performance note**: Definitions and workers are typically few in number (tens, not thousands). The batch-fetch is acceptable. For future optimization, consider adding a `get_by_ids_async(ids)` bulk method to repositories.

### 2.2 Enrich `GetLabletSessionQuery` Handler

**File**: `application/queries/lablet_session/get_lablet_session_query.py`

**Current**: Straight `entity → DTO` mapping.

**Changes**: Add cross-aggregate enrichment fields to `LabletSessionDto`:

| Field | Type | Source |
|-------|------|--------|
| `form_qualified_name` | `str \| None` | `LabletDefinitionState.form_qualified_name` |
| `node_count` | `int \| None` | `LabletDefinitionState.node_count` |
| `worker_name` | `str \| None` | `CMLWorkerState.name` |
| `worker_region` | `str \| None` | `CMLWorkerState.aws_region` |
| `resource_requirements` | `dict \| None` | `LabletDefinitionState.resource_requirements` serialized |
| `port_template` | `dict \| None` | `LabletDefinitionState.port_template` serialized |
| `upstream_sync_status` | `dict \| None` | `LabletDefinitionState.upstream_sync_status` |
| `upstream_version` | `str \| None` | `LabletDefinitionState.upstream_version` |
| `content_package_hash` | `str \| None` | `LabletDefinitionState.content_package_hash` |
| `lab_record_status` | `str \| None` | `LabRecordState.status` |
| `lab_record_node_count` | `int \| None` | `LabRecordState.node_count` |
| `lab_record_link_count` | `int \| None` | `LabRecordState.link_count` |
| `observed_resources` | `dict \| None` | Already on session state — ensure it's mapped to DTO |
| `observed_ports` | `dict \| None` | Already on session state — ensure it's mapped to DTO |
| `observation_count` | `int` | Already on session state — ensure it's mapped to DTO |
| `observed_at` | `str \| None` | Already on session state — ensure it's mapped to DTO |
| `port_drift_detected` | `bool` | Already on session state — ensure it's mapped to DTO |

### 2.3 Wire Sub-Entity BFF Routes

**File**: `api/controllers/lablet_sessions_controller.py`

Add 3 new endpoints (query handlers already exist and are registered):

```python
@get("/{session_id}/user-session")
async def get_user_session(self, session_id: str) -> JSONResponse:
    """Get the UserSession child entity for this lablet session."""
    result = await self.mediator.execute_async(
        GetUserSessionQuery(lablet_session_id=session_id)
    )
    return self.process(result)

@get("/{session_id}/grading-session")
async def get_grading_session(self, session_id: str) -> JSONResponse:
    """Get the GradingSession child entity for this lablet session."""
    result = await self.mediator.execute_async(
        GetGradingSessionQuery(lablet_session_id=session_id)
    )
    return self.process(result)

@get("/{session_id}/score-report")
async def get_score_report(self, session_id: str) -> JSONResponse:
    """Get the ScoreReport for this lablet session."""
    result = await self.mediator.execute_async(
        GetScoreReportQuery(lablet_session_id=session_id)
    )
    return self.process(result)
```

### 2.4 Add Frontend API Functions

**File**: `ui/src/scripts/api/lablet-sessions.js`

```javascript
/** Get the UserSession child entity for a lablet session */
export async function getUserSession(sessionId) {
    return apiClient.get(`/api/lablet-sessions/${sessionId}/user-session`);
}

/** Get the GradingSession child entity for a lablet session */
export async function getGradingSession(sessionId) {
    return apiClient.get(`/api/lablet-sessions/${sessionId}/grading-session`);
}

/** Get the ScoreReport for a lablet session */
export async function getScoreReport(sessionId) {
    return apiClient.get(`/api/lablet-sessions/${sessionId}/score-report`);
}
```

### 2.5 Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| 1 | List endpoint returns `form_qualified_name` per session | `GET /api/lablet-sessions/` → check payload |
| 2 | List endpoint returns `worker_name` per session | Same — verify worker name appears |
| 3 | List endpoint returns `node_count` per session | Same — verify node count |
| 4 | List endpoint returns `upstream_sync_status` per session | Same — verify sync dict |
| 5 | Detail endpoint returns all enrichment fields | `GET /api/lablet-sessions/{id}` → check new fields |
| 6 | `/lablet-sessions/{id}/user-session` returns UserSession data | `GET` → status 200 with devices, login_url, status |
| 7 | `/lablet-sessions/{id}/grading-session` returns GradingSession data | `GET` → status 200 |
| 8 | `/lablet-sessions/{id}/score-report` returns ScoreReport with sections | `GET` → status 200 with sections[] |
| 9 | Session without child entity returns 404 for sub-entity routes | `GET` → status 404 |
| 10 | Batch enrichment does not cause N+1 | Verify definition/worker lookups are batched |

---

## 3. Phase 2: Datatable Column Overhaul

> **Goal**: Replace the current 8-column layout with a denser, richer 9-column layout featuring unified topology, relative timeslots, dot-indicators, cross-ref links, and a form column.

### 3.1 Target Column Layout

| # | Field | Label | Width | Render |
|---|-------|-------|-------|--------|
| 1 | `definition_name` | Definition | 200px | Clickable name → `_showSessionDetailModal()`, `form_qualified_name` as small muted text below |
| 2 | `owner_id` | Candidate | 130px | Person icon + escaped text (unchanged) |
| 3 | `status` | Status | 100px | `<lcm-status-badge>` (unchanged) |
| 4 | `worker_name` | Worker | 120px | **Clickable cross-ref** → opens `WorkerDetailsModal` via EventBus; shows truncated ID if no name |
| 5 | `node_count` | Topology | 80px | `{nodes}N / {links}L` notation (e.g., "8N / 12L"); links from lab_record when available, definition node_count otherwise |
| 6 | `timeslot_start` | Timeslot | 150px | **Unified column**: relative time + conditional color; Bootstrap tooltip shows full timestamps; shows duration |
| 7 | `form_qualified_name` | Form | 160px | Truncated FQN with tooltip showing full name |
| 8 | (computed) | Pipeline | 120px | **Dot-indicators**: 5 small color-coded dots for Upstream, Storage, POD, LDS, Score |
| 9 | `actions` | Actions | 100px | Observe / Sync / Terminate (unchanged) |

**Removed columns**: `timeslot_end` (merged into Timeslot), `updated_at` (moved to tooltip)

### 3.2 Unified Timeslot Column

```javascript
{
    field: 'timeslot_start',
    label: 'Timeslot',
    sortable: true,
    render: (value, row) => {
        const start = value ? new Date(value) : null;
        const end = row.timeslot_end ? new Date(row.timeslot_end) : null;
        const now = new Date();

        if (!start) return '<span class="text-muted">—</span>';

        // Determine temporal context
        let colorClass = 'text-muted';       // past
        let icon = 'bi-clock-history';
        if (end && end > now && start <= now) {
            colorClass = 'text-success';     // current/active
            icon = 'bi-clock-fill';
        } else if (start > now) {
            colorClass = 'text-primary';     // future
            icon = 'bi-clock';
        } else if (end && end < now) {
            // Check if ended less than 30 min ago
            const minutesSinceEnd = (now - end) / 60000;
            if (minutesSinceEnd < 30) {
                colorClass = 'text-warning'; // recently ended
                icon = 'bi-clock-history';
            }
        }

        const relativeTime = formatRelativeTime(value);
        const duration = start && end ? formatDuration(end - start) : '';
        const fullStart = formatDateTime(value);
        const fullEnd = row.timeslot_end ? formatDateTime(row.timeslot_end) : '—';

        return `
            <span class="${colorClass}"
                  data-bs-toggle="tooltip" data-bs-placement="top"
                  data-bs-html="true"
                  title="${fullStart} → ${fullEnd}<br>Duration: ${duration}">
                <i class="bi ${icon} me-1" style="font-size: 0.75em;"></i>
                <span class="small">${relativeTime}</span>
                ${duration ? `<span class="text-muted small ms-1">(${duration})</span>` : ''}
            </span>
        `;
    },
},
```

### 3.3 Clickable Worker Cross-Ref

```javascript
{
    field: 'worker_name',
    label: 'Worker',
    sortable: true,
    render: (value, row) => {
        if (!row.worker_id) return '<span class="text-muted">—</span>';
        const displayName = value || row.worker_id.substring(0, 8) + '…';
        return `
            <a href="#" class="text-decoration-none open-worker-link"
               data-worker-id="${row.worker_id}"
               title="Open Worker ${row.worker_id}">
                <i class="bi bi-hdd-rack me-1" style="font-size: 0.75em;"></i>
                <code class="small">${this._escapeHtml(displayName)}</code>
                <i class="bi bi-box-arrow-up-right" style="font-size: 0.6em;"></i>
            </a>
        `;
    },
},
```

**Click handler** (in `_setupEventListeners()`):

```javascript
// Worker cross-ref clicks (delegation on table container)
this.addEventListener('click', e => {
    const workerLink = e.target.closest('.open-worker-link');
    if (workerLink) {
        e.preventDefault();
        const workerId = workerLink.dataset.workerId;
        const worker = getWorker(workerId);
        const region = worker?.aws_region || '';
        eventBus.emit('UI_OPEN_WORKER_DETAILS', { workerId, region });
    }
});
```

### 3.4 Topology Column

```javascript
{
    field: 'node_count',
    label: 'Topology',
    sortable: true,
    render: (value, row) => {
        const nodes = value ?? '—';
        // link_count only available when enriched from lab_record
        const links = row.link_count ?? '?';
        if (nodes === '—') return '<span class="text-muted">—</span>';
        return `
            <span title="Nodes / Links" class="small">
                <i class="bi bi-diagram-3 me-1 text-muted" style="font-size: 0.75em;"></i>
                <strong>${nodes}</strong>N / <strong>${links}</strong>L
            </span>
        `;
    },
},
```

### 3.5 Form Column

```javascript
{
    field: 'form_qualified_name',
    label: 'Form',
    sortable: true,
    render: (value) => {
        if (!value) return '<span class="text-muted">—</span>';
        // Truncate to last 2 segments for brevity
        const parts = value.split(' ');
        const short = parts.length > 3
            ? '…' + parts.slice(-3).join(' ')
            : value;
        return `
            <span class="small text-truncate d-inline-block" style="max-width: 150px;"
                  data-bs-toggle="tooltip" data-bs-placement="top"
                  title="${this._escapeHtml(value)}">
                ${this._escapeHtml(short)}
            </span>
        `;
    },
},
```

### 3.6 Pipeline Dot-Indicators Column

Each dot is a small `<span>` with a `border-radius: 50%` circle, color-coded by status, with a Bootstrap tooltip showing details.

**Dot statuses and colors**:

| Dot | Source | Green (✓) | Amber (⚠) | Red (✗) | Gray (○) |
|-----|--------|-----------|-----------|---------|----------|
| **Upstream** | `upstream_sync_status.mosaic_source` | `synced` | `sync_requested` | `error` | `null`/unknown |
| **Storage** | `upstream_sync_status.object_storage` | `synced` | `sync_requested` | `error` | `null`/unknown |
| **POD** | `lab_record_id` + status context | Has lab_record + running | Has lab_record + starting | error | No lab_record |
| **LDS** | `user_session_id` presence + status context | Has user_session + active | provisioning | faulted/expired | No user_session |
| **Score** | `grade_result` | `"pass"` | (n/a) | `"fail"` | `null` (not graded) |

```javascript
{
    field: 'pipeline',
    label: 'Pipeline',
    render: (_, row) => {
        const dots = [];

        // Helper
        const dot = (label, status, detail) => {
            const colors = {
                green: '#28a745', amber: '#ffc107', red: '#dc3545', gray: '#adb5bd'
            };
            const color = colors[status] || colors.gray;
            return `<span class="d-inline-block rounded-circle me-1"
                          style="width: 10px; height: 10px; background: ${color};"
                          data-bs-toggle="tooltip" data-bs-placement="top"
                          data-bs-html="true"
                          title="<strong>${label}</strong><br>${detail}">
                    </span>`;
        };

        // 1. Upstream Source
        const uSync = row.upstream_sync_status?.mosaic_source;
        const uStatus = uSync?.status === 'synced' ? 'green'
            : uSync?.status === 'error' ? 'red'
            : uSync?.status ? 'amber' : 'gray';
        const uVersion = uSync?.version ? `v${uSync.version}` : '—';
        dots.push(dot('Upstream', uStatus, `${uSync?.status || 'unknown'} • ${uVersion}`));

        // 2. Object Storage
        const oSync = row.upstream_sync_status?.object_storage;
        const oStatus = oSync?.status === 'synced' ? 'green'
            : oSync?.status === 'error' ? 'red'
            : oSync?.status ? 'amber' : 'gray';
        dots.push(dot('Storage', oStatus, `${oSync?.status || 'unknown'}`));

        // 3. POD (LabRecord)
        const podStatus = row.lab_record_id ? 'green' : 'gray';
        const podDetail = row.lab_record_id
            ? `${row.lab_record_id.substring(0, 8)}…`
            : 'No lab record';
        dots.push(dot('POD', podStatus, podDetail));

        // 4. LDS (UserSession)
        const ldsStatus = row.user_session_id ? 'green' : 'gray';
        const ldsDetail = row.user_session_id
            ? `${row.user_session_id.substring(0, 8)}…`
            : 'No user session';
        dots.push(dot('LDS', ldsStatus, ldsDetail));

        // 5. Score
        const scoreStatus = row.grade_result === 'pass' ? 'green'
            : row.grade_result === 'fail' ? 'red' : 'gray';
        const scoreDetail = row.grade_result || 'Not graded';
        dots.push(dot('Score', scoreStatus, scoreDetail));

        return `<span class="d-inline-flex align-items-center">${dots.join('')}</span>`;
    },
},
```

### 3.7 Definition Column Enhancement

Enhance the existing definition column to show `form_qualified_name` as a secondary line:

```javascript
{
    field: 'definition_name',
    label: 'Definition',
    sortable: true,
    render: (value, row) => {
        const fqn = row.form_qualified_name;
        const fqnHtml = fqn
            ? `<div class="small text-muted text-truncate" style="max-width: 180px;"
                    data-bs-toggle="tooltip" title="${this._escapeHtml(fqn)}">
                   ${this._escapeHtml(fqn)}
               </div>`
            : '';
        return `<span class="d-flex flex-column">
            <span class="d-flex align-items-center gap-1">
                <i class="bi bi-easel text-muted"></i>
                <strong class="session-title-link" role="button" data-session-id="${row.id}">
                    ${this._escapeHtml(value || row.definition_id || 'Unknown')}
                </strong>
            </span>
            ${fqnHtml}
        </span>`;
    },
},
```

### 3.8 Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| 1 | Topology column shows "8N / 12L" notation | Session with 8 nodes → column shows `8N / ?L` |
| 2 | Timeslot column shows relative time with color coding | Future session → blue; active → green; past → muted |
| 3 | Timeslot tooltip shows full timestamps and duration | Hover → "Feb 28, 2026 04:25 PM → 06:25 PM (2h)" |
| 4 | Worker column is clickable and opens WorkerDetailsModal | Click worker → modal opens for that worker |
| 5 | Form column shows truncated FQN with tooltip | Long FQN → truncated with full name on hover |
| 6 | Pipeline dots show correct colors for each service | Synced definition → green upstream + storage dots |
| 7 | Pipeline dot tooltips show service details | Hover upstream dot → "synced • v1.2" |
| 8 | Definition column shows FQN as secondary text | Definition with FQN → small muted text below name |
| 9 | `timeslot_end` and `updated_at` columns are removed | Only 9 columns visible |

---

## 4. Phase 3: Tabbed SessionDetailsModal

> **Goal**: Replace the inline `_showSessionDetailModal()` method (flat `<dl>` inside `#labletSessionDetailsModal` Jinja shell) with a proper `SessionDetailsModal` custom element following the `WorkerDetailsModal` pattern.

### 4.1 New File: `SessionDetailsModal.js`

**Path**: `ui/src/scripts/components/modals/SessionDetailsModal.js`

**Architecture** (following WorkerDetailsModal pattern):

```javascript
import BaseComponent from '@bvandewe/lcm-ui/BaseComponent';
import { EventTypes } from '../../app/eventBus.js';

const EVENT_OPEN = 'UI_OPEN_SESSION_DETAILS';

export default class SessionDetailsModal extends BaseComponent {
    constructor() {
        super();
        this._session = null;
        this._activeTab = 'overview';
        this._tabCache = {};   // { overview: html, pipeline: null, reports: null, resources: null }
    }

    connectedCallback() {
        this.innerHTML = this._renderShell();
        this._modal = new bootstrap.Modal(this.querySelector('.modal'));

        // Open via EventBus (consistent with WorkerDetailsModal)
        this.subscribe(EVENT_OPEN, ({ sessionId }) => this.open(sessionId));

        // SSE reactive updates
        this.subscribe(EventTypes.LABLET_SESSION_UPDATED, ({ id }) => {
            if (id === this._session?.id) this._invalidateAndRefresh();
        });
        this.subscribe(EventTypes.LABLET_SESSION_STATUS_CHANGED, ({ id }) => {
            if (id === this._session?.id) this._invalidateAndRefresh();
        });
    }

    async open(sessionId) {
        this._session = await labletSessionsApi.getLabletSession(sessionId);
        this._tabCache = {};
        this._activeTab = 'overview';
        this._renderContent();
        this._modal.show();
    }

    _renderShell() {
        return `
            <div class="modal fade" tabindex="-1" aria-hidden="true">
                <div class="modal-dialog modal-xl modal-dialog-scrollable">
                    <div class="modal-content">
                        <div class="modal-header">
                            <div>
                                <h5 class="modal-title mb-0">
                                    <i class="bi bi-easel me-2"></i>
                                    <span class="session-modal-title">Session Details</span>
                                </h5>
                                <small class="text-muted session-modal-subtitle"></small>
                            </div>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body p-0">
                            <!-- Tab nav + panels rendered dynamically -->
                            <div class="session-modal-content"></div>
                        </div>
                        <div class="modal-footer session-modal-footer"></div>
                    </div>
                </div>
            </div>
        `;
    }

    // _renderContent(), _switchTab(), _renderOverviewTab(), etc.
    // See Phase 4–7 for per-tab implementations
}

customElements.define('session-details-modal', SessionDetailsModal);
```

### 4.2 Tab Configuration

| Tab ID | Label | Icon | Lazy Load? | Data Source |
|--------|-------|------|------------|------------|
| `overview` | Overview | `bi-info-circle` | No (loaded on open) | `LabletSessionDto` (enriched) |
| `pipeline` | Pipeline | `bi-arrow-repeat` | Yes | `LabletSessionDto` + definition sync status |
| `reports` | Reports | `bi-clipboard-data` | Yes | `getUserSession()`, `getGradingSession()`, `getScoreReport()` |
| `resources` | Resources | `bi-bar-chart-line` | Yes | `LabletSessionDto` (observed) + definition (required) |

### 4.3 Mount in SessionsPage

**File**: `SessionsPage.js`

1. Import `SessionDetailsModal`:

   ```javascript
   import '../modals/SessionDetailsModal.js';
   ```

2. In `render()`, add the custom element after the tab content:

   ```html
   <session-details-modal></session-details-modal>
   ```

3. Replace `_showSessionDetailModal(sessionId)` body with EventBus emit:

   ```javascript
   _showSessionDetailModal(sessionId) {
       eventBus.emit('UI_OPEN_SESSION_DETAILS', { sessionId });
   }
   ```

### 4.4 Remove Jinja Modal Shell

The `#labletSessionDetailsModal` in `lablet_instances.jinja` becomes dead code — keep it temporarily with a `<!-- DEPRECATED: Use <session-details-modal> -->` comment, then remove after verification.

### 4.5 Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| 1 | Clicking a session row opens the new `SessionDetailsModal` | Click row → modal-xl with tabs |
| 2 | Modal header shows definition name + session ID | Open session → header matches |
| 3 | Four tabs visible: Overview, Pipeline, Reports, Resources | Count tabs = 4 |
| 4 | Tab switching works and preserves state | Click Pipeline → back to Overview → content intact |
| 5 | SSE events refresh the active tab | Trigger session update → modal refreshes |
| 6 | Old Jinja modal shell is unused | Verify `#labletSessionDetailsModal` not referenced |

---

## 5. Phase 4: Overview Tab

> **Goal**: Rich overview with identity, lifecycle timeline, timeslot visualization, definition and worker cross-references.

### 5.1 Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ OVERVIEW TAB                                                     │
├──────────────────────────────┬──────────────────────────────────┤
│ Identity                     │ Assignment                       │
│ ─────────                    │ ──────────                       │
│ Definition: exam-ccnp-…  🔗 │ Worker: worker-1  🔗             │
│ Version: 1.1                 │ CML Lab: lab-abc-123  🔗        │
│ Owner: 91881022-…            │ Lab Record: 4c3d…  🔗           │
│ Reservation: 123             │ Ports: ssh:5041, vnc:5044        │
│ Form: CCNP ENCOR v1 Lab 1.1 │                                  │
├──────────────────────────────┴──────────────────────────────────┤
│ Timeslot                                                         │
│ ─────────                                                        │
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░  (progress bar: elapsed / total)   │
│ Start: Feb 28, 04:25 PM (3h ago)  End: Feb 28, 06:25 PM (1h)   │
│ Duration: 2h 00m  •  Remaining: 1h 00m                          │
├─────────────────────────────────────────────────────────────────┤
│ Lifecycle Timeline                                               │
│ ───────────────                                                  │
│ ● PENDING  ────  ● SCHEDULED  ────  ◉ RUNNING  ────  ○ STOPPING │
│   Feb 28         Feb 28               Feb 28                     │
│   04:20 PM       04:22 PM             04:25 PM                   │
│                                                                  │
│ State History (collapsible)                                      │
│ ┌──────────┬──────────────┬──────────────┬───────────────────┐   │
│ │ From     │ To           │ When         │ Triggered By      │   │
│ │ PENDING  │ SCHEDULED    │ 3h ago       │ resource-scheduler│   │
│ │ SCHED…   │ INSTANTIATING│ 3h ago       │ worker-controller │   │
│ │ …        │ RUNNING      │ 3h ago       │ worker-controller │   │
│ └──────────┴──────────────┴──────────────┴───────────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│ Grade Result                                                     │
│ ─────────────                                                    │
│ 🟢 PASS  (or 🔴 FAIL  or ○ Not graded)                         │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Cross-Reference Links

All cross-refs follow the established pattern (close self → 300ms delay → emit/open target):

| Link | Target | Mechanism |
|------|--------|-----------|
| Definition name → | Definition details modal | `renderDefinitionDetailsHtml(def)` inline or link to Definitions tab |
| Worker name → | `WorkerDetailsModal` | `eventBus.emit('UI_OPEN_WORKER_DETAILS', { workerId, region })` |
| Lab Record ID → | `LabDetailModal` | `document.querySelector('lab-detail-modal').open(labRecordId)` |
| CML Lab ID → | (informational, no modal) | Display only |

### 5.3 Lifecycle Timeline Rendering

Use a horizontal step indicator with CSS:

```javascript
_renderLifecycleTimeline(session) {
    const allStates = [
        'pending', 'scheduled', 'instantiating', 'ready',
        'running', 'collecting', 'grading', 'stopping', 'stopped', 'archived'
    ];
    const currentIndex = allStates.indexOf(session.status.toLowerCase());
    const isTerminated = session.status.toLowerCase() === 'terminated';

    // Build timeline from state_history
    const historyMap = {};
    (session.state_history || []).forEach(t => {
        historyMap[t.to_state.toLowerCase()] = t.transitioned_at;
    });

    return allStates.map((state, i) => {
        const reached = i <= currentIndex;
        const isCurrent = i === currentIndex;
        const time = historyMap[state]
            ? formatRelativeTime(historyMap[state])
            : '';
        // ... render step dot + connector line
    });
}
```

### 5.4 Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| 1 | Identity section shows definition, version, owner, reservation, form FQN | Open session → all fields visible |
| 2 | Assignment section shows worker (clickable), lab record (clickable), CML lab, ports | Open assigned session → all fields + links |
| 3 | Timeslot shows progress bar with elapsed/remaining | Active session → progress bar at correct % |
| 4 | Lifecycle timeline highlights current state | RUNNING session → RUNNING dot is filled |
| 5 | State history table shows transitions with relative times | 3 transitions → 3 rows with "3h ago" |
| 6 | Clicking definition link opens definition details | Click → definition modal opens |
| 7 | Clicking worker link opens WorkerDetailsModal | Click → worker modal opens |
| 8 | Clicking lab record link opens LabDetailModal | Click → lab detail modal opens |
| 9 | Grade result shows pass/fail/not-graded badge | Graded session → green PASS badge |

---

## 6. Phase 5: Pipeline Tab

> **Goal**: Visualize the per-service sync/provisioning pipeline as a vertical status flow, showing each stage's state with expandable details.

### 6.1 Pipeline Stages

```
┌─────────────────────────────────────────────────────────────────┐
│ PIPELINE TAB                                                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ● Upstream Source                                    ✓ synced   │
│  │  Version: 1.2  •  Published: Jan 15, 2026                    │
│  │  Mosaic: exam-ccnp-test-v1-lab-1.1                           │
│  │  URL: https://mosaic.example.com/…   🔗                      │
│  │                                                              │
│  ● Object Storage                                     ✓ synced   │
│  │  Bucket: ccnp-encor-v1-lab-1-1  🔗                           │
│  │  Package: SVN.zip (245 KB)                                    │
│  │  Hash: a3f8c2…                                               │
│  │  Last synced: 2h ago                                          │
│  │                                                              │
│  ● POD (Lab Record)                                  ◉ running   │
│  │  Worker: worker-1  🔗                                         │
│  │  Lab Record: 4c3d2ffc…  🔗                                   │
│  │  CML Lab: lab-abc-123                                         │
│  │  Status: BOOTED • Last updated: 5m ago                        │
│  │                                                              │
│  ● User Session (LDS)                                ◉ active    │
│  │  LDS Session: lds-session-xyz  🔗                             │
│  │  Login URL: https://lds.example.com/…   🔗                    │
│  │  Status: ACTIVE • Started: 2h ago                             │
│  │  Devices: [router1, switch1, server1]                         │
│  │  Variables: { region: "us-east-1", … }                        │
│  │  Clients: 1 connected                                         │
│  │                                                              │
│  ● Grading Session                                   ○ pending   │
│  │  Session ID: —                                                │
│  │  Status: Not started                                          │
│  │                                                              │
│  ○ Score Report                                      ○ —         │
│     Not yet graded                                               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 Data Fetching Strategy

Pipeline tab fetches data **lazily** on first activation:

1. **Upstream Source + Object Storage**: Already available on the enriched `LabletSessionDto` via `upstream_sync_status`, `upstream_version`, `content_package_hash`
2. **POD (Lab Record)**: Already available via `lab_record_id`, `lab_record_status` (enriched in Phase 1)
3. **User Session**: Fetched via `getUserSession(sessionId)` (new BFF route from Phase 1)
4. **Grading Session**: Fetched via `getGradingSession(sessionId)` (new BFF route from Phase 1)
5. **Score Report**: Fetched via `getScoreReport(sessionId)` (new BFF route from Phase 1)

```javascript
async _loadPipelineTab() {
    const session = this._session;
    const results = await Promise.allSettled([
        session.user_session_id
            ? labletSessionsApi.getUserSession(session.id)
            : Promise.resolve(null),
        session.grading_session_id
            ? labletSessionsApi.getGradingSession(session.id)
            : Promise.resolve(null),
        session.score_report_id
            ? labletSessionsApi.getScoreReport(session.id)
            : Promise.resolve(null),
    ]);

    const userSession = results[0].status === 'fulfilled' ? results[0].value : null;
    const gradingSession = results[1].status === 'fulfilled' ? results[1].value : null;
    const scoreReport = results[2].status === 'fulfilled' ? results[2].value : null;

    this._renderPipelineContent(session, userSession, gradingSession, scoreReport);
}
```

### 6.3 User Session Detail Rendering

When the `UserSession` data is available, show rich details:

```javascript
_renderUserSessionStage(session, userSession) {
    if (!userSession) {
        return this._renderPipelineStage('LDS Session', 'gray', 'No user session provisioned');
    }

    const statusColor = {
        active: 'green', provisioned: 'green', provisioning: 'amber',
        paused: 'amber', ended: 'gray', expired: 'red', faulted: 'red'
    }[userSession.status] || 'gray';

    // Devices list
    const devicesHtml = (userSession.devices || []).map(d =>
        `<span class="badge bg-light text-dark border me-1">${d.name || d.id}</span>`
    ).join('');

    // Login URL
    const loginHtml = userSession.login_url
        ? `<a href="${userSession.login_url}" target="_blank" class="small">
               <i class="bi bi-box-arrow-up-right me-1"></i>Launch Lab
           </a>`
        : '';

    return this._renderPipelineStage('LDS Session', statusColor, `
        <dl class="row mb-0 small">
            <dt class="col-4">LDS Session</dt>
            <dd class="col-8"><code>${userSession.lds_session_id || '—'}</code></dd>
            <dt class="col-4">Status</dt>
            <dd class="col-8"><lcm-status-badge status="${userSession.status}" pill></lcm-status-badge></dd>
            <dt class="col-4">Login URL</dt>
            <dd class="col-8">${loginHtml || '—'}</dd>
            <dt class="col-4">Devices</dt>
            <dd class="col-8">${devicesHtml || '—'}</dd>
            <dt class="col-4">Started</dt>
            <dd class="col-8">${userSession.started_at ? formatRelativeTime(userSession.started_at) : '—'}</dd>
        </dl>
    `);
}
```

### 6.4 Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| 1 | Pipeline tab shows 6 vertical stages | Open Pipeline tab → 6 labeled stages |
| 2 | Each stage shows correct color (green/amber/red/gray) | Synced definition → green upstream + storage |
| 3 | Upstream Source shows version, date, mosaic link | Click upstream → details visible |
| 4 | Object Storage shows bucket name, package, hash | Storage synced → bucket + hash visible |
| 5 | POD stage shows lab record cross-ref link | Click lab record → LabDetailModal opens |
| 6 | LDS stage shows devices, login URL, status | Active session → devices listed, launch link |
| 7 | Grading stage shows status or "not started" | Pre-grading → "Not started" |
| 8 | Score stage shows grade_result or "Not yet graded" | Ungraded → gray dot |
| 9 | Sub-entity API calls are parallelized | Network tab → 3 concurrent requests |
| 10 | 404 responses for missing sub-entities handled gracefully | No user_session → "No user session provisioned" |

---

## 7. Phase 6: Reports Tab

> **Goal**: Display grading-related reports with score breakdowns, section tables, and evidence summaries.

### 7.1 Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ REPORTS TAB                                                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│ Score Report                                          🟢 PASS    │
│ ────────────                                                     │
│ Score: 85 / 100  (85%)  •  Cut: 70  •  Result: PASS             │
│ Submitted: Feb 28, 05:30 PM (45m ago)                            │
│                                                                  │
│ ┌────────────────────────────────────────────────────────────┐   │
│ │ Section Breakdown                                          │   │
│ │ ┌──────────────────┬───────┬─────┬───────┬──────────────┐ │   │
│ │ │ Section          │ Score │ Max │  %    │ Passed       │ │   │
│ │ ├──────────────────┼───────┼─────┼───────┼──────────────┤ │   │
│ │ │ OSPF Routing     │  25   │ 30  │  83%  │ ✓            │ │   │
│ │ │ BGP Config       │  30   │ 30  │ 100%  │ ✓            │ │   │
│ │ │ ACL Security     │  15   │ 20  │  75%  │ ✓            │ │   │
│ │ │ VLAN Trunking    │  15   │ 20  │  75%  │ ✓            │ │   │
│ │ └──────────────────┴───────┴─────┴───────┴──────────────┘ │   │
│ └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│ Instantiation Report                                             │
│ ─────────────────────                                            │
│ (Phase 8+ — will show lab instantiation timing, errors,          │
│  node boot sequence, interface mapping)                          │
│                                                                  │
│ Evidence Report                                                  │
│ ───────────────                                                  │
│ (Phase 8+ — will show grading evidence collection details,       │
│  device access logs, command outputs)                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 Score Report Rendering

```javascript
_renderScoreReport(scoreReport) {
    if (!scoreReport) {
        return `<div class="text-muted"><i class="bi bi-clipboard-x me-1"></i>No score report available.</div>`;
    }

    const pct = scoreReport.percentage != null
        ? scoreReport.percentage
        : Math.round((scoreReport.score / scoreReport.max_score) * 100);
    const passClass = scoreReport.passed ? 'text-success' : 'text-danger';
    const passIcon = scoreReport.passed ? 'bi-check-circle-fill' : 'bi-x-circle-fill';

    // Section breakdown table
    const sectionsHtml = (scoreReport.sections || []).map(s => {
        const sPct = s.max_score > 0 ? Math.round((s.score / s.max_score) * 100) : 0;
        const sPass = s.passed ? '<i class="bi bi-check text-success"></i>' : '<i class="bi bi-x text-danger"></i>';
        return `<tr>
            <td>${this._escapeHtml(s.name)}</td>
            <td class="text-end">${s.score}</td>
            <td class="text-end">${s.max_score}</td>
            <td class="text-end">${sPct}%</td>
            <td class="text-center">${sPass}</td>
        </tr>`;
    }).join('');

    return `
        <div class="mb-4">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h6 class="mb-0"><i class="bi bi-clipboard-data me-2"></i>Score Report</h6>
                <span class="${passClass} fw-bold">
                    <i class="bi ${passIcon} me-1"></i>${scoreReport.grade_result || (scoreReport.passed ? 'PASS' : 'FAIL')}
                </span>
            </div>
            <div class="row g-3 mb-3">
                <div class="col-3 text-center">
                    <div class="bg-light rounded p-2">
                        <div class="small text-muted">Score</div>
                        <div class="fw-bold">${scoreReport.score} / ${scoreReport.max_score}</div>
                    </div>
                </div>
                <div class="col-3 text-center">
                    <div class="bg-light rounded p-2">
                        <div class="small text-muted">Percentage</div>
                        <div class="fw-bold">${pct}%</div>
                    </div>
                </div>
                <div class="col-3 text-center">
                    <div class="bg-light rounded p-2">
                        <div class="small text-muted">Cut Score</div>
                        <div class="fw-bold">${scoreReport.cut_score ?? '—'}</div>
                    </div>
                </div>
                <div class="col-3 text-center">
                    <div class="bg-light rounded p-2">
                        <div class="small text-muted">Submitted</div>
                        <div class="fw-bold small">${scoreReport.created_at ? formatRelativeTime(scoreReport.created_at) : '—'}</div>
                    </div>
                </div>
            </div>
            ${sectionsHtml ? `
                <div class="table-responsive">
                    <table class="table table-sm table-hover mb-0">
                        <thead class="table-light">
                            <tr>
                                <th>Section</th>
                                <th class="text-end">Score</th>
                                <th class="text-end">Max</th>
                                <th class="text-end">%</th>
                                <th class="text-center">Pass</th>
                            </tr>
                        </thead>
                        <tbody>${sectionsHtml}</tbody>
                    </table>
                </div>
            ` : ''}
        </div>
    `;
}
```

### 7.3 Placeholder Reports

Instantiation and Evidence reports don't have backend entities yet. Show placeholders:

```javascript
_renderInstantiationReport() {
    return `
        <div class="mb-4">
            <h6 class="text-muted mb-2"><i class="bi bi-gear me-2"></i>Instantiation Report</h6>
            <div class="text-muted small border rounded p-3 bg-light">
                <i class="bi bi-info-circle me-1"></i>
                Instantiation report will show lab creation timing, node boot sequence,
                and interface mapping. <em>Coming in a future release.</em>
            </div>
        </div>
    `;
}

_renderEvidenceReport() {
    return `
        <div class="mb-4">
            <h6 class="text-muted mb-2"><i class="bi bi-search me-2"></i>Evidence Report</h6>
            <div class="text-muted small border rounded p-3 bg-light">
                <i class="bi bi-info-circle me-1"></i>
                Evidence report will show grading evidence collection details
                and device access logs. <em>Coming in a future release.</em>
            </div>
        </div>
    `;
}
```

### 7.4 Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| 1 | Score report shows score/max/percentage/cut/result | Graded session → all score metrics visible |
| 2 | Section breakdown table shows per-section scores | 4 sections → 4 table rows |
| 3 | Pass/fail icons render correctly per section | Passing section → green check |
| 4 | No score report → "No score report available" | Ungraded session → placeholder |
| 5 | Instantiation report shows "coming soon" placeholder | Open Reports tab → placeholder visible |
| 6 | Evidence report shows "coming soon" placeholder | Open Reports tab → placeholder visible |

---

## 8. Phase 7: Resources Tab

> **Goal**: Visualize the three dimensions of resource data — **Required** (from definition), **Observed** (from live CML), and **Available** (from worker capacity) — as comparative bar charts.

### 8.1 Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ RESOURCES TAB                                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│ Resource Comparison                                              │
│ ───────────────────                                              │
│                                                                  │
│ CPU Cores                                                        │
│ Required:  ████████░░░░░░░░░░░░░░  2 cores                      │
│ Observed:  ████████████████░░░░░░  8 cores                      │
│ Available: ████████████████████████ 16 cores                     │
│                                                                  │
│ Memory                                                           │
│ Required:  ████░░░░░░░░░░░░░░░░░░  4 GB                        │
│ Observed:  ████████████░░░░░░░░░░  12 GB                        │
│ Available: ████████████████████████ 32 GB                        │
│                                                                  │
│ Storage                                                          │
│ Required:  ██░░░░░░░░░░░░░░░░░░░░  20 GB                       │
│ Observed:  (not measured)                                        │
│ Available: ████████████████████████ 500 GB                       │
│                                                                  │
│ Nodes                                                            │
│ Required:  ████░░░░░░░░░░░░░░░░░░  1 node                      │
│ Observed:  ████████████████████░░░  8 nodes                     │
│                                                                  │
│ Port Allocation                                    ⚠️ Drift      │
│ ────────────────                                                 │
│ ┌──────────────┬───────────┬──────────┬────────────────┐        │
│ │ Port Name    │ Allocated │ Observed │ Status         │        │
│ ├──────────────┼───────────┼──────────┼────────────────┤        │
│ │ ssh          │ 5041      │ 5041     │ ✓ Match        │        │
│ │ vnc          │ 5044      │ 5044     │ ✓ Match        │        │
│ │ http         │ —         │ 8080     │ ⚠ Added        │        │
│ └──────────────┴───────────┴──────────┴────────────────┘        │
│                                                                  │
│ Observation Metadata                                             │
│ ────────────────────                                             │
│ Observations: 3  •  Last: Feb 28, 05:15 PM (1h ago)             │
│ [Observe Now] button (if RUNNING)                                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 Data Sources

| Dimension | Source | Available On |
|-----------|--------|-------------|
| **Required** | `LabletDefinitionState.resource_requirements` | Enriched `LabletSessionDto.resource_requirements` (Phase 1) |
| **Observed** | `LabletSessionState.observed_resources` | `LabletSessionDto.observed_resources` |
| **Available** | `CMLWorkerState.declared_capacity` | Fetched via `workersApi.getWorker(worker_id)` on tab load |

### 8.3 Bar Chart Rendering (CSS-only, no chart library)

```javascript
_renderResourceBar(label, value, maxValue, color) {
    const pct = maxValue > 0 ? Math.min(100, Math.round((value / maxValue) * 100)) : 0;
    return `
        <div class="d-flex align-items-center mb-1">
            <span class="small text-muted" style="width: 70px;">${label}</span>
            <div class="flex-grow-1 mx-2">
                <div class="progress" style="height: 14px;">
                    <div class="progress-bar bg-${color}" role="progressbar"
                         style="width: ${pct}%" aria-valuenow="${value}"
                         aria-valuemin="0" aria-valuemax="${maxValue}">
                    </div>
                </div>
            </div>
            <span class="small fw-bold" style="width: 80px; text-align: right;">${value}</span>
        </div>
    `;
}

_renderResourceComparison(metric, required, observed, available) {
    const max = Math.max(required || 0, observed || 0, available || 0, 1);
    return `
        <div class="mb-3">
            <div class="small fw-bold mb-1">${metric}</div>
            ${this._renderResourceBar('Required', required ?? '—', max, 'primary')}
            ${observed != null
                ? this._renderResourceBar('Observed', observed, max, 'info')
                : '<div class="d-flex align-items-center mb-1"><span class="small text-muted" style="width: 70px;">Observed</span><span class="small text-muted ms-2">(not measured)</span></div>'}
            ${available != null
                ? this._renderResourceBar('Available', available, max, 'success')
                : ''}
        </div>
    `;
}
```

### 8.4 Backend Addition: Worker Capacity on LabletSessionDto

To avoid an additional API call for worker capacity, consider adding these to the enriched `LabletSessionDto` (Phase 1 extension):

| Field | Type | Source |
|-------|------|--------|
| `worker_declared_capacity` | `dict \| None` | `CMLWorkerState.declared_capacity` serialized |
| `worker_allocated_capacity` | `dict \| None` | `CMLWorkerState.allocated_capacity` serialized |

Alternatively, the Resources tab can fetch worker data lazily:

```javascript
const worker = await workersApi.getWorker(session.worker_id, session.worker_region);
```

### 8.5 Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| 1 | CPU/Memory/Storage/Nodes bars show Required/Observed/Available | Session with all data → 3 bars per metric |
| 2 | Bars scale correctly relative to maximum value | Observed 8 cores, Available 16 cores → bars proportional |
| 3 | Missing observed data shows "(not measured)" | No observation → graceful fallback |
| 4 | Port allocation table shows allocated vs observed | 3 ports → 3 rows with match/drift status |
| 5 | Drift badge shows when `port_drift_detected` is true | Drifted session → ⚠️ Drift badge |
| 6 | "Observe Now" button appears for RUNNING sessions | Running → button visible; not running → hidden |
| 7 | Observation metadata shows count and last timestamp | 3 observations → "3 observations • Last: 1h ago" |

---

## 9. Phase 8: Cross-Ref Links on Related Modals

> **Goal**: Add bi-directional cross-reference links between all related modals so users can navigate the entity graph.

### 9.1 Link Matrix

| From Modal | To Modal | Link Text | Mechanism |
|------------|----------|-----------|-----------|
| **SessionDetailsModal** → | WorkerDetailsModal | Worker name/ID | `eventBus.emit('UI_OPEN_WORKER_DETAILS')` |
| **SessionDetailsModal** → | LabDetailModal | Lab Record ID | `labDetailModal.open(labRecordId)` |
| **SessionDetailsModal** → | Definition details | Definition name | `renderDefinitionDetailsHtml()` inline |
| **WorkerDetailsModal** → | SessionDetailsModal | Session ID (in Labs/Sessions tab) | `eventBus.emit('UI_OPEN_SESSION_DETAILS')` |
| **LabDetailModal** → | SessionDetailsModal | Lablet Session ID (in linkedLablets tab) | `eventBus.emit('UI_OPEN_SESSION_DETAILS')` |
| **Definition details** → | SessionDetailsModal | Active sessions count | Link to sessions table filtered by definition |

### 9.2 Changes to WorkerDetailsModal

**File**: `ui/src/scripts/components/modals/WorkerDetailsModal.js`

In the Labs tab or a new "Sessions" section, add links to assigned lablet sessions:

```javascript
// In worker data, session_ids contains assigned lablet session IDs
const sessionLinks = (worker.session_ids || []).map(sid =>
    `<a href="#" class="open-session-link text-decoration-none"
        data-session-id="${sid}" title="Open Session ${sid}">
        <code class="small">${sid.substring(0, 8)}…</code>
        <i class="bi bi-box-arrow-up-right" style="font-size: 0.7em;"></i>
    </a>`
).join(', ');
```

Click handler:

```javascript
this.$$('.open-session-link').forEach(link => {
    link.addEventListener('click', e => {
        e.preventDefault();
        const sessionId = link.dataset.sessionId;
        this.closeModal();
        setTimeout(() => {
            eventBus.emit('UI_OPEN_SESSION_DETAILS', { sessionId });
        }, 300);
    });
});
```

### 9.3 Changes to LabDetailModal

**File**: `ui/src/scripts/components/pages/LabDetailModal.js`

In the `linkedLablets` tab, make session IDs clickable:

```javascript
// Already shows linked lablet session IDs — make them clickable
const sessionLink = `
    <a href="#" class="open-session-link text-decoration-none"
       data-session-id="${session.id}">
        <code class="small">${session.id.substring(0, 8)}…</code>
        <i class="bi bi-box-arrow-up-right" style="font-size: 0.7em;"></i>
    </a>
`;
```

### 9.4 UUID Display Convention (ADR-029)

All cross-reference UUIDs use the **first segment** convention:

- Full: `4d1bc380-ddac-48d0-a0b4-838e73878cc8`
- Display: `4d1bc380…`
- Tooltip: Full UUID
- Click: Opens related modal

```javascript
function shortUuid(uuid) {
    return uuid ? uuid.split('-')[0] + '…' : '—';
}
```

### 9.5 Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| 1 | Session modal → Worker link opens WorkerDetailsModal | Click worker link → worker modal |
| 2 | Session modal → Lab Record link opens LabDetailModal | Click lab record → lab modal |
| 3 | Worker modal → Session link opens SessionDetailsModal | Click session ID in worker → session modal |
| 4 | Lab modal → Session link opens SessionDetailsModal | Click session ID in lab → session modal |
| 5 | All UUIDs show first-segment shorthand | Cross-ref shows `4d1bc380…` not full UUID |
| 6 | Full UUID visible in tooltip | Hover over short UUID → full ID in tooltip |
| 7 | Modal-to-modal transitions have 300ms delay | Close → delay → open (no flicker) |

---

## 10. File Index

### Backend Changes

| File | Phases | Changes |
|------|--------|---------|
| `application/dtos/lablet_session_dto.py` | 1 | Add enrichment fields to `ListLabletSessionDto` and `LabletSessionDto` |
| `application/queries/lablet_session/list_lablet_sessions_query.py` | 1 | Inject definition/worker repos, batch-enrich DTOs |
| `application/queries/lablet_session/get_lablet_session_query.py` | 1 | Inject repos, enrich with definition/worker/lab_record data |
| `api/controllers/lablet_sessions_controller.py` | 1 | Add 3 new routes: user-session, grading-session, score-report |

### Frontend Changes

| File | Phases | Changes |
|------|--------|---------|
| `ui/src/scripts/api/lablet-sessions.js` | 1 | Add `getUserSession()`, `getGradingSession()`, `getScoreReport()` |
| `ui/src/scripts/components/pages/SessionsPage.js` | 2, 3 | New column config, EventBus emit instead of inline modal |
| `ui/src/scripts/components/modals/SessionDetailsModal.js` | 3, 4, 5, 6, 7 | **New file**: Tabbed modal (Overview, Pipeline, Reports, Resources) |
| `ui/src/scripts/components/modals/WorkerDetailsModal.js` | 8 | Add session cross-ref links |
| `ui/src/scripts/components/pages/LabDetailModal.js` | 8 | Add session cross-ref links |
| `ui/src/templates/components/lablet_instances.jinja` | 3 | Deprecate `#labletSessionDetailsModal` shell |

### Shared/Utility

| File | Phases | Usage |
|------|--------|-------|
| `ui/src/scripts/utils/dates.js` | 2, 4, 5, 6 | `formatRelativeTime()`, `formatDateTimeWithTooltip()`, `formatTimeslotRange()` |
| `ui/src/scripts/app/eventBus.js` | 3, 8 | `UI_OPEN_SESSION_DETAILS` event |
| `ui/src/scripts/store/workerStore.js` | 2, 8 | `getWorker()` for cross-ref region lookup |

---

## 11. Test Approach

### Backend Tests

| Test | File | Scope |
|------|------|-------|
| Enriched list DTO contains all new fields | `tests/test_list_lablet_sessions_query.py` | Unit |
| Enriched detail DTO contains all new fields | `tests/test_get_lablet_session_query.py` | Unit |
| Batch enrichment handles missing definitions/workers | Same files | Unit |
| BFF user-session route returns 200 | `tests/test_lablet_sessions_controller.py` | Integration |
| BFF user-session route returns 404 when no child entity | Same file | Integration |
| BFF grading-session route returns 200 | Same file | Integration |
| BFF score-report route returns 200 with sections | Same file | Integration |

### Frontend Tests

| Test | Approach |
|------|----------|
| Datatable shows 9 columns with correct labels | Manual: open Sessions page → verify column headers |
| Timeslot column shows relative time with correct color | Manual: create sessions in past/present/future → verify colors |
| Worker column click opens WorkerDetailsModal | Manual: click worker → modal opens |
| Pipeline dots show correct colors | Manual: session with synced definition → green dots |
| Pipeline dot tooltips show details | Manual: hover each dot → tooltip content correct |
| SessionDetailsModal opens with 4 tabs | Manual: click session → verify modal tabs |
| Overview tab shows lifecycle timeline | Manual: RUNNING session → timeline shows progression |
| Pipeline tab loads sub-entity data | Manual: click Pipeline → user session details appear |
| Reports tab shows score breakdown | Manual: graded session → section table visible |
| Resources tab shows comparison bars | Manual: observed session → 3 bars per metric |
| Cross-ref navigation works between all modals | Manual: session → worker → session roundtrip |

---

## Appendix A: Existing Utilities Reference

### Date Formatting (`utils/dates.js`)

| Function | Output Example |
|----------|----------------|
| `formatRelativeTime(iso)` | "3h ago", "in 2h", "just now" |
| `formatDateTimeWithTooltip(iso)` | Full datetime + Bootstrap tooltip with relative |
| `formatTimeslotRange(start, end)` | "Jan 1, 2025 10:00 AM - 11:00 AM (1h)" |
| `formatDuration(ms)` | "2d 3h", "45m 12s" |
| `formatDateTime(iso)` | "Feb 28, 2026 04:25 PM" |

### EventBus Events (Relevant)

| Event | Payload | Used By |
|-------|---------|---------|
| `UI_OPEN_WORKER_DETAILS` | `{ workerId, region }` | LabDetailModal → WorkerDetailsModal |
| `UI_OPEN_SESSION_DETAILS` | `{ sessionId }` | **New**: Cross-ref → SessionDetailsModal |
| `lablet.session.updated` | `{ id, ... }` | SSE → SessionsPage |
| `lablet.session.status.changed` | `{ id, status, ... }` | SSE → SessionsPage |

### Cross-Reference Pattern

```javascript
// Standard pattern: close self → delay → open target
this.closeModal();
setTimeout(() => {
    eventBus.emit('UI_OPEN_SESSION_DETAILS', { sessionId });
}, 300);
```

### Status-to-Color Mapping

```javascript
const statusColors = {
    pending: 'warning', scheduled: 'info', instantiating: 'info',
    ready: 'success', running: 'success', collecting: 'info',
    grading: 'info', stopping: 'warning', stopped: 'secondary',
    archived: 'secondary', terminated: 'danger'
};
```
