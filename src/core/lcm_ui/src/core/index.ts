/**
 * Core module exports
 *
 * Contains the foundational classes:
 * - EventBus: Pub/sub event system
 * - StateStore: Centralized state management
 * - SSEClient: Server-Sent Events client
 * - SSEEventBuffer: Ring buffer for SSE events
 *
 * @module core
 */

// Core classes
export { EventBus, createScopedEventBus } from './EventBus.js';
export type { EventBusConfig } from './EventBus.js';

export { StateStore } from './StateStore.js';
export type { StateStoreConfig } from './StateStore.js';

export { SSEClient } from './SSEClient.js';
export { SSEEventBuffer } from './SSEEventBuffer.js';

// Constants (re-export from separate module to avoid circular deps)
export { EventTypes } from './constants.js';
export type { EventType } from './constants.js';
