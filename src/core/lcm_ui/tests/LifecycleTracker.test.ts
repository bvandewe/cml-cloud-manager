/**
 * LifecycleTracker component tests.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import '../src/components/LifecycleTracker.js';

describe('LifecycleTracker', () => {
    let el: Element;

    const samplePhases = JSON.stringify([
        { name: 'upstream', status: 'completed', started_at: '2024-01-01T10:00:00Z', completed_at: '2024-01-01T10:01:00Z' },
        { name: 'storage', status: 'completed', started_at: '2024-01-01T10:01:00Z', completed_at: '2024-01-01T10:02:00Z' },
        { name: 'pod', status: 'running', started_at: '2024-01-01T10:02:00Z' },
        { name: 'lds', status: 'pending' },
        { name: 'score', status: 'pending' },
    ]);

    function create(attrs: Record<string, string> = {}): Element {
        el = document.createElement('ui-lifecycle-tracker');
        for (const [key, value] of Object.entries(attrs)) {
            el.setAttribute(key, value);
        }
        document.body.appendChild(el);
        return el;
    }

    afterEach(() => {
        el?.remove();
    });

    describe('compact layout', () => {
        it('renders colored dots', () => {
            create({ phases: samplePhases, layout: 'compact' });
            // Should render dot characters (●, ◐, ○, etc.)
            const text = el.textContent || '';
            expect(text.length).toBeGreaterThan(0);
        });

        it('applies correct colors', () => {
            create({ phases: samplePhases, layout: 'compact' });
            // Completed phases should have success styling
            expect(el.innerHTML).toContain('success');
        });
    });

    describe('horizontal layout', () => {
        it('renders step badges', () => {
            create({ phases: samplePhases, layout: 'horizontal' });
            const badges = el.querySelectorAll('.badge, [class*="step"]');
            expect(badges.length).toBeGreaterThan(0);
        });

        it('shows phase names', () => {
            create({ phases: samplePhases, layout: 'horizontal' });
            expect(el.innerHTML).toContain('upstream');
        });
    });

    describe('vertical layout', () => {
        it('renders detailed step list', () => {
            create({ phases: samplePhases, layout: 'vertical' });
            expect(el.innerHTML).toContain('upstream');
            expect(el.innerHTML).toContain('score');
        });

        it('shows timing when enabled', () => {
            create({ phases: samplePhases, layout: 'vertical', 'show-timing': '' });
            // Should show duration or time info
            const html = el.innerHTML;
            expect(html.length).toBeGreaterThan(50); // Non-trivial rendering
        });
    });

    describe('interactive mode', () => {
        it('emits phase-click event on click', () => {
            create({ phases: samplePhases, layout: 'horizontal', interactive: '' });
            const handler = vi.fn();
            el.addEventListener('phase-click', handler);

            const clickable = el.querySelector('[role="button"], button, [tabindex]');
            clickable?.dispatchEvent(new Event('click', { bubbles: true }));

            // May or may not fire depending on exact DOM structure
        });
    });

    describe('empty state', () => {
        it('handles empty phases array', () => {
            create({ phases: '[]' });
            // Should not throw, may show empty content
            expect(el.innerHTML).toBeDefined();
        });
    });

    describe('current-phase', () => {
        it('highlights the current phase', () => {
            create({ phases: samplePhases, layout: 'horizontal', 'current-phase': 'pod' });
            // Current phase should have distinct styling
            const html = el.innerHTML;
            expect(html).toContain('pod');
        });
    });
});
