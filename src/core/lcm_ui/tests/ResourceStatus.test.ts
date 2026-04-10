/**
 * ResourceStatus component tests.
 */
import { describe, it, expect, afterEach } from 'vitest';
import '../src/components/ResourceStatus.js';

describe('ResourceStatus', () => {
    let el: Element;

    function create(attrs: Record<string, string> = {}): Element {
        el = document.createElement('ui-resource-status');
        for (const [key, value] of Object.entries(attrs)) {
            el.setAttribute(key, value);
        }
        document.body.appendChild(el);
        return el;
    }

    afterEach(() => {
        el?.remove();
    });

    describe('single status (not reconciling)', () => {
        it('renders a single badge when no desired-status set', () => {
            create({ status: 'running' });
            const badges = el.querySelectorAll('.badge');
            expect(badges.length).toBe(1);
            expect(badges[0].textContent).toContain('Running');
        });

        it('renders single badge when desired equals current', () => {
            create({ status: 'running', 'desired-status': 'running' });
            const badges = el.querySelectorAll('.badge');
            expect(badges.length).toBe(1);
        });

        it('applies correct color for known status', () => {
            create({ status: 'running' });
            const badge = el.querySelector('.badge');
            expect(badge?.classList.contains('bg-success')).toBe(true);
        });
    });

    describe('reconciling (dual badge)', () => {
        it('renders two badges when desired differs from current', () => {
            create({ status: 'running', 'desired-status': 'stopped' });
            const badges = el.querySelectorAll('.badge');
            expect(badges.length).toBe(2);
        });

        it('shows reconciling text in non-compact mode', () => {
            create({ status: 'running', 'desired-status': 'stopped' });
            expect(el.innerHTML).toContain('Reconciling');
        });

        it('hides reconciling text in compact mode', () => {
            create({ status: 'running', 'desired-status': 'stopped', compact: '' });
            expect(el.innerHTML).not.toContain('Reconciling…');
        });

        it('shows arrow between badges', () => {
            create({ status: 'running', 'desired-status': 'stopped' });
            expect(el.querySelector('[class*="arrow"]')).not.toBeNull();
        });
    });

    describe('ARIA', () => {
        it('has status role on badges', () => {
            create({ status: 'running' });
            expect(el.querySelector('[role="status"]')).not.toBeNull();
        });

        it('has group role with label when reconciling', () => {
            create({ status: 'running', 'desired-status': 'stopped' });
            const group = el.querySelector('[role="group"]');
            expect(group).not.toBeNull();
            expect(group?.getAttribute('aria-label')).toContain('transitioning to');
        });
    });

    describe('attribute changes', () => {
        it('re-renders when status changes', () => {
            create({ status: 'running' });
            expect(el.innerHTML).toContain('Running');
            el.setAttribute('status', 'stopped');
            expect(el.innerHTML).toContain('Stopped');
        });
    });
});
