# UI Refactoring Plan: Tabbed Navigation Architecture

## Progress Summary

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1: Core Infrastructure | ✅ Complete | EventBus, BaseComponent, SSEService refactor |
| Phase 2: Core Components | ✅ Complete | LcmTabView, LcmDataTable, LcmModal, LcmStatusBadge, etc. |
| Phase 3: Navigation Refactor | ✅ Complete | Tabbed navbar, LcmUserMenu, routing |
| Phase 4: Domain Components | ✅ Complete | WorkerCard, WorkerList, LabletInstanceCard, etc. |
| Phase 5: Page-Level Components | ✅ Complete | LabletsPage, WorkersPage, OverviewPage, SystemPage |
| Phase 6: Data Table Integration | 🔄 In Progress | Cards views done, table views partial |
| Phase 7: Observability | ✅ Complete | Grafana panels, Prometheus client |
| Phase 8: Overview Dashboard | ✅ Complete | Dashboard with aggregated metrics via OverviewPage |
| Phase 9: Legacy Code Removal | ✅ Complete | Feature flags removed, legacy files deleted |

**Overall Progress: ~95% Complete**

### Completed (Latest Session)

1. **OverviewPage.js** - Created dashboard page with:
   - Worker metrics cards (total, running, stopped, avg CPU)
   - Lablet metrics cards (total, running, scheduled, avg memory)
   - Grafana panel integration with time range selector
   - System status badges (Control Plane API, Prometheus, SSE)
   - Quick action buttons for admins

2. **SystemPage.js** - Created system admin page with:
   - Monitoring tab: System health, SSE connection, worker monitoring, controller status
   - Settings tab: Worker provisioning, monitoring config, idle detection, discovery settings

3. **Feature Flags Removed**:
   - `use-page-components` localStorage check removed from `app.js` and `WorkersApp.js`
   - Page components are now always used (no fallback to legacy)

4. **Legacy Files Deleted**:
   - `ui/lablet-instances.js` - Replaced by LabletsPage component
   - `ui/lablet-definitions.js` - Replaced by LabletsPage component
   - `ui/system.js` - Replaced by SystemPage component
   - `ui/settings.js` - Replaced by SystemPage component
   - Old Parcel build artifacts cleaned from `static/`

### Remaining Tasks (Low Priority)

| Task | Effort | Priority |
|------|--------|----------|
| Refactor workerStore.js to EventBus | 2-3h | Low |
| Add component tests with @web/test-runner | 4-6h | Low |
| Mobile responsive testing | 1-2h | Low |

---

## Overview

Refactor the Lablet Cloud Manager UI to a modern tabbed navigation architecture with reusable Web Components.

## Target Architecture

### Navigation Structure

