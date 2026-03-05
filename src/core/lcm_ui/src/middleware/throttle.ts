/**
 * Throttle Middleware
 *
 * Throttles rapid state updates to improve performance.
 * Useful for high-frequency updates like:
 * - Mouse/scroll position tracking
 * - Real-time metrics updates
 * - Form input changes
 *
 * @example
 * ```typescript
 * import { StateStore, createThrottleMiddleware } from '@neuroglia/ui-core';
 *
 * const store = new StateStore({
 *   slices: { metrics: { cpu: 0, memory: 0 } },
 *   middleware: [
 *     createThrottleMiddleware({
 *       // Throttle metrics updates to max 1 per 100ms
 *       throttledActions: ['metrics/update'],
 *       wait: 100
 *     })
 *   ]
 * });
 * ```
 *
 * @module middleware
 */

import type { StoreMiddleware, StoreAction, StoreAPI } from '../types/store.js';

/**
 * Throttle middleware options
 */
export interface ThrottleOptions {
    /** Action types to throttle */
    throttledActions: string[];
    /** Throttle wait time in ms (default: 100) */
    wait?: number;
    /** Whether to execute on leading edge (default: true) */
    leading?: boolean;
    /** Whether to execute on trailing edge (default: true) */
    trailing?: boolean;
    /** Custom throttle function per action type */
    actionThrottles?: Record<string, number>;
    /** Callback when action is throttled */
    onThrottle?: (action: StoreAction) => void;
}

/**
 * Throttle state for tracking pending actions
 */
interface ThrottleState {
    lastCall: number;
    pending: StoreAction | null;
    timeoutId: ReturnType<typeof setTimeout> | null;
}

/**
 * Default throttle options
 */
const DEFAULT_OPTIONS = {
    wait: 100,
    leading: true,
    trailing: true,
};

/**
 * Create throttle middleware
 *
 * @param options - Throttle options
 * @returns Middleware function
 */
export function createThrottleMiddleware(options: ThrottleOptions): StoreMiddleware {
    const config = { ...DEFAULT_OPTIONS, ...options };
    const throttleStates = new Map<string, ThrottleState>();

    /**
     * Get throttle wait time for an action
     */
    function getWaitTime(actionType: string): number {
        return config.actionThrottles?.[actionType] ?? config.wait;
    }

    /**
     * Get or create throttle state for an action type
     */
    function getThrottleState(actionType: string): ThrottleState {
        let state = throttleStates.get(actionType);
        if (!state) {
            state = { lastCall: 0, pending: null, timeoutId: null };
            throttleStates.set(actionType, state);
        }
        return state;
    }

    return (_store: StoreAPI) => next => (action: StoreAction) => {
        // Check if this action should be throttled
        if (!config.throttledActions.includes(action.type)) {
            return next(action);
        }

        const state = getThrottleState(action.type);
        const wait = getWaitTime(action.type);
        const now = Date.now();
        const elapsed = now - state.lastCall;

        /**
         * Execute trailing call
         */
        function executeTrailing() {
            if (state.pending) {
                const pendingAction = state.pending;
                state.pending = null;
                state.lastCall = Date.now();
                next(pendingAction);
            }
        }

        // Leading edge: execute immediately if enough time has passed
        if (elapsed >= wait) {
            // Clear any pending trailing call
            if (state.timeoutId) {
                clearTimeout(state.timeoutId);
                state.timeoutId = null;
            }

            if (config.leading) {
                state.lastCall = now;
                state.pending = null;
                return next(action);
            }
        }

        // Store as pending for trailing edge
        if (config.trailing) {
            state.pending = action;

            // Set up trailing edge execution
            if (!state.timeoutId) {
                const remaining = wait - elapsed;
                state.timeoutId = setTimeout(() => {
                    state.timeoutId = null;
                    executeTrailing();
                }, remaining);
            }
        }

        // Notify that action was throttled
        if (config.onThrottle) {
            config.onThrottle(action);
        }

        return undefined;
    };
}

/**
 * Debounce middleware options
 */
export interface DebounceOptions {
    /** Action types to debounce */
    debouncedActions: string[];
    /** Debounce wait time in ms (default: 300) */
    wait?: number;
    /** Custom debounce time per action type */
    actionDebounces?: Record<string, number>;
    /** Whether to execute on leading edge (default: false) */
    leading?: boolean;
    /** Callback when action is debounced */
    onDebounce?: (action: StoreAction) => void;
}

/**
 * Debounce state for tracking timers
 */
interface DebounceState {
    timeoutId: ReturnType<typeof setTimeout> | null;
    leadingExecuted: boolean;
}

/**
 * Default debounce options
 */
const DEFAULT_DEBOUNCE_OPTIONS = {
    wait: 300,
    leading: false,
};

/**
 * Create debounce middleware
 *
 * Unlike throttle which limits rate, debounce waits until
 * activity stops before executing.
 *
 * @param options - Debounce options
 * @returns Middleware function
 */
export function createDebounceMiddleware(options: DebounceOptions): StoreMiddleware {
    const config = { ...DEFAULT_DEBOUNCE_OPTIONS, ...options };
    const debounceStates = new Map<string, DebounceState>();

    /**
     * Get debounce wait time for an action
     */
    function getWaitTime(actionType: string): number {
        return config.actionDebounces?.[actionType] ?? config.wait;
    }

    /**
     * Get or create debounce state for an action type
     */
    function getDebounceState(actionType: string): DebounceState {
        let state = debounceStates.get(actionType);
        if (!state) {
            state = { timeoutId: null, leadingExecuted: false };
            debounceStates.set(actionType, state);
        }
        return state;
    }

    return (_store: StoreAPI) => next => (action: StoreAction) => {
        // Check if this action should be debounced
        if (!config.debouncedActions.includes(action.type)) {
            return next(action);
        }

        const state = getDebounceState(action.type);
        const wait = getWaitTime(action.type);

        // Clear existing timeout
        if (state.timeoutId) {
            clearTimeout(state.timeoutId);
            state.timeoutId = null;
        }

        // Leading edge: execute immediately on first call
        if (config.leading && !state.leadingExecuted) {
            state.leadingExecuted = true;
            state.timeoutId = setTimeout(() => {
                state.timeoutId = null;
                state.leadingExecuted = false;
            }, wait);
            return next(action);
        }

        // Set up trailing edge execution
        state.timeoutId = setTimeout(() => {
            state.timeoutId = null;
            state.leadingExecuted = false;
            next(action);
        }, wait);

        // Notify that action was debounced
        if (config.onDebounce) {
            config.onDebounce(action);
        }

        return undefined;
    };
}
