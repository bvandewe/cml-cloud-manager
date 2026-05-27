/**
 * EventBus - Centralized Pub/Sub Event System
 *
 * A type-safe, feature-rich event bus for browser applications.
 *
 * Features:
 * - Type-safe event contracts with generics
 * - Wildcard subscriptions (e.g., 'worker.*')
 * - Priority-based handler ordering
 * - Async event handlers with error isolation
 * - Event history with configurable limit
 * - Middleware pipeline for logging/debugging
 * - waitFor() promise API for async flows
 * - Memory leak prevention
 *
 * @example
 * ```typescript
 * const eventBus = EventBus.getInstance();
 *
 * // Subscribe with priority
 * eventBus.on('user:login', (data) => console.log('User logged in:', data), { priority: 10 });
 *
 * // Wildcard subscription
 * eventBus.on('user:*', (data, event) => console.log('User event:', event.type));
 *
 * // Wait for event
 * const data = await eventBus.waitFor('data:loaded', 5000);
 *
 * // Emit event
 * await eventBus.emit('user:login', { userId: '123', name: 'John' });
 * ```
 *
 * @module core
 */

import type { EventHandler, EventEnvelope, EventMiddleware, Subscription, SubscriptionOptions } from '../types/events.js';

/**
 * Handler registration with metadata
 */
interface HandlerRegistration<T = unknown> {
    handler: EventHandler<T>;
    priority: number;
    once: boolean;
    filter?: (data: unknown) => boolean;
}

/**
 * EventBus configuration options
 */
export interface EventBusConfig {
    /** Maximum number of events to keep in history */
    maxHistorySize?: number;
    /** Enable debug logging */
    debug?: boolean;
    /** Custom logger */
    logger?: Pick<Console, 'log' | 'error' | 'debug' | 'warn'>;
}

/**
 * Default configuration
 */
const DEFAULT_CONFIG: Required<EventBusConfig> = {
    maxHistorySize: 100,
    debug: false,
    logger: console,
};

/**
 * EventBus - Centralized pub/sub event system
 */
export class EventBus {
    private static instance: EventBus | null = null;

    private subscribers: Map<string, Set<HandlerRegistration>>;
    private middleware: EventMiddleware[];
    private history: EventEnvelope[];
    private config: Required<EventBusConfig>;

    /**
     * Create a new EventBus instance
     * @param config - Configuration options
     */
    constructor(config: EventBusConfig = {}) {
        this.subscribers = new Map();
        this.middleware = [];
        this.history = [];
        this.config = { ...DEFAULT_CONFIG, ...config };
    }

    /**
     * Get the singleton EventBus instance
     * @param config - Configuration options (only used on first call)
     */
    static getInstance(config?: EventBusConfig): EventBus {
        if (!EventBus.instance) {
            EventBus.instance = new EventBus(config);
        }
        return EventBus.instance;
    }

    /**
     * Reset the singleton instance (for testing)
     */
    static resetInstance(): void {
        EventBus.instance = null;
    }

    /**
     * Subscribe to events
     * @param eventType - Event type or wildcard pattern (e.g., 'worker.*')
     * @param handler - Event handler function
     * @param options - Subscription options
     * @returns Subscription object with unsubscribe method
     */
    on<T = unknown>(eventType: string, handler: EventHandler<T>, options: SubscriptionOptions = {}): Subscription {
        const { priority = 0, once = false, filter } = options;

        if (!this.subscribers.has(eventType)) {
            this.subscribers.set(eventType, new Set());
        }

        const registration: HandlerRegistration<T> = {
            handler: handler as EventHandler<unknown>,
            priority,
            once,
            filter,
        };

        this.subscribers.get(eventType)!.add(registration as HandlerRegistration);

        if (this.config.debug) {
            this.config.logger.debug(`[EventBus] Subscribed to "${eventType}" (priority: ${priority})`);
        }

        return {
            unsubscribe: () => this.offRegistration(eventType, registration as HandlerRegistration),
            eventType,
        };
    }

    /**
     * Unsubscribe a specific handler from an event type
     * @param eventType - Event type
     * @param handler - Handler to remove
     */
    off<T = unknown>(eventType: string, handler: EventHandler<T>): void {
        const handlers = this.subscribers.get(eventType);
        if (!handlers) return;

        for (const registration of handlers) {
            if (registration.handler === handler) {
                handlers.delete(registration);
                break;
            }
        }

        if (handlers.size === 0) {
            this.subscribers.delete(eventType);
        }
    }

