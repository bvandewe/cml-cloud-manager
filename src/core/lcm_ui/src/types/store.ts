/**
 * State store type definitions
 */

/**
 * State slice definition
 */
export interface SliceDefinition<T = unknown> {
    /** Slice name/key */
    name: string;
    /** Initial state value */
    initialState: T;
    /** Optional reducers for this slice */
    reducers?: Record<string, SliceReducer<T>>;
}

/**
 * Slice reducer function
 */
export type SliceReducer<T = unknown> = (state: T, payload: unknown) => T;

/**
 * Store configuration options
 */
export interface StoreConfig {
    /** State slice definitions */
    slices: Record<string, unknown>;
    /** Middleware to apply */
    middleware?: StoreMiddleware[];
    /** Maximum state history size */
    maxHistorySize?: number;
    /** Whether to enable devtools */
    devtools?: boolean;
}

/**
 * Store middleware function
 */
export type StoreMiddleware = (store: StoreAPI) => (next: StoreDispatch) => (action: StoreAction) => unknown;

/**
 * Store dispatch function.
 * Supports both action-object and positional (slice, reducer, payload) forms.
 */
export type StoreDispatch = {
    (action: StoreAction): void;
    (sliceName: string, reducerName: string, payload?: unknown): void;
};

/**
 * Store action
 */
export interface StoreAction {
    /** Action type identifier */
    type: string;
    /** Action payload */
    payload?: unknown;
    /** Action metadata */
    meta?: Record<string, unknown>;
}

/**
 * Store API exposed to middleware and selectors
 */
export interface StoreAPI {
    /** Get current state */
    getState: () => Record<string, unknown>;
    /** Get a specific slice */
    getSlice: <T>(name: string) => T | undefined;
    /** Dispatch an action (object or positional form) */
    dispatch: StoreDispatch;
    /** Subscribe to state changes */
    subscribe: (listener: StateListener) => () => void;
}

/**
 * State change listener
 */
export type StateListener = (newState: Record<string, unknown>, oldState: Record<string, unknown>, action: StoreAction) => void;

/**
 * Selector function
 */
export type Selector<T = unknown> = (state: Record<string, unknown>) => T;

/**
 * Memoized selector with cache
 */
export interface MemoizedSelector<T = unknown> {
    /** Get the selected value */
    (state: Record<string, unknown>): T;
    /** Clear the selector cache */
    clearCache: () => void;
    /** Get cache hit statistics */
    getCacheStats: () => { hits: number; misses: number };
}

/**
 * State history entry
 */
export interface HistoryEntry {
    /** State snapshot */
    state: Record<string, unknown>;
    /** Action that caused this state */
    action: StoreAction;
    /** Timestamp of the change */
    timestamp: number;
}
