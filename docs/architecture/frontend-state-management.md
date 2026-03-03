# Frontend State Management Architecture

> **Status**: Design Phase (Refined)
> **Created**: 2026-01-20
> **Updated**: 2026-01-20
> **Authors**: AI-assisted design session
> **Related Documents**:
>
> - [UI Modularization Architecture](./ui-modularization.md) - Package structure, build, publish
> - [Memory & Session Management](./ui-modularization.md#part-1-memory-management--immutable-state) - Memory safety, session handling

## Overview

This document outlines a **production-grade** state management architecture with clear separation between:

1. **Generic Core** (`@neuroglia/ui-core`) - Framework-agnostic, reusable classes
2. **LCM Application Layer** - Domain-specific stores, actions, and integrations

The architecture provides: centralized state, real-time SSE updates, computed selectors, middleware pipeline, devtools integration, and type-safe event contracts.

## Design Principles

| Principle | Description |
|-----------|-------------|
| **Framework Agnostic** | Core classes work with vanilla JS, Web Components, React, Vue, etc. |
| **Separation of Concerns** | Generic core vs application-specific implementations |
| **Immutable State** | All state updates create new objects (spread operator) |
| **Unidirectional Data Flow** | Actions → Middleware → Reducers → State → Subscribers |
| **Observable Everything** | State changes, events, and connections are all observable |
| **Memory Safe** | All subscriptions return cleanup functions |
| **Debuggable** | Built-in devtools, time-travel debugging, event logging |

### Why Immutable State?

The immutable state pattern (creating new objects via spread operator) is used for several important reasons:

| Benefit | Explanation |
|---------|-------------|
| **Change Detection** | Shallow equality (`===`) is O(1) vs deep comparison O(n). Components can quickly determine if re-render is needed. |
| **Time-Travel Debugging** | Each state snapshot is independent, enabling undo/redo and DevTools inspection. |
| **Predictable Updates** | No accidental mutations; state flows in one direction only. |
| **Framework Compatibility** | React, Vue, and others optimize rendering based on reference equality. |
| **Safer Concurrency** | Immutable objects can be safely shared across async operations. |

**Memory Implications:** See [Memory Management Strategy](./ui-modularization.md#part-1-memory-management--immutable-state) for:

- Ring buffer for SSE events (not stored indefinitely)
- State history limits for time-travel
- Periodic garbage collection
- WeakRef-based subscription cleanup

## Current State Analysis

**What Works Well:**

- EventBus exists with wildcard patterns and middleware support
- SSEService handles connection with auto-reconnect
- BaseComponent provides lifecycle management
- workerStore has request deduplication (inflight map)

**What Needs Improvement:**

- No unified StateStore class (workerStore is manual)
- Scattered caching across page components (`_workersCache`)
- No computed selectors (derived state)
- No state persistence (localStorage/sessionStorage)
- SSE events require manual wiring to store updates
- No devtools integration for debugging
- Tight coupling between SSE event types and store logic

## Target Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Browser                                         │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                         UI Components                                   │ │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐          │ │
│  │  │WorkersPage │ │LabletsPage │ │OverviewPg  │ │ SystemPage │   ...    │ │
│  │  └─────┬──────┘ └─────┬──────┘ └─────┬──────┘ └─────┬──────┘          │ │
│  │        │              │              │              │                  │ │
│  │        └──────────────┴──────────────┴──────────────┘                  │ │
│  │                              │                                          │ │
│  │                              │ useSelector() / dispatch()               │ │
│  │                              ▼                                          │ │
│  │  ╔═══════════════════════════════════════════════════════════════════╗ │ │
│  │  ║              LCM APPLICATION LAYER (Domain-Specific)              ║ │ │
│  │  ║  ┌──────────────────────────────────────────────────────────────┐ ║ │ │
│  │  ║  │                    lcmStore (AppStore)                       │ ║ │ │
│  │  ║  │  ┌─────────────┐┌─────────────┐┌─────────────┐┌───────────┐ │ ║ │ │
│  │  ║  │  │workersSlice ││labletsSlice ││templatesSlc ││systemSlice│ │ ║ │ │
│  │  ║  │  └─────────────┘└─────────────┘└─────────────┘└───────────┘ │ ║ │ │
│  │  ║  └──────────────────────────────────────────────────────────────┘ ║ │ │
│  │  ║                              │                                    ║ │ │
│  │  ║  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐  ║ │ │
│  │  ║  │   LcmActions    │  │  LcmSelectors   │  │ LcmSSEAdapter    │  ║ │ │
│  │  ║  │ (domain-aware)  │  │ (computed state)│  │ (event→actions)  │  ║ │ │
│  │  ║  └─────────────────┘  └─────────────────┘  └──────────────────┘  ║ │ │
│  │  ╚═══════════════════════════════════════════════════════════════════╝ │ │
│  │                              │                                          │ │
│  │                              │ extends/uses                             │ │
│  │                              ▼                                          │ │
│  │  ╔═══════════════════════════════════════════════════════════════════╗ │ │
│  │  ║           @NEUROGLIA/UI-CORE (Generic, Framework-Agnostic)        ║ │ │
│  │  ║  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐               ║ │ │
│  │  ║  │   EventBus   │ │  StateStore  │ │  SSEClient   │               ║ │ │
│  │  ║  │  (pub/sub)   │ │  (slices)    │ │  (realtime)  │               ║ │ │
│  │  ║  └──────────────┘ └──────────────┘ └──────────────┘               ║ │ │
│  │  ║  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐               ║ │ │
│  │  ║  │ Middleware   │ │  Selector    │ │  DevTools    │               ║ │ │
│  │  ║  │  Pipeline    │ │  (computed)  │ │  (debug)     │               ║ │ │
│  │  ║  └──────────────┘ └──────────────┘ └──────────────┘               ║ │ │
│  │  ╚═══════════════════════════════════════════════════════════════════╝ │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                              │                                               │
│                              │ EventSource (SSE)                             │
│                              ▼                                               │
└─────────────────────────────────────────────────────────────────────────────┘
                               │
                               │ /api/events/stream
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Control Plane API                                    │
│                       (SSE Event Publisher)                                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Part 1: Generic Core (@neuroglia/ui-core)

These classes are framework-agnostic and can be extracted to a standalone package.

### 1.1 EventBus (Enhanced)

Centralized pub/sub with namespacing, middleware, and debugging.

```javascript
/**
 * @class EventBus
 * @description Generic publish/subscribe event system with advanced features
 *
 * Features:
 * - Wildcard patterns (worker.*, *.created)
 * - Namespace support (domain:event.type)
 * - Async middleware pipeline
 * - Priority-based handler ordering
 * - Weak reference support for memory safety
 * - Debug mode with event history
 *
 * @example
 * const bus = new EventBus({ debug: true, historySize: 100 });
 *
 * // Subscribe with priority (lower = earlier)
 * bus.on('worker.updated', handler, { priority: 10 });
 *
 * // Wildcard subscription
 * bus.on('worker.*', data => console.log('Any worker event:', data));
 *
 * // Emit with metadata
 * bus.emit('worker.updated', { id: '123' }, { source: 'sse' });
 */
class EventBus {
    /**
     * @param {Object} options
     * @param {boolean} [options.debug=false] - Enable debug logging
     * @param {number} [options.historySize=0] - Number of events to keep in history (0 = disabled)
     */
    constructor(options = {}) {
        this._subscribers = new Map();    // eventType -> SortedSet<{handler, priority, id}>
        this._middleware = [];            // Array<(event, data, meta) => Promise<{data, meta}>>
        this._history = [];               // Event history for debugging
        this._options = {
            debug: false,
            historySize: 0,
            ...options
        };
        this._handlerId = 0;
    }

    /**
     * Subscribe to events
     * @param {string} eventType - Event type or pattern (supports *, **, ?)
     * @param {Function} handler - Async or sync handler function
     * @param {Object} [options] - Subscription options
     * @param {number} [options.priority=100] - Handler priority (lower = earlier)
     * @param {boolean} [options.once=false] - Auto-unsubscribe after first call
     * @returns {Function} Unsubscribe function
     */
    on(eventType, handler, options = {}) {
        const { priority = 100, once = false } = options;
        const id = ++this._handlerId;

        if (!this._subscribers.has(eventType)) {
            this._subscribers.set(eventType, []);
        }

        const subscription = { handler, priority, id, once };
        const handlers = this._subscribers.get(eventType);
        handlers.push(subscription);
        handlers.sort((a, b) => a.priority - b.priority);

        // Return unsubscribe function
        return () => this._off(eventType, id);
    }

    /**
     * Subscribe once (convenience method)
     */
    once(eventType, handler, options = {}) {
        return this.on(eventType, handler, { ...options, once: true });
    }

    /**
     * Emit an event through the middleware pipeline to all matching subscribers
     * @param {string} eventType - Event type
     * @param {*} data - Event payload
     * @param {Object} [meta] - Event metadata (source, timestamp, etc.)
     * @returns {Promise<void>}
     */
    async emit(eventType, data, meta = {}) {
        const eventMeta = {
            timestamp: Date.now(),
            eventType,
            ...meta
        };

        // Run through middleware pipeline
        let processedData = data;
        let processedMeta = eventMeta;

        for (const mw of this._middleware) {
            try {
                const result = await mw(eventType, processedData, processedMeta);
                if (result) {
                    processedData = result.data ?? processedData;
                    processedMeta = result.meta ?? processedMeta;
                }
            } catch (error) {
                console.error(`[EventBus] Middleware error:`, error);
            }
        }

        // Record in history
        if (this._options.historySize > 0) {
            this._history.push({ eventType, data: processedData, meta: processedMeta });
            if (this._history.length > this._options.historySize) {
                this._history.shift();
            }
        }

        // Debug logging
        if (this._options.debug) {
            console.log(`[EventBus] ${eventType}`, processedData, processedMeta);
        }

        // Collect matching handlers
        const toRemove = [];
        const handlersToCall = [];

        for (const [pattern, handlers] of this._subscribers) {
            if (this._matches(pattern, eventType)) {
                for (const sub of handlers) {
                    handlersToCall.push(sub);
                    if (sub.once) {
                        toRemove.push({ pattern, id: sub.id });
                    }
                }
            }
        }

        // Sort by priority across all matching patterns
        handlersToCall.sort((a, b) => a.priority - b.priority);

        // Call handlers
        for (const { handler } of handlersToCall) {
            try {
                await handler(processedData, processedMeta);
            } catch (error) {
                console.error(`[EventBus] Handler error for ${eventType}:`, error);
            }
        }

        // Clean up once handlers
        for (const { pattern, id } of toRemove) {
            this._off(pattern, id);
        }
    }

    /**
     * Add middleware to the pipeline
     * @param {Function} middleware - (eventType, data, meta) => { data, meta } | void
     */
    use(middleware) {
        this._middleware.push(middleware);
        return this; // Chainable
    }

    /**
     * Get event history (for debugging)
     */
    getHistory() {
        return [...this._history];
    }

    /**
     * Clear all subscribers
     */
    clear() {
        this._subscribers.clear();
        this._history = [];
    }

    /**
     * Get subscriber count for an event type
     */
    listenerCount(eventType) {
        return this._subscribers.get(eventType)?.length ?? 0;
    }

    // Private methods
    _off(eventType, id) {
        const handlers = this._subscribers.get(eventType);
        if (handlers) {
            const idx = handlers.findIndex(h => h.id === id);
            if (idx !== -1) handlers.splice(idx, 1);
            if (handlers.length === 0) {
                this._subscribers.delete(eventType);
            }
        }
    }

    _matches(pattern, eventType) {
        if (pattern === eventType) return true;
        if (!pattern.includes('*') && !pattern.includes('?')) return false;

        // Convert pattern to regex
        // * = any characters except dot, ** = any characters including dot, ? = single char
        const regexStr = pattern
            .replace(/\*\*/g, '<<<GLOBSTAR>>>')
            .replace(/\*/g, '[^.]*')
            .replace(/<<<GLOBSTAR>>>/g, '.*')
            .replace(/\?/g, '.');

        return new RegExp(`^${regexStr}$`).test(eventType);
    }
}
```

### 1.2 StateStore (New)

Generic slice-based state container with selectors, middleware, and persistence.

```javascript
/**
 * @class StateStore
 * @description Centralized state management with slices, selectors, and middleware
 *
 * Features:
 * - Slice-based state organization
 * - Computed selectors with memoization
 * - Middleware pipeline (logging, persistence, devtools)
 * - Optimistic updates with rollback
 * - Batch updates for performance
 * - State persistence (localStorage/sessionStorage)
 *
 * @example
 * const store = new StateStore({
 *     slices: {
 *         workers: { items: [], loading: false, error: null },
 *         ui: { theme: 'light', sidebarOpen: true }
 *     },
 *     middleware: [loggerMiddleware, persistMiddleware],
 *     persist: { key: 'app-state', slices: ['ui'], storage: localStorage }
 * });
 *
 * // Subscribe to slice changes
 * store.subscribe('workers', state => console.log('Workers:', state));
 *
 * // Update state
 * store.setState('workers', { loading: true });
 *
 * // Dispatch action
 * store.dispatch({ type: 'workers/fetch', payload: { region: 'us-east-1' } });
 */
class StateStore {
    /**
     * @param {Object} options
     * @param {Object} options.slices - Initial state organized by slice name
     * @param {Array} [options.middleware] - Middleware functions
     * @param {Object} [options.persist] - Persistence configuration
     * @param {EventBus} [options.eventBus] - EventBus instance for state change events
     */
    constructor(options = {}) {
        const { slices = {}, middleware = [], persist = null, eventBus = null } = options;

        this._state = this._deepClone(slices);
        this._subscribers = new Map();      // slice -> Set<callback>
        this._globalSubscribers = new Set(); // Subscribe to all changes
        this._middleware = middleware;
        this._actionHandlers = new Map();   // actionType -> handler
        this._selectors = new Map();        // selectorId -> { fn, deps, cache }
        this._eventBus = eventBus;
        this._batchQueue = null;
        this._batchTimeout = null;

        // Persistence
        this._persist = persist;
        if (persist) {
            this._loadPersistedState();
        }
    }

    // ==================== State Access ====================

    /**
     * Get state for a slice
     * @param {string} slice - Slice name
     * @returns {*} Slice state (frozen copy)
     */
    getState(slice) {
        if (slice) {
            return this._deepFreeze(this._deepClone(this._state[slice]));
        }
        return this._deepFreeze(this._deepClone(this._state));
    }

    /**
     * Get full state snapshot
     */
    getSnapshot() {
        return this._deepFreeze(this._deepClone(this._state));
    }

    // ==================== State Updates ====================

    /**
     * Replace slice state entirely
     * @param {string} slice - Slice name
     * @param {*} newState - New state for slice
     * @param {Object} [options] - Update options
     * @param {boolean} [options.silent=false] - Skip notifying subscribers
     */
    setState(slice, newState, options = {}) {
        const oldState = this._state[slice];
        this._state = {
            ...this._state,
            [slice]: newState
        };

        if (!options.silent) {
            this._notify(slice, newState, oldState);
        }

        this._maybePersist(slice);
    }

    /**
     * Merge partial state into a slice
     * @param {string} slice - Slice name
     * @param {Object} partialState - Partial state to merge
     */
    mergeState(slice, partialState) {
        const current = this._state[slice] || {};
        this.setState(slice, { ...current, ...partialState });
    }

    /**
     * Update an item in an array by ID
     * @param {string} slice - Slice name
     * @param {string} itemsKey - Key of the items array within the slice
     * @param {string} id - Item ID to update
     * @param {Object|Function} update - Partial update or update function
     */
    updateItem(slice, itemsKey, id, update) {
        const current = this._state[slice]?.[itemsKey] || [];
        const updated = current.map(item => {
            if (item.id !== id) return item;
            const newItem = typeof update === 'function' ? update(item) : { ...item, ...update };
            return newItem;
        });
        this.mergeState(slice, { [itemsKey]: updated });
    }

    /**
     * Upsert an item (update if exists, insert if not)
     * @param {string} slice - Slice name
     * @param {string} itemsKey - Key of the items array
     * @param {Object} item - Item with 'id' property
     */
    upsertItem(slice, itemsKey, item) {
        const current = this._state[slice]?.[itemsKey] || [];
        const index = current.findIndex(i => i.id === item.id);

        if (index >= 0) {
            // Merge with existing
            const updated = [...current];
            updated[index] = { ...current[index], ...item };
            this.mergeState(slice, { [itemsKey]: updated });
        } else {
            // Add new
            this.mergeState(slice, { [itemsKey]: [...current, item] });
        }
    }

    /**
     * Remove an item by ID
     * @param {string} slice - Slice name
     * @param {string} itemsKey - Key of the items array
     * @param {string} id - Item ID to remove
     */
    removeItem(slice, itemsKey, id) {
        const current = this._state[slice]?.[itemsKey] || [];
        this.mergeState(slice, { [itemsKey]: current.filter(i => i.id !== id) });
    }

    /**
     * Batch multiple updates (notifies once at end)
     * @param {Function} updater - (store) => void
     */
    batch(updater) {
        const changes = new Map(); // slice -> { oldState, newState }
        const originalNotify = this._notify.bind(this);

        // Replace notify to collect changes
        this._notify = (slice, newState, oldState) => {
            if (!changes.has(slice)) {
                changes.set(slice, { oldState, newState });
            } else {
                changes.get(slice).newState = newState;
            }
        };

        try {
            updater(this);
        } finally {
            this._notify = originalNotify;
        }

        // Notify all collected changes
        for (const [slice, { newState, oldState }] of changes) {
            this._notify(slice, newState, oldState);
        }
    }

    // ==================== Actions ====================

    /**
     * Register an action handler
     * @param {string} type - Action type (e.g., 'workers/fetch')
     * @param {Function} handler - (state, payload, { getState, setState, dispatch }) => Promise<void>
     */
    registerAction(type, handler) {
        this._actionHandlers.set(type, handler);
    }

    /**
     * Dispatch an action
     * @param {Object} action - { type, payload, meta }
     * @returns {Promise<*>} Action result
     */
    async dispatch(action) {
        const { type, payload, meta = {} } = action;

        // Run through middleware
        let processedAction = action;
        for (const mw of this._middleware) {
            const result = await mw(processedAction, this);
            if (result === false) return; // Middleware can cancel
            if (result) processedAction = result;
        }

        // Execute handler
        const handler = this._actionHandlers.get(processedAction.type);
        if (!handler) {
            console.warn(`[StateStore] No handler for action: ${type}`);
            return;
        }

        const context = {
            getState: this.getState.bind(this),
            setState: this.setState.bind(this),
            mergeState: this.mergeState.bind(this),
            dispatch: this.dispatch.bind(this),
            eventBus: this._eventBus
        };

        try {
            return await handler(processedAction.payload, context);
        } catch (error) {
            console.error(`[StateStore] Action error for ${type}:`, error);
            throw error;
        }
    }

    // ==================== Selectors ====================

    /**
     * Create a memoized selector
     * @param {string} id - Unique selector ID
     * @param {Array<string|Function>} deps - Dependency selectors or slice names
     * @param {Function} compute - (dep1Result, dep2Result, ...) => derivedValue
     * @returns {Function} Selector function
     */
    createSelector(id, deps, compute) {
        this._selectors.set(id, {
            deps,
            compute,
            cache: { args: null, result: null }
        });

        return () => this.select(id);
    }

    /**
     * Execute a selector
     * @param {string} id - Selector ID
     * @returns {*} Computed value
     */
    select(id) {
        const selector = this._selectors.get(id);
        if (!selector) throw new Error(`Unknown selector: ${id}`);

        const { deps, compute, cache } = selector;

        // Resolve dependencies
        const args = deps.map(dep => {
            if (typeof dep === 'string') {
                return dep.includes('/') ? this.select(dep) : this.getState(dep);
            }
            return dep(this.getSnapshot());
        });

        // Check cache
        if (cache.args && this._shallowEqual(cache.args, args)) {
            return cache.result;
        }

        // Compute and cache
        const result = compute(...args);
        selector.cache = { args, result };
        return result;
    }

    // ==================== Subscriptions ====================

    /**
     * Subscribe to slice changes
     * @param {string|null} slice - Slice name or null for all changes
     * @param {Function} callback - (newState, oldState, slice) => void
     * @returns {Function} Unsubscribe function
     */
    subscribe(slice, callback) {
        if (slice === null) {
            this._globalSubscribers.add(callback);
            return () => this._globalSubscribers.delete(callback);
        }

        if (!this._subscribers.has(slice)) {
            this._subscribers.set(slice, new Set());
        }
        this._subscribers.get(slice).add(callback);

        return () => this._subscribers.get(slice)?.delete(callback);
    }

    // ==================== Private Methods ====================

    _notify(slice, newState, oldState) {
        // Slice subscribers
        const sliceSubs = this._subscribers.get(slice);
        if (sliceSubs) {
            for (const cb of sliceSubs) {
                try {
                    cb(newState, oldState, slice);
                } catch (error) {
                    console.error(`[StateStore] Subscriber error:`, error);
                }
            }
        }

        // Global subscribers
        for (const cb of this._globalSubscribers) {
            try {
                cb(this.getSnapshot(), slice);
            } catch (error) {
                console.error(`[StateStore] Global subscriber error:`, error);
            }
        }

        // Emit to EventBus
        if (this._eventBus) {
            this._eventBus.emit(`state.${slice}.changed`, { slice, newState, oldState });
        }
    }

    _maybePersist(slice) {
        if (!this._persist) return;
        const { key, slices, storage } = this._persist;

        if (!slices || slices.includes(slice)) {
            const toPersist = {};
            const persistSlices = slices || Object.keys(this._state);
            for (const s of persistSlices) {
                toPersist[s] = this._state[s];
            }
            try {
                storage.setItem(key, JSON.stringify(toPersist));
            } catch (e) {
                console.warn('[StateStore] Persist failed:', e);
            }
        }
    }

    _loadPersistedState() {
        const { key, storage } = this._persist;
        try {
            const saved = storage.getItem(key);
            if (saved) {
                const parsed = JSON.parse(saved);
                for (const [slice, state] of Object.entries(parsed)) {
                    if (this._state[slice] !== undefined) {
                        this._state[slice] = { ...this._state[slice], ...state };
                    }
                }
            }
        } catch (e) {
            console.warn('[StateStore] Load persisted state failed:', e);
        }
    }

    _deepClone(obj) {
        if (obj === null || typeof obj !== 'object') return obj;
        if (Array.isArray(obj)) return obj.map(i => this._deepClone(i));
        const clone = {};
        for (const key of Object.keys(obj)) {
            clone[key] = this._deepClone(obj[key]);
        }
        return clone;
    }

    _deepFreeze(obj) {
        if (obj === null || typeof obj !== 'object') return obj;
        Object.freeze(obj);
        for (const key of Object.keys(obj)) {
            this._deepFreeze(obj[key]);
        }
        return obj;
    }

    _shallowEqual(a, b) {
        if (a === b) return true;
        if (!a || !b || a.length !== b.length) return false;
        for (let i = 0; i < a.length; i++) {
            if (a[i] !== b[i]) return false;
        }
        return true;
    }
}
```

### 1.3 SSEClient (Enhanced)

Generic SSE connection manager with event mapping and connection lifecycle.

```javascript
/**
 * @class SSEClient
 * @description Generic SSE connection manager with auto-reconnect and event routing
 *
 * Features:
 * - Automatic reconnection with exponential backoff
 * - Event type mapping to EventBus
 * - Connection state management
 * - Heartbeat monitoring
 * - Custom event parsers
 *
 * @example
 * const sse = new SSEClient({
 *     url: '/api/events/stream',
 *     eventBus: eventBus,
 *     eventMap: {
 *         'worker.snapshot': 'worker.updated',  // Rename events
 *         'worker.*': null  // Pass through with same name
 *     },
 *     parseEvent: (eventType, rawData) => JSON.parse(rawData).data
 * });
 *
 * sse.connect();
 */
class SSEClient {
    /**
     * @param {Object} options
     * @param {string} options.url - SSE endpoint URL
     * @param {EventBus} options.eventBus - EventBus instance
     * @param {Object} [options.eventMap] - Map SSE event types to EventBus event types
     * @param {Function} [options.parseEvent] - Custom event data parser
     * @param {number} [options.reconnectDelay=1000] - Initial reconnect delay (ms)
     * @param {number} [options.maxReconnectDelay=30000] - Maximum reconnect delay (ms)
     * @param {number} [options.heartbeatTimeout=45000] - Heartbeat timeout (ms)
     */
    constructor(options) {
        this._url = options.url;
        this._eventBus = options.eventBus;
        this._eventMap = options.eventMap || {};
        this._parseEvent = options.parseEvent || this._defaultParser;
        this._reconnectDelay = options.reconnectDelay || 1000;
        this._maxReconnectDelay = options.maxReconnectDelay || 30000;
        this._heartbeatTimeout = options.heartbeatTimeout || 45000;

        this._eventSource = null;
        this._reconnectAttempts = 0;
        this._reconnectTimer = null;
        this._heartbeatTimer = null;
        this._isIntentionalDisconnect = false;
        this._registeredEventTypes = new Set();

        this._state = {
            connected: false,
            connecting: false,
            lastEventTime: null,
            reconnectAttempts: 0
        };
    }

    /**
     * Connect to SSE stream
     */
    connect() {
        if (this._eventSource || this._state.connecting) {
            console.log('[SSEClient] Already connected or connecting');
            return;
        }

        this._isIntentionalDisconnect = false;
        this._state.connecting = true;

        console.log(`[SSEClient] Connecting to ${this._url}...`);

        try {
            this._eventSource = new EventSource(this._url, { withCredentials: true });

            this._eventSource.onopen = () => {
                console.log('[SSEClient] Connection opened');
                this._state.connected = true;
                this._state.connecting = false;
                this._state.reconnectAttempts = 0;
                this._reconnectDelay = 1000;
                this._startHeartbeatMonitor();

                this._eventBus.emit('sse.connected', {
                    url: this._url,
                    timestamp: Date.now()
                });
            };

            this._eventSource.onerror = (error) => {
                console.error('[SSEClient] Connection error', error);
                this._state.connected = false;
                this._state.connecting = false;
                this._stopHeartbeatMonitor();

                this._eventBus.emit('sse.error', { error });

                if (!this._isIntentionalDisconnect) {
                    this._scheduleReconnect();
                }
            };

            // Register for all mapped event types
            this._registerEventListeners();

        } catch (error) {
            console.error('[SSEClient] Failed to connect:', error);
            this._state.connecting = false;
            this._eventBus.emit('sse.error', { error });
            this._scheduleReconnect();
        }
    }

    /**
     * Disconnect from SSE stream
     */
    disconnect() {
        this._isIntentionalDisconnect = true;
        this._stopHeartbeatMonitor();

        if (this._reconnectTimer) {
            clearTimeout(this._reconnectTimer);
            this._reconnectTimer = null;
        }

        if (this._eventSource) {
            this._eventSource.close();
            this._eventSource = null;
            this._state.connected = false;

            console.log('[SSEClient] Disconnected');
            this._eventBus.emit('sse.disconnected', {});
        }
    }

    /**
     * Register a dynamic event type to listen for
     * @param {string} sseEventType - SSE event type
     * @param {string} [busEventType] - EventBus event type (defaults to sseEventType)
     */
    registerEventType(sseEventType, busEventType = null) {
        this._eventMap[sseEventType] = busEventType;

        if (this._eventSource) {
            this._registerSingleEventListener(sseEventType);
        }
    }

    /**
     * Get connection status
     */
    getStatus() {
        return { ...this._state };
    }

    /**
     * Check if connected
     */
    isConnected() {
        return this._state.connected;
    }

    // Private methods

    _registerEventListeners() {
        // Heartbeat handling
        this._eventSource.addEventListener('heartbeat', (event) => {
            this._state.lastEventTime = Date.now();
            this._resetHeartbeatMonitor();
        });

        // Connected event
        this._eventSource.addEventListener('connected', (event) => {
            try {
                const data = JSON.parse(event.data);
                this._eventBus.emit('sse.connected', data);
            } catch (e) {
                console.warn('[SSEClient] Failed to parse connected event:', e);
            }
        });

        // Register all mapped event types
        for (const sseEventType of Object.keys(this._eventMap)) {
            this._registerSingleEventListener(sseEventType);
        }
    }

    _registerSingleEventListener(sseEventType) {
        if (this._registeredEventTypes.has(sseEventType)) return;
        if (!this._eventSource) return;

        this._registeredEventTypes.add(sseEventType);

        this._eventSource.addEventListener(sseEventType, (event) => {
            this._state.lastEventTime = Date.now();
            this._resetHeartbeatMonitor();

            try {
                const data = this._parseEvent(sseEventType, event.data);
                const busEventType = this._eventMap[sseEventType] ?? sseEventType;

                if (busEventType !== false) {
                    this._eventBus.emit(busEventType, data, { source: 'sse', sseEventType });
                }
            } catch (error) {
                console.error(`[SSEClient] Error handling ${sseEventType}:`, error);
            }
        });
    }

    _defaultParser(eventType, rawData) {
        try {
            const parsed = JSON.parse(rawData);
            return parsed.data ?? parsed;
        } catch (e) {
            return rawData;
        }
    }

    _scheduleReconnect() {
        if (this._reconnectTimer || this._isIntentionalDisconnect) return;

        this._state.reconnectAttempts++;
        const delay = Math.min(
            this._reconnectDelay * Math.pow(2, this._state.reconnectAttempts - 1),
            this._maxReconnectDelay
        );

        console.log(`[SSEClient] Reconnecting in ${delay}ms (attempt ${this._state.reconnectAttempts})`);

        this._eventBus.emit('sse.reconnecting', {
            attempt: this._state.reconnectAttempts,
            delay
        });

        this._reconnectTimer = setTimeout(() => {
            this._reconnectTimer = null;
            if (this._eventSource) {
                this._eventSource.close();
                this._eventSource = null;
            }
            this._registeredEventTypes.clear();
            this.connect();
        }, delay);
    }

    _startHeartbeatMonitor() {
        this._resetHeartbeatMonitor();
    }

    _resetHeartbeatMonitor() {
        if (this._heartbeatTimer) {
            clearTimeout(this._heartbeatTimer);
        }

        this._heartbeatTimer = setTimeout(() => {
            console.warn('[SSEClient] Heartbeat timeout, reconnecting...');
            this._eventBus.emit('sse.heartbeat.timeout', {});
            this.disconnect();
            this._isIntentionalDisconnect = false;
            this.connect();
        }, this._heartbeatTimeout);
    }

    _stopHeartbeatMonitor() {
        if (this._heartbeatTimer) {
            clearTimeout(this._heartbeatTimer);
            this._heartbeatTimer = null;
        }
    }
}
```

### 1.4 Built-in Middleware

```javascript
/**
 * Logger middleware - logs all state changes
 */
function loggerMiddleware(action, store) {
    console.group(`[Store] ${action.type}`);
    console.log('Payload:', action.payload);
    console.log('State before:', store.getSnapshot());
    console.groupEnd();
    return action;
}

/**
 * DevTools middleware - integrates with Redux DevTools
 */
function devToolsMiddleware(action, store) {
    if (typeof window !== 'undefined' && window.__REDUX_DEVTOOLS_EXTENSION__) {
        const devtools = window.__REDUX_DEVTOOLS_EXTENSION__.connect({
            name: 'StateStore'
        });
        devtools.send(action, store.getSnapshot());
    }
    return action;
}

/**
 * Throttle middleware - prevents rapid-fire actions
 */
function createThrottleMiddleware(options = {}) {
    const lastCall = new Map();
    const defaultDelay = options.defaultDelay || 100;
    const actionDelays = options.actions || {};

    return (action, store) => {
        const delay = actionDelays[action.type] ?? defaultDelay;
        const now = Date.now();
        const last = lastCall.get(action.type) || 0;

        if (now - last < delay) {
            console.debug(`[Throttle] Skipping ${action.type}`);
            return false; // Cancel action
        }

        lastCall.set(action.type, now);
        return action;
    };
}
```

---

## Part 2: LCM Application Layer

Domain-specific implementations that use the generic core.

### 2.1 File Structure

```
ui/src/scripts/
├── core/                           # @neuroglia/ui-core (generic)
│   ├── EventBus.js                 # Enhanced EventBus
│   ├── StateStore.js               # Generic StateStore
│   ├── SSEClient.js                # Generic SSE client
│   ├── BaseComponent.js            # Web Component base class
│   ├── middleware/
│   │   ├── logger.js               # Logging middleware
│   │   ├── devtools.js             # Redux DevTools integration
│   │   ├── throttle.js             # Action throttling
│   │   └── index.js
│   └── index.js                    # Exports all core classes
│
├── app/                            # LCM-specific application layer
│   ├── store.js                    # AppStore configuration
│   ├── slices/
│   │   ├── workersSlice.js         # Workers state + actions + selectors
│   │   ├── labletsSlice.js         # Lablets state + actions + selectors
│   │   ├── templatesSlice.js       # Templates state + actions + selectors
│   │   ├── systemSlice.js          # System/settings state
│   │   └── uiSlice.js              # UI preferences state
│   ├── sse/
│   │   ├── sseAdapter.js           # Wire SSE events to store actions
│   │   └── eventTypes.js           # SSE event type constants
│   ├── selectors/
│   │   ├── workerSelectors.js      # Computed worker selectors
│   │   └── labletSelectors.js      # Computed lablet selectors
│   └── index.js                    # Exports store, eventBus, sseClient
│
├── api/                            # REST API clients (existing)
│   ├── workers.js
│   ├── lablets.js
│   └── ...
│
└── components/                     # UI components (existing)
    ├── pages/
    │   ├── WorkersPage.js          # Refactored to use store
    │   └── ...
    └── ...
```

### 2.2 LCM Store Configuration

```javascript
// app/store.js
import { StateStore, EventBus, SSEClient } from '../core/index.js';
import { loggerMiddleware, devToolsMiddleware } from '../core/middleware/index.js';
import { workersSlice, registerWorkerActions } from './slices/workersSlice.js';
import { labletsSlice, registerLabletActions } from './slices/labletsSlice.js';
import { templatesSlice, registerTemplateActions } from './slices/templatesSlice.js';
import { systemSlice, registerSystemActions } from './slices/systemSlice.js';
import { uiSlice, registerUIActions } from './slices/uiSlice.js';
import { configureSSEAdapter } from './sse/sseAdapter.js';
import { registerSelectors } from './selectors/index.js';

// Create EventBus singleton
export const eventBus = new EventBus({
    debug: localStorage.getItem('debug') === 'true',
    historySize: 100
});

// Create StateStore with all slices
export const store = new StateStore({
    slices: {
        workers: workersSlice.initialState,
        lablets: labletsSlice.initialState,
        templates: templatesSlice.initialState,
        system: systemSlice.initialState,
        ui: uiSlice.initialState
    },
    middleware: [
        loggerMiddleware,
        ...(process.env.NODE_ENV === 'development' ? [devToolsMiddleware] : [])
    ],
    persist: {
        key: 'lcm-ui-state',
        slices: ['ui'],  // Only persist UI preferences
        storage: localStorage
    },
    eventBus
});

// Register all action handlers
registerWorkerActions(store);
registerLabletActions(store);
registerTemplateActions(store);
registerSystemActions(store);
registerUIActions(store);

// Register computed selectors
registerSelectors(store);

// Create and configure SSE client
export const sseClient = new SSEClient({
    url: '/api/events/stream',
    eventBus,
    reconnectDelay: 1000,
    maxReconnectDelay: 30000,
    heartbeatTimeout: 45000,
    parseEvent: (eventType, rawData) => {
        try {
            const parsed = JSON.parse(rawData);
            return parsed.data ?? parsed;
        } catch (e) {
            return rawData;
        }
    }
});

// Wire SSE events to store actions
configureSSEAdapter(sseClient, store, eventBus);

// Auto-connect on load
if (typeof window !== 'undefined') {
    sseClient.connect();
}

// Export convenience hooks for components
export function useSelector(selectorId) {
    return store.select(selectorId);
}

export function useSlice(sliceName) {
    return store.getState(sliceName);
}

export function dispatch(action) {
    return store.dispatch(action);
}
```

### 2.3 Workers Slice Example

```javascript
// app/slices/workersSlice.js
import * as workersApi from '../../api/workers.js';

/**
 * Workers slice - manages CML worker state
 */
export const workersSlice = {
    name: 'workers',

    initialState: {
        items: [],              // Worker objects by ID
        itemsById: new Map(),   // Quick lookup map
        loading: false,
        error: null,
        selectedRegion: null,
        activeWorkerId: null,

        // Request deduplication
        inflight: new Map(),    // key -> Promise

        // Timing metadata
        timing: new Map(),      // workerId -> { pollInterval, nextRefreshAt, lastRefreshedAt }
    }
};

/**
 * Register worker action handlers
 */
export function registerWorkerActions(store) {

    // Fetch all workers
    store.registerAction('workers/fetchAll', async (payload, { getState, mergeState, eventBus }) => {
        const { region, force = false } = payload || {};

        // Check if already loading
        if (getState('workers').loading && !force) {
            return;
        }

        mergeState('workers', { loading: true, error: null });

        try {
            const workers = await workersApi.getWorkers(region);

            // Build lookup map
            const itemsById = new Map(workers.map(w => [w.id, w]));

            mergeState('workers', {
                items: workers,
                itemsById,
                loading: false,
                selectedRegion: region
            });

            eventBus?.emit('workers.loaded', { count: workers.length, region });

        } catch (error) {
            mergeState('workers', {
                loading: false,
                error: error.message
            });
            throw error;
        }
    });

    // Fetch single worker details
    store.registerAction('workers/fetchDetails', async (payload, { getState, mergeState }) => {
        const { workerId, region, force = false } = payload;
        const key = `${region}:${workerId}`;
        const current = getState('workers');

        // Skip if already loaded (unless forced)
        if (!force) {
            const existing = current.itemsById.get(workerId);
            if (existing?.detailsLoaded) {
                return existing;
            }
        }

        // Check inflight
        if (current.inflight.has(key)) {
            return current.inflight.get(key);
        }

        const promise = workersApi.getWorkerDetails(region, workerId)
            .then(worker => {
                worker.detailsLoaded = true;
                store.upsertItem('workers', 'items', worker);

                // Update lookup map
                const updated = getState('workers');
                updated.itemsById.set(worker.id, worker);

                return worker;
            })
            .finally(() => {
                const s = getState('workers');
                s.inflight.delete(key);
            });

        // Track inflight
        current.inflight.set(key, promise);

        return promise;
    });

    // Set active worker
    store.registerAction('workers/setActive', (payload, { mergeState, eventBus }) => {
        const { workerId } = payload;
        mergeState('workers', { activeWorkerId: workerId });
        eventBus?.emit('worker.active.changed', { workerId });
    });

    // Update worker from SSE snapshot
    store.registerAction('workers/updateFromSSE', (payload, { getState }) => {
        const worker = payload;
        if (!worker?.id) return;

        const current = getState('workers');
        const existing = current.itemsById.get(worker.id);

        // Merge with existing, preserving detail fields
        const merged = { ...existing, ...worker };

        store.upsertItem('workers', 'items', merged);
        current.itemsById.set(worker.id, merged);
    });

    // Update worker metrics only
    store.registerAction('workers/updateMetrics', (payload, { getState }) => {
        const { worker_id, ...metrics } = payload;
        if (!worker_id) return;

        store.updateItem('workers', 'items', worker_id, item => ({
            ...item,
            ...metrics,
            metricsUpdatedAt: new Date().toISOString()
        }));
    });

    // Update timing metadata
    store.registerAction('workers/updateTiming', (payload, { getState }) => {
        const { worker_id, poll_interval, next_refresh_at, last_refreshed_at } = payload;
        if (!worker_id) return;

        const timing = getState('workers').timing;
        timing.set(worker_id, {
            pollInterval: poll_interval,
            nextRefreshAt: next_refresh_at,
            lastRefreshedAt: last_refreshed_at,
            updatedAt: new Date().toISOString()
        });
    });

    // Remove worker
    store.registerAction('workers/remove', (payload, { getState, eventBus }) => {
        const { workerId } = payload;

        store.removeItem('workers', 'items', workerId);

        const current = getState('workers');
        current.itemsById.delete(workerId);
        current.timing.delete(workerId);

        if (current.activeWorkerId === workerId) {
            store.mergeState('workers', { activeWorkerId: null });
        }

        eventBus?.emit('worker.removed', { workerId });
    });
}
```

### 2.4 Computed Selectors

```javascript
// app/selectors/workerSelectors.js

export function registerWorkerSelectors(store) {

    // Active worker object
    store.createSelector(
        'workers/active',
        ['workers'],
        (workers) => {
            if (!workers.activeWorkerId) return null;
            return workers.itemsById.get(workers.activeWorkerId) || null;
        }
    );

    // Workers filtered by region
    store.createSelector(
        'workers/byRegion',
        ['workers'],
        (workers) => {
            if (!workers.selectedRegion) return workers.items;
            return workers.items.filter(w => w.region === workers.selectedRegion);
        }
    );

    // Workers grouped by status
    store.createSelector(
        'workers/byStatus',
        ['workers'],
        (workers) => {
            const groups = {
                running: [],
                stopped: [],
                pending: [],
                terminated: [],
                error: []
            };

            for (const worker of workers.items) {
                const status = worker.status?.toLowerCase() || 'unknown';
                if (groups[status]) {
                    groups[status].push(worker);
                }
            }

            return groups;
        }
    );

    // Worker count summary
    store.createSelector(
        'workers/summary',
        ['workers/byStatus'],
        (byStatus) => ({
            total: Object.values(byStatus).flat().length,
            running: byStatus.running.length,
            stopped: byStatus.stopped.length,
            pending: byStatus.pending.length,
            error: byStatus.error.length
        })
    );

    // Workers with high CPU utilization
    store.createSelector(
        'workers/highCpu',
        ['workers'],
        (workers) => workers.items.filter(w => (w.cpu_utilization || 0) > 80)
    );
}
```

### 2.5 SSE Adapter

```javascript
// app/sse/sseAdapter.js
import { LCM_SSE_EVENTS } from './eventTypes.js';

/**
 * Configure SSE event routing to store actions
 */
export function configureSSEAdapter(sseClient, store, eventBus) {

    // Register all SSE event types
    const eventMappings = {
        // Worker events
        'worker.snapshot': 'workers/updateFromSSE',
        'worker.metrics.updated': 'workers/updateMetrics',
        'worker.status.updated': 'workers/updateFromSSE',
        'worker.created': 'workers/updateFromSSE',
        'worker.imported': 'workers/updateFromSSE',
        'worker.terminated': 'workers/remove',
        'worker.activity.updated': 'workers/updateFromSSE',
        'worker.endpoint.updated': 'workers/updateFromSSE',
        'worker.ec2_details.updated': 'workers/updateFromSSE',
        'worker.paused': 'workers/updateFromSSE',
        'worker.resumed': 'workers/updateFromSSE',

        // Lablet events
        'lablet.instance.snapshot': 'lablets/updateFromSSE',
        'lablet.instance.created': 'lablets/updateFromSSE',
        'lablet.instance.status.changed': 'lablets/updateFromSSE',
        'lablet.instance.terminated': 'lablets/remove',

        // System events
        'system.health': 'system/updateHealth',
        'system.sse.shutdown': null  // Handled separately
    };

    // Register events with SSE client
    for (const [sseEvent, action] of Object.entries(eventMappings)) {
        sseClient.registerEventType(sseEvent, sseEvent);

        if (action) {
            eventBus.on(sseEvent, async (data, meta) => {
                try {
                    await store.dispatch({
                        type: action,
                        payload: data,
                        meta: { source: 'sse', ...meta }
                    });
                } catch (error) {
                    console.error(`[SSEAdapter] Error dispatching ${action}:`, error);
                }
            });
        }
    }

    // Special handling for SSE shutdown
    eventBus.on('system.sse.shutdown', () => {
        console.log('[SSEAdapter] Server shutdown, will reconnect...');
    });

    // Track connection status in store
    eventBus.on('sse.connected', () => {
        store.mergeState('system', { sseConnected: true });
    });

    eventBus.on('sse.disconnected', () => {
        store.mergeState('system', { sseConnected: false });
    });

    eventBus.on('sse.error', () => {
        store.mergeState('system', { sseConnected: false });
    });
}
```

### 2.6 Component Integration

```javascript
// components/pages/WorkersPage.js (refactored)
import { BaseComponent } from '../../core/BaseComponent.js';
import { store, dispatch, eventBus } from '../../app/index.js';

export class WorkersPage extends BaseComponent {
    constructor() {
        super();
        this._unsubscribers = [];
    }

    onMount() {
        // Subscribe to workers state
        this._unsubscribers.push(
            store.subscribe('workers', (state, oldState) => {
                this._onWorkersChanged(state, oldState);
            })
        );

        // Subscribe to specific events
        this._unsubscribers.push(
            eventBus.on('worker.active.changed', ({ workerId }) => {
                this._highlightActiveWorker(workerId);
            })
        );

        // Initial render with current state
        this.render();

        // Fetch data if not loaded
        const workers = store.getState('workers');
        if (workers.items.length === 0 && !workers.loading) {
            dispatch({ type: 'workers/fetchAll' });
        }
    }

    onUnmount() {
        // Clean up all subscriptions
        this._unsubscribers.forEach(fn => fn());
        this._unsubscribers = [];
    }

    render() {
        const workers = store.getState('workers');
        const summary = store.select('workers/summary');
        const isLoading = workers.loading;

        this.innerHTML = `
            <div class="workers-page">
                ${isLoading ? this._renderLoading() : ''}
                <div class="workers-summary">
                    <span>Total: ${summary.total}</span>
                    <span>Running: ${summary.running}</span>
                    <span>Stopped: ${summary.stopped}</span>
                </div>
                <div class="workers-list">
                    ${this._renderWorkersList(workers.items)}
                </div>
            </div>
        `;
    }

    _onWorkersChanged(newState, oldState) {
        // Only re-render if items actually changed
        if (newState.items !== oldState?.items || newState.loading !== oldState?.loading) {
            this.render();
        }
    }

    _renderWorkersList(workers) {
        return workers.map(w => `
            <worker-card
                worker-id="${w.id}"
                status="${w.status}"
                name="${w.name}">
            </worker-card>
        `).join('');
    }

    _highlightActiveWorker(workerId) {
        // Update active class without full re-render
        this.querySelectorAll('worker-card').forEach(card => {
            card.classList.toggle('active', card.getAttribute('worker-id') === workerId);
        });
    }

    // Action handlers
    _handleRefresh() {
        dispatch({ type: 'workers/fetchAll', payload: { force: true } });
    }

    _handleSelectWorker(workerId) {
        dispatch({ type: 'workers/setActive', payload: { workerId } });
    }
}

customElements.define('workers-page', WorkersPage);
```

---

## Part 3: State Shape Reference

### Complete State Tree

```javascript
{
    workers: {
        items: Worker[],              // Array of worker objects
        itemsById: Map<string, Worker>, // Quick lookup by ID
        loading: boolean,
        error: string | null,
        selectedRegion: string | null,
        activeWorkerId: string | null,
        inflight: Map<string, Promise>, // Request deduplication
        timing: Map<string, TimingMeta> // Polling metadata
    },

    lablets: {
        instances: LabletInstance[],
        definitions: LabletDefinition[],
        loading: boolean,
        error: string | null,
        activeInstanceId: string | null,
        filter: {
            status: string | null,
            definitionId: string | null
        }
    },

    templates: {
        items: WorkerTemplate[],
        loading: boolean,
        error: string | null
    },

    system: {
        settings: SystemSettings | null,
        health: HealthStatus | null,
        sseConnected: boolean,
        user: UserInfo | null
    },

    ui: {
        theme: 'light' | 'dark',
        sidebarOpen: boolean,
        workersViewMode: 'cards' | 'table',
        labletsViewMode: 'cards' | 'table',
        activeTab: string
    }
}
```

### Entity Types

```typescript
interface Worker {
    id: string;
    name: string;
    status: 'running' | 'stopped' | 'pending' | 'terminated' | 'error';
    region: string;
    instance_id: string;
    public_ip: string | null;
    private_ip: string | null;
    instance_type: string;

    // Metrics
    cpu_utilization: number | null;
    memory_utilization: number | null;
    storage_utilization: number | null;

    // CML info
    cml_version: string | null;
    cml_license_info: object | null;
    license_status: string | null;

    // Timestamps
    created_at: string;
    updated_at: string;
    last_active_at: string | null;

    // UI flags
    detailsLoaded: boolean;
    metricsUpdatedAt: string | null;
}

interface LabletInstance {
    id: string;
    definition_id: string;
    name: string;
    status: 'scheduled' | 'provisioning' | 'ready' | 'running' | 'stopping' | 'terminated';
    worker_id: string | null;
    lab_id: string | null;
    owner_id: string;
    scheduled_start: string;
    scheduled_end: string;
    created_at: string;
    updated_at: string;
}

interface LabletDefinition {
    id: string;
    name: string;
    description: string;
    lab_topology_yaml: string;
    node_count: number;
    cpu_required: number;
    memory_required: number;
    enabled: boolean;
    created_at: string;
    updated_at: string;
}
```

---

## Part 4: SSE Event Types Reference

### Event Type Constants

```javascript
// app/sse/eventTypes.js

export const LCM_SSE_EVENTS = {
    // Worker lifecycle
    WORKER_SNAPSHOT: 'worker.snapshot',
    WORKER_CREATED: 'worker.created',
    WORKER_IMPORTED: 'worker.imported',
    WORKER_TERMINATED: 'worker.terminated',
    WORKER_PAUSED: 'worker.paused',
    WORKER_RESUMED: 'worker.resumed',

    // Worker status
    WORKER_STATUS_UPDATED: 'worker.status.updated',
    WORKER_ENDPOINT_UPDATED: 'worker.endpoint.updated',
    WORKER_EC2_DETAILS_UPDATED: 'worker.ec2_details.updated',
    WORKER_ACTIVITY_UPDATED: 'worker.activity.updated',

    // Worker metrics
    WORKER_METRICS_UPDATED: 'worker.metrics.updated',
    WORKER_DATA_REFRESHED: 'worker.data.refreshed',
    WORKER_REFRESH_THROTTLED: 'worker.refresh.throttled',

    // Worker licensing
    WORKER_LICENSE_REGISTRATION_STARTED: 'worker.license.registration.started',
    WORKER_LICENSE_REGISTRATION_COMPLETED: 'worker.license.registration.completed',
    WORKER_LICENSE_REGISTRATION_FAILED: 'worker.license.registration.failed',
    WORKER_LICENSE_DEREGISTERED: 'worker.license.deregistered',

    // Bulk operations
    WORKERS_REFRESH_COMPLETED: 'workers.refresh.completed',

    // Lablet instances
    LABLET_INSTANCE_SNAPSHOT: 'lablet.instance.snapshot',
    LABLET_INSTANCE_CREATED: 'lablet.instance.created',
    LABLET_INSTANCE_UPDATED: 'lablet.instance.updated',
    LABLET_INSTANCE_STATUS_CHANGED: 'lablet.instance.status.changed',
    LABLET_INSTANCE_SCHEDULED: 'lablet.instance.scheduled',
    LABLET_INSTANCE_PROVISIONING: 'lablet.instance.provisioning',
    LABLET_INSTANCE_READY: 'lablet.instance.ready',
    LABLET_INSTANCE_TERMINATED: 'lablet.instance.terminated',

    // Lablet definitions
    LABLET_DEFINITION_CREATED: 'lablet.definition.created',
    LABLET_DEFINITION_UPDATED: 'lablet.definition.updated',
    LABLET_DEFINITION_DELETED: 'lablet.definition.deleted',
    LABLET_DEFINITIONS_REFRESH_COMPLETED: 'lablet.definitions.refresh.completed',

    // System
    SYSTEM_HEALTH: 'system.health',
    SYSTEM_SSE_SHUTDOWN: 'system.sse.shutdown',

    // Auth
    AUTH_SESSION_EXPIRED: 'auth.session.expired'
};
```

---

## Part 5: Migration Plan

### Phase 1: Core Infrastructure (Week 1)

| Task | Description | Files |
|------|-------------|-------|
| 1.1 | Enhance EventBus with priority, history, middleware | `core/EventBus.js` |
| 1.2 | Implement StateStore class | `core/StateStore.js` |
| 1.3 | Refactor SSEClient to use new patterns | `core/SSEClient.js` |
| 1.4 | Add built-in middleware | `core/middleware/*.js` |
| 1.5 | Write unit tests for core classes | `tests/core/*.test.js` |

**Deliverable:** Generic core classes working independently.

### Phase 2: LCM Application Layer (Week 2)

| Task | Description | Files |
|------|-------------|-------|
| 2.1 | Create workers slice | `app/slices/workersSlice.js` |
| 2.2 | Create lablets slice | `app/slices/labletsSlice.js` |
| 2.3 | Create other slices (templates, system, ui) | `app/slices/*.js` |
| 2.4 | Implement computed selectors | `app/selectors/*.js` |
| 2.5 | Configure SSE adapter | `app/sse/sseAdapter.js` |
| 2.6 | Create app store configuration | `app/store.js` |

**Deliverable:** LCM-specific store fully configured with all slices.

### Phase 3: Component Migration (Week 3)

| Task | Description | Files |
|------|-------------|-------|
| 3.1 | Refactor WorkersPage | `components/pages/WorkersPage.js` |
| 3.2 | Refactor LabletsPage | `components/pages/LabletsPage.js` |
| 3.3 | Refactor OverviewPage | `components/pages/OverviewPage.js` |
| 3.4 | Refactor SystemPage | `components/pages/SystemPage.js` |
| 3.5 | Update BaseComponent with store helpers | `core/BaseComponent.js` |
| 3.6 | Remove legacy workerStore | `store/workerStore.js` (delete) |

**Deliverable:** All pages using centralized store.

### Phase 4: Polish & DevTools (Week 4)

| Task | Description | Files |
|------|-------------|-------|
| 4.1 | Add Redux DevTools integration | `core/middleware/devtools.js` |
| 4.2 | Add connection status indicator | `components/ConnectionIndicator.js` |
| 4.3 | Add state persistence for UI prefs | Already in StateStore |
| 4.4 | Performance optimization (memoization) | Various |
| 4.5 | Integration tests | `tests/integration/*.test.js` |

**Deliverable:** Production-ready state management.

### Phase 5: Framework Extraction (Future)

| Task | Description |
|------|-------------|
| 5.1 | Extract core classes to `@neuroglia/ui-core` package |
| 5.2 | Add TypeScript definitions |
| 5.3 | Write package documentation |
| 5.4 | Publish to npm (internal registry) |
| 5.5 | Update LCM to use package |

**Deliverable:** Reusable Neuroglia UI core package.

---

## Part 6: Design Decisions

### AD-UI-STATE-1: Slice-based State Organization

**Decision**: Organize state by domain slice (workers, lablets, etc.)
**Rationale**: Natural domain boundaries, easier subscriptions, independent loading states per domain.

### AD-UI-STATE-2: Global Singletons Pattern

**Decision**: Use global singleton instances for store, eventBus, sseClient
**Rationale**: Simpler for SPA context, consistent with existing patterns. DI can be added later for testing.

### AD-UI-STATE-3: SSE Event Mapping via Adapter

**Decision**: Use a separate adapter to wire SSE events to store actions
**Rationale**: Decouples SSE transport from store logic. Makes it easy to add/remove event handlers. Can be mocked for testing.

### AD-UI-STATE-4: Computed Selectors with Memoization

**Decision**: Implement selector pattern with automatic memoization
**Rationale**: Prevents expensive recomputation. Components can subscribe to derived state without manual caching.

### AD-UI-STATE-5: Action-based State Updates

**Decision**: Use dispatch(action) pattern for complex state updates
**Rationale**: Enables middleware pipeline (logging, throttling, devtools). Makes state transitions explicit and traceable.

### AD-UI-STATE-6: Immutable State by Convention

**Decision**: Use spread operators for state updates, return frozen copies
**Rationale**: Enables change detection, prevents accidental mutations. Compatible with React/Vue if we migrate later.

### AD-UI-STATE-7: Core/App Layer Separation

**Decision**: Separate generic core classes from LCM-specific implementations
**Rationale**: Core classes can be extracted to Neuroglia framework package. LCM layer contains only domain-specific logic.

---

## Part 7: Success Metrics

### Functional Requirements

- [ ] All components receive real-time updates via SSE within 100ms
- [ ] View switching preserves data without additional API calls
- [ ] Connection status visible in UI (indicator component)
- [ ] State persists across page refreshes (UI preferences)
- [ ] Graceful degradation when SSE disconnected

### Performance Requirements

- [ ] < 100ms latency from SSE event to UI update
- [ ] < 16ms render time for state change (60fps)
- [ ] Zero memory leaks from subscription cleanup
- [ ] State updates batched when multiple SSE events arrive

### Quality Requirements

- [ ] Core components have 90%+ test coverage
- [ ] All public APIs have JSDoc documentation
- [ ] Redux DevTools integration working in development
- [ ] No console errors in production mode

### Architecture Requirements

- [ ] Clear separation between core and app layers
- [ ] Core classes have zero LCM-specific dependencies
- [ ] All SSE events routed through single adapter
- [ ] Computed selectors prevent redundant calculations

---

## Part 8: Testing Strategy

### Unit Tests (Core Layer)

```javascript
// tests/core/EventBus.test.js
describe('EventBus', () => {
    test('emits events to subscribers', async () => {
        const bus = new EventBus();
        const handler = jest.fn();

        bus.on('test.event', handler);
        await bus.emit('test.event', { value: 42 });

        expect(handler).toHaveBeenCalledWith({ value: 42 }, expect.any(Object));
    });

    test('supports wildcard patterns', async () => {
        const bus = new EventBus();
        const handler = jest.fn();

        bus.on('worker.*', handler);
        await bus.emit('worker.created', { id: '1' });
        await bus.emit('worker.updated', { id: '1' });

        expect(handler).toHaveBeenCalledTimes(2);
    });

    test('respects handler priority', async () => {
        const bus = new EventBus();
        const calls = [];

        bus.on('event', () => calls.push('low'), { priority: 100 });
        bus.on('event', () => calls.push('high'), { priority: 10 });

        await bus.emit('event', {});

        expect(calls).toEqual(['high', 'low']);
    });
});
```

### Integration Tests (App Layer)

```javascript
// tests/app/workersSlice.test.js
describe('Workers Slice', () => {
    let store, eventBus;

    beforeEach(() => {
        eventBus = new EventBus();
        store = new StateStore({
            slices: { workers: workersSlice.initialState },
            eventBus
        });
        registerWorkerActions(store);
    });

    test('updates worker from SSE snapshot', async () => {
        await store.dispatch({
            type: 'workers/updateFromSSE',
            payload: { id: 'w1', name: 'Worker 1', status: 'running' }
        });

        const workers = store.getState('workers');
        expect(workers.items).toHaveLength(1);
        expect(workers.items[0].status).toBe('running');
    });

    test('merges metrics without losing existing data', async () => {
        // Add initial worker
        await store.dispatch({
            type: 'workers/updateFromSSE',
            payload: { id: 'w1', name: 'Worker 1', detailsLoaded: true }
        });

        // Update metrics only
        await store.dispatch({
            type: 'workers/updateMetrics',
            payload: { worker_id: 'w1', cpu_utilization: 75 }
        });

        const worker = store.getState('workers').itemsById.get('w1');
        expect(worker.name).toBe('Worker 1');  // Preserved
        expect(worker.detailsLoaded).toBe(true);  // Preserved
        expect(worker.cpu_utilization).toBe(75);  // Updated
    });
});
```

---

## References

- [Existing EventBus Implementation](../../src/control-plane-api/ui/src/scripts/core/EventBus.js)
- [Existing SSE Service](../../src/control-plane-api/ui/src/scripts/services/SSEService.js)
- [Existing Worker Store](../../src/control-plane-api/ui/src/scripts/store/workerStore.js)
- [BaseComponent](../../src/control-plane-api/ui/src/scripts/core/BaseComponent.js)
- [SSE Event Relay (Backend)](../../src/control-plane-api/application/services/sse_event_relay.py)
