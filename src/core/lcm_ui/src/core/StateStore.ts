/**
 * StateStore - Centralized State Management
 *
 * A lightweight, slice-based state management solution with:
 * - Slice-based state organization
 * - Computed selectors with memoization
 * - Middleware pipeline for side effects
 * - State history for debugging/undo
 * - Batch updates for performance
 * - EventBus integration for state change events
 *
 * @example
 * ```typescript
 * import { StateStore, EventBus } from '@neuroglia/ui-core';
 *
 * const store = new StateStore({
 *   slices: {
 *     counter: { value: 0 },
 *     user: { name: '', isLoggedIn: false }
 *   },
 *   maxHistorySize: 50
 * });
 *
 * // Subscribe to changes
 * store.subscribe((newState, oldState, action) => {
 *   console.log('State changed:', action.type);
 * });
 *
 * // Update state
 * store.dispatch({ type: 'counter/increment', payload: 1 });
 *
 * // Use selectors
 * const count = store.select(state => state.counter.value);
 * ```
 *
 * @module core
 */

import type { StoreAction, StoreMiddleware, StateListener, Selector, MemoizedSelector, HistoryEntry, StoreAPI, SliceDefinition, SliceReducer, StoreDispatch } from '../types/store.js';
import type { EventBus } from './EventBus.js';
import { EventTypes } from './constants.js';

/**
 * StateStore configuration with defaults
 */
export interface StateStoreConfig {
    /** Initial state slices */
    slices: Record<string, unknown>;
    /** Middleware to apply */
    middleware?: StoreMiddleware[];
    /** Maximum state history size (default: 50) */
    maxHistorySize?: number;
    /** Optional EventBus for state change events */
    eventBus?: EventBus;
    /** Enable debug logging */
    debug?: boolean;
}

/**
 * Default configuration
 */
const DEFAULT_CONFIG = {
    maxHistorySize: 50,
    debug: false,
};

/**
 * StateStore - Centralized state management
 */
export class StateStore implements StoreAPI {
    private state: Record<string, unknown>;
    private listeners: Set<StateListener>;
    private middleware: StoreMiddleware[];
    private history: HistoryEntry[];
    private maxHistorySize: number;
    private eventBus?: EventBus;
    private debug: boolean;
    private isBatching: boolean;
    private batchedActions: StoreAction[];
    private selectorCache: Map<Selector, { deps: unknown[]; result: unknown }>;
    private sliceReducers: Map<string, Record<string, SliceReducer>>;

    /**
     * Create a new StateStore
     * @param config - Store configuration
     */
    constructor(config: StateStoreConfig) {
        this.state = { ...config.slices };
        this.listeners = new Set();
        this.middleware = config.middleware ?? [];
        this.history = [];
        this.maxHistorySize = config.maxHistorySize ?? DEFAULT_CONFIG.maxHistorySize;
        this.eventBus = config.eventBus;
        this.debug = config.debug ?? DEFAULT_CONFIG.debug;
        this.isBatching = false;
        this.batchedActions = [];
        this.selectorCache = new Map();
        this.sliceReducers = new Map();

        // Initialize state in history
        this.addToHistory({ type: '@@INIT' });

        // Emit initialization event
        this.emitStateEvent(EventTypes.STATE_INITIALIZED);
    }

    /**
     * Get the current state
     */
    getState(): Record<string, unknown> {
        return { ...this.state };
    }

    /**
     * Get a specific slice of state
     * @param name - Slice name
     */
    getSlice<T>(name: string): T | undefined {
        return this.state[name] as T | undefined;
    }

    /**
     * Set a specific slice of state directly
     * @param name - Slice name
     * @param value - New slice value
     */
    setSlice<T>(name: string, value: T): void {
        this.dispatch({
            type: `${name}/set`,
            payload: value,
            meta: { slice: name },
        });
    }

