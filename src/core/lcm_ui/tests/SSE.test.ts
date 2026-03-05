/**
 * SSEClient and SSEEventBuffer Tests
 */

import { describe, it, expect, beforeEach, afterEach, vi, Mock } from 'vitest';
import { SSEClient } from '../src/core/SSEClient.js';
import { SSEEventBuffer } from '../src/core/SSEEventBuffer.js';
import { EventBus } from '../src/core/EventBus.js';
import { EventTypes } from '../src/core/index.js';

// Mock EventSource
class MockEventSource {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    static readonly CLOSED = 2;

    url: string;
    withCredentials: boolean;
    readyState: number;
    onopen: ((event: Event) => void) | null = null;
    onerror: ((event: Event) => void) | null = null;
    onmessage: ((event: MessageEvent) => void) | null = null;
    private listeners: Map<string, Set<(event: MessageEvent) => void>> = new Map();

    constructor(url: string, options?: { withCredentials?: boolean }) {
        this.url = url;
        this.withCredentials = options?.withCredentials ?? false;
        this.readyState = MockEventSource.CONNECTING;
    }

    addEventListener(type: string, listener: (event: MessageEvent) => void): void {
        if (!this.listeners.has(type)) {
            this.listeners.set(type, new Set());
        }
        this.listeners.get(type)!.add(listener);
    }

    removeEventListener(type: string, listener: (event: MessageEvent) => void): void {
        this.listeners.get(type)?.delete(listener);
    }

    close(): void {
        this.readyState = MockEventSource.CLOSED;
    }

    // Test helpers
    simulateOpen(): void {
        this.readyState = MockEventSource.OPEN;
        this.onopen?.(new Event('open'));
    }

    simulateError(closeConnection = false): void {
        if (closeConnection) {
            this.readyState = MockEventSource.CLOSED;
        }
        this.onerror?.(new Event('error'));
    }

    simulateMessage(data: string, lastEventId?: string): void {
        const event = new MessageEvent('message', {
            data,
            lastEventId: lastEventId ?? '',
        });
        this.onmessage?.(event);
    }

    simulateNamedEvent(type: string, data: string, lastEventId?: string): void {
        const event = new MessageEvent(type, {
            data,
            lastEventId: lastEventId ?? '',
        });
        this.listeners.get(type)?.forEach(listener => listener(event));
    }
}

// Install mock globally
const originalEventSource = globalThis.EventSource;