```
┌─────────────────────────────────────────────────────────────────────┐
│ Lablet Cloud Manager    [Overview][Lablets][Workers][System]   👤 ▼ │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  [Current Tab Content]                                              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Main Navigation (Pill-Tabs)

| Tab | Sub-Tabs | Description |
|-----|----------|-------------|
| **Overview** | Today \| This Week \| This Month | Dashboard with metrics cards and trend charts |
| **Lablets** | Instances \| Definitions | Data tables with CRUD operations |
| **Workers** | Instances \| Templates | Data tables with CRUD operations |
| **System** | Monitoring \| Settings | System health and configuration |

### User Profile Dropdown

- **Preferences**: Theme, notifications, display settings
- **Logout**: End session

## Reusable Web Components

### Core Components (Candidates for Neuroglia Framework)

| Component | Tag | Description |
|-----------|-----|-------------|
| `LcmTabView` | `<lcm-tab-view>` | Generic tabbed container with pill/underline variants |
| `LcmDataTable` | `<lcm-data-table>` | Interactive data table with filtering/sorting/pagination |
| `LcmMetricCard` | `<lcm-metric-card>` | Statistic card with icon, value, trend indicator |
| `LcmTrendChart` | `<lcm-trend-chart>` | Simple line/bar chart for time series |
| `LcmActionBar` | `<lcm-action-bar>` | Toolbar with bulk actions, search, filters |
| `LcmUserMenu` | `<lcm-user-menu>` | User profile dropdown with avatar |
| `LcmStatusBadge` | `<lcm-status-badge>` | Colored badge for entity status |
| `LcmModal` | `<lcm-modal>` | Reusable modal dialog |
| `LcmToast` | `<lcm-toast>` | Toast notification component |

### Domain-Specific Components

| Component | Tag | Description |
|-----------|-----|-------------|
| `WorkerInstanceRow` | `<worker-instance-row>` | Table row for worker instance |
| `WorkerTemplateRow` | `<worker-template-row>` | Table row for worker template |
| `LabletInstanceRow` | `<lablet-instance-row>` | Table row for lablet instance |
| `LabletDefinitionRow` | `<lablet-definition-row>` | Table row for lablet definition |

## Component API Design

### LcmTabView

```html
<lcm-tab-view variant="pills" position="nav">
  <lcm-tab id="overview" label="Overview" icon="bi-speedometer2" active></lcm-tab>
  <lcm-tab id="lablets" label="Lablets" icon="bi-collection"></lcm-tab>
  <lcm-tab id="workers" label="Workers" icon="bi-server"></lcm-tab>
  <lcm-tab id="system" label="System" icon="bi-gear"></lcm-tab>
</lcm-tab-view>
```

**Attributes:**

- `variant`: `pills` | `underline` | `buttons`
- `position`: `nav` (navbar) | `content` (within page)
- `persist-key`: LocalStorage key for remembering active tab

**Events:**

- `tab-change`: `{ tabId, previousTabId }`

### LcmDataTable

```html
<lcm-data-table
  id="workers-table"
  data-source="/api/workers"
  columns='[{"field":"name","label":"Name","sortable":true}]'
  page-size="25"
  selectable="true"
  actions='["edit","delete","start","stop"]'
>
</lcm-data-table>
```

**Attributes:**

- `data-source`: API endpoint or data array
- `columns`: JSON column configuration
- `page-size`: Items per page (10, 25, 50, 100)
- `selectable`: Enable row selection
- `actions`: Available row actions
- `bulk-actions`: Available bulk actions

**Events:**

- `row-action`: `{ action, row }`
- `bulk-action`: `{ action, selectedRows }`
- `selection-change`: `{ selectedIds }`
- `page-change`: `{ page, pageSize }`
- `sort-change`: `{ field, direction }`
- `filter-change`: `{ filters }`

### LcmMetricCard

```html
<lcm-metric-card
  title="Total Workers"
  value="24"
  icon="bi-server"
  color="primary"
  trend="up"
  trend-value="+12%"
>
</lcm-metric-card>
```

**Attributes:**

- `title`: Card title
- `value`: Main metric value
- `icon`: Bootstrap icon class
- `color`: `primary` | `success` | `warning` | `danger` | `info`
- `trend`: `up` | `down` | `flat`
- `trend-value`: Trend percentage
- `link`: Optional click destination

### LcmUserMenu

```html
<lcm-user-menu
  user-name="John Doe"
  user-email="john@example.com"
  avatar-url="/api/users/me/avatar"
>
  <lcm-menu-item icon="bi-gear" action="preferences">Preferences</lcm-menu-item>
  <lcm-menu-divider></lcm-menu-divider>
  <lcm-menu-item icon="bi-box-arrow-right" action="logout">Logout</lcm-menu-item>