    /**
     * Update a slice with a partial update
     * @param name - Slice name
     * @param update - Partial update or updater function
     */
    updateSlice<T extends Record<string, unknown>>(name: string, update: Partial<T> | ((current: T) => Partial<T>)): void {
        const current = this.getSlice<T>(name);
        const partial = typeof update === 'function' ? update(current as T) : update;

        this.dispatch({
            type: `${name}/update`,
            payload: partial,
            meta: { slice: name, partial: true },
        });
    }

    /**
     * Register a slice definition with initial state and optional reducers.
     *
     * Initializes the slice state and stores its reducers so that
     * dispatched actions of the form `sliceName/reducerName` invoke
     * the corresponding reducer function.
     *
     * @param name - Slice name (used as state key and action type prefix)
     * @param definition - Slice definition with initialState and optional reducers
     *
     * @example
     * ```typescript
     * store.registerSlice('counter', {
     *   name: 'counter',
     *   initialState: { value: 0 },
     *   reducers: {
     *     increment(state, amount) { return { ...state, value: state.value + amount }; },
     *     reset(state) { return { ...state, value: 0 }; }
     *   }
     * });
     *
     * store.dispatch('counter', 'increment', 5);
     * // or: store.dispatch({ type: 'counter/increment', payload: 5 });
     * ```
     */
    registerSlice<T = unknown>(name: string, definition: SliceDefinition<T>): void {
        // Initialize slice state
        this.state = {
            ...this.state,
            [name]: definition.initialState,
        };

        // Store reducers if provided
        if (definition.reducers) {
            this.sliceReducers.set(name, definition.reducers as Record<string, SliceReducer>);
        }

        if (this.debug) {
            const reducerNames = definition.reducers ? Object.keys(definition.reducers) : [];
            console.log(`[StateStore] Registered slice "${name}" with reducers:`, reducerNames);
        }
    }

    /**
     * Dispatch an action to update state.
     *
     * Supports two calling conventions:
     * 1. Action object: `dispatch({ type: 'slice/reducer', payload: data })`
     * 2. Positional args: `dispatch('slice', 'reducer', payload)`
     *
     * When a slice has registered reducers (via `registerSlice`), the reducer
     * function matching the action suffix is invoked with the current slice
     * state and the payload. The return value replaces the slice state.
     *
     * @param actionOrSlice - StoreAction object, or slice name (string)
     * @param reducerName - Reducer name (only when first arg is a string)
     * @param payload - Action payload (only when first arg is a string)
     */
    dispatch(actionOrSlice: StoreAction | string, reducerName?: string, payload?: unknown): void {
        let action: StoreAction;

        if (typeof actionOrSlice === 'string') {
            // Positional form: dispatch('workers', 'upsertWorker', data)
            const sliceName = actionOrSlice;
            const type = reducerName ? `${sliceName}/${reducerName}` : `${sliceName}/set`;
            action = {
                type,
                payload,
                meta: { slice: sliceName },
            };
        } else {
            action = actionOrSlice;
        }

        if (this.isBatching) {
            this.batchedActions.push(action);
            return;
        }

        this.processAction(action);
    }

    /**
     * Process an action through middleware and update state.
     *
     * If the target slice has registered reducers, the matching reducer is
     * invoked with `(currentSliceState, payload)` and its return value
     * becomes the new slice state. Otherwise falls back to payload
     * replacement / partial merge behaviour.
     */
    private processAction(action: StoreAction): void {
        const oldState = { ...this.state };

        if (this.debug) {
            console.log('[StateStore] Dispatch:', action.type, action.payload);
        }

        // Run through middleware chain
        const dispatchWithMiddleware = this.applyMiddleware(action);
        dispatchWithMiddleware();

        // Determine the slice being updated from action type or meta
        const sliceName = (action.meta?.slice as string | undefined) ?? action.type.split('/')[0];

        // Update state based on action
        if (sliceName && sliceName in this.state) {
            const newSliceState = this.reduceSlice(sliceName, action);
            this.state = {
                ...this.state,
                [sliceName]: newSliceState,
            };
        }

        // Add to history
        this.addToHistory(action);

        // Clear selector cache on state change
        this.selectorCache.clear();

        // Notify listeners
        this.notifyListeners(oldState, action);

        // Emit state change events
        this.emitStateEvent(EventTypes.STATE_CHANGED, { action, sliceName });
        if (sliceName) {
            this.emitStateEvent(EventTypes.STATE_SLICE_UPDATED, { slice: sliceName, action });
        }
    }

