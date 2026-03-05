/**
 * StateStore unit tests
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { StateStore } from '../src/core/StateStore.js';
import { EventBus } from '../src/core/EventBus.js';
import { EventTypes } from '../src/core/index.js';

describe('StateStore', () => {
    let store: StateStore;

    beforeEach(() => {
        store = new StateStore({
            slices: {
                counter: { value: 0 },
                user: { name: '', isLoggedIn: false },
            },
        });
    });

    describe('initialization', () => {
        it('should initialize with provided slices', () => {
            const state = store.getState();
            expect(state.counter).toEqual({ value: 0 });
            expect(state.user).toEqual({ name: '', isLoggedIn: false });
        });

        it('should return a copy of state (immutable)', () => {
            const state1 = store.getState();
            const state2 = store.getState();
            expect(state1).toEqual(state2);
            expect(state1).not.toBe(state2);
        });
    });

    describe('getSlice', () => {
        it('should return specific slice', () => {
            const counter = store.getSlice<{ value: number }>('counter');
            expect(counter).toEqual({ value: 0 });
        });

        it('should return undefined for non-existent slice', () => {
            const unknown = store.getSlice('unknown');
            expect(unknown).toBeUndefined();
        });
    });

    describe('setSlice', () => {
        it('should replace entire slice', () => {
            store.setSlice('counter', { value: 42 });
            expect(store.getSlice('counter')).toEqual({ value: 42 });
        });

        it('should dispatch action with correct type', () => {
            const listener = vi.fn();
            store.subscribe(listener);

            store.setSlice('counter', { value: 10 });

            expect(listener).toHaveBeenCalledWith(expect.any(Object), expect.any(Object), expect.objectContaining({ type: 'counter/set' }));
        });
    });

    describe('updateSlice', () => {
        it('should merge partial update', () => {
            store.updateSlice('user', { name: 'John' });
            expect(store.getSlice('user')).toEqual({ name: 'John', isLoggedIn: false });
        });

        it('should accept updater function', () => {
            store.setSlice('counter', { value: 5 });
            store.updateSlice<{ value: number }>('counter', current => ({
                value: current.value + 10,
            }));
            expect(store.getSlice('counter')).toEqual({ value: 15 });
        });
    });

    describe('dispatch', () => {
        it('should update state based on action', () => {
            store.dispatch({ type: 'counter/set', payload: { value: 100 } });
            expect(store.getSlice('counter')).toEqual({ value: 100 });
        });

        it('should parse slice name from action type', () => {
            store.dispatch({ type: 'user/set', payload: { name: 'Jane', isLoggedIn: true } });
            expect(store.getSlice('user')).toEqual({ name: 'Jane', isLoggedIn: true });
        });
    });

    describe('subscribe', () => {
        it('should notify listeners on state change', () => {
            const listener = vi.fn();
            store.subscribe(listener);

            store.setSlice('counter', { value: 5 });

            expect(listener).toHaveBeenCalledTimes(1);
            expect(listener).toHaveBeenCalledWith({ counter: { value: 5 }, user: { name: '', isLoggedIn: false } }, { counter: { value: 0 }, user: { name: '', isLoggedIn: false } }, expect.objectContaining({ type: 'counter/set' }));
        });

        it('should return unsubscribe function', () => {
            const listener = vi.fn();
            const unsubscribe = store.subscribe(listener);

            store.setSlice('counter', { value: 1 });
            expect(listener).toHaveBeenCalledTimes(1);

            unsubscribe();

            store.setSlice('counter', { value: 2 });
            expect(listener).toHaveBeenCalledTimes(1);
        });

        it('should isolate listener errors', () => {
            const errorListener = vi.fn(() => {
                throw new Error('Listener error');
            });
            const successListener = vi.fn();

            store.subscribe(errorListener);
            store.subscribe(successListener);

            store.setSlice('counter', { value: 1 });

            expect(errorListener).toHaveBeenCalled();
            expect(successListener).toHaveBeenCalled();
        });
    });

    describe('select', () => {
        it('should select value from state', () => {
            store.setSlice('counter', { value: 42 });
            const value = store.select(state => (state.counter as { value: number }).value);
            expect(value).toBe(42);
        });
    });

    describe('createSelector (memoization)', () => {
        it('should memoize selector results', () => {
            const combiner = vi.fn((counter: { value: number }) => counter.value * 2);

            const doubleValue = store.createSelector([state => state.counter as { value: number }], combiner);

            // First call - computes
            expect(doubleValue(store.getState())).toBe(0);
            expect(combiner).toHaveBeenCalledTimes(1);

            // Second call with same state - cached
            expect(doubleValue(store.getState())).toBe(0);
            expect(combiner).toHaveBeenCalledTimes(1);

            // Change state - recomputes
            store.setSlice('counter', { value: 5 });
            expect(doubleValue(store.getState())).toBe(10);
            expect(combiner).toHaveBeenCalledTimes(2);
        });

        it('should track cache stats', () => {
            const selector = store.createSelector([state => state.counter], counter => counter);

            selector(store.getState()); // miss
            selector(store.getState()); // hit

            const stats = selector.getCacheStats();
            expect(stats.hits).toBe(1);
            expect(stats.misses).toBe(1);
        });

        it('should clear cache', () => {
            const combiner = vi.fn(counter => counter);
            const selector = store.createSelector([state => state.counter], combiner);

            selector(store.getState());
            selector.clearCache();
            selector(store.getState());

            expect(combiner).toHaveBeenCalledTimes(2);
        });
    });

    describe('batch', () => {
        it('should batch multiple updates into single notification', () => {
            const listener = vi.fn();
            store.subscribe(listener);

            store.batch(() => {
                store.setSlice('counter', { value: 1 });
                store.setSlice('counter', { value: 2 });
                store.setSlice('counter', { value: 3 });
            });

            // Only one notification for batch
            expect(listener).toHaveBeenCalledTimes(1);
            expect(store.getSlice('counter')).toEqual({ value: 3 });
        });

        it('should handle nested batches', () => {
            const listener = vi.fn();
            store.subscribe(listener);

            store.batch(() => {
                store.setSlice('counter', { value: 1 });
                // Nested calls should still be batched
                store.setSlice('user', { name: 'Test', isLoggedIn: true });
            });

            expect(listener).toHaveBeenCalledTimes(1);
        });
    });

    describe('history', () => {
        it('should record state history', () => {
            store.setSlice('counter', { value: 1 });
            store.setSlice('counter', { value: 2 });

            const history = store.getHistory();
            expect(history.length).toBe(3); // init + 2 updates
        });

        it('should limit history size', () => {
            const smallStore = new StateStore({
                slices: { counter: { value: 0 } },
                maxHistorySize: 3,
            });

            smallStore.setSlice('counter', { value: 1 });
            smallStore.setSlice('counter', { value: 2 });
            smallStore.setSlice('counter', { value: 3 });
            smallStore.setSlice('counter', { value: 4 });

            const history = smallStore.getHistory();
            expect(history.length).toBe(3);
        });

        it('should support undo', () => {
            store.setSlice('counter', { value: 1 });
            store.setSlice('counter', { value: 2 });

            expect(store.getSlice('counter')).toEqual({ value: 2 });

            const undone = store.undo();
            expect(undone).toBe(true);
            expect(store.getSlice('counter')).toEqual({ value: 1 });
        });

        it('should return false when no undo available', () => {
            const freshStore = new StateStore({
                slices: { counter: { value: 0 } },
            });

            const undone = freshStore.undo();
            expect(undone).toBe(false);
        });
    });

    describe('gc', () => {
        it('should clear history except most recent', () => {
            store.setSlice('counter', { value: 1 });
            store.setSlice('counter', { value: 2 });
            store.setSlice('counter', { value: 3 });

            expect(store.getHistory().length).toBe(4);

            store.gc();

            expect(store.getHistory().length).toBe(1);
            // State should be preserved
            expect(store.getSlice('counter')).toEqual({ value: 3 });
        });
    });

    describe('reset', () => {
        it('should reset to new initial state', () => {
            store.setSlice('counter', { value: 100 });
            store.setSlice('user', { name: 'Test', isLoggedIn: true });

            store.reset({
                counter: { value: 0 },
                user: { name: '', isLoggedIn: false },
            });

            expect(store.getSlice('counter')).toEqual({ value: 0 });
            expect(store.getSlice('user')).toEqual({ name: '', isLoggedIn: false });
            expect(store.getHistory().length).toBe(1); // Only init
        });
    });

    describe('middleware', () => {
        it('should run middleware on dispatch', () => {
            const middleware = vi.fn(() => next => action => {
                next(action);
            });

            const storeWithMiddleware = new StateStore({
                slices: { counter: { value: 0 } },
                middleware: [middleware],
            });

            storeWithMiddleware.setSlice('counter', { value: 1 });

            expect(middleware).toHaveBeenCalled();
        });

        it('should provide store API to middleware', () => {
            let capturedApi: unknown;

            const middleware = (api: unknown) => {
                capturedApi = api;
                return next => action => next(action);
            };

            const storeWithMiddleware = new StateStore({
                slices: { counter: { value: 0 } },
                middleware: [middleware as unknown as () => (next: unknown) => (action: unknown) => void],
            });

            storeWithMiddleware.setSlice('counter', { value: 1 });

            expect(capturedApi).toHaveProperty('getState');
            expect(capturedApi).toHaveProperty('dispatch');
            expect(capturedApi).toHaveProperty('subscribe');
        });
    });

    describe('EventBus integration', () => {
        it('should emit state change events', async () => {
            const eventBus = new EventBus();
            const handler = vi.fn();

            eventBus.on(EventTypes.STATE_CHANGED, handler);

            const storeWithEvents = new StateStore({
                slices: { counter: { value: 0 } },
                eventBus,
            });

            storeWithEvents.setSlice('counter', { value: 1 });

            // Allow async event handling
            await new Promise(r => setTimeout(r, 10));

            expect(handler).toHaveBeenCalled();
        });

        it('should emit slice updated events', async () => {
            const eventBus = new EventBus();
            const handler = vi.fn();

            eventBus.on(EventTypes.STATE_SLICE_UPDATED, handler);

            const storeWithEvents = new StateStore({
                slices: { counter: { value: 0 } },
                eventBus,
            });

            storeWithEvents.setSlice('counter', { value: 1 });

            await new Promise(r => setTimeout(r, 10));

            expect(handler).toHaveBeenCalledWith(expect.objectContaining({ slice: 'counter' }), expect.any(Object));
        });
    });

    describe('registerSlice', () => {
        it('should initialize slice state from definition', () => {
            const emptyStore = new StateStore({ slices: {} });

            emptyStore.registerSlice('todos', {
                name: 'todos',
                initialState: { items: [], count: 0 },
            });

            expect(emptyStore.getSlice('todos')).toEqual({ items: [], count: 0 });
        });

        it('should register reducers that are invokable via dispatch', () => {
            const emptyStore = new StateStore({ slices: {} });

            emptyStore.registerSlice('counter', {
                name: 'counter',
                initialState: { value: 0 },
                reducers: {
                    increment(state: { value: number }, amount: number) {
                        return { ...state, value: state.value + amount };
                    },
                    reset(state: { value: number }) {
                        return { ...state, value: 0 };
                    },
                },
            });

            // Dispatch via action object
            emptyStore.dispatch({ type: 'counter/increment', payload: 5 });
            expect(emptyStore.getSlice('counter')).toEqual({ value: 5 });

            emptyStore.dispatch({ type: 'counter/increment', payload: 3 });
            expect(emptyStore.getSlice('counter')).toEqual({ value: 8 });

            emptyStore.dispatch({ type: 'counter/reset' });
            expect(emptyStore.getSlice('counter')).toEqual({ value: 0 });
        });

        it('should support positional dispatch (sliceName, reducerName, payload)', () => {
            const emptyStore = new StateStore({ slices: {} });

            emptyStore.registerSlice('workers', {
                name: 'workers',
                initialState: { byId: {}, allIds: [] },
                reducers: {
                    upsertWorker(state: { byId: Record<string, unknown>; allIds: string[] }, worker: { id: string; name: string }) {
                        const isNew = !(worker.id in state.byId);
                        return {
                            ...state,
                            byId: { ...state.byId, [worker.id]: worker },
                            allIds: isNew ? [...state.allIds, worker.id] : state.allIds,
                        };
                    },
                },
            });

            // Positional dispatch: (sliceName, reducerName, payload)
            emptyStore.dispatch('workers', 'upsertWorker', { id: 'w1', name: 'Worker 1' });

            const workers = emptyStore.getSlice<{ byId: Record<string, unknown>; allIds: string[] }>('workers');
            expect(workers?.byId['w1']).toEqual({ id: 'w1', name: 'Worker 1' });
            expect(workers?.allIds).toEqual(['w1']);
        });

        it('should fall back to payload replacement for unknown reducer names', () => {
            const emptyStore = new StateStore({ slices: {} });

            emptyStore.registerSlice('data', {
                name: 'data',
                initialState: { items: [] },
                reducers: {},
            });

            // Unknown reducer name → falls back to payload replacement
            emptyStore.dispatch({ type: 'data/set', payload: { items: [1, 2, 3] } });
            expect(emptyStore.getSlice('data')).toEqual({ items: [1, 2, 3] });
        });

        it('should work with batch dispatch', () => {
            const emptyStore = new StateStore({ slices: {} });

            emptyStore.registerSlice('counter', {
                name: 'counter',
                initialState: { value: 0 },
                reducers: {
                    increment(state: { value: number }, amount: number) {
                        return { ...state, value: state.value + (amount ?? 1) };
                    },
                },
            });

            const listener = vi.fn();
            emptyStore.subscribe(listener);

            emptyStore.batch(() => {
                emptyStore.dispatch('counter', 'increment', 1);
                emptyStore.dispatch('counter', 'increment', 2);
                emptyStore.dispatch('counter', 'increment', 3);
            });

            // Single notification for batch
            expect(listener).toHaveBeenCalledTimes(1);
            expect(emptyStore.getSlice('counter')).toEqual({ value: 6 });
        });

        it('should allow registering slices after construction alongside constructor slices', () => {
            // Constructor slices still work
            expect(store.getSlice('counter')).toEqual({ value: 0 });

            // Register additional slice
            store.registerSlice('todos', {
                name: 'todos',
                initialState: { items: [] },
                reducers: {
                    addItem(state: { items: string[] }, item: string) {
                        return { ...state, items: [...state.items, item] };
                    },
                },
            });

            // Both slices work
            store.setSlice('counter', { value: 42 });
            store.dispatch('todos', 'addItem', 'Buy milk');

            expect(store.getSlice('counter')).toEqual({ value: 42 });
            expect(store.getSlice('todos')).toEqual({ items: ['Buy milk'] });
        });

        it('should notify listeners when dispatching reducer actions', () => {
            const emptyStore = new StateStore({ slices: {} });

            emptyStore.registerSlice('counter', {
                name: 'counter',
                initialState: { value: 0 },
                reducers: {
                    increment(state: { value: number }, amount: number) {
                        return { ...state, value: state.value + amount };
                    },
                },
            });

            const listener = vi.fn();
            emptyStore.subscribe(listener);

            emptyStore.dispatch('counter', 'increment', 10);

            expect(listener).toHaveBeenCalledTimes(1);
            expect(listener).toHaveBeenCalledWith(expect.objectContaining({ counter: { value: 10 } }), expect.objectContaining({ counter: { value: 0 } }), expect.objectContaining({ type: 'counter/increment' }));
        });
    });
});