</lcm-user-menu>
```

## Implementation Phases

### Phase 1: Core Infrastructure ✅ COMPLETE

- [x] Create component directory structure
- [x] Define `BaseComponent` with lifecycle hooks (`core/BaseComponent.js`)
- [x] Set up `EventBus` for component communication (`core/EventBus.js`)
- [x] Refactor `SSEService` to publish to EventBus (`services/SSEService.js`)
- [x] Define comprehensive `EventTypes` constants (50+ event types)

### Phase 2: Core Components ✅ COMPLETE

- [x] `LcmTabView` and `LcmTab` components - Tabbed container with pills/underline/button variants
- [x] `LcmUserMenu` component - User profile dropdown with avatar/initials
- [x] `LcmStatusBadge` component - Colored status badges with 30+ status mappings
- [x] `LcmModal` and `LcmConfirmModal` components - Modal dialogs with promise API
- [x] `LcmMetricCard` component - Metric display cards with trend indicators
- [x] `LcmDataTable` component - Full data table with pagination/sorting/filtering
- [x] `LcmActionBar`, `LcmFilterChip`, `LcmDropdownAction` - Toolbar components
- [x] `LcmGrafanaPanel` component - Grafana panel embedding
- [x] `components/core/index.js` - Component registry and exports

### Phase 3: Navigation Refactor ✅ COMPLETE

- [x] Create `navbar_tabbed.jinja` with new pill-tab structure
- [x] Add LcmUserMenu component integration
- [x] Update `index.jinja` to use new navbar (feature-flagged)
- [x] Update `app.js` for new navigation routing with dropdown menus
- [x] Update `auth.js` to configure LcmUserMenu on login
- [ ] Test responsive mobile behavior

### Phase 4: Domain Components ✅ COMPLETE

- [x] `WorkerCard.js` - Self-contained worker card with reactive EventBus updates (376 lines)
- [x] `WorkerList.js` - Worker collection with filtering, sorting, real-time updates (503 lines)
- [x] `WorkerDetailsModal.js` - Modal with horizontal tabs (AWS, CML, Labs, Monitoring, Events)
- [x] `WorkersApp.js` - Workers page controller with SSE management
- [x] `StatisticsPanel.js` - Statistics summary panel
- [x] `FilterBar.js` - Filter toolbar component
- [x] `LabletInstanceCard.js` - Lablet instance card component
- [x] `LabletInstanceList.js` - Lablet instance list component
- [x] `LabletDefinitionCard.js` - Lablet definition card component
- [x] `LabletDefinitionList.js` - Lablet definition list component

### Phase 5: Page-Level Components 🔄 IN PROGRESS

- [x] `LabletsPage.js` - Full page implementation with tabs (Instances/Definitions) (639 lines)
- [x] `WorkersPage.js` - Page wrapper for workers view
- [ ] `OverviewPage.js` - Dashboard with metrics cards and trend charts
- [ ] `SystemPage.js` - Monitoring + Settings sub-tabs
- [x] Feature flag support via `use-page-components` localStorage key
- [x] `app.js` integration with `initializeLabletsPage()` function

### Phase 6: Data Table Integration 🔄 IN PROGRESS

- [x] `LcmDataTable` with sorting/filtering/pagination (DONE)
- [x] `LcmActionBar` for bulk actions (DONE)
- [x] Row selection and bulk operations (DONE)
- [x] Workers cards view fully integrated with Web Components
- [x] Lablets cards/table view integrated in LabletsPage
- [ ] Complete Workers table view with LcmDataTable
- [ ] Add bulk operations to Workers/Lablets views

### Phase 7: Observability Components ✅ COMPLETE

- [x] `LcmMetricCard` component (DONE)
- [x] `LcmGrafanaPanel` and `LcmGrafanaDashboard` - Grafana embedding
- [x] `PrometheusClient` service - Direct Prometheus queries with graceful fallback
- [ ] `LcmTrendChart` with Chart.js integration (optional - using Grafana instead)

### Phase 8: Overview Dashboard 🔜 NOT STARTED

- [ ] Prometheus/Grafana integration planning
- [ ] Aggregate metrics implementation
- [ ] Trend chart data sources
- [ ] OverviewPage.js component implementation

### Phase 9: Legacy Code Removal 🔜 NOT STARTED

- [ ] Remove feature flag checks (enable Web Components by default)
- [ ] Delete legacy worker-*.js files (worker-sse.js, worker-render.js, etc.)
- [ ] Remove `window.workersApp` global namespace
- [ ] Clean up unused store subscriptions
- [ ] Update documentation

## File Structure (Current)

```
ui/src/
├── scripts/
│   ├── core/                        # Foundation (✅ COMPLETE)
│   │   ├── BaseComponent.js         # Base class with lifecycle, EventBus, state
│   │   └── EventBus.js              # Unified pub/sub with 50+ EventTypes
│   │
│   ├── components/
│   │   ├── core/                    # Reusable core components (✅ COMPLETE)
│   │   │   ├── LcmTabView.js
│   │   │   ├── LcmDataTable.js
│   │   │   ├── LcmMetricCard.js
│   │   │   ├── LcmGrafanaPanel.js
│   │   │   ├── LcmActionBar.js
│   │   │   ├── LcmUserMenu.js
│   │   │   ├── LcmStatusBadge.js
│   │   │   ├── LcmModal.js
│   │   │   └── index.js             # Component registry
│   │   │
│   │   ├── pages/                   # Page-level components (🔄 IN PROGRESS)
│   │   │   ├── LabletsPage.js       # ✅ Instances + Definitions tabs
│   │   │   ├── WorkersPage.js       # ✅ Workers page wrapper
│   │   │   ├── OverviewPage.js      # 🔜 Dashboard (TODO)
│   │   │   ├── SystemPage.js        # 🔜 Monitoring + Settings (TODO)
│   │   │   └── index.js
│   │   │
│   │   ├── WorkerCard.js            # ✅ Worker card component
│   │   ├── WorkerList.js            # ✅ Worker list with filtering
│   │   ├── WorkerDetailsModal.js    # ✅ Worker details modal
│   │   ├── WorkersApp.js            # ✅ Workers page controller
│   │   ├── StatisticsPanel.js       # ✅ Statistics panel
│   │   ├── FilterBar.js             # ✅ Filter toolbar
│   │   ├── LabletInstanceCard.js    # ✅ Lablet instance card
│   │   ├── LabletInstanceList.js    # ✅ Lablet instance list
│   │   ├── LabletDefinitionCard.js  # ✅ Lablet definition card
│   │   ├── LabletDefinitionList.js  # ✅ Lablet definition list
│   │   └── ... (legacy components)
│   │
│   ├── services/                    # Singleton services (✅ COMPLETE)
│   │   ├── SSEService.js            # SSE → EventBus integration
│   │   ├── PrometheusClient.js      # Prometheus API queries
│   │   ├── session-manager.js
│   │   ├── connection-indicator.js
│   │   └── theme.js
│   │
│   ├── store/                       # State management
│   │   └── workerStore.js           # Worker state (to be EventBus-ified)
│   │
│   ├── api/                         # API client modules
│   │   ├── client.js
│   │   ├── workers.js
│   │   └── lablets.js
│   │
│   ├── ui/                          # UI utilities
│   │   ├── auth.js
│   │   ├── notifications.js
│   │   └── ...
│   │
│   ├── utils/                       # Pure utility functions
│   │   └── dates.js
│   │
│   └── app.js                       # Entry point with feature flags
│
└── templates/
    ├── index.jinja                  # Main layout
    └── partials/
        └── navbar_tabbed.jinja      # Tabbed navigation