    /**
     * Remove a handler registration
     */
    private offRegistration(eventType: string, registration: HandlerRegistration): void {
        const handlers = this.subscribers.get(eventType);
        if (handlers) {
            handlers.delete(registration);
            if (handlers.size === 0) {
                this.subscribers.delete(eventType);
            }
        }
    }

    /**
     * Subscribe to an event once (auto-unsubscribes after first event)
     * @param eventType - Event type
     * @param handler - Event handler function
     * @param options - Subscription options (once is automatically true)
     * @returns Subscription object
     */
    once<T = unknown>(eventType: string, handler: EventHandler<T>, options: Omit<SubscriptionOptions, 'once'> = {}): Subscription {
        return this.on(eventType, handler, { ...options, once: true });
    }

    /**
     * Emit an event to all subscribers
     * @param eventType - Event type
     * @param data - Event payload
     * @param options - Emit options
     */
    async emit<T = unknown>(eventType: string, data: T, options: { source?: string; correlationId?: string } = {}): Promise<void> {
        const envelope: EventEnvelope<T> = {
            type: eventType,
            data,
            timestamp: Date.now(),
            source: options.source,
            correlationId: options.correlationId,
        };

        // Add to history
        this.addToHistory(envelope as EventEnvelope);

        // Create the handler execution function
        const executeHandlers = async (): Promise<void> => {
            // Use envelope.data (not the captured `data` param) so middleware
            // transformations (e.g. CloudEvent unwrapping) are visible to handlers.
            const processedData = envelope.data;

            if (this.config.debug) {
                this.config.logger.log(`[EventBus] Emit "${eventType}"`, processedData);
            }

            // Collect all matching handlers
            const matchingHandlers: Array<{ registration: HandlerRegistration; eventType: string }> = [];

            // Direct subscribers
            const directHandlers = this.subscribers.get(eventType);
            if (directHandlers) {
                for (const registration of directHandlers) {
                    matchingHandlers.push({ registration, eventType });
                }
            }

            // Wildcard subscribers
            for (const [pattern, handlers] of this.subscribers) {
                if (this.matchesPattern(pattern, eventType)) {
                    for (const registration of handlers) {
                        matchingHandlers.push({ registration, eventType: pattern });
                    }
                }
            }

            // Sort by priority (higher first)
            matchingHandlers.sort((a, b) => b.registration.priority - a.registration.priority);

            // Collect handlers to remove after execution (once handlers)
            const toRemove: Array<{ eventType: string; registration: HandlerRegistration }> = [];

            // Execute handlers
            for (const { registration, eventType: subEventType } of matchingHandlers) {
                // Apply filter if present
                if (registration.filter && !registration.filter(processedData)) {
                    continue;
                }

                try {
                    await registration.handler(processedData, envelope as EventEnvelope);
                } catch (error) {
                    this.config.logger.error(`[EventBus] Error in handler for "${eventType}":`, error);
                }

                // Mark for removal if once
                if (registration.once) {
                    toRemove.push({ eventType: subEventType, registration });
                }
            }

            // Remove once handlers
            for (const { eventType: subEventType, registration } of toRemove) {
                this.offRegistration(subEventType, registration);
            }
        };

        // Run middleware pipeline wrapping handler execution
        await this.runMiddleware(envelope as EventEnvelope, executeHandlers);
    }

    /**
     * Wait for a specific event to occur
     * @param eventType - Event type to wait for
     * @param timeout - Maximum time to wait in milliseconds (0 = no timeout)
     * @returns Promise that resolves with event data
     */
    waitFor<T = unknown>(eventType: string, timeout: number = 0): Promise<T> {
        return new Promise((resolve, reject) => {
            let timeoutId: ReturnType<typeof setTimeout> | undefined;

            const subscription = this.once<T>(eventType, data => {
                if (timeoutId) {
                    clearTimeout(timeoutId);
                }
                resolve(data);
            });

            if (timeout > 0) {
                timeoutId = setTimeout(() => {
                    subscription.unsubscribe();
                    reject(new Error(`Timeout waiting for event "${eventType}" after ${timeout}ms`));
                }, timeout);
            }
        });
    }

    /**
     * Add middleware to the event pipeline
     * @param middleware - Middleware function
     */
    use(middleware: EventMiddleware): void {
        this.middleware.push(middleware);
    }

    /**
     * Remove middleware from the pipeline
     * @param middleware - Middleware function to remove
     */
    removeMiddleware(middleware: EventMiddleware): void {
        const index = this.middleware.indexOf(middleware);
        if (index !== -1) {
            this.middleware.splice(index, 1);
        }
    }

