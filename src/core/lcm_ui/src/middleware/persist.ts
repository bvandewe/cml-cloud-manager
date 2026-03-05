/**
 * Persist Middleware
 *
 * Persists state to localStorage (or custom storage) with configurable:
 * - Whitelist/blacklist for slices
 * - Debounced writes for performance
 * - Automatic rehydration on init
 *
 * @example
 * ```typescript
 * import { StateStore, createPersistMiddleware } from '@neuroglia/ui-core';
 *
 * const store = new StateStore({
 *   slices: {
 *     user: { name: '', preferences: {} },
 *     ui: { theme: 'light' }
 *   },
 *   middleware: [
 *     createPersistMiddleware({
 *       key: 'my-app-state',
 *       whitelist: ['user', 'ui'],  // Only persist these slices
 *       debounce: 500
 *     })
 *   ]
 * });
 *
 * // Manually trigger save or clear
 * store.dispatch({ type: '@@persist/SAVE' });
 * store.dispatch({ type: '@@persist/CLEAR' });
 * ```
 *
 * @module middleware
 */

import type { StoreMiddleware, StoreAction, StoreAPI } from '../types/store.js';

/**
 * Persist middleware options
 */
export interface PersistOptions {
    /** Storage key (required) */
    key: string;
    /** Slices to persist (empty = all) */
    whitelist?: string[];
    /** Slices to exclude from persistence */
    blacklist?: string[];
    /** Storage implementation (default: localStorage) */
    storage?: Storage;
    /** Debounce time for writes in ms (default: 100) */
    debounce?: number;
    /** Custom serializer (default: JSON.stringify) */
    serialize?: (state: Record<string, unknown>) => string;
    /** Custom deserializer (default: JSON.parse) */
    deserialize?: (data: string) => Record<string, unknown>;
    /** Version for migrations */
    version?: number;
    /** Migration function for version updates */
    migrate?: (state: Record<string, unknown>, version: number) => Record<string, unknown>;
    /** Callback on persist error */
    onError?: (error: Error, operation: 'save' | 'load') => void;
    /** Callback after successful rehydration */
    onRehydrate?: (state: Record<string, unknown>) => void;
    /** Enable debug logging */
    debug?: boolean;
}

/**
 * Persisted state wrapper
 */
interface PersistedData {
    version: number;
    state: Record<string, unknown>;
    timestamp: number;
}

/**
 * Default persist options
 */
const DEFAULT_OPTIONS = {
    debounce: 100,
    serialize: JSON.stringify,
    deserialize: JSON.parse,
    version: 1,
    debug: false,
};

/**
 * In-memory storage fallback for SSR/testing
 */
class MemoryStorage implements Storage {
    private data = new Map<string, string>();

    get length(): number {
        return this.data.size;
    }

    key(index: number): string | null {
        return [...this.data.keys()][index] ?? null;
    }

    getItem(key: string): string | null {
        return this.data.get(key) ?? null;
    }

    setItem(key: string, value: string): void {
        this.data.set(key, value);
    }

    removeItem(key: string): void {
        this.data.delete(key);
    }

    clear(): void {
        this.data.clear();
    }
}

/**
 * Get storage implementation safely
 */
function getStorage(providedStorage?: Storage): Storage {
    if (providedStorage) {
        return providedStorage;
    }

    // Try localStorage
    if (typeof window !== 'undefined' && window.localStorage) {
        try {
            // Test if localStorage is available
            const testKey = '__persist_test__';
            window.localStorage.setItem(testKey, 'test');
            window.localStorage.removeItem(testKey);
            return window.localStorage;
        } catch {
            // localStorage not available (e.g., private browsing)
        }
    }

    // Fallback to in-memory storage
    return new MemoryStorage();
}

/**
 * Create persist middleware
 *
 * @param options - Persist options
 * @returns Middleware function
 */
