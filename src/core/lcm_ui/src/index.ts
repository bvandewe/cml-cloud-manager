/**
 * @neuroglia/ui-core
 *
 * Reusable UI foundation library providing:
 * - EventBus: Pub/sub event system with wildcards and middleware
 * - StateStore: Centralized state management with slices
 * - SSEClient: Server-Sent Events client with auto-reconnect
 * - SessionManager: Authentication session management
 * - BaseComponent: Web Component base class
 * - Middleware: Logger, devtools, throttle, persist
 *
 * @example
 * ```typescript
 * import { EventBus, StateStore, SSEClient } from '@neuroglia/ui-core';
 *
 * // Create event bus
 * const eventBus = EventBus.getInstance();
 *
 * // Create state store
 * const store = new StateStore({
 *   slices: { counter: { value: 0 } }
 * });
 *
 * // Connect to SSE
 * const sseClient = new SSEClient('/api/events/stream', eventBus);
 * ```
 *
 * @packageDocumentation
 */

// Core exports
export * from './core/index.js';

// Session exports
export * from './session/index.js';

// Middleware exports
export * from './middleware/index.js';

// Component exports
export * from './components/index.js';

// Type exports
export * from './types/index.js';
