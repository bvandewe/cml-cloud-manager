/**
 * LCM Store Configuration
 *
 * Creates and configures the StateStore instance for the LCM application.
 * Registers all LCM-specific slices and middleware.
 */

import { StateStore, loggerMiddleware, devtoolsMiddleware } from '@neuroglia/ui-core';
import { eventBus } from './eventBus.js';
import { workersSlice } from './slices/workersSlice.js';
import { labletsSlice } from './slices/labletsSlice.js';
import { labRecordsSlice } from './slices/labRecordsSlice.js';
import { sessionsSlice } from './slices/sessionsSlice.js';

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
    store.registerSlice('lablets', labletsSlice);
    store.registerSlice('labRecords', labRecordsSlice);
    store.registerSlice('sessions', sessionsSlice);

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
 * Helper to subscribe to state changes
 */
export function subscribe(selector, callback) {
    return store.subscribe(selector, callback);
}

export default store;
