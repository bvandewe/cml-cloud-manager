/**
 * EventBus - Compatibility Shim
 *
 * This file re-exports from the new @neuroglia/ui-core based implementation
 * in app/eventBus.js to maintain backward compatibility with existing imports.
 *
 */

// Re-export from app module
export { eventBus, LcmEventTypes as EventTypes } from '../app/eventBus.js';
export { LcmEventTypes } from '../app/eventTypes.js';

// Default export for compatibility
export { eventBus as default } from '../app/eventBus.js';
