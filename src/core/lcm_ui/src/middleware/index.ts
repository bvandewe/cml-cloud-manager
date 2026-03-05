/**
 * Middleware module exports
 *
 * Contains state management middleware:
 * - logger: Log state changes to console
 * - devtools: Expose store to window for debugging
 * - throttle: Throttle rapid state updates
 * - debounce: Debounce state updates until activity stops
 * - persist: Persist state to localStorage
 *
 * @module middleware
 */

// Logger middleware
export { createLoggerMiddleware, loggerMiddleware } from './logger.js';
export type { LoggerOptions } from './logger.js';

// Devtools middleware
export { createDevtoolsMiddleware, devtoolsMiddleware } from './devtools.js';
export type { DevtoolsOptions, DevtoolsStore, DevtoolsHistoryEntry } from './devtools.js';

// Throttle and debounce middleware
export { createThrottleMiddleware, createDebounceMiddleware } from './throttle.js';
export type { ThrottleOptions, DebounceOptions } from './throttle.js';

// Persist middleware
export { createPersistMiddleware, createSessionPersistMiddleware } from './persist.js';
export type { PersistOptions } from './persist.js';

// Re-export types from store for convenience
export type { StoreMiddleware, StoreAction, StoreAPI, StoreDispatch } from '../types/store.js';