describe('SSEEventBuffer', () => {
    let buffer: SSEEventBuffer;

    beforeEach(() => {
        buffer = new SSEEventBuffer(5);
    });

    describe('constructor', () => {
        it('should create buffer with specified capacity', () => {
            expect(buffer.capacity).toBe(5);
            expect(buffer.size).toBe(0);
        });

        it('should use default capacity if not specified', () => {
            const defaultBuffer = new SSEEventBuffer();
            expect(defaultBuffer.capacity).toBe(100);
        });
    });

    describe('push', () => {
        it('should add events to buffer', () => {
            buffer.push({ type: 'test', data: 'data1', receivedAt: 1000 });
            expect(buffer.size).toBe(1);

            buffer.push({ type: 'test', data: 'data2', receivedAt: 2000 });
            expect(buffer.size).toBe(2);
        });

        it('should overwrite oldest events when at capacity', () => {
            for (let i = 0; i < 7; i++) {
                buffer.push({ type: 'test', data: `data${i}`, receivedAt: i * 1000 });
            }

            expect(buffer.size).toBe(5);
            const events = buffer.getAll();
            expect(events[0].data).toBe('data2'); // 0 and 1 were overwritten
            expect(events[4].data).toBe('data6');
        });
    });

    describe('getRecent', () => {
        beforeEach(() => {
            for (let i = 0; i < 5; i++) {
                buffer.push({ type: 'test', data: `data${i}`, receivedAt: i * 1000 });
            }
        });

        it('should return recent events in order', () => {
            const recent = buffer.getRecent(3);
            expect(recent).toHaveLength(3);
            expect(recent[0].data).toBe('data2');
            expect(recent[2].data).toBe('data4');
        });

        it('should return all events if count exceeds size', () => {
            const recent = buffer.getRecent(10);
            expect(recent).toHaveLength(5);
        });

        it('should return empty array for empty buffer', () => {
            const emptyBuffer = new SSEEventBuffer();
            expect(emptyBuffer.getRecent(5)).toHaveLength(0);
        });
    });

    describe('getByType', () => {
        beforeEach(() => {
            buffer.push({ type: 'alpha', data: 'a1', receivedAt: 1000 });
            buffer.push({ type: 'beta', data: 'b1', receivedAt: 2000 });
            buffer.push({ type: 'alpha', data: 'a2', receivedAt: 3000 });
            buffer.push({ type: 'gamma', data: 'g1', receivedAt: 4000 });
            buffer.push({ type: 'alpha', data: 'a3', receivedAt: 5000 });
        });

        it('should filter events by type', () => {
            const alphaEvents = buffer.getByType('alpha');
            expect(alphaEvents).toHaveLength(3);
            expect(alphaEvents.every(e => e.type === 'alpha')).toBe(true);
        });

        it('should return empty array for non-existent type', () => {
            const events = buffer.getByType('nonexistent');
            expect(events).toHaveLength(0);
        });
    });

    describe('getAfter', () => {
        beforeEach(() => {
            for (let i = 0; i < 5; i++) {
                buffer.push({ type: 'test', data: `data${i}`, receivedAt: (i + 1) * 1000 });
            }
        });

        it('should return events after timestamp', () => {
            const events = buffer.getAfter(3000);
            expect(events).toHaveLength(2);
            expect(events[0].receivedAt).toBe(4000);
            expect(events[1].receivedAt).toBe(5000);
        });

        it('should return all events if timestamp is 0', () => {
            const events = buffer.getAfter(0);
            expect(events).toHaveLength(5);
        });

        it('should return empty array if all events are before timestamp', () => {
            const events = buffer.getAfter(10000);
            expect(events).toHaveLength(0);
        });
    });

    describe('peek', () => {
        it('should return most recent event without removing', () => {
            buffer.push({ type: 'test', data: 'data1', receivedAt: 1000 });
            buffer.push({ type: 'test', data: 'data2', receivedAt: 2000 });

            const peeked = buffer.peek();
            expect(peeked?.data).toBe('data2');
            expect(buffer.size).toBe(2); // Not removed
        });

        it('should return undefined for empty buffer', () => {
            expect(buffer.peek()).toBeUndefined();
        });
    });

    describe('peekOldest', () => {
        it('should return oldest event without removing', () => {
            buffer.push({ type: 'test', data: 'data1', receivedAt: 1000 });
            buffer.push({ type: 'test', data: 'data2', receivedAt: 2000 });

            const oldest = buffer.peekOldest();
            expect(oldest?.data).toBe('data1');
            expect(buffer.size).toBe(2);
        });

        it('should return undefined for empty buffer', () => {
            expect(buffer.peekOldest()).toBeUndefined();
        });
    });

    describe('clear', () => {
        it('should clear all events', () => {
            buffer.push({ type: 'test', data: 'data1', receivedAt: 1000 });
            buffer.push({ type: 'test', data: 'data2', receivedAt: 2000 });

            buffer.clear();
            expect(buffer.size).toBe(0);
            expect(buffer.getAll()).toHaveLength(0);
        });
    });

    describe('getStats', () => {
        it('should return correct statistics', () => {
            buffer.push({ type: 'alpha', data: 'a1', receivedAt: 1000 });
            buffer.push({ type: 'beta', data: 'b1', receivedAt: 2000 });
            buffer.push({ type: 'alpha', data: 'a2', receivedAt: 3000 });

            const stats = buffer.getStats();
            expect(stats.size).toBe(3);
            expect(stats.capacity).toBe(5);
            expect(stats.oldestTimestamp).toBe(1000);
            expect(stats.newestTimestamp).toBe(3000);
            expect(stats.eventTypeCounts).toEqual({ alpha: 2, beta: 1 });
        });

        it('should handle empty buffer', () => {
            const stats = buffer.getStats();
            expect(stats.size).toBe(0);
            expect(stats.oldestTimestamp).toBeUndefined();
            expect(stats.newestTimestamp).toBeUndefined();
            expect(stats.eventTypeCounts).toEqual({});
        });
    });
});

