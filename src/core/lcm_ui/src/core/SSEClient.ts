/**
 * SSEClient - Server-Sent Events Client
 *
 * A generic SSE client with:
 * - Auto-reconnect with exponential backoff
 * - Configurable event mapping to EventBus
 * - Heartbeat monitoring
 * - Event buffering for replay
 * - Connection state management
 *
 * @example
 * ```typescript
 * import { SSEClient, EventBus } from '@neuroglia/ui-core';
 *
 * const eventBus = EventBus.getInstance();
 * const client = new SSEClient('/api/events/stream', eventBus, {
 *   eventMap: {
 *     'worker.snapshot': 'worker:snapshot',
 *     'worker.metrics': 'worker:metrics',
 *   },
 *   autoReconnect: true,
 *   heartbeatTimeout: 60000,
 * });
 *
 * client.connect();
 * ```
 *
 * @module core
 */

import type { SSEEvent, SSEConnectionState, SSEClientOptions } from '../types/events.js';
import type { EventBus } from './EventBus.js';
import { SSEEventBuffer } from './SSEEventBuffer.js';
import { EventTypes } from './constants.js';

/**
 * Default SSE client options
 */
const DEFAULT_OPTIONS: Required<SSEClientOptions> = {
    eventMap: {},
    autoReconnect: true,
    reconnectDelay: 1000,
    maxReconnectAttempts: 10,
    heartbeatTimeout: 60000,
    bufferSize: 100,
};

/**
 * SSEClient - Server-Sent Events client with EventBus integration
 */
export class SSEClient {
    private url: string;
    private eventBus: EventBus;
    private options: Required<SSEClientOptions>;
    private eventSource: EventSource | null;
    private connectionState: SSEConnectionState;
    private reconnectAttempts: number;
    private reconnectTimer: ReturnType<typeof setTimeout> | null;
    private heartbeatTimer: ReturnType<typeof setTimeout> | null;
    private lastEventTime: number;
    private eventBuffer: SSEEventBuffer;
    private isIntentionalDisconnect: boolean;
    private registeredEventTypes: Set<string>;

    /**
     * Create a new SSEClient
     * @param url - SSE endpoint URL
     * @param eventBus - EventBus instance for event publishing
     * @param options - Client options
     */
    constructor(url: string, eventBus: EventBus, options: SSEClientOptions = {}) {
        this.url = url;
        this.eventBus = eventBus;
        this.options = { ...DEFAULT_OPTIONS, ...options };
        this.eventSource = null;
        this.connectionState = 'disconnected';
        this.reconnectAttempts = 0;
        this.reconnectTimer = null;
        this.heartbeatTimer = null;
        this.lastEventTime = 0;
        this.eventBuffer = new SSEEventBuffer(this.options.bufferSize);
        this.isIntentionalDisconnect = false;
        this.registeredEventTypes = new Set();
    }

    /**
     * Get the current connection state
     */
    getConnectionState(): SSEConnectionState {
        return this.connectionState;
    }

    /**
     * Check if connected
     */
    isConnected(): boolean {
        return this.connectionState === 'connected';
    }

    /**
     * Get the event buffer
     */
    getEventBuffer(): SSEEventBuffer {
        return this.eventBuffer;
    }

    /**
     * Connect to the SSE endpoint
     */
    connect(): void {
        if (this.eventSource) {
            console.log('[SSEClient] Already connected');
            return;
        }

        this.isIntentionalDisconnect = false;
        this.setConnectionState('connecting');

        console.log(`[SSEClient] Connecting to ${this.url}...`);

        try {
            this.eventSource = new EventSource(this.url, {
                withCredentials: true,
            });

            this.setupEventHandlers();
        } catch (error) {
            console.error('[SSEClient] Failed to create EventSource:', error);
            this.setConnectionState('error');
            this.scheduleReconnect();
        }
    }

    /**
     * Disconnect from the SSE endpoint
     */
    disconnect(): void {
        this.isIntentionalDisconnect = true;
        this.cleanup();
        this.setConnectionState('disconnected');
        console.log('[SSEClient] Disconnected');
    }

    /**
     * Register an event type to listen for
     * @param eventType - SSE event type to listen for
     * @param busEventType - Optional EventBus event type to emit (defaults to eventType)
     */
    registerEventType(eventType: string, busEventType?: string): void {
        if (this.registeredEventTypes.has(eventType)) {
            return;
        }

        this.registeredEventTypes.add(eventType);

        // Update event map
        if (busEventType) {
            this.options.eventMap[eventType] = busEventType;
        }

        // Add listener if already connected
        if (this.eventSource) {
            this.addEventTypeListener(eventType);
        }
    }

    /**
     * Unregister an event type
     * @param eventType - SSE event type to stop listening for
     */
    unregisterEventType(eventType: string): void {
        this.registeredEventTypes.delete(eventType);
        delete this.options.eventMap[eventType];
        // Note: EventSource doesn't support removeEventListener for named events
        // The event will still be received but not processed
    }

    /**
     * Get registered event types
     */
    getRegisteredEventTypes(): string[] {
        return Array.from(this.registeredEventTypes);
    }

    /**
     * Update event mapping
     * @param eventMap - New event mappings to merge
     */
    updateEventMap(eventMap: Record<string, string>): void {
        this.options.eventMap = { ...this.options.eventMap, ...eventMap };

        // Register any new event types
        for (const eventType of Object.keys(eventMap)) {
            this.registerEventType(eventType, eventMap[eventType]);
        }
    }

