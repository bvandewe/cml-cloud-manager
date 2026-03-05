/**
 * Event type constants
 *
 * Generic event types used across the library.
 * Applications should extend these with domain-specific types.
 *
 * @module core
 */

/**
 * Standard event types for the UI library
 */
export const EventTypes = {
    // SSE connection events
    SSE_CONNECTED: 'sse:connected',
    SSE_DISCONNECTED: 'sse:disconnected',
    SSE_ERROR: 'sse:error',
    SSE_MESSAGE: 'sse:message',
    SSE_RECONNECTING: 'sse:reconnecting',

    // State events
    STATE_CHANGED: 'state:changed',
    STATE_INITIALIZED: 'state:initialized',
    STATE_SLICE_UPDATED: 'state:slice:updated',

    // UI events
    UI_READY: 'ui:ready',
    UI_ERROR: 'ui:error',

    // Auth events
    AUTH_LOGIN: 'auth:login',
    AUTH_LOGOUT: 'auth:logout',
    AUTH_TOKEN_REFRESHED: 'auth:token:refreshed',
    AUTH_SESSION_EXPIRING: 'auth:session:expiring',
    AUTH_SESSION_EXPIRED: 'auth:session:expired',
} as const;

/**
 * Type for event type values
 */
export type EventType = (typeof EventTypes)[keyof typeof EventTypes];