    /**
     * Subscribe to state changes
     * @param listener - Callback function
     * @returns Unsubscribe function
     */
    subscribe(listener: StateListener): () => void {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }

    /**
     * Select a value from state using a selector function
     * @param selector - Selector function
     */
    select<T>(selector: Selector<T>): T {
        return selector(this.state);
    }

    /**
     * Create a memoized selector that caches results
     * @param deps - Dependency selectors
     * @param combiner - Combiner function
     */
    createSelector<T, D extends unknown[]>(deps: { [K in keyof D]: Selector<D[K]> }, combiner: (...args: D) => T): MemoizedSelector<T> {
        let cachedDeps: D | null = null;
        let cachedResult: T | null = null;
        let hits = 0;
        let misses = 0;

        const memoizedSelector = (state: Record<string, unknown>): T => {
            const currentDeps = deps.map(dep => dep(state)) as D;

            // Check if deps changed
            const depsChanged = cachedDeps === null || currentDeps.some((dep, i) => !Object.is(dep, cachedDeps![i]));

            if (depsChanged) {
                misses++;
                cachedDeps = currentDeps;
                cachedResult = combiner(...currentDeps);
            } else {
                hits++;
            }

            return cachedResult as T;
        };

        memoizedSelector.clearCache = () => {
            cachedDeps = null;
            cachedResult = null;
        };

        memoizedSelector.getCacheStats = () => ({ hits, misses });

        return memoizedSelector;
    }

    /**
     * Batch multiple actions together (single notification)
     * @param fn - Function containing dispatch calls
     */
    batch(fn: () => void): void {
        this.isBatching = true;
        this.batchedActions = [];

        try {
            fn();
        } finally {
            this.isBatching = false;

            // Process all batched actions
            if (this.batchedActions.length > 0) {
                const oldState = { ...this.state };

                for (const action of this.batchedActions) {
                    this.processActionSilent(action);
                }

                // Add batch action to history
                this.addToHistory({
                    type: '@@BATCH',
                    meta: { actions: this.batchedActions.map(a => a.type) },
                });

                // Clear selector cache
                this.selectorCache.clear();

                // Single notification for all changes
                this.notifyListeners(oldState, {
                    type: '@@BATCH',
                    meta: { count: this.batchedActions.length },
                });

                this.emitStateEvent(EventTypes.STATE_CHANGED, {
                    action: { type: '@@BATCH' },
                    batchSize: this.batchedActions.length,
                });

                this.batchedActions = [];
            }
        }
    }

    /**
     * Process action without notifications (for batching)
     */
    private processActionSilent(action: StoreAction): void {
        const sliceName = (action.meta?.slice as string | undefined) ?? action.type.split('/')[0];

        if (sliceName && sliceName in this.state) {
            const newSliceState = this.reduceSlice(sliceName, action);
            this.state = {
                ...this.state,
                [sliceName]: newSliceState,
            };
        }
    }

    /**
     * Compute the new state for a slice given an action.
     *
     * If the slice has a registered reducer matching the action suffix,
     * that reducer is invoked. Otherwise falls back to payload replacement
     * or partial merge.
     */
    private reduceSlice(sliceName: string, action: StoreAction): unknown {
        const currentState = this.state[sliceName];
        const actionSuffix = action.type.includes('/') ? action.type.split('/').slice(1).join('/') : undefined;

        // Try registered reducer first
        const reducers = this.sliceReducers.get(sliceName);
        if (reducers && actionSuffix && actionSuffix in reducers) {
            const reducer = reducers[actionSuffix]!;
            return reducer(currentState, action.payload);
        }

        // Fallback: partial merge or full replacement
        const isPartialUpdate = action.meta?.partial === true;

        if (isPartialUpdate && typeof currentState === 'object' && currentState !== null) {
            return {
                ...(currentState as Record<string, unknown>),
                ...(action.payload as Record<string, unknown>),
            };
        }

        return action.payload;
    }