    /**
     * Get event history
     * @param eventType - Optional filter by event type
     * @param limit - Maximum number of events to return
     */
    getHistory(eventType?: string, limit?: number): EventEnvelope[] {
        let result = this.history;

        if (eventType) {
            result = result.filter(e => e.type === eventType || this.matchesPattern(eventType, e.type));
        }

        if (limit !== undefined && limit > 0) {
            result = result.slice(-limit);
        }

        return [...result];
    }

    /**
     * Clear event history
     */
    clearHistory(): void {
        this.history = [];
    }

    /**
     * Get subscriber count for an event type
     * @param eventType - Event type (optional, returns total if not specified)
     */
    subscriberCount(eventType?: string): number {
        if (eventType) {
            return this.subscribers.get(eventType)?.size ?? 0;
        }
        let total = 0;
        for (const handlers of this.subscribers.values()) {
            total += handlers.size;
        }
        return total;
    }

    /**
     * Check if there are any subscribers for an event type
     * @param eventType - Event type
     */
    hasSubscribers(eventType: string): boolean {
        // Check direct subscribers
        if (this.subscribers.has(eventType) && this.subscribers.get(eventType)!.size > 0) {
            return true;
        }

        // Check wildcard subscribers that would match
        for (const pattern of this.subscribers.keys()) {
            if (this.matchesPattern(pattern, eventType)) {
                return true;
            }
        }

        return false;
    }

    /**
     * Enable debug mode
     */
    enableDebug(): void {
        this.config.debug = true;
    }

    /**
     * Disable debug mode
     */
    disableDebug(): void {
        this.config.debug = false;
    }

    /**
     * Clear all subscribers and middleware
     */
    clear(): void {
        this.subscribers.clear();
        this.middleware = [];
        if (this.config.debug) {
            this.config.logger.debug('[EventBus] Cleared all subscribers and middleware');
        }
    }

    /**
     * Clear all subscribers, middleware, and history (full reset)
     */
    reset(): void {
        this.clear();
        this.clearHistory();
    }

    /**
     * Check if event type matches a wildcard pattern
     */
    private matchesPattern(pattern: string, eventType: string): boolean {
        if (!pattern.includes('*')) return false;
        if (pattern === eventType) return false; // Avoid double-matching direct subscribers

        // Convert glob pattern to regex
        const regexPattern = pattern
            .replace(/[.+?^${}()|[\]\\]/g, '\\$&') // Escape special chars except *
            .replace(/\*/g, '.*'); // Convert * to .*

        const regex = new RegExp(`^${regexPattern}$`);
        return regex.test(eventType);
    }

    /**
     * Add event to history with size limit
     */
    private addToHistory(envelope: EventEnvelope): void {
        this.history.push(envelope);

        // Trim history if exceeds max size
        if (this.history.length > this.config.maxHistorySize) {
            this.history = this.history.slice(-this.config.maxHistorySize);
        }
    }

    /**
     * Run middleware pipeline
     */
    private async runMiddleware(envelope: EventEnvelope, finalHandler: () => Promise<void>): Promise<void> {
        if (this.middleware.length === 0) {
            await finalHandler();
            return;
        }

        let index = 0;

        const next = async (): Promise<void> => {
            if (index < this.middleware.length) {
                const mw = this.middleware[index]!;
                index++;
                await mw(envelope, next);
            } else {
                await finalHandler();
            }
        };

        await next();
    }
}

/**
 * Create a scoped event bus that prefixes all event types
 * Useful for isolating events in components or modules
 *
 * @param eventBus - Parent EventBus instance
 * @param scope - Prefix to add to all event types
 * @returns Scoped EventBus interface
 */
export function createScopedEventBus(eventBus: EventBus, scope: string): Pick<EventBus, 'on' | 'once' | 'off' | 'emit'> {
    const prefix = (eventType: string) => `${scope}:${eventType}`;

    return {
        on: <T>(eventType: string, handler: EventHandler<T>, options?: SubscriptionOptions) => eventBus.on(prefix(eventType), handler, options),

        once: <T>(eventType: string, handler: EventHandler<T>, options?: Omit<SubscriptionOptions, 'once'>) => eventBus.once(prefix(eventType), handler, options),

        off: <T>(eventType: string, handler: EventHandler<T>) => eventBus.off(prefix(eventType), handler),

        emit: <T>(eventType: string, data: T, options?: { source?: string; correlationId?: string }) => eventBus.emit(prefix(eventType), data, options),
    };
}
