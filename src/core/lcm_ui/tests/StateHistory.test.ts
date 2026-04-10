/**
 * StateHistory component tests.
 */
import { describe, it, expect, afterEach } from 'vitest';
import '../src/components/StateHistory.js';

describe('StateHistory', () => {
    let el: Element;

    const sampleTransitions = JSON.stringify([
        { from_state: 'pending', to_state: 'provisioning', transitioned_at: '2024-01-01T10:00:00Z', triggered_by: 'user' },
        { from_state: 'provisioning', to_state: 'running', transitioned_at: '2024-01-01T10:05:00Z' },
        { from_state: 'running', to_state: 'stopping', transitioned_at: '2024-01-01T12:00:00Z', reason: 'idle timeout' },
    ]);

    function create(attrs: Record<string, string> = {}): Element {
        el = document.createElement('ui-state-history');
        for (const [key, value] of Object.entries(attrs)) {
            el.setAttribute(key, value);
        }
        document.body.appendChild(el);
        return el;
    }

    afterEach(() => {
        el?.remove();
    });

    describe('compact mode', () => {
        it('renders badge chain in compact mode', () => {
            create({ transitions: sampleTransitions, compact: '' });
            const badges = el.querySelectorAll('.badge');
            expect(badges.length).toBeGreaterThan(0);
        });

        it('renders chevron separators', () => {
            create({ transitions: sampleTransitions, compact: '' });
            expect(el.innerHTML).toContain('chevron');
        });
    });

    describe('full mode', () => {
        it('renders timeline list in full mode', () => {
            create({ transitions: sampleTransitions });
            const items = el.querySelectorAll('[role="listitem"]');
            expect(items.length).toBeGreaterThan(0);
        });

        it('shows triggered_by when available', () => {
            create({ transitions: sampleTransitions, 'show-metadata': '' });
            expect(el.innerHTML).toContain('user');
        });

        it('shows reason when available', () => {
            create({ transitions: sampleTransitions, 'show-metadata': '' });
            expect(el.innerHTML).toContain('idle timeout');
        });
    });

    describe('max-visible', () => {
        it('limits displayed transitions', () => {
            const many = JSON.stringify(
                Array.from({ length: 10 }, (_, i) => ({
                    from_state: `state_${i}`,
                    to_state: `state_${i + 1}`,
                    transitioned_at: new Date(2024, 0, 1, 10 + i).toISOString(),
                }))
            );
            create({ transitions: many, 'max-visible': '3' });
            expect(el.innerHTML).toContain('Show');
        });
    });

    describe('empty state', () => {
        it('renders empty message when no transitions', () => {
            create({ transitions: '[]' });
            expect(el.innerHTML).toContain('No');
        });
    });

    describe('ARIA', () => {
        it('has navigation landmark', () => {
            create({ transitions: sampleTransitions });
            const nav = el.querySelector('[role="navigation"], [aria-label*="history"], [aria-label*="State"]');
            expect(nav).not.toBeNull();
        });
    });
});