    /**
     * Get state history
     * @param limit - Maximum entries to return
     */
    getHistory(limit?: number): HistoryEntry[] {
        const result = [...this.history];
        if (limit !== undefined && limit > 0) {
            return result.slice(-limit);
        }
        return result;
    }

    /**
     * Undo the last action (if history available)
     * @returns Whether undo was successful
     */
    undo(): boolean {
        if (this.history.length < 2) {
            return false;
        }

        // Remove current state
        this.history.pop();

        // Get previous state
        const previousEntry = this.history[this.history.length - 1];
        if (previousEntry) {
            const oldState = { ...this.state };
            this.state = { ...previousEntry.state };

            // Clear selector cache
            this.selectorCache.clear();

            // Notify listeners
            this.notifyListeners(oldState, { type: '@@UNDO' });
            this.emitStateEvent(EventTypes.STATE_CHANGED, { action: { type: '@@UNDO' } });

            return true;
        }

        return false;
    }

    /**
     * Garbage collect - clear history and selector cache
     */
    gc(): void {
        // Keep only the most recent history entry
        if (this.history.length > 1) {
            this.history = [this.history[this.history.length - 1]!];
        }

        // Clear selector cache
        this.selectorCache.clear();

        if (this.debug) {
            console.log('[StateStore] GC complete');
        }
    }

    /**
     * Reset store to initial state
     * @param initialSlices - New initial slices
     */
    reset(initialSlices: Record<string, unknown>): void {
        const oldState = { ...this.state };
        this.state = { ...initialSlices };
        this.history = [];
        this.selectorCache.clear();

        this.addToHistory({ type: '@@RESET' });
        this.notifyListeners(oldState, { type: '@@RESET' });
        this.emitStateEvent(EventTypes.STATE_INITIALIZED);
    }

    /**
     * Add middleware
     * @param middleware - Middleware function
     */
    use(middleware: StoreMiddleware): void {
        this.middleware.push(middleware);
    }

    /**
     * Apply middleware chain to dispatch
     */
    private applyMiddleware(action: StoreAction): () => void {
        const storeApi: StoreAPI = {
            getState: () => this.getState(),
            getSlice: <T>(name: string) => this.getSlice<T>(name),
            dispatch: ((actionOrSlice: StoreAction | string, reducerName?: string, payload?: unknown) => this.dispatch(actionOrSlice as StoreAction, reducerName, payload)) as StoreDispatch,
            subscribe: (listener: StateListener) => this.subscribe(listener),
        };

        // Build middleware chain
        let dispatch = () => {};

        const chain = this.middleware.map(mw => mw(storeApi));
        dispatch = chain.reduceRight(
            (next, mw) => () => mw(next)(action),
            () => {}
        );

        return dispatch;
    }

    /**
     * Add entry to history
     */
    private addToHistory(action: StoreAction): void {
        this.history.push({
            state: { ...this.state },
            action,
            timestamp: Date.now(),
        });

        // Trim history if exceeds max size
        if (this.history.length > this.maxHistorySize) {
            this.history = this.history.slice(-this.maxHistorySize);
        }
    }

    /**
     * Notify all listeners of state change
     */
    private notifyListeners(oldState: Record<string, unknown>, action: StoreAction): void {
        for (const listener of this.listeners) {
            try {
                listener(this.state, oldState, action);
            } catch (error) {
                console.error('[StateStore] Error in listener:', error);
            }
        }
    }

    /**
     * Emit state event to EventBus
     */
    private emitStateEvent(eventType: string, data?: Record<string, unknown>): void {
        if (this.eventBus) {
            this.eventBus
                .emit(eventType, {
                    ...data,
                    state: this.getState(),
                    timestamp: Date.now(),
                })
                .catch(err => {
                    console.error('[StateStore] Error emitting event:', err);
                });
        }
    }
}
