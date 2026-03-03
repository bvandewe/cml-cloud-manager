# Frontend UX — Resource Observation Discoverability

**Status**: ✅ Complete
**Created**: 2026-02-28
**Last Updated**: 2026-02-28
**Author**: AI Architect (lcm-senior-architect)
**Depends On**: [ADR-030 "Learn from Live"](observe_live_resources.md) (all 10 phases complete)
**Scope**: Frontend-only changes in `control-plane-api/ui/` to make resource observation discoverable and optional in definition/session workflows.

---

## Implementation Progress

| Phase | Scope | Status | Effort |
|-------|-------|--------|--------|
| **Phase 1** | Optional resource requirements toggle in Create/Edit Definition modals | ✅ Complete | Small |
| **Phase 2** | "Observe Resources" button on session table rows + session cards + detail modal | ✅ Complete | Medium |
| **Phase 3** | Fix Port Definition UX (add/remove rows, collect on submit, display in details) | ✅ Complete | Medium |

---

## Table of Contents

1. [Overview](#1-overview)
2. [Phase 1: Optional Resource Requirements in Definition Modals](#2-phase-1-optional-resource-requirements-in-definition-modals)
3. [Phase 2: Observe Resources from Session Table & Details Modal](#3-phase-2-observe-resources-from-session-table--details-modal)
4. [Phase 3: Fix Port Definition UX](#4-phase-3-fix-port-definition-ux)
5. [File Index](#5-file-index)
6. [Test Approach](#6-test-approach)

---

## 1. Overview

### 1.1 Problem Statement

ADR-030 backend is fully implemented — definitions can be created, sessions observed, and aggregated observations queried. However the frontend doesn't surface these capabilities:

1. **Resource requirements feel mandatory** — the Create/Edit Definition form shows CPU/Memory/Storage/Nodes as always-visible fields with no indication that defaults work fine and can be refined later via observation.
2. **Observe Resources is buried** — the `requestResourceObservation()` API exists, but the only trigger is in `SessionDetailPage.js` (a web component that isn't used in the main `SessionsPage.js` table workflow). The main sessions table and `LabletSessionCard.js` lack observe buttons.
3. **Port definitions are broken** — the Jinja template has `#addPortDefinition` button and `#portDefinitionsContainer` but zero JS handlers exist. The submit handler in `lablet-modals.js` doesn't collect ports.

### 1.2 Design Principles

- **Progressive disclosure**: Hide complexity behind toggles; show defaults are safe
- **Consistency**: Follow existing patterns (Bootstrap 5 accordion/collapse, `showToast()`, `data-action` delegation)
- **No backend changes**: All work is in `ui/` (templates, scripts, components)
- **Graceful degradation**: Existing definitions with non-default resources auto-expand the toggle

### 1.3 Key Files

All paths relative to `src/control-plane-api/`.

| File | Role | Phases |
|------|------|--------|
| `ui/src/templates/components/lablet_definitions.jinja` | Create/Edit/Details modal HTML shells | 1, 3 |
| `ui/src/templates/components/lablet_instances.jinja` | Session Details modal HTML shell | 2 |
| `ui/src/scripts/ui/lablet-modals.js` | `setupCreateLabletDefinitionModal()` — form submission | 1, 3 |
| `ui/src/scripts/components/shared/definition-details-renderer.js` | `renderDefinitionDetailsHtml()` — Details modal body | 1, 3 |
| `ui/src/scripts/components/pages/SessionsPage.js` | Main sessions page — table, row actions, detail modal | 2 |
| `ui/src/scripts/components/sessions/SessionDetailPage.js` | **Reference**: observation panel with "Observe Now" | 2 |
| `ui/src/scripts/components/sessions/LabletSessionCard.js` | Session card actions | 2 |
| `ui/src/scripts/api/lablet-sessions.js` | `requestResourceObservation()` — already implemented | 2 |

---

## 2. Phase 1: Optional Resource Requirements in Definition Modals

> **Goal**: Make resource specification feel optional by hiding it behind a collapsible toggle. Users learn that defaults (2 CPU, 4 GB, 20 GB) work and can be refined after first session observation.

### 2.1 Changes to `lablet_definitions.jinja`

**File**: `ui/src/templates/components/lablet_definitions.jinja`

Wrap the **Resource Requirements** section (currently inside `<div class="col-md-6">` on the right side of the form) in a Bootstrap 5 collapse widget with a toggle.

#### 2.1.1 Replace the right column's Resource Requirements block

**Before** (lines ~97–130 in the template):

```html
<!-- Resource Requirements -->
<div class="col-md-6">
    <h6 class="mb-3"><i class="bi bi-cpu"></i> Resource Requirements</h6>
    <div class="row mb-3">
        <!-- CPU, Memory, Storage, NodeCount, Nested Virt fields -->
    </div>
    ...
</div>
```

**After**:

```html
<!-- Resource Requirements (collapsible) -->
<div class="col-md-6">
    <!-- Toggle -->
    <div class="form-check form-switch mb-2">
        <input class="form-check-input" type="checkbox" role="switch"
               id="defResourceToggle">
        <label class="form-check-label" for="defResourceToggle">
            <i class="bi bi-cpu me-1"></i>
            Enable resource specification
            <small class="text-muted d-block">
                Optional — resources will use defaults and can be refined after first session observation.
            </small>
        </label>
    </div>

    <!-- Collapsed content -->
    <div class="collapse" id="resourceRequirementsCollapse">
        <div class="border rounded p-3 bg-light">
            <h6 class="mb-3"><i class="bi bi-cpu"></i> Resource Requirements</h6>
            <div class="row mb-3">
                <div class="col-md-6">
                    <label for="defCpuCores" class="form-label">CPU Cores</label>
                    <input type="number" class="form-control" id="defCpuCores"
                           min="1" max="64" value="2">
                </div>
                <div class="col-md-6">
                    <label for="defMemoryGb" class="form-label">Memory (GB)</label>
                    <input type="number" class="form-control" id="defMemoryGb"
                           min="1" max="256" value="4">
                </div>
            </div>
            <div class="row mb-3">
                <div class="col-md-6">
                    <label for="defStorageGb" class="form-label">Storage (GB)</label>
                    <input type="number" class="form-control" id="defStorageGb"
                           min="1" max="1000" value="20">
                </div>
                <div class="col-md-6">
                    <label for="defNodeCount" class="form-label">Node Count</label>
                    <input type="number" class="form-control" id="defNodeCount"
                           min="1" max="50" value="1">
                </div>
            </div>
            <div class="form-check mb-3">
                <input type="checkbox" class="form-check-input" id="defNestedVirt"
                       checked>
                <label class="form-check-label" for="defNestedVirt">
                    Requires Nested Virtualization
                </label>
            </div>
        </div>
    </div>

    <!-- Default hint (visible when collapsed) -->
    <div id="resourceDefaultsHint" class="alert alert-light border py-2 px-3 small mt-2">
        <i class="bi bi-info-circle text-primary me-1"></i>
        Defaults: <strong>2 CPU</strong>, <strong>4 GB RAM</strong>,
        <strong>20 GB Storage</strong>, <strong>1 Node</strong>.
        Resources can be refined after first session observation.
    </div>

    <!-- Lifecycle Settings (always visible, not part of resource toggle) -->
    <h6 class="mb-3 mt-3"><i class="bi bi-clock"></i> Lifecycle Settings</h6>
    <!-- ... existing lifecycle fields (maxDuration, warmPoolDepth, bootLeadTime, licenseAffinity) ... -->
</div>
```

#### 2.1.2 Wire the toggle

Add an inline `<script>` block (or extend the existing DOMContentLoaded handler at the bottom of the template) to toggle the collapse and hint:

```javascript
// Resource requirements toggle
const resourceToggle = document.getElementById('defResourceToggle');
const collapseEl = document.getElementById('resourceRequirementsCollapse');
const defaultsHint = document.getElementById('resourceDefaultsHint');

if (resourceToggle && collapseEl) {
    const bsCollapse = new bootstrap.Collapse(collapseEl, { toggle: false });

    resourceToggle.addEventListener('change', function () {
        if (this.checked) {
            bsCollapse.show();
            if (defaultsHint) defaultsHint.style.display = 'none';
        } else {
            bsCollapse.hide();
            if (defaultsHint) defaultsHint.style.display = '';
        }
    });
}
```

#### 2.1.3 Port Definitions section also collapses under the same toggle

Move the existing **Port Definitions** section (`#portDefinitionsContainer` + `#addPortDefinition` button) inside `#resourceRequirementsCollapse`, below the resource fields. This groups all "resource specification" fields together:

```html
<!-- Inside #resourceRequirementsCollapse, after Nested Virt checkbox -->
<hr class="my-2">
<h6 class="mb-2"><i class="bi bi-plug"></i> Port Definitions</h6>
<div id="portDefinitionsContainer">
    <!-- Dynamic port definition rows (Phase 3) -->
</div>
<button type="button" class="btn btn-sm btn-outline-primary"
        id="addPortDefinition">
    <i class="bi bi-plus"></i> Add Port
</button>
```

### 2.2 Changes to `lablet-modals.js`

**File**: `ui/src/scripts/ui/lablet-modals.js`

#### 2.2.1 Submit handler — respect toggle state

In `setupCreateLabletDefinitionModal()`, modify the submit click handler to check the toggle:

```javascript
// After gathering form data, check toggle state
const resourceToggle = document.getElementById('defResourceToggle');
const isResourceExpanded = resourceToggle?.checked ?? false;

// If toggle is OFF, use explicit defaults (don't read hidden fields)
const cpuCores = isResourceExpanded
    ? (parseInt(document.getElementById('defCpuCores')?.value) || 2)
    : 2;
const memoryGb = isResourceExpanded
    ? (parseInt(document.getElementById('defMemoryGb')?.value) || 4)
    : 4;
const storageGb = isResourceExpanded
    ? (parseInt(document.getElementById('defStorageGb')?.value) || 20)
    : 20;
const nodeCount = isResourceExpanded
    ? (parseInt(document.getElementById('defNodeCount')?.value) || 1)
    : 1;
const nestedVirt = isResourceExpanded
    ? (document.getElementById('defNestedVirt')?.checked ?? true)
    : true;
```

No change needed to the API payload shape — the values are the same whether user-specified or defaults.

#### 2.2.2 Reset handler — collapse toggle on modal hidden

In the `hidden.bs.modal` event handler, add:

```javascript
// Reset resource toggle
const resourceToggle = document.getElementById('defResourceToggle');
if (resourceToggle) resourceToggle.checked = false;
const collapseEl = document.getElementById('resourceRequirementsCollapse');
if (collapseEl) {
    const bsCollapse = bootstrap.Collapse.getInstance(collapseEl);
    if (bsCollapse) bsCollapse.hide();
}
const defaultsHint = document.getElementById('resourceDefaultsHint');
if (defaultsHint) defaultsHint.style.display = '';
```

### 2.3 Changes to `SessionsPage.js` — Edit Definition auto-expand

**File**: `ui/src/scripts/components/pages/SessionsPage.js`

In `_editDefinition(definitionId)`, after populating form fields, auto-expand the toggle when the definition has non-default resources:

```javascript
// After populating resource fields
// Auto-expand toggle if definition has non-default resources
const hasNonDefaultResources =
    (def.resource_requirements?.cpu_cores && def.resource_requirements.cpu_cores !== 2) ||
    (def.resource_requirements?.memory_gb && def.resource_requirements.memory_gb !== 4) ||
    (def.resource_requirements?.storage_gb && def.resource_requirements.storage_gb !== 20) ||
    (def.node_count && def.node_count !== 1) ||
    (def.resource_requirements?.nested_virt === false) ||
    (def.port_template?.ports?.length > 0);

const resourceToggle = document.getElementById('defResourceToggle');
const collapseEl = document.getElementById('resourceRequirementsCollapse');
const defaultsHint = document.getElementById('resourceDefaultsHint');

if (hasNonDefaultResources && resourceToggle && collapseEl) {
    resourceToggle.checked = true;
    const bsCollapse = bootstrap.Collapse.getOrCreateInstance(collapseEl);
    bsCollapse.show();
    if (defaultsHint) defaultsHint.style.display = 'none';
}
```

### 2.4 Changes to `definition-details-renderer.js` — Show defaults context

**File**: `ui/src/scripts/components/shared/definition-details-renderer.js`

In `renderDefinitionDetailsHtml()`, add a subtle indicator when resources are at default values:

```javascript
// In the Resource Requirements section of renderDefinitionDetailsHtml()
const isDefault =
    (def.resource_requirements?.cpu_cores === 2 || !def.resource_requirements?.cpu_cores) &&
    (def.resource_requirements?.memory_gb === 4 || !def.resource_requirements?.memory_gb) &&
    (def.resource_requirements?.storage_gb === 20 || !def.resource_requirements?.storage_gb);

// Add after the resource DL, before lifecycle
const defaultNote = isDefault
    ? `<div class="small text-muted mt-1">
         <i class="bi bi-info-circle me-1"></i>Using defaults — can be refined after session observation.
       </div>`
    : '';
```

Insert `${defaultNote}` after the Resource Requirements `<dl>` block closing tag.

### 2.5 Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| 1 | Create Definition modal shows resource fields collapsed by default | Open modal → fields hidden, defaults hint visible |
| 2 | Toggling switch expands resource fields, hides defaults hint | Click toggle → collapse opens smoothly |
| 3 | Submitting with toggle OFF sends defaults (2, 4, 20, 1, nested=true) | Check network request payload |
| 4 | Submitting with toggle ON sends user-entered values | Enter 8 CPU, submit → payload has `cpu_cores: 8` |
| 5 | Edit existing def with non-default resources auto-expands toggle | Edit def with 8 CPU → toggle is checked, fields visible |
| 6 | Edit existing def with default resources keeps toggle collapsed | Edit def with 2/4/20/1 → toggle unchecked |
| 7 | Modal reset on close collapses toggle and resets fields | Close modal → reopen → toggle off, defaults hint visible |
| 8 | Details modal shows "Using defaults" note for default-resource defs | View details of fresh definition → note visible |
| 9 | Port definitions section is inside the collapse (visible only when expanded) | Toggle on → port section visible; toggle off → hidden |

---

## 3. Phase 2: Observe Resources from Session Table & Details Modal

> **Goal**: Surface the `requestResourceObservation()` API in all session views — table rows, session cards, and the detail modal — so admins can trigger observation without navigating to the `SessionDetailPage` web component.

### 3.1 Changes to `SessionsPage.js` — Add "Observe" action to table rows

**File**: `ui/src/scripts/components/pages/SessionsPage.js`

#### 3.1.1 Add observe button to session table Actions column

In `_configureLabletSessionsTable()`, modify the `actions` column render function:

```javascript
{
    field: 'actions',
    label: 'Actions',
    render: (_, row) => {
        const st = (row.status || '').toLowerCase();
        const isTerminal = st === 'terminated' || st === 'archived';
        if (isTerminal) return '<span class="text-muted">—</span>';

        // Observe button — only for RUNNING sessions
        const observeBtn = st === 'running'
            ? `<button class="btn btn-outline-info btn-sm"
                       data-action="observe-resources"
                       data-id="${row.id}"
                       title="Observe live CML resources">
                   <i class="bi bi-binoculars"></i>
               </button>`
            : '';

        return `
            <div class="btn-group btn-group-sm">
                ${observeBtn}
                <button class="btn btn-outline-primary btn-sm"
                        data-action="requeue" data-id="${row.id}"
                        title="Re-queue (sync)">
                    <i class="bi bi-arrow-repeat"></i>
                </button>
                <button class="btn btn-outline-danger btn-sm"
                        data-action="terminate" data-id="${row.id}"
                        title="Terminate">
                    <i class="bi bi-x-circle"></i>
                </button>
            </div>
        `;
    },
},
```

#### 3.1.2 Handle the observe action in click delegation

In `_setupEventListeners()`, add a case to the click delegation switch:

```javascript
case 'observe-resources':
    if (id) this._observeResources(id);
    break;
```

#### 3.1.3 Implement `_observeResources()` method

Add new method to `SessionsPage`:

```javascript
/**
 * Request resource observation for a RUNNING session (ADR-030).
 * Calls the existing API, shows toast feedback.
 */
async _observeResources(sessionId) {
    const btn = this.querySelector(
        `[data-action="observe-resources"][data-id="${sessionId}"]`
    );

    try {
        if (btn) {
            btn.disabled = true;
            btn.innerHTML =
                '<span class="spinner-border spinner-border-sm"></span>';
        }

        await labletSessionsApi.requestResourceObservation(sessionId);
        showToast(
            'Resource observation requested — results will appear shortly.',
            'info'
        );
    } catch (error) {
        console.error(
            '[SessionsPage] Observe resources failed:',
            error
        );
        showToast(
            `Observation failed: ${error.message}`,
            'error'
        );
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-binoculars"></i>';
        }
    }
}
```

#### 3.1.4 Add import for `requestResourceObservation`

At the top of `SessionsPage.js`, the import is already present via `labletSessionsApi` wildcard import:

```javascript
import * as labletSessionsApi from '../../api/lablet-sessions.js';
```

`requestResourceObservation` is exported from `lablet-sessions.js` so `labletSessionsApi.requestResourceObservation(id)` works.

### 3.2 Changes to `LabletSessionCard.js` — Add "Observe" button

**File**: `ui/src/scripts/components/sessions/LabletSessionCard.js`

#### 3.2.1 Add observe button to `renderActionButtons()`

In `renderActionButtons(session)`, add an observe button for RUNNING sessions before the status-specific actions:

```javascript
renderActionButtons(session) {
    const status = (session.status || '').toLowerCase();
    const buttons = [];

    // View details button — always available
    buttons.push(`
        <button class="btn btn-outline-primary btn-sm"
                data-action="view" title="View Details">
            <i class="bi bi-eye"></i>
        </button>
    `);

    // Observe Resources button — RUNNING sessions only (ADR-030)
    if (status === 'running') {
        buttons.push(`
            <button class="btn btn-outline-info btn-sm"
                    data-action="observe-resources"
                    title="Observe live CML resources">
                <i class="bi bi-binoculars"></i>
            </button>
        `);
    }

    // Status-specific action buttons (AD-P7-06)
    // ... existing code ...
```

#### 3.2.2 Wire the observe button in `setupEventHandlers()`

Add handler after the existing view/transition/terminate handlers:

```javascript
// Observe Resources button (ADR-030)
const observeBtn = this.querySelector('[data-action="observe-resources"]');
if (observeBtn) {
    observeBtn.addEventListener('click', async () => {
        try {
            observeBtn.disabled = true;
            observeBtn.innerHTML =
                '<span class="spinner-border spinner-border-sm"></span>';

            const { requestResourceObservation } =
                await import('../api/lablet-sessions.js');
            await requestResourceObservation(session.id);

            const { showToast } =
                await import('../ui/notifications.js');
            showToast(
                'Resource observation requested — results will appear shortly.',
                'info'
            );
        } catch (error) {
            console.error('Failed to observe resources:', error);
            const { showToast } =
                await import('../ui/notifications.js');
            showToast(
                `Observation failed: ${error.message}`,
                'error'
            );
        } finally {
            observeBtn.disabled = false;
            observeBtn.innerHTML = '<i class="bi bi-binoculars"></i>';
        }
    });
}
```

### 3.3 Changes to `SessionsPage.js` — Observation panel in detail modal

**File**: `ui/src/scripts/components/pages/SessionsPage.js`

#### 3.3.1 Extend `_showSessionDetailModal()` with observation display

After the existing session detail fields in the modal content, add an observation summary panel (reusing patterns from `SessionDetailPage._renderObservationPanel()`):

```javascript
// Inside _showSessionDetailModal(), after the main dl content but before
// the footer metadata <div class="mt-3 pt-3 border-top">:

// --- Resource Observation Panel (ADR-030) ---
const canObserve = (session.status || '').toLowerCase() === 'running';
const hasObs = !!session.observed_resources;

let observationHtml = '';
if (hasObs) {
    const obs = session.observed_resources;
    const obsCount = session.observation_count || 0;
    const obsTime = session.observed_at
        ? this._formatDateTime(session.observed_at)
        : '—';
    const driftDetected = session.port_drift_detected || false;

    observationHtml = `
        <hr class="my-3">
        <h6 class="text-muted mb-2">
            <i class="bi bi-binoculars me-1"></i>Resource Observations
            ${driftDetected
                ? '<span class="badge bg-warning text-dark ms-2">⚠️ Drift</span>'
                : ''}
        </h6>
        <div class="small text-muted mb-2">
            ${obsCount} observation${obsCount !== 1 ? 's' : ''} • Last: ${obsTime}
        </div>
        <div class="row g-2 mb-2">
            <div class="col-3 text-center">
                <div class="bg-light rounded p-2">
                    <div class="small text-muted">CPU</div>
                    <div class="fw-bold">${obs.total_cpu_cores ?? '—'}</div>
                </div>
            </div>
            <div class="col-3 text-center">
                <div class="bg-light rounded p-2">
                    <div class="small text-muted">Memory</div>
                    <div class="fw-bold">${
                        obs.total_memory_mb != null
                            ? Math.round((obs.total_memory_mb / 1024) * 10) / 10 + ' GB'
                            : '—'
                    }</div>
                </div>
            </div>
            <div class="col-3 text-center">
                <div class="bg-light rounded p-2">
                    <div class="small text-muted">Nodes</div>
                    <div class="fw-bold">${obs.actual_node_count ?? '—'}</div>
                </div>
            </div>
            <div class="col-3 text-center">
                <div class="bg-light rounded p-2">
                    <div class="small text-muted">Ports</div>
                    <div class="fw-bold">${
                        Object.keys(session.observed_ports || {}).length
                    }</div>
                </div>
            </div>
        </div>
    `;
} else if (canObserve) {
    observationHtml = `
        <hr class="my-3">
        <div class="text-muted small">
            <i class="bi bi-eye-slash me-1"></i>No resource observations yet.
            Click "Observe Resources" to capture live CML resources.
        </div>
    `;
}
```

Insert `${observationHtml}` into the `content.innerHTML` template string.

#### 3.3.2 Add "Observe Resources" button to modal footer

In the modal footer action buttons (the `!isTerminal` branch), add an observe button for RUNNING sessions:

```javascript
const isRunning = (session.status || '').toLowerCase() === 'running';
const observeFooterBtn = isRunning
    ? `<button type="button" class="btn btn-outline-info"
              id="modal-observe-btn"
              title="Observe live CML resources">
           <i class="bi bi-binoculars me-1"></i>Observe
       </button>`
    : '';

// Insert observeFooterBtn into the btn-group alongside dry-run, sync, terminate
```

Wire the handler:

```javascript
footer.querySelector('#modal-observe-btn')?.addEventListener('click', async () => {
    const btn = footer.querySelector('#modal-observe-btn');
    try {
        btn.disabled = true;
        btn.innerHTML =
            '<span class="spinner-border spinner-border-sm me-1"></span>Observing…';
        await labletSessionsApi.requestResourceObservation(session.id);
        showToast(
            'Resource observation requested. Results will appear shortly.',
            'info'
        );
        // Re-open modal after delay to show results
        setTimeout(() => this._showSessionDetailModal(session.id), 3000);
    } catch (err) {
        showToast(`Observation failed: ${err.message}`, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-binoculars me-1"></i>Observe';
        }
    }
});
```

### 3.4 Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| 1 | RUNNING sessions show binoculars icon button in table Actions column | Create running session → table row has observe button |
| 2 | Non-RUNNING sessions do NOT show observe button | PENDING/READY/TERMINATED sessions → no binoculars |
| 3 | Clicking observe button shows spinner, then success toast | Click → spinner → "observation requested" toast |
| 4 | Observe failure shows error toast | Trigger on non-running session via API → error toast |
| 5 | `LabletSessionCard` shows observe button for RUNNING status | Render card with RUNNING session → binoculars button visible |
| 6 | Session detail modal shows observation data when available | Open detail of observed session → CPU/Memory/Nodes/Ports grid |
| 7 | Session detail modal shows "no observations" hint for unobserved RUNNING | Open running session → hint with observe prompt |
| 8 | Session detail modal footer has "Observe" button for RUNNING sessions | Open running session modal → footer has observe button |
| 9 | Drift badge renders in modal when `port_drift_detected` is true | Mock session with drift → ⚠️ badge visible |

---

## 4. Phase 3: Fix Port Definition UX

> **Goal**: Implement the missing JS for dynamic port definition rows in the Create/Edit Definition modal. The HTML skeleton (`#portDefinitionsContainer`, `#addPortDefinition`) exists but has no handlers. Port format follows ADR-029 PortTemplate pattern: `protocol:port` (e.g., `ssh:22`, `http:80`).

### 4.1 Port Row Template

Each port definition row will have:

- **Name** (text): Port name/label (e.g., "ssh", "http", "vnc")
- **Protocol** (select): `tcp` | `udp`
- **Port Number** (number): 1–65535
- **Remove** button (×)

HTML for a single row:

```html
<div class="port-definition-row d-flex gap-2 align-items-center mb-2">
    <input type="text" class="form-control form-control-sm"
           placeholder="Name (e.g., ssh)" style="width: 120px;"
           data-port-field="name" required>
    <select class="form-select form-select-sm" style="width: 90px;"
            data-port-field="protocol">
        <option value="tcp" selected>TCP</option>
        <option value="udp">UDP</option>
    </select>
    <input type="number" class="form-control form-control-sm"
           placeholder="Port" min="1" max="65535" style="width: 100px;"
           data-port-field="port" required>
    <button type="button" class="btn btn-sm btn-outline-danger"
            data-port-action="remove" title="Remove port">
        <i class="bi bi-x-lg"></i>
    </button>
</div>
```

### 4.2 Changes to `lablet-modals.js` — Port definition handlers

**File**: `ui/src/scripts/ui/lablet-modals.js`

#### 4.2.1 Add port row management functions

Add at module level (before the exported functions):

```javascript
// =========================================================================
// Port Definition Helpers
// =========================================================================

/**
 * Create a new port definition row element.
 * @param {Object} [defaults] - Optional defaults {name, protocol, port}
 * @returns {HTMLElement} Port row div
 */
function createPortDefinitionRow(defaults = {}) {
    const row = document.createElement('div');
    row.className = 'port-definition-row d-flex gap-2 align-items-center mb-2';
    row.innerHTML = `
        <input type="text" class="form-control form-control-sm"
               placeholder="Name (e.g., ssh)" style="width: 120px;"
               data-port-field="name" value="${defaults.name || ''}" required>
        <select class="form-select form-select-sm" style="width: 90px;"
                data-port-field="protocol">
            <option value="tcp" ${(defaults.protocol || 'tcp') === 'tcp' ? 'selected' : ''}>TCP</option>
            <option value="udp" ${defaults.protocol === 'udp' ? 'selected' : ''}>UDP</option>
        </select>
        <input type="number" class="form-control form-control-sm"
               placeholder="Port" min="1" max="65535" style="width: 100px;"
               data-port-field="port" value="${defaults.port || ''}" required>
        <button type="button" class="btn btn-sm btn-outline-danger"
                data-port-action="remove" title="Remove port">
            <i class="bi bi-x-lg"></i>
        </button>
    `;

    // Wire remove button
    row.querySelector('[data-port-action="remove"]')
       .addEventListener('click', () => row.remove());

    return row;
}

/**
 * Collect port definitions from the container.
 * @returns {Array<{name: string, protocol: string, port: number}>}
 */
function collectPortDefinitions() {
    const container = document.getElementById('portDefinitionsContainer');
    if (!container) return [];

    const ports = [];
    container.querySelectorAll('.port-definition-row').forEach(row => {
        const name = row.querySelector('[data-port-field="name"]')
                        ?.value?.trim();
        const protocol = row.querySelector('[data-port-field="protocol"]')
                            ?.value || 'tcp';
        const port = parseInt(
            row.querySelector('[data-port-field="port"]')?.value
        );

        if (name && port && port >= 1 && port <= 65535) {
            ports.push({ name, protocol, port });
        }
    });

    return ports;
}

/**
 * Populate port definitions container with existing ports (for edit mode).
 * @param {Array<{name: string, protocol: string, port: number}>} ports
 */
function populatePortDefinitions(ports) {
    const container = document.getElementById('portDefinitionsContainer');
    if (!container) return;

    container.innerHTML = '';
    (ports || []).forEach(p => {
        container.appendChild(createPortDefinitionRow(p));
    });
}

/**
 * Validate port definitions. Returns error message or null.
 * @returns {string|null}
 */
function validatePortDefinitions() {
    const ports = collectPortDefinitions();
    const names = new Set();
    const portNums = new Set();

    for (const p of ports) {
        if (!p.name) return 'Port name is required';
        if (!/^[a-z0-9_-]+$/i.test(p.name))
            return `Invalid port name "${p.name}" — use letters, numbers, hyphens, underscores`;
        if (p.port < 1 || p.port > 65535)
            return `Port number ${p.port} out of range (1–65535)`;
        if (names.has(p.name.toLowerCase()))
            return `Duplicate port name "${p.name}"`;
        if (portNums.has(`${p.protocol}:${p.port}`))
            return `Duplicate port ${p.protocol}:${p.port}`;

        names.add(p.name.toLowerCase());
        portNums.add(`${p.protocol}:${p.port}`);
    }

    return null;
}
```

#### 4.2.2 Wire `#addPortDefinition` button

Inside `setupCreateLabletDefinitionModal()`, after the existing setup:

```javascript
// Port definition add button
const addPortBtn = document.getElementById('addPortDefinition');
const portContainer = document.getElementById('portDefinitionsContainer');
if (addPortBtn && portContainer) {
    addPortBtn.addEventListener('click', () => {
        portContainer.appendChild(createPortDefinitionRow());
    });
}
```

#### 4.2.3 Collect ports in submit handler

In the submit click handler, add port collection and validation:

```javascript
// After gathering other form data but before the API call:

// Collect port definitions
const portValidationError = validatePortDefinitions();
if (portValidationError) {
    showToast(portValidationError, 'error');
    return;
}
const portDefinitions = collectPortDefinitions();

// Add to definitionData
const definitionData = {
    // ... existing fields ...
    port_definitions: portDefinitions.length > 0 ? portDefinitions : null,
};
```

#### 4.2.4 Reset port container on modal close

In the `hidden.bs.modal` handler, add:

```javascript
// Clear port definitions
const portContainer = document.getElementById('portDefinitionsContainer');
if (portContainer) portContainer.innerHTML = '';
```

### 4.3 Changes to `SessionsPage.js` — Populate ports in edit mode

**File**: `ui/src/scripts/components/pages/SessionsPage.js`

In `_editDefinition(definitionId)`, after populating other fields, add:

```javascript
// Populate port definitions for edit mode
// Import populatePortDefinitions or inline:
const portContainer = document.getElementById('portDefinitionsContainer');
if (portContainer) {
    portContainer.innerHTML = '';

    const ports = def.port_template?.ports || def.port_definitions || [];
    ports.forEach(p => {
        const row = document.createElement('div');
        row.className = 'port-definition-row d-flex gap-2 align-items-center mb-2';
        row.innerHTML = `
            <input type="text" class="form-control form-control-sm"
                   placeholder="Name" style="width: 120px;"
                   data-port-field="name" value="${p.name || ''}" required>
            <select class="form-select form-select-sm" style="width: 90px;"
                    data-port-field="protocol">
                <option value="tcp" ${(p.protocol || 'tcp') === 'tcp' ? 'selected' : ''}>TCP</option>
                <option value="udp" ${p.protocol === 'udp' ? 'selected' : ''}>UDP</option>
            </select>
            <input type="number" class="form-control form-control-sm"
                   placeholder="Port" min="1" max="65535" style="width: 100px;"
                   data-port-field="port" value="${p.port || ''}" required>
            <button type="button" class="btn btn-sm btn-outline-danger"
                    data-port-action="remove" title="Remove port">
                <i class="bi bi-x-lg"></i>
            </button>
        `;
        row.querySelector('[data-port-action="remove"]')
           .addEventListener('click', () => row.remove());
        portContainer.appendChild(row);
    });

    // Auto-expand resource toggle if ports exist
    if (ports.length > 0) {
        const resourceToggle = document.getElementById('defResourceToggle');
        const collapseEl = document.getElementById('resourceRequirementsCollapse');
        const defaultsHint = document.getElementById('resourceDefaultsHint');
        if (resourceToggle && collapseEl) {
            resourceToggle.checked = true;
            bootstrap.Collapse.getOrCreateInstance(collapseEl).show();
            if (defaultsHint) defaultsHint.style.display = 'none';
        }
    }
}
```

### 4.4 Changes to `definition-details-renderer.js` — Display ports

**File**: `ui/src/scripts/components/shared/definition-details-renderer.js`

In `renderDefinitionDetailsHtml()`, add port display after the existing Resource Requirements section:

```javascript
// After the Lifecycle section, before Content Synchronization
const portTemplate = def.port_template;
const ports = portTemplate?.ports || def.port_definitions || [];
let portHtml = '';
if (ports.length > 0) {
    const portRows = ports.map(p => `
        <tr>
            <td class="font-monospace">${p.name || '—'}</td>
            <td class="text-center text-uppercase">${p.protocol || 'tcp'}</td>
            <td class="text-center">${p.port || '—'}</td>
        </tr>
    `).join('');

    portHtml = `
        <h6 class="text-muted mb-2 mt-3">
            <i class="bi bi-plug me-1"></i>Port Definitions
            <span class="badge bg-secondary ms-1">${ports.length}</span>
        </h6>
        <div class="table-responsive">
            <table class="table table-sm table-bordered mb-0">
                <thead class="table-light">
                    <tr>
                        <th>Name</th>
                        <th class="text-center">Protocol</th>
                        <th class="text-center">Port</th>
                    </tr>
                </thead>
                <tbody>${portRows}</tbody>
            </table>
        </div>
    `;
}
```

Insert `${portHtml}` into the right column after the Lifecycle `<dl>`.

### 4.5 Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| 1 | "Add Port" button creates a new row with Name, Protocol, Port fields | Click → row appears with empty fields |
| 2 | Remove button (×) removes the specific row | Click × on second row → only that row removed |
| 3 | Submitting definition includes `port_definitions` in payload | Add 2 ports, submit → network request has ports array |
| 4 | Submitting with no ports sends `port_definitions: null` | Don't add ports → payload has null |
| 5 | Duplicate port names are rejected with toast | Add "ssh" twice → error toast "Duplicate port name" |
| 6 | Invalid port numbers are rejected | Enter 0 or 99999 → error toast |
| 7 | Edit mode pre-populates existing port definitions | Edit def with ports → rows pre-filled |
| 8 | Port definitions display in Details modal table | View def with ports → Name/Protocol/Port table |
| 9 | Modal close clears all port rows | Close → reopen → empty container |
| 10 | Resource toggle auto-expands when ports exist in edit mode | Edit def with ports → toggle checked, section expanded |

---

## 5. File Index

All paths relative to `src/control-plane-api/`.

### Modified Files

| File | Phases | Changes |
|------|--------|---------|
| `ui/src/templates/components/lablet_definitions.jinja` | 1, 3 | Wrap resource fields in collapse toggle; move port section inside collapse |
| `ui/src/scripts/ui/lablet-modals.js` | 1, 3 | Respect toggle in submit; add port row CRUD; collect/validate ports |
| `ui/src/scripts/components/pages/SessionsPage.js` | 1, 2 | Auto-expand toggle in edit mode; observe button in table; observation panel in detail modal |
| `ui/src/scripts/components/shared/definition-details-renderer.js` | 1, 3 | Defaults indicator; port definitions table in details |
| `ui/src/scripts/components/sessions/LabletSessionCard.js` | 2 | Observe button for RUNNING sessions |

### No New Files

All changes are modifications to existing files. No new JS modules, components, or templates needed.

### Reference Files (read-only)

| File | Used For |
|------|----------|
| `ui/src/scripts/components/sessions/SessionDetailPage.js` | Pattern reference for observation panel rendering |
| `ui/src/scripts/components/definitions/LabletDefinitionCard.js` | Pattern reference for observation indicators and "Apply Max/Latest" flow |
| `ui/src/scripts/api/lablet-sessions.js` | `requestResourceObservation()` already implemented |

---

## 6. Test Approach

### 6.1 Manual Testing

Each phase has a manual test checklist matching its acceptance criteria table. Run through each criterion in a browser with DevTools open.

**Setup**:

```bash
make build-ui   # Rebuild Parcel frontend
make run         # Start app locally
```

### 6.2 Automated Testing (UI)

The project uses `vitest` for UI component tests (see `lcm_ui/vitest.config.ts`). Port definition helpers can be unit-tested:

| Test | Target |
|------|--------|
| `createPortDefinitionRow()` returns valid DOM | Port helpers |
| `collectPortDefinitions()` extracts data from rows | Port helpers |
| `validatePortDefinitions()` catches duplicates, range errors | Port helpers |
| Toggle collapse show/hide (mock Bootstrap) | Phase 1 toggle |

These can be added to `lcm_ui/tests/` if the test infrastructure supports DOM manipulation (jsdom).

### 6.3 Regression

- Existing definition create/edit workflow still works with toggle collapsed (defaults path)
- Existing session table actions (requeue, terminate) still work
- `SessionDetailPage` "Observe Now" still works (no changes to that component)
- Definition details modal renders correctly for definitions with and without observations

---

_End of implementation plan._
