# @neuroglia/ui-core

Reusable UI foundation library providing core infrastructure for building modern web applications with Web Components.

[![TypeScript](https://img.shields.io/badge/TypeScript-5.3-blue.svg)](https://www.typescriptlang.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## Features

- **EventBus** - Pub/sub event system with wildcards, middleware, and priority-based handlers
- **StateStore** - Centralized state management with slices, computed selectors, and middleware
- **SSEClient** - Server-Sent Events client with auto-reconnect and event buffering
- **SessionManager** - Authentication session lifecycle management
- **Web Components** - Ready-to-use UI components with `ui-*` element prefix
- **Middleware** - Logger, devtools, throttle, debounce, and persist middleware

## Installation

```bash
# From GitHub Packages
npm install @neuroglia/ui-core

# Or link locally during development
npm link ../path/to/lcm_ui
```

## Quick Start

```typescript
import {
  EventBus,
  StateStore,
  SSEClient,
  SessionManager,
  EventTypes
} from '@neuroglia/ui-core';

// 1. Create EventBus singleton
const eventBus = EventBus.getInstance();

// 2. Create StateStore with slices
const store = new StateStore({
  slices: {
    counter: { value: 0 },
    user: { name: '', isLoggedIn: false }
  },
  middleware: [logger(), devtools()],
  maxHistorySize: 50
});

// 3. Subscribe to state changes
store.subscribe((newState, oldState, action) => {
  console.log('State changed:', action.type);
});

// 4. Connect to SSE stream
const sseClient = new SSEClient('/api/events/stream', eventBus, {
  autoReconnect: true,
  eventMap: {
    'worker_status': EventTypes.SSE_MESSAGE,
    'heartbeat': 'sse:heartbeat'
  }
});

// 5. Initialize session manager
const session = new SessionManager(store, eventBus, {
  refreshEndpoint: '/api/auth/refresh',
  inactivityTimeout: 30 * 60 * 1000
});
```

## Modules

### Core (`@neuroglia/ui-core/core`)

The core module contains the foundational infrastructure classes.

```typescript
import { EventBus, StateStore, SSEClient, SSEEventBuffer, EventTypes } from '@neuroglia/ui-core/core';

// EventBus - Pub/Sub with wildcards and priorities
const eventBus = EventBus.getInstance();

// Subscribe with priority (higher = called first)
eventBus.on('worker:*', (data) => console.log('Any worker event:', data), { priority: 10 });
eventBus.on('worker:created', (data) => console.log('Worker created:', data));

// Emit events
await eventBus.emit('worker:created', { id: '123', name: 'Worker 1' });

// Wait for specific event
const data = await eventBus.waitFor('worker:ready', 5000); // 5s timeout

// StateStore - Centralized state management
const store = new StateStore({
  slices: {
    workers: { items: {}, loading: false },
    ui: { theme: 'dark', sidebarOpen: true }
  },
  eventBus, // Emits state:changed events
  maxHistorySize: 100
});

// Dispatch actions
store.dispatch({ type: 'workers/setLoading', payload: true });

// Get state
const workers = store.getSlice('workers');

// Create memoized selectors
const getWorkerById = store.createSelector(
  (state) => state.workers.items[workerId]
);
```

### Session (`@neuroglia/ui-core/session`)

Complete authentication session lifecycle management.

```typescript
import { SessionManager, SessionState, sessionActions, sessionSelectors } from '@neuroglia/ui-core/session';

const sessionManager = new SessionManager({
  store,
  eventBus,
  fetchSession: () => fetch('/api/auth/session').then(r => r.json()),
  refreshSession: () => fetch('/api/auth/refresh', { method: 'POST' }),
  onLogout: () => window.location.href = '/login',
  onExpired: () => showSessionExpiredModal(),
  refreshThreshold: 5 * 60 * 1000,  // Refresh 5 min before expiry
  inactivityTimeout: 30 * 60 * 1000 // Logout after 30 min inactive
});

// Start session management
await sessionManager.start();

// Check authentication
if (sessionManager.isAuthenticated()) {
  const user = sessionManager.getUser();
  console.log(`Logged in as ${user.name}`);
}

// Handle session events
eventBus.on(EventTypes.AUTH_SESSION_EXPIRING, ({ expiresIn }) => {
  showWarning(`Session expires in ${expiresIn} seconds`);
});
```

### Middleware (`@neuroglia/ui-core/middleware`)

```typescript
import {
  createLoggerMiddleware,
  createDevtoolsMiddleware,
  createThrottleMiddleware,
  createDebounceMiddleware,
  createPersistMiddleware
} from '@neuroglia/ui-core/middleware';

const store = new StateStore({
  slices: { ... },
  middleware: [
    // Log all state changes to console
    createLoggerMiddleware({ collapsed: true, colors: true }),

    // Expose store to window.__STORE__ for debugging
    createDevtoolsMiddleware({ name: 'MyApp' }),

    // Throttle rapid updates (max 1 per 100ms)
    createThrottleMiddleware({ wait: 100, slices: ['ui'] }),

    // Debounce search input (wait 300ms after typing stops)
    createDebounceMiddleware({ wait: 300, actionTypes: ['search/setQuery'] }),

    // Persist specific slices to localStorage
    createPersistMiddleware({
      key: 'app-state',
      whitelist: ['user', 'settings'],
      storage: localStorage
    })
  ]
});
```

### Components (`@neuroglia/ui-core/components`)

```typescript
import {
  BaseComponent,
  configureComponents,
  TabView,
  DataTable,
  Modal,
  StatusBadge,
  MetricCard,
  ActionBar
} from '@neuroglia/ui-core/components';

// Configure global EventBus and StateStore for components
configureComponents({ eventBus, store });

// Components auto-register their custom elements
// Use in HTML:
// <ui-tab-view>
// <ui-data-table>
// <ui-modal>
// <ui-status-badge>
// <ui-metric-card>
// <ui-action-bar>
```

## Web Components

| Component | Element | Description |
|-----------|---------|-------------|
| TabView | `<ui-tab-view>` | Tabbed content container with keyboard navigation |
| DataTable | `<ui-data-table>` | Sortable, filterable data table with selection |
| Modal | `<ui-modal>` | Dialog/modal component with confirm/alert helpers |
| ActionBar | `<ui-action-bar>` | Button/action toolbar with dropdown support |
| MetricCard | `<ui-metric-card>` | Metric display card with trend indicators |
| StatusBadge | `<ui-status-badge>` | Status indicator badge with configurable mappings |

### Component Examples

#### DataTable

```html
<ui-data-table
  id="workers-table"
  selectable
  sortable
  paginated
  page-size="10"
></ui-data-table>

<script>
const table = document.getElementById('workers-table');

// Configure columns
table.setColumns([
  { id: 'name', label: 'Name', sortable: true },
  { id: 'status', label: 'Status', render: (val) => `<ui-status-badge status="${val}"></ui-status-badge>` },
  { id: 'cpu', label: 'CPU %', type: 'number', sortable: true }
]);

// Set data
table.setData([
  { id: '1', name: 'Worker 1', status: 'running', cpu: 45 },
  { id: '2', name: 'Worker 2', status: 'stopped', cpu: 0 }
]);

// Listen for events
table.addEventListener('row-click', (e) => console.log('Clicked:', e.detail.row));
table.addEventListener('selection-change', (e) => console.log('Selected:', e.detail.selectedIds));
</script>
```

#### StatusBadge with Custom Mappings

```typescript
import { StatusBadge } from '@neuroglia/ui-core/components';

// Register custom status mappings
StatusBadge.registerMappings({
  'running': { className: 'bg-success', label: 'Running', icon: 'bi-play-fill' },
  'stopped': { className: 'bg-secondary', label: 'Stopped', icon: 'bi-stop-fill' },
  'error': { className: 'bg-danger', label: 'Error', icon: 'bi-exclamation-triangle' }
});
```

```html
<ui-status-badge status="running"></ui-status-badge>
```

#### Modal

```typescript
import { Modal } from '@neuroglia/ui-core/components';

// Show a confirmation dialog
const confirmed = await Modal.confirm({
  title: 'Delete Worker?',
  message: 'This action cannot be undone.',
  confirmText: 'Delete',
  confirmVariant: 'danger'
});

if (confirmed) {
  await deleteWorker(workerId);
}

// Show an alert
await Modal.alert({
  title: 'Success',
  message: 'Worker deleted successfully.',
  variant: 'success'
});
```

## Development

```bash
# Install dependencies
make install

# Build the package
make build

# Run tests
make test

# Run tests with coverage
make test-cov

# Type check
make typecheck

# Lint
make lint

# Full CI pipeline
make ci
```

## Build Outputs

The package produces:

| Output | Size | Description |
|--------|------|-------------|
| `dist/index.esm.js` | 169KB | Full bundle (ES Modules) |
| `dist/index.umd.js` | 191KB | Full bundle (UMD) |
| `dist/core/index.esm.js` | 42KB | Core module only |
| `dist/session/index.esm.js` | 22KB | Session module only |
| `dist/middleware/index.esm.js` | 22KB | Middleware module only |
| `dist/components/index.esm.js` | 83KB | Components module only |
| `dist/types/*.d.ts` | - | TypeScript declarations |

**Tree-shaking**: Import from subpaths to reduce bundle size:

```typescript
// Full bundle (169KB)
import { EventBus, StateStore } from '@neuroglia/ui-core';

// Only core (42KB)
import { EventBus, StateStore } from '@neuroglia/ui-core/core';
```

## Extending for Your Application

### Custom Event Types

```typescript
import { EventTypes as CoreEventTypes } from '@neuroglia/ui-core';

export const EventTypes = {
  ...CoreEventTypes,
  // Add your app-specific events
  WORKER_CREATED: 'worker:created',
  WORKER_UPDATED: 'worker:updated',
  WORKER_DELETED: 'worker:deleted',
  LAB_STARTED: 'lab:started',
  LAB_STOPPED: 'lab:stopped',
} as const;
```

### Custom State Slices

```typescript
import { StateStore } from '@neuroglia/ui-core';

// Define your application state
interface WorkerState {
  items: Record<string, Worker>;
  loading: boolean;
  error: string | null;
}

const store = new StateStore({
  slices: {
    workers: {
      items: {},
      loading: false,
      error: null
    } as WorkerState,
    labs: {
      items: {},
      activeLabId: null
    }
  }
});

// Create typed selectors
const getWorkers = (state) => Object.values(state.workers.items);
const getActiveWorkers = (state) => getWorkers(state).filter(w => w.status === 'running');
```

### Custom SSE Event Mapping

```typescript
import { SSEClient } from '@neuroglia/ui-core';

const sseClient = new SSEClient('/api/events/stream', eventBus, {
  eventMap: {
    // Map SSE event types to your EventBus event types
    'worker_status_changed': 'worker:updated',
    'lab_state_changed': 'lab:updated',
    'metrics_update': 'metrics:received',
    'heartbeat': 'sse:heartbeat'
  },
  autoReconnect: true,
  maxReconnectAttempts: 10,
  heartbeatTimeout: 30000
});
```

## API Reference

See the [TypeScript declarations](./dist/types/) for complete API documentation.

### Core Classes

- **EventBus**: `getInstance()`, `on()`, `once()`, `off()`, `emit()`, `waitFor()`, `use()`
- **StateStore**: `dispatch()`, `getState()`, `getSlice()`, `subscribe()`, `createSelector()`, `batch()`, `gc()`
- **SSEClient**: `connect()`, `disconnect()`, `updateEventMap()`, `getStats()`, `getBuffer()`
- **SSEEventBuffer**: `push()`, `getEvents()`, `clear()`, `getStats()`

### Session

- **SessionManager**: `start()`, `stop()`, `refresh()`, `logout()`, `isAuthenticated()`, `getUser()`
- **sessionActions**: `init()`, `login()`, `logout()`, `update()`, `refreshStart()`, `refreshSuccess()`
- **sessionSelectors**: `isAuthenticated()`, `getUser()`, `isRefreshing()`, `getExpiresAt()`

### Middleware Factories

- `createLoggerMiddleware(options?)`: Log state changes
- `createDevtoolsMiddleware(options?)`: Expose to window for debugging
- `createThrottleMiddleware(options)`: Throttle rapid updates
- `createDebounceMiddleware(options)`: Debounce updates
- `createPersistMiddleware(options)`: Persist to storage

## Development

### Prerequisites

- Node.js >= 18.0.0
- npm >= 9.0.0

### Setup

```bash
# Install dependencies
npm install

# Run tests
npm run test

# Run tests in watch mode
npm run test:watch

# Build package
npm run build

# Type check
npm run typecheck

# Lint
npm run lint
npm run lint:fix
```

### Project Structure

```
src/
├── core/           # EventBus, StateStore, SSEClient, SSEEventBuffer
├── session/        # SessionManager, sessionSlice
├── middleware/     # logger, devtools, throttle, persist
├── components/     # BaseComponent + Web Components
├── types/          # TypeScript type definitions
└── index.ts        # Main entry point
```

## Publishing

### Release Process

1. **Prepare release**: Update CHANGELOG, ensure tests pass
2. **Bump version**: Use one of the following commands:

   ```bash
   npm run release:patch   # 0.1.0 → 0.1.1 (bug fixes)
   npm run release:minor   # 0.1.0 → 0.2.0 (new features)
   npm run release:major   # 0.1.0 → 1.0.0 (breaking changes)
   ```

3. **Create git tag**: The command outputs the tag command to run:

   ```bash
   git add package.json
   git commit -m "chore: release @neuroglia/ui-core v0.1.1"
   git tag ui-core-v0.1.1
   git push origin main --tags
   ```

4. **Automatic publish**: GitHub Actions publishes to GitHub Packages when the tag is pushed

### Manual Publishing

If needed, you can publish manually:

```bash
# Configure npm for GitHub Packages
echo "@neuroglia:registry=https://npm.pkg.github.com" >> .npmrc
echo "//npm.pkg.github.com/:_authToken=YOUR_GITHUB_TOKEN" >> .npmrc

# Build and publish
npm run build
npm publish --access public
```

### Version Tags

- Use `ui-core-v*.*.*` format for tags (e.g., `ui-core-v0.1.1`)
- This distinguishes UI core releases from main application releases

## License

MIT