export function createPersistMiddleware(options: PersistOptions): StoreMiddleware {
    const config = {
        ...DEFAULT_OPTIONS,
        ...options,
        storage: getStorage(options.storage),
    };

    let saveTimeoutId: ReturnType<typeof setTimeout> | null = null;
    let initialized = false;

    /**
     * Filter state based on whitelist/blacklist
     */
    function filterState(state: Record<string, unknown>): Record<string, unknown> {
        const keys = Object.keys(state);
        let filteredKeys = keys;

        // Apply whitelist
        if (config.whitelist && config.whitelist.length > 0) {
            filteredKeys = filteredKeys.filter(k => config.whitelist!.includes(k));
        }

        // Apply blacklist
        if (config.blacklist && config.blacklist.length > 0) {
            filteredKeys = filteredKeys.filter(k => !config.blacklist!.includes(k));
        }

        const result: Record<string, unknown> = {};
        for (const key of filteredKeys) {
            result[key] = state[key];
        }
        return result;
    }

    /**
     * Save state to storage
     */
    function saveState(state: Record<string, unknown>): void {
        try {
            const filteredState = filterState(state);
            const data: PersistedData = {
                version: config.version,
                state: filteredState,
                timestamp: Date.now(),
            };
            const serialized = config.serialize(data as unknown as Record<string, unknown>);
            config.storage.setItem(config.key, serialized);

            if (config.debug) {
                console.log(`[Persist:${config.key}] State saved`, filteredState);
            }
        } catch (error) {
            if (config.onError) {
                config.onError(error as Error, 'save');
            } else if (config.debug) {
                console.error(`[Persist:${config.key}] Save error:`, error);
            }
        }
    }

    /**
     * Load state from storage
     */
    function loadState(): Record<string, unknown> | null {
        try {
            const serialized = config.storage.getItem(config.key);
            if (!serialized) {
                return null;
            }

            const data = config.deserialize(serialized) as PersistedData;

            // Handle version migration
            let state = data.state;
            if (data.version !== config.version && config.migrate) {
                state = config.migrate(state, data.version);
                if (config.debug) {
                    console.log(`[Persist:${config.key}] Migrated from v${data.version} to v${config.version}`);
                }
            }

            if (config.debug) {
                console.log(`[Persist:${config.key}] State loaded`, state);
            }

            return state;
        } catch (error) {
            if (config.onError) {
                config.onError(error as Error, 'load');
            } else if (config.debug) {
                console.error(`[Persist:${config.key}] Load error:`, error);
            }
            return null;
        }
    }

    /**
     * Clear persisted state
     */
    function clearState(): void {
        try {
            config.storage.removeItem(config.key);
            if (config.debug) {
                console.log(`[Persist:${config.key}] State cleared`);
            }
        } catch (error) {
            if (config.onError) {
                config.onError(error as Error, 'save');
            }
        }
    }

    /**
     * Debounced save
     */
    function debouncedSave(state: Record<string, unknown>): void {
        if (saveTimeoutId) {
            clearTimeout(saveTimeoutId);
        }
        saveTimeoutId = setTimeout(() => {
            saveTimeoutId = null;
            saveState(state);
        }, config.debounce);
    }

    return (store: StoreAPI) => {
        // Rehydrate state on initialization
        if (!initialized) {
            initialized = true;
            const persistedState = loadState();

            if (persistedState) {
                // Dispatch rehydration action
                // This is done asynchronously to allow store to finish initializing
                queueMicrotask(() => {
                    store.dispatch({
                        type: '@@persist/REHYDRATE',
                        payload: persistedState,
                        meta: { source: 'persist' },
                    });

                    if (config.onRehydrate) {
                        config.onRehydrate(persistedState);
                    }
                });
            }
        }

        return next => (action: StoreAction) => {
            // Handle special persist actions
            if (action.type === '@@persist/SAVE') {
                saveState(store.getState());
                return undefined;
            }

            if (action.type === '@@persist/CLEAR') {
                clearState();
                return undefined;
            }

            // Handle rehydration
            if (action.type === '@@persist/REHYDRATE') {
                // Merge persisted state with current state
                const persistedState = action.payload as Record<string, unknown>;
                for (const [slice, value] of Object.entries(persistedState)) {
                    store.dispatch({
                        type: `${slice}/set`,
                        payload: value,
                        meta: { slice, source: 'rehydrate' },
                    });
                }
                return undefined;
            }

            // Execute action
            const result = next(action);

            // Persist state after action (debounced)
            // Skip internal actions
            if (!action.type.startsWith('@@')) {
                debouncedSave(store.getState());
            }

            return result;
        };
    };
}

/**
 * Create persist middleware with session storage
 */
export function createSessionPersistMiddleware(options: Omit<PersistOptions, 'storage'>): StoreMiddleware {
    const storage = typeof window !== 'undefined' && window.sessionStorage ? window.sessionStorage : new MemoryStorage();

    return createPersistMiddleware({
        ...options,
        storage,
    });
}