describe('SSEClient', () => {
    let client: SSEClient;
    let eventBus: EventBus;
    let mockEventSource: MockEventSource;

    beforeEach(() => {
        // Reset EventBus singleton
        (EventBus as any)._instance = null;
        eventBus = EventBus.getInstance();

        // Mock EventSource constructor as a function that returns MockEventSource
        const MockEventSourceConstructor = vi.fn((url: string, options?: { withCredentials?: boolean }) => {
            mockEventSource = new MockEventSource(url, options);
            return mockEventSource;
        }) as any;

        // Add static properties for EventSource states
        MockEventSourceConstructor.CONNECTING = 0;
        MockEventSourceConstructor.OPEN = 1;
        MockEventSourceConstructor.CLOSED = 2;

        (globalThis as any).EventSource = MockEventSourceConstructor;

        vi.useFakeTimers();
    });

    afterEach(() => {
        vi.clearAllTimers();
        vi.useRealTimers();
        (globalThis as any).EventSource = originalEventSource;
        (EventBus as any)._instance = null;
    });

    describe('constructor', () => {
        it('should create client with default options', () => {
            client = new SSEClient('/api/events', eventBus);
            expect(client.getConnectionState()).toBe('disconnected');
            expect(client.isConnected()).toBe(false);
        });

        it('should accept custom options', () => {
            client = new SSEClient('/api/events', eventBus, {
                autoReconnect: false,
                reconnectDelay: 5000,
                maxReconnectAttempts: 5,
                heartbeatTimeout: 30000,
                bufferSize: 50,
                eventMap: { 'worker.status': 'worker:status' },
            });

            expect(client.getConnectionState()).toBe('disconnected');
        });
    });

    describe('connect', () => {
        beforeEach(() => {
            client = new SSEClient('/api/events', eventBus);
        });

        it('should create EventSource and set connecting state', () => {
            client.connect();

            expect(globalThis.EventSource).toHaveBeenCalledWith('/api/events', { withCredentials: true });
            expect(client.getConnectionState()).toBe('connecting');
        });

        it('should set connected state on open', () => {
            const connectedHandler = vi.fn();
            eventBus.on(EventTypes.SSE_CONNECTED, connectedHandler);

            client.connect();
            mockEventSource.simulateOpen();

            expect(client.getConnectionState()).toBe('connected');
            expect(client.isConnected()).toBe(true);
            expect(connectedHandler).toHaveBeenCalled();
        });

        it('should not create duplicate connections', () => {
            client.connect();
            client.connect();

            expect(globalThis.EventSource).toHaveBeenCalledTimes(1);
        });
    });

    describe('disconnect', () => {
        beforeEach(() => {
            client = new SSEClient('/api/events', eventBus);
        });

        it('should close connection and set disconnected state', () => {
            client.connect();
            mockEventSource.simulateOpen();

            const disconnectedHandler = vi.fn();
            eventBus.on(EventTypes.SSE_DISCONNECTED, disconnectedHandler);

            client.disconnect();

            expect(client.getConnectionState()).toBe('disconnected');
            expect(client.isConnected()).toBe(false);
            expect(mockEventSource.readyState).toBe(MockEventSource.CLOSED);
            expect(disconnectedHandler).toHaveBeenCalledWith(expect.objectContaining({ wasIntentional: true }), expect.any(Object));
        });
    });

    describe('event handling', () => {
        beforeEach(() => {
            client = new SSEClient('/api/events', eventBus, {
                eventMap: {
                    'worker.status': 'worker:status',
                },
            });
        });

        it('should emit events to EventBus', async () => {
            const messageHandler = vi.fn();
            eventBus.on('message', messageHandler);

            client.connect();
            mockEventSource.simulateOpen();
            mockEventSource.simulateMessage('{"id": "123", "name": "test"}');

            // Wait for async emit to complete
            await vi.waitFor(() => {
                expect(messageHandler).toHaveBeenCalledWith({ id: '123', name: 'test' }, expect.objectContaining({ source: 'sse' }));
            });
        });

        it('should map event types according to eventMap', async () => {
            const statusHandler = vi.fn();
            eventBus.on('worker:status', statusHandler);

            client.connect();
            mockEventSource.simulateOpen();
            mockEventSource.simulateNamedEvent('worker.status', '{"status": "running"}');

            await vi.waitFor(() => {
                expect(statusHandler).toHaveBeenCalledWith({ status: 'running' }, expect.any(Object));
            });
        });

        it('should buffer events', async () => {
            client.connect();
            mockEventSource.simulateOpen();

            for (let i = 0; i < 5; i++) {
                mockEventSource.simulateMessage(`{"id": ${i}}`);
            }

            // Wait for async processing
            await vi.waitFor(() => {
                const buffer = client.getEventBuffer();
                expect(buffer.size).toBe(5);
            });
        });

        it('should handle non-JSON data', async () => {
            const messageHandler = vi.fn();
            eventBus.on('message', messageHandler);

            client.connect();
            mockEventSource.simulateOpen();
            mockEventSource.simulateMessage('plain text message');

            await vi.waitFor(() => {
                expect(messageHandler).toHaveBeenCalledWith('plain text message', expect.any(Object));
            });
        });
    });

    describe('registerEventType', () => {
        beforeEach(() => {
            client = new SSEClient('/api/events', eventBus);
        });

        it('should register new event types', () => {
            client.registerEventType('custom.event', 'custom:event');

            expect(client.getRegisteredEventTypes()).toContain('custom.event');
        });

        it('should add listeners for registered types when connected', () => {
            client.connect();
            mockEventSource.simulateOpen();

            client.registerEventType('custom.event', 'custom:event');

            const customHandler = vi.fn();
            eventBus.on('custom:event', customHandler);

            mockEventSource.simulateNamedEvent('custom.event', '{"data": "test"}');

            expect(customHandler).toHaveBeenCalled();
        });
    });

    describe('auto-reconnect', () => {
        beforeEach(() => {
            client = new SSEClient('/api/events', eventBus, {
                autoReconnect: true,
                reconnectDelay: 1000,
                maxReconnectAttempts: 3,
            });
        });

        it('should schedule reconnect on connection error', async () => {
            const reconnectingHandler = vi.fn();
            eventBus.on(EventTypes.SSE_RECONNECTING, reconnectingHandler);

            client.connect();
            mockEventSource.simulateOpen();
            mockEventSource.simulateError(true); // Close connection

            // Wait for async emit to complete
            await vi.waitFor(() => {
                expect(reconnectingHandler).toHaveBeenCalledWith(expect.objectContaining({ attempt: 1 }), expect.any(Object));
            });
        });

        it('should use exponential backoff', async () => {
            client.connect();
            mockEventSource.simulateOpen();
            mockEventSource.simulateError(true);

            // First reconnect after ~1000ms (with up to 1000ms jitter)
            await vi.advanceTimersByTimeAsync(2500);
            expect(globalThis.EventSource).toHaveBeenCalledTimes(2);

            // Simulate next connection opening and failing
            mockEventSource.simulateOpen();
            mockEventSource.simulateError(true);

            // Second reconnect after ~2000ms + jitter
            await vi.advanceTimersByTimeAsync(4000);
            expect(globalThis.EventSource).toHaveBeenCalledTimes(3);
        });

        it('should stop after max attempts', async () => {
            // With maxReconnectAttempts=3, we need 3 failed reconnects (not counting initial)
            // Connection failures without successful open don't reset the counter

            client.connect(); // Initial connection

            // Initial connect fails immediately (never opens)
            mockEventSource.simulateError(true);
            await vi.advanceTimersByTimeAsync(2500); // First reconnect fires (attempt 1)

            // Reconnect 1 fails immediately
            mockEventSource.simulateError(true);
            await vi.advanceTimersByTimeAsync(5000); // Second reconnect fires (attempt 2)

            // Reconnect 2 fails immediately
            mockEventSource.simulateError(true);
            await vi.advanceTimersByTimeAsync(10000); // Third reconnect fires (attempt 3)

            // Reconnect 3 fails immediately → max attempts reached
            mockEventSource.simulateError(true);

            // Wait for any pending async operations
            await vi.advanceTimersByTimeAsync(1000);

            // Should now be in error state
            expect(client.getConnectionState()).toBe('error');
        });

        it('should not reconnect if intentionally disconnected', async () => {
            client.connect();
            mockEventSource.simulateOpen();
            client.disconnect();

            await vi.advanceTimersByTimeAsync(5000);
            expect(globalThis.EventSource).toHaveBeenCalledTimes(1);
        });
    });

    describe('heartbeat monitoring', () => {
        beforeEach(() => {
            client = new SSEClient('/api/events', eventBus, {
                heartbeatTimeout: 5000,
                autoReconnect: true,
                reconnectDelay: 1000,
            });
        });

        it('should trigger reconnect on heartbeat timeout', () => {
            client.connect();
            mockEventSource.simulateOpen();

            // Advance past heartbeat timeout
            vi.advanceTimersByTime(6000);

            expect(client.getConnectionState()).not.toBe('connected');
        });

        it('should reset timer on event received', () => {
            client.connect();
            mockEventSource.simulateOpen();

            // Advance part way
            vi.advanceTimersByTime(3000);

            // Receive event
            mockEventSource.simulateMessage('{"keep": "alive"}');

            // Advance more (but less than full timeout from event)
            vi.advanceTimersByTime(3000);

            // Should still be connected
            expect(client.isConnected()).toBe(true);
        });
    });

    describe('getStats', () => {
        beforeEach(() => {
            client = new SSEClient('/api/events', eventBus, {
                eventMap: { 'worker.status': 'worker:status' },
            });
        });

        it('should return connection statistics', async () => {
            client.connect();
            mockEventSource.simulateOpen();
            mockEventSource.simulateMessage('{"test": "data"}');

            // Wait for async processing
            await vi.waitFor(() => {
                const stats = client.getStats();
                expect(stats.bufferStats.size).toBe(1);
            });

            const stats = client.getStats();
            expect(stats.connectionState).toBe('connected');
            expect(stats.reconnectAttempts).toBe(0);
            expect(stats.lastEventTime).toBeGreaterThan(0);
            expect(stats.registeredEventTypes).toContain('worker.status');
        });
    });

    describe('updateEventMap', () => {
        beforeEach(() => {
            client = new SSEClient('/api/events', eventBus);
        });

        it('should update event mappings', () => {
            client.updateEventMap({
                'lab.created': 'lab:created',
                'lab.deleted': 'lab:deleted',
            });

            expect(client.getRegisteredEventTypes()).toContain('lab.created');
            expect(client.getRegisteredEventTypes()).toContain('lab.deleted');
        });

        it('should apply mappings to new events', async () => {
            client.connect();
            mockEventSource.simulateOpen();

            client.updateEventMap({ 'custom.event': 'custom:event' });

            const handler = vi.fn();
            eventBus.on('custom:event', handler);

            mockEventSource.simulateNamedEvent('custom.event', '{"data": 1}');

            await vi.waitFor(() => {
                expect(handler).toHaveBeenCalled();
            });
        });
    });
});
