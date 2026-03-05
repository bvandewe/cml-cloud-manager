/**
 * Devtools Middleware
 *
 * Exposes the store to the browser's developer tools for debugging.
 * - Adds `window.__STORE__` for direct state inspection
 * - Provides time-travel debugging via history
 * - Enables action replay
 *
 * @example
 * ```typescript
 * import { StateStore, createDevtoolsMiddleware } from '@neuroglia/ui-core';
 *
 * const store = new StateStore({
 *   slices: { counter: { value: 0 } },
 *   middleware: [
 *     createDevtoolsMiddleware({ name: 'MyApp' })
 *   ]
 * });
 *
 * // In browser console:
 * // window.__STORE__.getState()
 * // window.__STORE__.dispatch({ type: 'counter/set', payload: { value: 10 } })
 * // window.__STORE__.history()
 * ```
 *
 * @module middleware
 */

import type { StoreMiddleware, StoreAction, StoreAPI } from '../types/store.js';

/**
 * Devtools options
 */
export interface DevtoolsOptions {
    /** Name for the store (useful with multiple stores) */
    name?: string;
    /** Whether devtools are enabled (default: true in development) */
    enabled?: boolean;
    /** Maximum actions to keep in history (default: 100) */
    maxHistory?: number;
    /** Whether to log actions to console (default: false) */
    logActions?: boolean;
}

/**
 * Devtools store interface exposed to window
 */
export interface DevtoolsStore {
    /** Get current state */
    getState: () => Record<string, unknown>;
    /** Get a specific slice */
    getSlice: <T>(name: string) => T | undefined;
    /** Dispatch an action */
    dispatch: (action: StoreAction) => void;
    /** Get action history */
    history: () => DevtoolsHistoryEntry[];
    /** Jump to a specific point in history */
    jumpTo: (index: number) => void;
    /** Clear action history */
    clearHistory: () => void;
    /** Replay all actions from beginning */
    replay: () => void;
    /** Export state as JSON */
    exportState: () => string;
    /** Import state from JSON */
    importState: (json: string) => void;
    /** Store name */
    name: string;
}

/**
 * Devtools history entry
 */
export interface DevtoolsHistoryEntry {
    /** Action index */
    index: number;
    /** Action that was dispatched */
    action: StoreAction;
    /** State after action */
    state: Record<string, unknown>;
    /** Timestamp */
    timestamp: number;
}

/**
 * Default devtools options
 */
const DEFAULT_OPTIONS: Required<DevtoolsOptions> = {
    name: 'store',
    enabled: true, // Enable by default - let tests control this
    maxHistory: 100,
    logActions: false,
};

/**
 * Declare global window extension
 */
declare global {
    interface Window {
        __STORE__?: DevtoolsStore;
        __STORES__?: Map<string, DevtoolsStore>;
    }
}

/**
 * Create devtools middleware
 *
 * @param options - Devtools options
 * @returns Middleware function
 */
export function createDevtoolsMiddleware(options: DevtoolsOptions = {}): StoreMiddleware {
    const config = { ...DEFAULT_OPTIONS, ...options };
    const history: DevtoolsHistoryEntry[] = [];
    let actionIndex = 0;

    return (store: StoreAPI) => {
        // Skip if disabled or not in browser
        if (!config.enabled || typeof window === 'undefined') {
            return next => (action: StoreAction) => next(action);
        }

        // Create devtools store interface
        const devtoolsStore: DevtoolsStore = {
            name: config.name,

            getState: () => store.getState(),

            getSlice: <T>(name: string) => store.getSlice<T>(name),

            dispatch: (action: StoreAction) => store.dispatch(action),

            history: () => [...history],

            jumpTo: (index: number) => {
                const entry = history.find(h => h.index === index);
                if (entry) {
                    // Dispatch a special action to restore state
                    store.dispatch({
                        type: '@@devtools/JUMP_TO',
                        payload: entry.state,
                        meta: { targetIndex: index },
                    });
                    console.log(`[Devtools:${config.name}] Jumped to action #${index}`);
                } else {
                    console.warn(`[Devtools:${config.name}] No action at index ${index}`);
                }
            },

            clearHistory: () => {
                history.length = 0;
                actionIndex = 0;
                console.log(`[Devtools:${config.name}] History cleared`);
            },

            replay: () => {
                console.group(`[Devtools:${config.name}] Replaying ${history.length} actions`);
                for (const entry of history) {
                    if (entry.action.type !== '@@INIT' && !entry.action.type.startsWith('@@devtools/')) {
                        store.dispatch(entry.action);
                    }
                }
                console.groupEnd();
            },

            exportState: () => {
                return JSON.stringify(
                    {
                        state: store.getState(),
                        history: history.map(h => ({
                            index: h.index,
                            action: h.action,
                            timestamp: h.timestamp,
                        })),
                    },
                    null,
                    2
                );
            },

            importState: (json: string) => {
                try {
                    const data = JSON.parse(json);
                    if (data.state) {
                        store.dispatch({
                            type: '@@devtools/IMPORT_STATE',
                            payload: data.state,
                        });
                        console.log(`[Devtools:${config.name}] State imported`);
                    }
                } catch (error) {
                    console.error(`[Devtools:${config.name}] Failed to import state:`, error);
                }
            },
        };

        // Expose to window
        if (typeof window !== 'undefined') {
            // Support single store
            window.__STORE__ = devtoolsStore;

            // Support multiple stores
            if (!window.__STORES__) {
                window.__STORES__ = new Map();
            }
            window.__STORES__.set(config.name, devtoolsStore);

            console.log(`[Devtools] Store "${config.name}" available at window.__STORE__ or window.__STORES__.get("${config.name}")`);
        }

        return next => (action: StoreAction) => {
            const result = next(action);

            // Record in history
            const entry: DevtoolsHistoryEntry = {
                index: actionIndex++,
                action,
                state: store.getState(),
                timestamp: Date.now(),
            };

            history.push(entry);

            // Trim history if needed
            while (history.length > config.maxHistory) {
                history.shift();
            }

            // Optional logging
            if (config.logActions) {
                console.log(`[Devtools:${config.name}] #${entry.index} ${action.type}`, action.payload);
            }

            return result;
        };
    };
}

/**
 * Pre-configured devtools middleware
 */
export const devtoolsMiddleware = createDevtoolsMiddleware();
