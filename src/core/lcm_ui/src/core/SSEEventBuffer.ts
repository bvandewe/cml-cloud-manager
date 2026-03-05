/**
 * SSEEventBuffer - Ring Buffer for SSE Events
 *
 * A fixed-size circular buffer for storing SSE events with memory safety.
 * Automatically discards oldest events when capacity is reached.
 *
 * @example
 * ```typescript
 * const buffer = new SSEEventBuffer(100);
 *
 * buffer.push({ type: 'heartbeat', data: {}, receivedAt: Date.now() });
 *
 * const recent = buffer.getRecent(10);
 * const byType = buffer.getByType('worker.snapshot');
 * ```
 *
 * @module core
 */

import type { SSEEvent } from '../types/events.js';

/**
 * SSEEventBuffer - Ring buffer for SSE events
 */
export class SSEEventBuffer {
    private buffer: (SSEEvent | null)[];
    private head: number;
    private tail: number;
    private count: number;
    private readonly _capacity: number;

    /**
     * Create a new SSEEventBuffer
     * @param capacity - Maximum number of events to store
     */
    constructor(capacity: number = 100) {
        if (capacity < 1) {
            throw new Error('Buffer capacity must be at least 1');
        }
        this._capacity = capacity;
        this.buffer = new Array(capacity).fill(null);
        this.head = 0;
        this.tail = 0;
        this.count = 0;
    }

    /**
     * Add an event to the buffer
     * @param event - SSE event to add
     */
    push(event: SSEEvent): void {
        this.buffer[this.tail] = event;
        this.tail = (this.tail + 1) % this._capacity;

        if (this.count < this._capacity) {
            this.count++;
        } else {
            // Buffer is full, move head forward (discarding oldest)
            this.head = (this.head + 1) % this._capacity;
        }
    }

    /**
     * Get the most recent N events
     * @param n - Number of events to retrieve
     * @returns Array of events (newest last)
     */
    getRecent(n: number): SSEEvent[] {
        const result: SSEEvent[] = [];
        const limit = Math.min(n, this.count);

        // Start from the most recent (tail - 1) and go backwards
        for (let i = 0; i < limit; i++) {
            const index = (this.tail - 1 - i + this._capacity) % this._capacity;
            const event = this.buffer[index];
            if (event != null) {
                result.unshift(event);
            }
        }

        return result;
    }

    /**
     * Get all events of a specific type
     * @param type - Event type to filter by
     * @returns Array of matching events
     */
    getByType(type: string): SSEEvent[] {
        const result: SSEEvent[] = [];

        for (let i = 0; i < this.count; i++) {
            const index = (this.head + i) % this._capacity;
            const event = this.buffer[index];
            if (event != null && event.type === type) {
                result.push(event);
            }
        }

        return result;
    }

    /**
     * Get events received after a specific timestamp
     * @param timestamp - Unix timestamp in milliseconds
     * @returns Array of matching events
     */
    getAfter(timestamp: number): SSEEvent[] {
        const result: SSEEvent[] = [];

        for (let i = 0; i < this.count; i++) {
            const index = (this.head + i) % this._capacity;
            const event = this.buffer[index];
            if (event != null && event.receivedAt > timestamp) {
                result.push(event);
            }
        }

        return result;
    }

    /**
     * Get all events in the buffer
     * @returns Array of all events (oldest first)
     */
    getAll(): SSEEvent[] {
        const result: SSEEvent[] = [];

        for (let i = 0; i < this.count; i++) {
            const index = (this.head + i) % this._capacity;
            const event = this.buffer[index];
            if (event != null) {
                result.push(event);
            }
        }

        return result;
    }

    /**
     * Get the most recent event
     * @returns Most recent event or undefined if buffer is empty
     */
    peek(): SSEEvent | undefined {
        if (this.count === 0) {
            return undefined;
        }
        const index = (this.tail - 1 + this._capacity) % this._capacity;
        return this.buffer[index] ?? undefined;
    }

    /**
     * Get the oldest event
     * @returns Oldest event or undefined if buffer is empty
     */
    peekOldest(): SSEEvent | undefined {
        if (this.count === 0) {
            return undefined;
        }
        return this.buffer[this.head] ?? undefined;
    }

    /**
     * Check if the buffer is empty
     */
    isEmpty(): boolean {
        return this.count === 0;
    }

    /**
     * Check if the buffer is full
     */
    isFull(): boolean {
        return this.count === this._capacity;
    }

    /**
     * Get the current size (property accessor)
     */
    get size(): number {
        return this.count;
    }

    /**
     * Get the buffer capacity (property accessor)
     */
    get capacity(): number {
        return this._capacity;
    }

    /**
     * Clear all events from the buffer
     */
    clear(): void {
        this.buffer.fill(null);
        this.head = 0;
        this.tail = 0;
        this.count = 0;
    }

    /**
     * Get buffer statistics
     */
    getStats(): {
        size: number;
        capacity: number;
        fillPercentage: number;
        oldestTimestamp: number | undefined;
        newestTimestamp: number | undefined;
        eventTypeCounts: Record<string, number>;
    } {
        const oldest = this.peekOldest();
        const newest = this.peek();

        // Count events by type
        const eventTypeCounts: Record<string, number> = {};
        const events = this.getAll();
        for (const event of events) {
            eventTypeCounts[event.type] = (eventTypeCounts[event.type] ?? 0) + 1;
        }

        return {
            size: this.count,
            capacity: this._capacity,
            fillPercentage: (this.count / this._capacity) * 100,
            oldestTimestamp: oldest?.receivedAt,
            newestTimestamp: newest?.receivedAt,
            eventTypeCounts,
        };
    }
}
