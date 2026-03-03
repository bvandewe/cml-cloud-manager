# Frontend Refactoring Plan: Web Components + Pub/Sub Architecture

## Implementation Progress Summary

| Phase | Status | Key Deliverables |
|-------|--------|------------------|
| Phase 1: Foundation | ✅ Complete | EventBus, BaseComponent, SSEService refactor |
| Phase 2: First Components | ✅ Complete | WorkerCard, WorkerList |
| Phase 3: Complex Components | ✅ Complete | WorkerDetailsModal, all core LCM components |
| Phase 4: Migration | 🔄 In Progress | Feature flags, cards views migrated |
| Phase 5: Legacy Cleanup | 🔜 Not Started | Remove feature flags, delete legacy code |

**Overall Progress: ~75% Complete**

**Remaining Work:**

- Create `OverviewPage.js` dashboard (~4-6 hours)
- Create `SystemPage.js` (~3-4 hours)
- Complete Workers table integration (~2-3 hours)
- Remove feature flags and legacy code (~4-6 hours)
- Add component tests (~4-6 hours)

---

## Executive Summary

The current frontend is **unmaintainable** due to:

- 1,104-line monolithic files split across 15+ tightly coupled modules
- 3 separate event systems (SSE custom emitter, store subscriptions, DOM events)
- Manual dependency injection hell (80+ lines of `bindDependencies` calls)
- Global state pollution (4 different `window.*` namespaces)
- Real-time updates trigger full re-renders (300+ line table HTML regeneration per SSE event)
- Zero test coverage due to tight DOM coupling

**Recommendation**: Incremental migration to Web Components + unified EventBus pub/sub pattern.

---

## Current Architecture Problems

### 1. File Structure Chaos

```
workers.js (1,104 lines) - orchestration nightmare
├── worker-sse.js (317 lines) - SSE event handlers
├── worker-render.js (518 lines) - rendering logic
├── worker-labs.js (383 lines) - labs functionality
├── worker-modals.js (?) - modal interactions
├── worker-details.js (?) - details view
├── worker-timing.js (?) - countdown timers
├── worker-init.js (?) - initialization
├── worker-actions.js (?) - start/stop actions
└── worker-jobs.js, worker-monitoring.js, worker-events.js
```

**Problem**: Despite splitting, **coupling remains tight**. Every module needs 5-10 dependencies injected via object literals.

### 2. Dependency Injection Hell

**Current Pattern** (workers.js lines 42-76):

```javascript
bindWorkerDetailsDependencies({
    getCurrentWorkerDetails: () => currentWorkerDetails,
    setCurrentWorkerDetails: v => { currentWorkerDetails = v; },
    setupRefreshButton: () => setupRefreshButton(),
    setupDeleteButtonInDetails: () => setupDeleteButtonInDetails(),
});

initializeWorkersViewCore(user, {
    upsertWorkerSnapshot,
    updateWorkerMetrics,
    updateTiming,
    onLabsTabShouldReload: () => loadLabsTab(),
    subscribe,
    handleStoreUpdate,
    bindRenderDependencies,
    loadWorkers,
    getCurrentWorkerDetails: () => currentWorkerDetails,
    setCurrentWorkerDetails: v => { currentWorkerDetails = v; },
    setUnsubscribe: fn => { unsubscribeStore = fn; },
    showDeleteModal,
    setCurrentRegion: v => { currentRegion = v; },
    getWorkersData: () => workersData,
});
```

**Issues**:

- Brittle - any signature change breaks 5+ files
- No type safety
- Hard to test (need mock all dependencies)
- Impossible to track data flow

### 3. Global State Pollution

```javascript
// In workers.js
let currentUser = null;
let workersData = [];
let currentRegion = 'us-east-1';
let currentWorkerDetails = null;

// Exposed via window
window.workersApp = { /* 15 functions */ };
window.workersUi = window.workersApp;
window.workersInternal = { /* state accessors */ };
window._workersJs = { /* legacy compat */ };
```

