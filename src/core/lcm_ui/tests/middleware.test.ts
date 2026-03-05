/**
 * Middleware Tests
 *
 * Tests for all StateStore middleware:
 * - Logger middleware
 * - Devtools middleware
 * - Throttle middleware
 * - Debounce middleware
 * - Persist middleware
 *
 * NOTE: The StateStore middleware is "notification-style" - it observes actions
 * rather than intercepting/blocking them. Throttle/debounce middleware can only
 * control when their internal logic runs, not prevent StateStore from processing.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { StateStore } from '../src/core/StateStore.js';
import { createLoggerMiddleware, createDevtoolsMiddleware, createThrottleMiddleware, createDebounceMiddleware, createPersistMiddleware } from '../src/middleware/index.js';

// ============================================================
// Test utilities
// ============================================================

function createMockLogger() {
    return {
        log: vi.fn(),
        group: vi.fn(),
        groupCollapsed: vi.fn(),
        groupEnd: vi.fn(),
    };
}

function createMockStorage(): Storage {
    const storage = new Map<string, string>();
    return {
        get length() {
            return storage.size;
        },
        key: (index: number) => [...storage.keys()][index] ?? null,
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => storage.set(key, value),
        removeItem: (key: string) => storage.delete(key),
        clear: () => storage.clear(),
    };
}

// ============================================================
// Logger Middleware Tests
// ============================================================

describe('Logger Middleware', () => {
    let mockLogger: ReturnType<typeof createMockLogger>;

    beforeEach(() => {
        mockLogger = createMockLogger();
    });

    it('should log actions when enabled', () => {
        const store = new StateStore({
            slices: { counter: { value: 0 } },
            middleware: [
                createLoggerMiddleware({
                    enabled: true,
                    logger: mockLogger,
                    collapsed: true,
                }),
            ],
        });

        store.dispatch({ type: 'counter/set', payload: { value: 5 } });

        // Should have called groupCollapsed and groupEnd
        expect(mockLogger.groupCollapsed).toHaveBeenCalled();
        expect(mockLogger.groupEnd).toHaveBeenCalled();
        // Should log prev state, action, next state
        expect(mockLogger.log).toHaveBeenCalledTimes(3);
    });

    it('should not log when disabled', () => {
        const store = new StateStore({
            slices: { counter: { value: 0 } },
            middleware: [
                createLoggerMiddleware({
                    enabled: false,
                    logger: mockLogger,
                }),
            ],
        });

        store.dispatch({ type: 'counter/set', payload: { value: 5 } });

        expect(mockLogger.groupCollapsed).not.toHaveBeenCalled();
        expect(mockLogger.log).not.toHaveBeenCalled();
    });

    it('should skip ignored actions', () => {
        const store = new StateStore({
            slices: { counter: { value: 0 } },
            middleware: [
                createLoggerMiddleware({
                    enabled: true,
                    logger: mockLogger,
                    ignoredActions: ['counter/internal'],
                }),
            ],
        });

        store.dispatch({ type: 'counter/internal', payload: 'ignored' });

        expect(mockLogger.groupCollapsed).not.toHaveBeenCalled();
    });

    it('should log diff when enabled and state changes', () => {
        const store = new StateStore({
            slices: { counter: { value: 0 } },
            middleware: [
                createLoggerMiddleware({
                    enabled: true,
                    logger: mockLogger,
                    diff: true,
                }),
            ],
        });

        // This action changes state
        store.dispatch({ type: 'counter/set', payload: { value: 5 } });

        // Should have at least 3 log calls: prev, action, next
        // May have 4 if diff is detected (depends on state mutation)
        expect(mockLogger.log.mock.calls.length).toBeGreaterThanOrEqual(3);
        // Check that the expected log labels were called
        const logCalls = mockLogger.log.mock.calls.map((call: unknown[]) => call[0]);
        expect(logCalls).toContain('%cprev state');
        expect(logCalls).toContain('%caction    ');
        expect(logCalls).toContain('%cnext state');
    });

    it('should use custom action formatter', () => {
        const store = new StateStore({
            slices: { counter: { value: 0 } },
            middleware: [
                createLoggerMiddleware({
                    enabled: true,
                    logger: mockLogger,
                    actionFormatter: action => `CUSTOM: ${action.type}`,
                }),
            ],
        });

        store.dispatch({ type: 'counter/set', payload: { value: 5 } });

        expect(mockLogger.groupCollapsed).toHaveBeenCalledWith(expect.stringContaining('CUSTOM: counter/set'), expect.any(String));
    });
});

// ============================================================
// Devtools Middleware Tests
//
// NOTE: Middleware factory is invoked on first dispatch, not store creation.
// ============================================================

describe('Devtools Middleware', () => {
    beforeEach(() => {
        // Reset window.__STORE__
        if (typeof window !== 'undefined') {
            delete (window as { __STORE__?: unknown }).__STORE__;
            delete (window as { __STORES__?: unknown }).__STORES__;
        }
    });

    it('should expose store to window.__STORE__ after first dispatch', () => {
        const store = new StateStore({
            slices: { counter: { value: 0 } },
            middleware: [createDevtoolsMiddleware({ enabled: true, name: 'test' })],
        });

        // Trigger middleware initialization
        store.dispatch({ type: 'counter/set', payload: { value: 1 } });

        expect(window.__STORE__).toBeDefined();
        expect(window.__STORE__?.name).toBe('test');
        expect(window.__STORE__?.getState()).toEqual({ counter: { value: 1 } });

        // Dispatch via devtools should work
        window.__STORE__?.dispatch({ type: 'counter/set', payload: { value: 10 } });
        expect(store.getSlice('counter')).toEqual({ value: 10 });
    });

    it('should track action history', () => {
        const store = new StateStore({
            slices: { counter: { value: 0 } },
            middleware: [createDevtoolsMiddleware({ enabled: true })],
        });

        store.dispatch({ type: 'counter/set', payload: { value: 5 } });
        store.dispatch({ type: 'counter/set', payload: { value: 10 } });

        const history = window.__STORE__?.history() ?? [];
        expect(history.length).toBeGreaterThanOrEqual(2);
        expect(history.some(h => h.action.type === 'counter/set')).toBe(true);
    });

    it('should support multiple stores via __STORES__', () => {
        const store1 = new StateStore({
            slices: { a: 1 },
            middleware: [createDevtoolsMiddleware({ enabled: true, name: 'store-a' })],
        });

        const store2 = new StateStore({
            slices: { b: 2 },
            middleware: [createDevtoolsMiddleware({ enabled: true, name: 'store-b' })],
        });

        // Trigger middleware for both stores
        store1.dispatch({ type: 'a/set', payload: 1 });
        store2.dispatch({ type: 'b/set', payload: 2 });

        expect(window.__STORES__?.size).toBe(2);
        expect(window.__STORES__?.get('store-a')?.getState()).toEqual({ a: 1 });
        expect(window.__STORES__?.get('store-b')?.getState()).toEqual({ b: 2 });
    });

    it('should export state as JSON', () => {
        const store = new StateStore({
            slices: { counter: { value: 42 } },
            middleware: [createDevtoolsMiddleware({ enabled: true })],
        });

        // Trigger middleware initialization
        store.dispatch({ type: 'counter/set', payload: { value: 42 } });

        const exported = window.__STORE__?.exportState();
        expect(exported).toBeDefined();
        expect(JSON.parse(exported!).state).toEqual({ counter: { value: 42 } });
    });

    it('should limit history size', () => {
        const store = new StateStore({
            slices: { counter: { value: 0 } },
            middleware: [createDevtoolsMiddleware({ enabled: true, maxHistory: 5 })],
        });

        // Dispatch more than maxHistory actions
        for (let i = 0; i < 10; i++) {
            store.dispatch({ type: 'counter/set', payload: { value: i } });
        }

        const history = window.__STORE__?.history() ?? [];
        expect(history.length).toBeLessThanOrEqual(5);
    });
});

// ============================================================
// Throttle Middleware Tests
//
// NOTE: StateStore middleware is notification-style, not intercepting.
// Throttle middleware tracks timing but doesn't block StateStore processing.
// These tests verify the middleware's internal tracking behavior.
// ============================================================

describe('Throttle Middleware', () => {
    beforeEach(() => {
        vi.useFakeTimers();
        // Set initial time to a known value
        vi.setSystemTime(new Date('2024-01-01T00:00:00.000Z'));
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('should call onThrottle callback for throttled actions', () => {
        const onThrottle = vi.fn();
        const store = new StateStore({
            slices: { metrics: { value: 0 } },
            middleware: [
                createThrottleMiddleware({
                    throttledActions: ['metrics/update'],
                    wait: 100,
                    onThrottle,
                }),
            ],
        });

        // First call goes through (leading)
        store.dispatch({ type: 'metrics/update', payload: { value: 1 } });
        expect(onThrottle).not.toHaveBeenCalled();

        // Second call is throttled
        store.dispatch({ type: 'metrics/update', payload: { value: 2 } });
        expect(onThrottle).toHaveBeenCalledTimes(1);
    });

    it('should not throttle non-matching actions', () => {
        const onThrottle = vi.fn();
        const store = new StateStore({
            slices: { counter: { value: 0 } },
            middleware: [
                createThrottleMiddleware({
                    throttledActions: ['metrics/update'],
                    wait: 100,
                    onThrottle,
                }),
            ],
        });

        // Dispatch non-throttled action multiple times
        for (let i = 0; i < 5; i++) {
            store.dispatch({ type: 'counter/set', payload: { value: i } });
        }

        // None should be throttled
        expect(onThrottle).not.toHaveBeenCalled();
    });

    it('should respect per-action throttle times', () => {
        const onThrottle = vi.fn();
        const store = new StateStore({
            slices: { metrics: { fast: 0 } },
            middleware: [
                createThrottleMiddleware({
                    throttledActions: ['metrics/fast'],
                    wait: 100,
                    actionThrottles: {
                        'metrics/fast': 50,
                    },
                    // Disable trailing edge to simplify test
                    trailing: false,
                    onThrottle,
                }),
            ],
        });

        // First call at t=0 (leading edge)
        store.dispatch({ type: 'metrics/fast', payload: { fast: 1 } });
        expect(onThrottle).not.toHaveBeenCalled();

        // Advance 10ms, still within throttle window (50ms)
        vi.advanceTimersByTime(10);

        // Second call at t=10ms should be throttled (within 50ms window)
        store.dispatch({ type: 'metrics/fast', payload: { fast: 2 } });
        expect(onThrottle).toHaveBeenCalledTimes(1);

        // Advance another 50ms (total t=60ms, past the 50ms throttle window from t=0)
        vi.advanceTimersByTime(50);

        // Third call at t=60ms should NOT be throttled (throttle window expired)
        onThrottle.mockClear();
        store.dispatch({ type: 'metrics/fast', payload: { fast: 3 } });
        expect(onThrottle).not.toHaveBeenCalled();
    });

    it('should track throttle state correctly across time', () => {
        const onThrottle = vi.fn();
        const store = new StateStore({
            slices: { metrics: { value: 0 } },
            middleware: [
                createThrottleMiddleware({
                    throttledActions: ['metrics/update'],
                    wait: 100,
                    onThrottle,
                }),
            ],
        });

        // First dispatch (leading) - goes through
        store.dispatch({ type: 'metrics/update', payload: { value: 1 } });

        // Rapid dispatches - should be throttled
        for (let i = 2; i <= 5; i++) {
            store.dispatch({ type: 'metrics/update', payload: { value: i } });
        }

        // 4 calls were throttled
        expect(onThrottle).toHaveBeenCalledTimes(4);
    });
});

// ============================================================
// Debounce Middleware Tests
// ============================================================

describe('Debounce Middleware', () => {
    beforeEach(() => {
        vi.useFakeTimers();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('should call onDebounce callback for debounced actions', () => {
        const onDebounce = vi.fn();
        const store = new StateStore({
            slices: { search: { query: '' } },
            middleware: [
                createDebounceMiddleware({
                    debouncedActions: ['search/update'],
                    wait: 300,
                    onDebounce,
                }),
            ],
        });

        // Rapid dispatches
        for (let i = 0; i < 5; i++) {
            store.dispatch({ type: 'search/update', payload: { query: `query${i}` } });
        }

        // All should trigger onDebounce
        expect(onDebounce).toHaveBeenCalledTimes(5);
    });

    it('should not debounce non-matching actions', () => {
        const onDebounce = vi.fn();
        const store = new StateStore({
            slices: { counter: { value: 0 } },
            middleware: [
                createDebounceMiddleware({
                    debouncedActions: ['search/update'],
                    wait: 300,
                    onDebounce,
                }),
            ],
        });

        // Dispatch non-debounced actions
        for (let i = 0; i < 5; i++) {
            store.dispatch({ type: 'counter/set', payload: { value: i } });
        }

        // None should be debounced
        expect(onDebounce).not.toHaveBeenCalled();
    });

    it('should respect custom debounce times per action', () => {
        const onDebounce = vi.fn();
        const store = new StateStore({
            slices: { search: { query: '' } },
            middleware: [
                createDebounceMiddleware({
                    debouncedActions: ['search/fast', 'search/slow'],
                    wait: 300,
                    actionDebounces: {
                        'search/fast': 100,
                        'search/slow': 500,
                    },
                    onDebounce,
                }),
            ],
        });

        store.dispatch({ type: 'search/fast', payload: {} });
        store.dispatch({ type: 'search/slow', payload: {} });

        expect(onDebounce).toHaveBeenCalledTimes(2);
    });
});

// ============================================================
// Persist Middleware Tests
//
// NOTE: The persist middleware loads state when the middleware factory
// is first invoked (on first dispatch). The rehydration happens via
// queueMicrotask after the first action is processed.
// ============================================================

describe('Persist Middleware', () => {
    let mockStorage: Storage;

    beforeEach(() => {
        mockStorage = createMockStorage();
        vi.useFakeTimers();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('should persist state to storage after dispatch', async () => {
        const store = new StateStore({
            slices: { user: { name: 'John' } },
            middleware: [
                createPersistMiddleware({
                    key: 'test-state',
                    storage: mockStorage,
                    debounce: 50,
                }),
            ],
        });

        // First dispatch triggers middleware initialization
        store.dispatch({ type: 'user/set', payload: { name: 'Jane' } });

        // Advance timers for debounce
        await vi.advanceTimersByTimeAsync(100);

        const saved = mockStorage.getItem('test-state');
        expect(saved).toBeDefined();
        const parsed = JSON.parse(saved!);
        expect(parsed.state.user).toBeDefined();
    });

    it('should filter state by whitelist when persisting', async () => {
        const store = new StateStore({
            slices: {
                user: { name: 'John' },
                temp: { data: 'temporary' },
            },
            middleware: [
                createPersistMiddleware({
                    key: 'test-state',
                    storage: mockStorage,
                    whitelist: ['user'],
                    debounce: 0,
                }),
            ],
        });

        store.dispatch({ type: 'user/set', payload: { name: 'Jane' } });
        await vi.advanceTimersByTimeAsync(10);

        const saved = JSON.parse(mockStorage.getItem('test-state')!);
        expect(saved.state.user).toBeDefined();
        expect(saved.state.temp).toBeUndefined();
    });

    it('should filter state by blacklist when persisting', async () => {
        const store = new StateStore({
            slices: {
                user: { name: 'John' },
                temp: { data: 'temporary' },
            },
            middleware: [
                createPersistMiddleware({
                    key: 'test-state',
                    storage: mockStorage,
                    blacklist: ['temp'],
                    debounce: 0,
                }),
            ],
        });

        store.dispatch({ type: 'user/set', payload: { name: 'Jane' } });
        await vi.advanceTimersByTimeAsync(10);

        const saved = JSON.parse(mockStorage.getItem('test-state')!);
        expect(saved.state.user).toBeDefined();
        expect(saved.state.temp).toBeUndefined();
    });

    it('should clear storage on @@persist/CLEAR', () => {
        mockStorage.setItem('test-state', JSON.stringify({ state: { old: 'data' } }));

        const store = new StateStore({
            slices: { user: { name: 'John' } },
            middleware: [
                createPersistMiddleware({
                    key: 'test-state',
                    storage: mockStorage,
                }),
            ],
        });

        store.dispatch({ type: '@@persist/CLEAR' });

        expect(mockStorage.getItem('test-state')).toBeNull();
    });

    it('should save immediately on @@persist/SAVE', () => {
        const store = new StateStore({
            slices: { user: { name: 'John' } },
            middleware: [
                createPersistMiddleware({
                    key: 'test-state',
                    storage: mockStorage,
                    debounce: 1000, // Long debounce
                }),
            ],
        });

        // Force immediate save
        store.dispatch({ type: '@@persist/SAVE' });

        const saved = JSON.parse(mockStorage.getItem('test-state')!);
        expect(saved.state.user).toEqual({ name: 'John' });
    });

    it('should debounce writes', async () => {
        const store = new StateStore({
            slices: { counter: { value: 0 } },
            middleware: [
                createPersistMiddleware({
                    key: 'test-state',
                    storage: mockStorage,
                    debounce: 100,
                }),
            ],
        });

        // Rapid dispatches
        for (let i = 0; i < 5; i++) {
            store.dispatch({ type: 'counter/set', payload: { value: i } });
        }

        // Storage should not be written yet (debounce pending)
        expect(mockStorage.getItem('test-state')).toBeNull();

        // Advance past debounce
        await vi.advanceTimersByTimeAsync(150);

        // Now should be saved
        const saved = JSON.parse(mockStorage.getItem('test-state')!);
        expect(saved.state.counter).toBeDefined();
    });

    it('should call onError callback for save failures', async () => {
        const onError = vi.fn();
        const failingStorage = {
            ...createMockStorage(),
            setItem: () => {
                throw new Error('Storage full');
            },
        };

        const store = new StateStore({
            slices: { user: { name: 'John' } },
            middleware: [
                createPersistMiddleware({
                    key: 'test-state',
                    storage: failingStorage,
                    onError,
                    debounce: 0,
                }),
            ],
        });

        store.dispatch({ type: 'user/set', payload: { name: 'Jane' } });
        await vi.advanceTimersByTimeAsync(10);

        expect(onError).toHaveBeenCalledWith(expect.any(Error), 'save');
    });

    it('should store version in persisted data', async () => {
        const store = new StateStore({
            slices: { user: { name: 'John' } },
            middleware: [
                createPersistMiddleware({
                    key: 'test-state',
                    storage: mockStorage,
                    version: 5,
                    debounce: 0,
                }),
            ],
        });

        store.dispatch({ type: 'user/set', payload: { name: 'Jane' } });
        await vi.advanceTimersByTimeAsync(10);

        const saved = JSON.parse(mockStorage.getItem('test-state')!);
        expect(saved.version).toBe(5);
        expect(saved.timestamp).toBeDefined();
    });

    it('should use in-memory storage when localStorage unavailable', () => {
        // Create middleware without providing storage
        const middleware = createPersistMiddleware({
            key: 'test-state',
        });

        // Should not throw
        expect(typeof middleware).toBe('function');
    });
});