    /**
     * Set up event handlers on the EventSource
     */
    private setupEventHandlers(): void {
        if (!this.eventSource) return;

        // Standard EventSource events
        this.eventSource.onopen = () => {
            console.log('[SSEClient] Connection opened');
            this.setConnectionState('connected');
            this.reconnectAttempts = 0;
            this.lastEventTime = Date.now();
            this.startHeartbeatMonitor();

            this.eventBus.emit(EventTypes.SSE_CONNECTED, {
                url: this.url,
                timestamp: Date.now(),
            });
        };

        this.eventSource.onerror = event => {
            console.error('[SSEClient] Connection error:', event);

            if (this.eventSource?.readyState === EventSource.CLOSED) {
                this.setConnectionState('disconnected');
                this.cleanup();

                if (!this.isIntentionalDisconnect) {
                    this.scheduleReconnect();
                }
            } else {
                this.setConnectionState('error');
            }

            this.eventBus.emit(EventTypes.SSE_ERROR, {
                url: this.url,
                timestamp: Date.now(),
            });
        };

        // Default message handler
        this.eventSource.onmessage = event => {
            this.handleEvent('message', event);
        };

        // Register all known event types
        for (const eventType of this.registeredEventTypes) {
            this.addEventTypeListener(eventType);
        }

        // Also register event types from the event map
        for (const eventType of Object.keys(this.options.eventMap)) {
            if (!this.registeredEventTypes.has(eventType)) {
                this.registeredEventTypes.add(eventType);
                this.addEventTypeListener(eventType);
            }
        }
    }

    /**
     * Add a listener for a specific event type
     */
    private addEventTypeListener(eventType: string): void {
        if (!this.eventSource) return;

        this.eventSource.addEventListener(eventType, (event: MessageEvent) => {
            this.handleEvent(eventType, event);
        });
    }

    /**
     * Handle an incoming SSE event
     */
    private handleEvent(eventType: string, event: MessageEvent): void {
        this.lastEventTime = Date.now();
        this.resetHeartbeatMonitor();

        let data: unknown;
        try {
            data = JSON.parse(event.data);
        } catch {
            data = event.data;
        }

        // Create SSE event record
        const sseEvent: SSEEvent = {
            type: eventType,
            data,
            id: event.lastEventId || undefined,
            receivedAt: Date.now(),
        };

        // Add to buffer
        this.eventBuffer.push(sseEvent);

        // Map to EventBus event type
        const busEventType = this.options.eventMap[eventType] ?? eventType;

        // Emit to EventBus
        this.eventBus.emit(busEventType, data, {
            source: 'sse',
            correlationId: event.lastEventId,
        });
    }

    /**
     * Schedule a reconnection attempt
     */
    private scheduleReconnect(): void {
        if (!this.options.autoReconnect) {
            return;
        }

        if (this.reconnectAttempts >= this.options.maxReconnectAttempts) {
            console.error('[SSEClient] Max reconnect attempts reached');
            this.setConnectionState('error');
            return;
        }

        // Exponential backoff with jitter
        const delay = Math.min(
            this.options.reconnectDelay * Math.pow(2, this.reconnectAttempts) + Math.random() * 1000,
            30000 // Max 30 seconds
        );

        console.log(`[SSEClient] Reconnecting in ${Math.round(delay)}ms (attempt ${this.reconnectAttempts + 1}/${this.options.maxReconnectAttempts})`);

        this.eventBus.emit(EventTypes.SSE_RECONNECTING, {
            url: this.url,
            attempt: this.reconnectAttempts + 1,
            maxAttempts: this.options.maxReconnectAttempts,
            delay,
        });

        this.reconnectTimer = setTimeout(() => {
            this.reconnectAttempts++;
            this.connect();
        }, delay);
    }

    /**
     * Start heartbeat monitoring
     */
    private startHeartbeatMonitor(): void {
        this.resetHeartbeatMonitor();
    }

    /**
     * Reset heartbeat timer
     */
    private resetHeartbeatMonitor(): void {
        if (this.heartbeatTimer) {
            clearTimeout(this.heartbeatTimer);
        }

        if (this.options.heartbeatTimeout > 0) {
            this.heartbeatTimer = setTimeout(() => {
                console.warn('[SSEClient] Heartbeat timeout - no events received');
                this.handleHeartbeatTimeout();
            }, this.options.heartbeatTimeout);
        }
    }

    /**
     * Handle heartbeat timeout
     */
    private handleHeartbeatTimeout(): void {
        // Connection may be stale, force reconnect
        this.cleanup();
        this.setConnectionState('disconnected');

        if (!this.isIntentionalDisconnect && this.options.autoReconnect) {
            this.scheduleReconnect();
        }
    }

    /**
     * Set connection state and emit event
     */
    private setConnectionState(state: SSEConnectionState): void {
        const previousState = this.connectionState;
        this.connectionState = state;

        if (previousState !== state) {
            if (state === 'disconnected' && previousState === 'connected') {
                this.eventBus.emit(EventTypes.SSE_DISCONNECTED, {
                    url: this.url,
                    timestamp: Date.now(),
                    wasIntentional: this.isIntentionalDisconnect,
                });
            }
        }
    }

    /**
     * Clean up resources
     */
    private cleanup(): void {
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }

        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }

        if (this.heartbeatTimer) {
            clearTimeout(this.heartbeatTimer);
            this.heartbeatTimer = null;
        }
    }

    /**
     * Get connection statistics
     */
    getStats(): {
        connectionState: SSEConnectionState;
        reconnectAttempts: number;
        lastEventTime: number;
        bufferStats: ReturnType<SSEEventBuffer['getStats']>;
        registeredEventTypes: string[];
    } {
        return {
            connectionState: this.connectionState,
            reconnectAttempts: this.reconnectAttempts,
            lastEventTime: this.lastEventTime,
            bufferStats: this.eventBuffer.getStats(),
            registeredEventTypes: this.getRegisteredEventTypes(),
        };
    }
}