**Problem**: 4 different namespaces, no clear ownership. Race conditions possible.

### 4. Triple Event System Nightmare

**System 1: SSE Custom Emitter** (sse-client.js):

```javascript
class SSEClient {
    on(eventType, handler) { /* custom impl */ }
    emit(eventType, data) { /* loops handlers */ }
}
```

**System 2: Store Subscriptions** (workerStore.js):

```javascript
const state = { listeners: new Set() };
function emit() {
    state.listeners.forEach(fn => fn(state));
}
```

**System 3: DOM Events**:

```javascript
filterRegion.addEventListener('change', ...);
workerDetailsModal.addEventListener('hidden.bs.modal', ...);
```

**Result**: Event flow is **impossible to trace**. Debugging requires stepping through 3 different emitters.

### 5. Real-Time Update Inefficiency

**Current Flow** (every SSE event):

```
SSE event → worker-sse.js handler → upsertWorkerSnapshot(data)
→ workerStore.emit() → handleStoreUpdate(state)
→ workersData = getAllWorkers()
→ updateStatistics()  [recalc all averages]
→ renderWorkersTable() [300+ line innerHTML regeneration]
   OR renderWorkersCards() [full card list rebuild]
→ if (modal open) { render all 5 tabs }
```

**Problem**:

- CPU utilization SSE event triggers **full table re-render**
- No granular updates
- No virtual DOM diffing
- Metrics counters reset on every render (timing bugs)

### 6. DOM Manipulation Everywhere

- 50+ `document.getElementById()` calls scattered across files
- 15+ direct `innerHTML` assignments
- No encapsulation - any function can touch any element
- Bootstrap modal coupling (hardcoded IDs)

### 7. Testing Impossibility

**Current Blockers**:

- Tight coupling to DOM (requires full page context)
- Global state mutations
- No dependency injection framework
- Bootstrap modal dependencies
- SSE client is singleton (can't mock)

**Test Coverage**: **0%** (no unit tests exist)

---

## Proposed Architecture: Web Components + EventBus

### High-Level Design

```
┌─────────────────────────────────────────────────────────┐
│              EventBus (Unified Pub/Sub)                  │
│  - Type-safe event contracts (EventTypes constants)     │
│  - Wildcard subscriptions (worker.*)                     │
│  - Middleware support (logging, analytics)               │
│  - Auto-cleanup on component unmount                     │
└──────────────────────┬──────────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼              ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ SSEService  │ │ WorkerStore │ │ APIService  │
│ (singleton) │ │ (singleton) │ │ (singleton) │
└──────┬──────┘ └──────┬──────┘ └──────┬──────┘
       │               │               │
       └───────────────┴───────────────┘
                       │
         ┌─────────────┼─────────────────────┐
         ▼             ▼                      ▼
  ┌─────────────┐ ┌─────────────┐  ┌──────────────────┐
  │ <worker-    │ │ <worker-    │  │ <worker-details- │
  │  list>      │ │  card>      │  │  modal>          │
  └─────────────┘ └─────────────┘  └──────────────────┘
         │             │                      │
         ├── <worker-card> (many)             │
         └── <filter-bar>                     ├── <labs-panel>
                                              ├── <metrics-chart>
                                              ├── <license-manager>
                                              └── <events-log>
```

### Core Principles

1. **Single Event System**: EventBus replaces all 3 current systems
2. **Encapsulation**: Each component owns its DOM (Shadow DOM)
3. **Reactive**: Components subscribe to relevant events only
4. **Testable**: Pure functions, mockable dependencies
5. **Incremental**: Migrate one component at a time

---

## Implementation Guide

### Phase 1: Foundation (Week 1)

**Create Core Infrastructure**:

✅ **1. EventBus** (`src/ui/src/scripts/core/EventBus.js`) - DONE

- Singleton pub/sub with wildcard support
- Type-safe event constants (50+ EventTypes defined)
- Middleware hooks for logging

✅ **2. BaseComponent** (`src/ui/src/scripts/core/BaseComponent.js`) - DONE

- Base class for all web components
- Auto-cleanup subscriptions on unmount
- State management helpers
- Lifecycle hooks (onMount, onUnmount, onAttributeChange, onStateChange)
- Utility methods (debounce, throttle, $, $$)

✅ **3. SSEService Refactor** (`src/ui/src/scripts/services/SSEService.js`) - DONE

- Removed custom event emitter
- Publishes directly to EventBus (50+ SSE event types mapped)
- Singleton pattern maintained
- Exponential backoff reconnection
- Graceful shutdown handling

✅ **4. WorkerStore Integration** - DONE (via SSEService)

- SSEService now publishes all worker events to EventBus
- Components subscribe directly to EventBus
- Legacy store subscriptions still work for backward compatibility

✅ **5. Testing Setup** - PARTIALLY DONE

- Parcel build configured
- Component structure supports testing
- TODO: Add @web/test-runner configuration

### Phase 2: First Components (Week 2)

**Priority 1: Worker Card Component**

✅ **Created** (`src/ui/src/scripts/components/WorkerCard.js`) - DONE (376 lines)

**Features**:

- Self-contained rendering (Light DOM for Bootstrap integration)
- Subscribes to `WORKER_SNAPSHOT`, `WORKER_METRICS_UPDATED`, `WORKER_STATUS_CHANGED`
- Reactive state updates via BaseComponent.setState()
- Compact and full card variants
- Tooltip support for metrics

**Priority 2: Worker List Component**

✅ **Created** (`src/ui/src/scripts/components/WorkerList.js`) - DONE (503 lines)

**Features**:

- Collection management with Map-based worker storage
- Filtering by region, status, search term
- Real-time SSE updates with race condition prevention
- Debounced rendering for performance
- Cards and table view support

### Phase 3: Complex Components (Week 3)

**Worker Details Modal Component**

✅ **Created** (`src/ui/src/scripts/components/WorkerDetailsModal.js`) - DONE

**Features**:

- Horizontal tabs (AWS, CML, Labs, Monitoring, Events)
- Subscribes to worker snapshot updates
- Lab management operations
- License management panel
- Real-time metrics display

**Additional Domain Components** - ALL DONE:

- ✅ `WorkersApp.js` - Workers page controller with SSE management
- ✅ `StatisticsPanel.js` - Statistics summary panel
- ✅ `FilterBar.js` - Filter toolbar component
- ✅ `LabletInstanceCard.js` - Lablet instance card component
- ✅ `LabletInstanceList.js` - Lablet instance list component
- ✅ `LabletDefinitionCard.js` - Lablet definition card component
- ✅ `LabletDefinitionList.js` - Lablet definition list component

**Core Reusable Components** - ALL DONE:

- ✅ `LcmTabView.js` - Tabbed container with variants
- ✅ `LcmDataTable.js` - Data table with sort/filter/pagination
- ✅ `LcmMetricCard.js` - Metric display cards
- ✅ `LcmActionBar.js` - Toolbar with actions
- ✅ `LcmUserMenu.js` - User profile dropdown
- ✅ `LcmStatusBadge.js` - Status badges
- ✅ `LcmModal.js` - Modal dialogs
- ✅ `LcmGrafanaPanel.js` - Grafana panel embedding

### Phase 4: Migration Strategy (Weeks 4-5)

**Incremental Replacement** - IN PROGRESS:

1. ✅ **Keep existing code running** - dual mode via feature flags
2. ✅ **Workers cards view** - Replaced with `<worker-list>` and `<worker-card>`
3. ✅ **Lablets page** - Full page component with `<lablets-page>`
4. 🔄 **Workers table view** - Partially integrated
5. 🔜 **Overview dashboard** - Not started
6. 🔜 **System page** - Not started

**Feature Flags** - IMPLEMENTED:

```javascript
const USE_WEB_COMPONENTS = localStorage.getItem('use-web-components') === 'true';

if (USE_WEB_COMPONENTS) {
    // New implementation
    document.querySelector('#workers-container').innerHTML = `
        <worker-list region="${currentRegion}"></worker-list>
    `;
} else {
    // Legacy implementation
    renderWorkersCards();
}
```

**Compatibility Shim**:

```javascript
// workers.js (legacy) can emit to EventBus
import { eventBus, EventTypes } from './core/EventBus.js';

function handleStoreUpdate(storeState) {
    // ... existing logic ...

    // Also emit to EventBus for new components
    eventBus.emit(EventTypes.WORKER_UPDATED, { workers: workersData });
}
```

### Phase 5: Complete Migration (Week 6) - 🔜 NOT STARTED

**Remove Legacy Code**:

1. Delete `workers.js`, `worker-render.js`, `worker-sse.js`, etc.
2. Remove global `window.workersApp` namespace
3. Refactor store to pure EventBus publisher
4. Update templates to use web components only

**Current Final Structure**:

```
src/ui/src/scripts/
├── core/
│   ├── EventBus.js         ✅ (created - 50+ event types)
│   └── BaseComponent.js    ✅ (created - 254 lines)
├── services/
│   ├── SSEService.js       ✅ (refactored - 335 lines, EventBus integration)
│   ├── PrometheusClient.js ✅ (created - Prometheus API queries)
│   ├── session-manager.js  ✅ (exists)
│   ├── connection-indicator.js ✅ (exists)
│   └── theme.js            ✅ (exists)
├── store/
│   └── workerStore.js      🔄 (legacy - needs EventBus migration)
├── components/
│   ├── core/               ✅ ALL DONE
│   │   ├── LcmTabView.js
│   │   ├── LcmDataTable.js
│   │   ├── LcmMetricCard.js
│   │   ├── LcmGrafanaPanel.js
│   │   ├── LcmActionBar.js
│   │   ├── LcmUserMenu.js
│   │   ├── LcmStatusBadge.js
│   │   ├── LcmModal.js
│   │   └── index.js
│   ├── pages/              🔄 IN PROGRESS
│   │   ├── LabletsPage.js  ✅ (639 lines)
│   │   ├── WorkersPage.js  ✅ (created)
│   │   ├── OverviewPage.js 🔜 (TODO)
│   │   ├── SystemPage.js   🔜 (TODO)
│   │   └── index.js
│   ├── WorkerCard.js       ✅ (376 lines)
│   ├── WorkerList.js       ✅ (503 lines)
│   ├── WorkerDetailsModal.js ✅ (created)
│   ├── WorkersApp.js       ✅ (created)
│   ├── StatisticsPanel.js  ✅ (created)
│   ├── FilterBar.js        ✅ (created)
│   ├── LabletInstanceCard.js ✅ (created)
│   ├── LabletInstanceList.js ✅ (created)
│   ├── LabletDefinitionCard.js ✅ (created)
│   ├── LabletDefinitionList.js ✅ (created)
│   └── ... (legacy files to be removed)
├── api/                    ✅ (unchanged - pure functions)
├── ui/                     ✅ (unchanged - utilities)
└── utils/                  ✅ (unchanged - pure functions)
```

---

## Benefits of New Architecture

### 1. **Maintainability**

- **Before**: 1,104-line files, 80+ line dependency injection
- **After**: 200-300 line components, zero manual DI

### 2. **Testability**

- **Before**: 0% test coverage, untestable due to tight coupling
- **After**: 80%+ coverage, each component tested in isolation

### 3. **Performance**

- **Before**: Full table re-render on every SSE event (300+ lines HTML)
- **After**: Granular updates - only affected components re-render

**Example**:

```
Before: CPU metric update → 300ms full table rebuild
After:  CPU metric update → 5ms single card shadow DOM patch
```

### 4. **Real-Time Updates**

- **Before**: Events flow through 3 systems (SSE→Store→Render)
- **After**: Direct EventBus flow (SSE→EventBus→Component)

**Traceability**:

```javascript
// Enable debug mode
eventBus.enableDebug();

// Output:
// [EventBus] worker.metrics.updated { worker_id: 'abc', cpu: 45.2 }
// → WorkerCard(abc) updated
// → StatisticsPanel recalculated
```

### 5. **Developer Experience**

- **Before**: 15+ file changes for simple feature
- **After**: Edit single component file

**Example** - Add disk metrics display:

```javascript
// Before: Touch workers.js, worker-render.js, worker-sse.js, workerStore.js
// After: Edit WorkerCard.js only

// In WorkerCard.js renderFullCard():
<div class="metric-row">
    <span>Disk</span>
    <span>${worker.storage_utilization?.toFixed(1)}%</span>
</div>
```

### 6. **Debugging**

- **Before**: Set 10+ breakpoints across files
- **After**: EventBus middleware logs all events

```javascript
// Add logging middleware
eventBus.use(async (eventType, data) => {
    console.log(`[Event] ${eventType}`, data);
    // Could also send to analytics, Sentry, etc.
});
```

---

## Migration Risks & Mitigation

### Risk 1: Breaking Existing Functionality

**Mitigation**:

- Feature flags (dual mode during migration)
- Comprehensive manual testing before removal
- Rollback plan (keep legacy code for 1 sprint)

### Risk 2: Learning Curve

**Mitigation**:

- Document Web Components API
- Provide migration examples for each pattern
- Pair programming sessions

### Risk 3: Browser Compatibility

**Mitigation**:

- Web Components supported in all modern browsers (Chrome 67+, Firefox 63+, Safari 12.1+)
- Polyfills available if needed (`@webcomponents/webcomponentsjs`)

### Risk 4: Performance Regression

**Mitigation**:

- Benchmark before/after
- Profile SSE event → render latency
- Add performance monitoring

---

## Success Metrics

1. **Code Metrics**:
   - Lines of code: 5,000+ → 3,000 (40% reduction)
   - Average file size: 500+ → 200 lines (60% reduction)
   - Dependency graph depth: 5+ levels → 2 levels (60% reduction)

2. **Performance**:
   - SSE event → render: 300ms → <50ms (6x faster)
   - Initial page load: Track metrics before/after

3. **Developer Velocity**:
   - Time to add feature: 2-3 days → 4-6 hours (75% faster)
   - Files touched per feature: 5-10 → 1-2 (80% reduction)

4. **Quality**:
   - Test coverage: 0% → 80%+
   - Production bugs: Establish baseline → track reduction

---

## Conclusion

The current frontend **refactoring is ~75% complete**. The major architectural improvements have been implemented:

**Completed:**
✅ Unified EventBus replaces 3 fragmented event systems
✅ BaseComponent provides consistent lifecycle management
✅ SSEService refactored to publish to EventBus
✅ All core reusable components created (LcmTabView, LcmDataTable, LcmModal, etc.)
✅ All domain components created (WorkerCard, WorkerList, LabletInstanceCard, etc.)
✅ LabletsPage and WorkersPage implemented as page-level components
✅ Feature flag system enables gradual rollout

**Remaining:**
🔜 Create OverviewPage.js dashboard
🔜 Create SystemPage.js (monitoring + settings)
🔜 Complete Workers table view integration
🔜 Remove feature flags (enable Web Components by default)
🔜 Delete legacy code (worker-*.js files, window.workersApp)
🔜 Add component tests with @web/test-runner

**Timeline**: Estimated 2-3 additional weeks for complete migration with testing.
**Risk**: Low - feature flags enable safe dual-mode operation during transition.

**Next Steps**:

1. Create OverviewPage.js with metrics dashboard
2. Create SystemPage.js with monitoring/settings tabs
3. Complete Workers table integration with LcmDataTable
4. Enable Web Components by default (remove feature flags)
5. Delete legacy code and clean up unused files
6. Add comprehensive component tests
