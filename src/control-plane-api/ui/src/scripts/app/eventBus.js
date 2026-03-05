/**
 * LCM EventBus Configuration
 *
 * Creates and configures the shared EventBus instance for the LCM application.
 * Uses the singleton pattern from @neuroglia/ui-core.
 */

import { EventBus } from '@neuroglia/ui-core';

/**
 * Shared EventBus instance for the LCM application
 *
 * Usage:
 * ```javascript
 * import { eventBus, LcmEventTypes } from './app/eventBus.js';
 *
 * // Subscribe to events
 * eventBus.on(LcmEventTypes.WORKER_CREATED, (data) => {
 *     console.log('Worker created:', data);
 * });
 *
 * // Emit events
 * eventBus.emit(LcmEventTypes.WORKER_UPDATED, { id: '123', name: 'Worker 1' });
 * ```
 */
export const eventBus = EventBus.getInstance({
    maxHistorySize: 100,
    debug: false, // Set to true for development debugging
});

// Re-export LcmEventTypes for convenience
export { LcmEventTypes, EventTypes } from './eventTypes.js';

export default eventBus;
