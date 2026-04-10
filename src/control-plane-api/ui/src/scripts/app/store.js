/**
 * LCM Store Configuration
 *
 * Creates and configures the StateStore instance for the LCM application.
 * Registers all LCM-specific slices and middleware.
 */

import { StateStore, loggerMiddleware, devtoolsMiddleware } from '@neuroglia/ui-core';
import { eventBus } from './eventBus.js';
import { workersSlice } from './slices/workersSlice.js';
import { definitionsSlice } from './slices/definitionsSlice.js';
import { labRecordsSlice } from './slices/labRecordsSlice.js';
import { sessionsSlice } from './slices/sessionsSlice.js';
import { templatesSlice } from './slices/templatesSlice.js';

/**
 * Create and configure the LCM StateStore
 */
function createStore() {
    const store = new StateStore({
        maxHistorySize: 50,
        debug: false,
        eventBus: eventBus,
    });

    // Register middleware (in order: logger runs last, sees final state)
    if (process.env.NODE_ENV !== 'production') {
        store.use(devtoolsMiddleware('__LCM_STORE__'));
        store.use(loggerMiddleware('[LCM Store]'));
    }

    // Register slices
    store.registerSlice('workers', workersSlice);
    store.registerSlice('definitions', definitionsSlice);
    store.registerSlice('labRecords', labRecordsSlice);
    store.registerSlice('sessions', sessionsSlice);
    store.registerSlice('templates', templatesSlice);

    return store;
}

/**
 * Shared StateStore instance for the LCM application
 */
export const store = createStore();

/**
 * Helper to get current state snapshot
 */
export function getState() {
    return store.getState();
}

/**
 * Helper to get a slice of state
 */
export function getSlice(sliceName) {
    return store.getSlice(sliceName);
}

/**
 * Helper to subscribe to selected state changes.
 * Uses a selector to derive a value from state and only invokes
 * the callback when that derived value changes (by reference).
 *
 * @param {Function} selector - (state) => derivedValue
 * @param {Function} callback - (derivedValue) => void
 * @returns {Function} Unsubscribe function
 */
export function subscribe(selector, callback) {
    let previousValue = selector(store.getState());
    return store.subscribe(newState => {
        const newValue = selector(newState);
        if (newValue !== previousValue) {
            previousValue = newValue;
            callback(newValue);
        }
    });
}

export default store;