```

## SSE Integration

All components subscribe to SSE events via EventBus:

```javascript
// In LcmDataTable
this.subscribe(EventTypes.WORKER_CREATED, (data) => {
  this.addRow(data);
});

this.subscribe(EventTypes.WORKER_STATUS_CHANGED, (data) => {
  this.updateRow(data.worker_id, { status: data.status });
});
```

## Styling Strategy

- Use Bootstrap 5 CSS utilities where possible
- Component-scoped styles for customization
- CSS custom properties for theming
- Dark mode support via `data-bs-theme` attribute

## Migration Strategy

1. **Parallel implementation**: Build new components alongside existing
2. **Feature flag**: Enable new UI via `APP_CONFIG.useNewUI`
3. **Gradual rollout**: Replace one page at a time
4. **Backward compatibility**: Keep legacy views until fully tested

## Open Questions — RESOLVED

### 1. Overview Metrics

**Decision**: Pull from Prometheus directly with graceful error handling.

- Create `LcmPrometheusClient` service for querying Prometheus API
- Components display "Unavailable" state when Prometheus is down
- Use PromQL queries for aggregated metrics

### 2. Chart Library

**Decision**: Integrate Grafana panels via iframe embedding.

- Create `LcmGrafanaPanel` component for generic panel embedding
- Support dashboard-uid + panel-id configuration
- Pass time range, variables, and theme
- Add to core components library for reuse

### 3. Neuroglia Framework Promotion

**Decision**: Defer until components are production-ready.

- Components must be clean, well-documented, and fully flexible
- Evaluate after LCM UI is complete and battle-tested
- Candidates: LcmTabView, LcmDataTable, LcmModal, LcmStatusBadge, LcmGrafanaPanel

---

## Next Steps (Prioritized)

### Immediate Tasks (Phase 5-6 Completion)

1. **Create `OverviewPage.js`** - Dashboard page with:
   - Aggregate metrics cards (total workers, running lablets, etc.)
   - Grafana panels for trend visualization
   - Quick action buttons (create worker, create lablet)

2. **Create `SystemPage.js`** - System admin page with:
   - Monitoring sub-tab: Health checks, logs, SSE status
   - Settings sub-tab: Configuration management (existing settings.js)

3. **Complete Workers table view** - Wire up LcmDataTable:
   - Define column configuration for workers
   - Add bulk operations (start, stop, terminate)
   - Integrate with existing WorkersPage

### Short-term Tasks (Phase 8-9)

1. **Remove feature flags** - Enable Web Components by default:
   - Remove `use-page-components` localStorage check
   - Remove `USE_WEB_COMPONENTS` conditionals
   - Update documentation

2. **Clean up legacy code**:
   - Delete `worker-sse.js`, `worker-render.js`, `worker-labs.js`, etc.
   - Remove `window.workersApp` global namespace
   - Remove unused store subscriptions from `workerStore.js`
   - Update main entry point to only use Web Components

3. **Refactor `workerStore.js`** to pure EventBus publisher:
   - Remove custom subscription system
   - Publish state changes to EventBus
   - Components subscribe directly to EventBus events

### Testing & Documentation

1. **Add component tests**:
   - Set up `@web/test-runner` with Playwright
   - Write unit tests for core components (EventBus, BaseComponent)
   - Write integration tests for domain components (WorkerCard, WorkerList)

2. **Test responsive mobile behavior**:
   - Verify navbar collapse on mobile
   - Test touch interactions for modals and tables
   - Ensure cards stack properly on small screens

3. **Update documentation**:
   - Document component APIs and usage examples
   - Create migration guide for legacy code
   - Update README with new architecture overview

---

## Estimated Remaining Effort

| Task | Effort | Priority |
|------|--------|----------|
| OverviewPage.js | 4-6 hours | High |
| SystemPage.js | 3-4 hours | High |
| Workers table integration | 2-3 hours | Medium |
| Remove feature flags | 1-2 hours | Medium |
| Legacy code cleanup | 3-4 hours | Low |
| workerStore refactor | 2-3 hours | Low |
| Component tests | 4-6 hours | Low |
| Mobile testing | 1-2 hours | Low |
| Documentation | 2-3 hours | Low |

**Total estimated: ~25-35 hours to complete refactoring**
