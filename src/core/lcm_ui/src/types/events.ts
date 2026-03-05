/**
 * Event-related type definitions
 */

/**
 * Event handler function type
 */
export type EventHandler<T = unknown> = (data: T, event: EventEnvelope<T>) => void | Promise<void>;

/**
 * Event envelope containing metadata
 */
export interface EventEnvelope<T = unknown> {
    /** Event type identifier */
    type: string;
    /** Event payload data */
    data: T;
    /** Timestamp when event was created */
    timestamp: number;
    /** Optional source identifier */
    source?: string;
    /** Optional correlation ID for tracing */
    correlationId?: string;
}

/**
 * Event subscription options
 */
export interface SubscriptionOptions {
    /** Handler priority (higher = called first) */
    priority?: number;
    /** Whether to only handle once then unsubscribe */
    once?: boolean;
    /** Optional filter function */
    filter?: (data: unknown) => boolean;
}

/**
 * Subscription handle for unsubscribing
 */
export interface Subscription {
    /** Unsubscribe from the event */
    unsubscribe: () => void;
    /** Event type this subscription is for */
    eventType: string;
}

/**
 * EventBus middleware function
 */
export type EventMiddleware = (event: EventEnvelope, next: () => Promise<void>) => Promise<void>;

/**
 * SSE event data structure
 */
export interface SSEEvent {
    /** Event type from SSE */
    type: string;
    /** Event data (parsed JSON or string) */
    data: unknown;
    /** Event ID if provided by server */
    id?: string;
    /** Retry interval suggested by server */
    retry?: number;
    /** Timestamp when received */
    receivedAt: number;
}

/**
 * SSE connection state
 */
export type SSEConnectionState = 'connecting' | 'connected' | 'disconnected' | 'error';

/**
 * SSE client options
 */
export interface SSEClientOptions {
    /** Event mappings from SSE event types to EventBus event types */
    eventMap?: Record<string, string>;
    /** Whether to auto-reconnect on disconnect */
    autoReconnect?: boolean;
    /** Base delay for reconnection (ms) */
    reconnectDelay?: number;
    /** Maximum reconnection attempts */
    maxReconnectAttempts?: number;
    /** Heartbeat timeout (ms) - triggers reconnect if no events */
    heartbeatTimeout?: number;
    /** Event buffer size limit */
    bufferSize?: number;
}
