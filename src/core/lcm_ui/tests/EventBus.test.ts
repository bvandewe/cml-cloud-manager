/**
 * EventBus unit tests
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { EventBus, createScopedEventBus } from '../src/core/EventBus.js';

describe('EventBus', () => {
    let eventBus: EventBus;

    beforeEach(() => {
        EventBus.resetInstance();
        eventBus = new EventBus();
    });

    afterEach(() => {
        eventBus.reset();
    });

    describe('singleton', () => {
        it('should return same instance from getInstance()', () => {
            const instance1 = EventBus.getInstance();
            const instance2 = EventBus.getInstance();
            expect(instance1).toBe(instance2);
        });

        it('should reset instance with resetInstance()', () => {
            const instance1 = EventBus.getInstance();
            EventBus.resetInstance();
            const instance2 = EventBus.getInstance();
            expect(instance1).not.toBe(instance2);
        });
    });

    describe('on/off/emit', () => {
        it('should subscribe and receive events', async () => {
            const handler = vi.fn();
            eventBus.on('test:event', handler);

            await eventBus.emit('test:event', { value: 42 });

            expect(handler).toHaveBeenCalledTimes(1);
            expect(handler).toHaveBeenCalledWith(
                { value: 42 },
                expect.objectContaining({
                    type: 'test:event',
                    data: { value: 42 },
                    timestamp: expect.any(Number),
                })
            );
        });

        it('should unsubscribe with off()', async () => {
            const handler = vi.fn();
            eventBus.on('test:event', handler);
            eventBus.off('test:event', handler);

            await eventBus.emit('test:event', { value: 42 });

            expect(handler).not.toHaveBeenCalled();
        });

        it('should unsubscribe with subscription.unsubscribe()', async () => {
            const handler = vi.fn();
            const subscription = eventBus.on('test:event', handler);
            subscription.unsubscribe();

            await eventBus.emit('test:event', { value: 42 });

            expect(handler).not.toHaveBeenCalled();
        });

        it('should handle multiple subscribers', async () => {
            const handler1 = vi.fn();
            const handler2 = vi.fn();
            eventBus.on('test:event', handler1);
            eventBus.on('test:event', handler2);

            await eventBus.emit('test:event', { value: 42 });

            expect(handler1).toHaveBeenCalledTimes(1);
            expect(handler2).toHaveBeenCalledTimes(1);
        });

        it('should isolate handler errors', async () => {
            const errorHandler = vi.fn(() => {
                throw new Error('Handler error');
            });
            const successHandler = vi.fn();

            eventBus.on('test:event', errorHandler);
            eventBus.on('test:event', successHandler);

            await eventBus.emit('test:event', { value: 42 });

            expect(errorHandler).toHaveBeenCalled();
            expect(successHandler).toHaveBeenCalled();
        });

        it('should handle async handlers', async () => {
            const results: number[] = [];

            eventBus.on('test:event', async () => {
                await new Promise(r => setTimeout(r, 10));
                results.push(1);
            });

            eventBus.on('test:event', async () => {
                results.push(2);
            });

            await eventBus.emit('test:event', {});

            expect(results).toEqual([1, 2]);
        });
    });

    describe('once', () => {
        it('should only fire handler once', async () => {
            const handler = vi.fn();
            eventBus.once('test:event', handler);

            await eventBus.emit('test:event', { value: 1 });
            await eventBus.emit('test:event', { value: 2 });

            expect(handler).toHaveBeenCalledTimes(1);
            expect(handler).toHaveBeenCalledWith({ value: 1 }, expect.any(Object));
        });
    });

    describe('wildcard subscriptions', () => {
        it('should match wildcard patterns', async () => {
            const handler = vi.fn();
            eventBus.on('worker:*', handler);

            await eventBus.emit('worker:created', { id: '1' });
            await eventBus.emit('worker:updated', { id: '1' });
            await eventBus.emit('other:event', { id: '1' });

            expect(handler).toHaveBeenCalledTimes(2);
        });

        it('should match nested wildcard patterns', async () => {
            const handler = vi.fn();
            eventBus.on('worker:status:*', handler);

            await eventBus.emit('worker:status:changed', { id: '1' });
            await eventBus.emit('worker:status:pending', { id: '1' });
            await eventBus.emit('worker:created', { id: '1' });

            expect(handler).toHaveBeenCalledTimes(2);
        });

        it('should not double-call direct + wildcard subscribers', async () => {
            const directHandler = vi.fn();
            const wildcardHandler = vi.fn();

            eventBus.on('worker:created', directHandler);
            eventBus.on('worker:*', wildcardHandler);

            await eventBus.emit('worker:created', { id: '1' });

            expect(directHandler).toHaveBeenCalledTimes(1);
            expect(wildcardHandler).toHaveBeenCalledTimes(1);
        });
    });

    describe('priority ordering', () => {
        it('should call higher priority handlers first', async () => {
            const results: number[] = [];

            eventBus.on('test:event', () => results.push(1), { priority: 1 });
            eventBus.on('test:event', () => results.push(2), { priority: 10 });
            eventBus.on('test:event', () => results.push(3), { priority: 5 });

            await eventBus.emit('test:event', {});

            expect(results).toEqual([2, 3, 1]);
        });
    });

    describe('filter option', () => {
        it('should filter events based on predicate', async () => {
            const handler = vi.fn();

            eventBus.on('test:event', handler, {
                filter: data => (data as { include: boolean }).include === true,
            });

            await eventBus.emit('test:event', { include: true, value: 1 });
            await eventBus.emit('test:event', { include: false, value: 2 });
            await eventBus.emit('test:event', { include: true, value: 3 });

            expect(handler).toHaveBeenCalledTimes(2);
        });
    });

    describe('waitFor', () => {
        it('should resolve when event is emitted', async () => {
            const promise = eventBus.waitFor<{ value: number }>('test:event');

            // Emit after a short delay
            setTimeout(() => eventBus.emit('test:event', { value: 42 }), 10);

            const result = await promise;
            expect(result).toEqual({ value: 42 });
        });

        it('should reject on timeout', async () => {
            const promise = eventBus.waitFor('test:event', 50);

            await expect(promise).rejects.toThrow('Timeout waiting for event');
        });

        it('should cleanup subscription on timeout', async () => {
            const promise = eventBus.waitFor('test:event', 50);

            try {
                await promise;
            } catch {
                // Expected timeout
            }

            expect(eventBus.subscriberCount('test:event')).toBe(0);
        });
    });

    describe('event history', () => {
        it('should record events in history', async () => {
            await eventBus.emit('event:1', { a: 1 });
            await eventBus.emit('event:2', { b: 2 });

            const history = eventBus.getHistory();
            expect(history).toHaveLength(2);
            expect(history[0]?.type).toBe('event:1');
            expect(history[1]?.type).toBe('event:2');
        });

        it('should filter history by event type', async () => {
            await eventBus.emit('type:a', { v: 1 });
            await eventBus.emit('type:b', { v: 2 });
            await eventBus.emit('type:a', { v: 3 });

            const history = eventBus.getHistory('type:a');
            expect(history).toHaveLength(2);
        });

        it('should limit history size', async () => {
            const bus = new EventBus({ maxHistorySize: 3 });

            await bus.emit('e', { v: 1 });
            await bus.emit('e', { v: 2 });
            await bus.emit('e', { v: 3 });
            await bus.emit('e', { v: 4 });
            await bus.emit('e', { v: 5 });

            const history = bus.getHistory();
            expect(history).toHaveLength(3);
            expect(history[0]?.data).toEqual({ v: 3 });
        });

        it('should clear history', async () => {
            await eventBus.emit('event', { v: 1 });
            eventBus.clearHistory();

            expect(eventBus.getHistory()).toHaveLength(0);
        });
    });

    describe('middleware', () => {
        it('should run middleware before handlers', async () => {
            const order: string[] = [];

            eventBus.use(async (event, next) => {
                order.push('middleware:before');
                await next();
                order.push('middleware:after');
            });

            eventBus.on('test:event', () => {
                order.push('handler');
            });

            await eventBus.emit('test:event', {});

            expect(order).toEqual(['middleware:before', 'handler', 'middleware:after']);
        });

        it('should chain multiple middleware', async () => {
            const order: string[] = [];

            eventBus.use(async (event, next) => {
                order.push('mw1:before');
                await next();
                order.push('mw1:after');
            });

            eventBus.use(async (event, next) => {
                order.push('mw2:before');
                await next();
                order.push('mw2:after');
            });

            eventBus.on('test:event', () => order.push('handler'));

            await eventBus.emit('test:event', {});

            expect(order).toEqual(['mw1:before', 'mw2:before', 'handler', 'mw2:after', 'mw1:after']);
        });

        it('should remove middleware', async () => {
            const middleware = vi.fn(async (_event, next) => await next());
            eventBus.use(middleware);
            eventBus.removeMiddleware(middleware);

            await eventBus.emit('test:event', {});

            expect(middleware).not.toHaveBeenCalled();
        });
    });

    describe('subscriberCount', () => {
        it('should return count for specific event type', () => {
            eventBus.on('event:a', () => {});
            eventBus.on('event:a', () => {});
            eventBus.on('event:b', () => {});

            expect(eventBus.subscriberCount('event:a')).toBe(2);
            expect(eventBus.subscriberCount('event:b')).toBe(1);
            expect(eventBus.subscriberCount('event:c')).toBe(0);
        });

        it('should return total count when no type specified', () => {
            eventBus.on('event:a', () => {});
            eventBus.on('event:b', () => {});

            expect(eventBus.subscriberCount()).toBe(2);
        });
    });

    describe('hasSubscribers', () => {
        it('should return true for direct subscribers', () => {
            eventBus.on('test:event', () => {});
            expect(eventBus.hasSubscribers('test:event')).toBe(true);
        });

        it('should return true for wildcard match', () => {
            eventBus.on('test:*', () => {});
            expect(eventBus.hasSubscribers('test:event')).toBe(true);
        });

        it('should return false when no subscribers', () => {
            expect(eventBus.hasSubscribers('test:event')).toBe(false);
        });
    });

    describe('clear/reset', () => {
        it('should clear subscribers and middleware', async () => {
            const handler = vi.fn();
            const middleware = vi.fn(async (_e, next) => await next());

            eventBus.on('test:event', handler);
            eventBus.use(middleware);
            eventBus.clear();

            await eventBus.emit('test:event', {});

            expect(handler).not.toHaveBeenCalled();
            expect(middleware).not.toHaveBeenCalled();
        });

        it('should reset subscribers, middleware, and history', async () => {
            eventBus.on('test:event', () => {});
            eventBus.use(async (_e, next) => await next());
            await eventBus.emit('test:event', {});

            eventBus.reset();

            expect(eventBus.subscriberCount()).toBe(0);
            expect(eventBus.getHistory()).toHaveLength(0);
        });
    });

    describe('emit options', () => {
        it('should include source in envelope', async () => {
            const handler = vi.fn();
            eventBus.on('test:event', handler);

            await eventBus.emit('test:event', { value: 1 }, { source: 'test-component' });

            expect(handler).toHaveBeenCalledWith({ value: 1 }, expect.objectContaining({ source: 'test-component' }));
        });

        it('should include correlationId in envelope', async () => {
            const handler = vi.fn();
            eventBus.on('test:event', handler);

            await eventBus.emit('test:event', { value: 1 }, { correlationId: 'req-123' });

            expect(handler).toHaveBeenCalledWith({ value: 1 }, expect.objectContaining({ correlationId: 'req-123' }));
        });
    });
});

describe('createScopedEventBus', () => {
    let eventBus: EventBus;
    let scopedBus: ReturnType<typeof createScopedEventBus>;

    beforeEach(() => {
        eventBus = new EventBus();
        scopedBus = createScopedEventBus(eventBus, 'myComponent');
    });

    it('should prefix event types on emit', async () => {
        const handler = vi.fn();
        eventBus.on('myComponent:test', handler);

        await scopedBus.emit('test', { value: 1 });

        expect(handler).toHaveBeenCalledWith({ value: 1 }, expect.any(Object));
    });

    it('should prefix event types on subscribe', async () => {
        const handler = vi.fn();
        scopedBus.on('test', handler);

        await eventBus.emit('myComponent:test', { value: 1 });

        expect(handler).toHaveBeenCalledWith({ value: 1 }, expect.any(Object));
    });
});
