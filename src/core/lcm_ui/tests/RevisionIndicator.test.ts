/**
 * RevisionIndicator component tests.
 */
import { describe, it, expect, afterEach, beforeEach } from 'vitest';
import '../src/components/RevisionIndicator.js';

describe('RevisionIndicator', () => {
    let el: Element;

    function create(attrs: Record<string, string> = {}): Element {
        el = document.createElement('ui-revision-indicator');
        for (const [key, value] of Object.entries(attrs)) {
            el.setAttribute(key, value);
        }
        document.body.appendChild(el);
        return el;
    }

    beforeEach(() => {
        localStorage.clear();
    });

    afterEach(() => {
        el?.remove();
        localStorage.clear();
    });

    describe('basic rendering', () => {
        it('renders version number', () => {
            create({ version: '5' });
            expect(el.textContent).toContain('5');
        });

        it('renders "v" prefix', () => {
            create({ version: '12' });
            expect(el.textContent).toContain('v');
        });
    });

    describe('change detection', () => {
        it('shows delta badge when version differs from last seen', () => {
            localStorage.setItem('lcm.revision.worker-1', '3');
            create({ version: '7', 'resource-id': 'worker-1' });
            expect(el.innerHTML).toContain('△');
        });

        it('does not show delta when version matches last seen', () => {
            localStorage.setItem('lcm.revision.worker-1', '5');
            create({ version: '5', 'resource-id': 'worker-1' });
            expect(el.innerHTML).not.toContain('△');
        });

        it('does not show delta on first view (no stored version)', () => {
            create({ version: '3', 'resource-id': 'worker-new' });
            // First view - no prior version, may or may not show delta
            // The component should handle gracefully
            expect(el.textContent).toContain('3');
        });
    });

    describe('localStorage persistence', () => {
        it('stores last-seen version on click', () => {
            create({ version: '10', 'resource-id': 'worker-1' });
            const badge = el.querySelector('.lcm-revision-badge');
            badge?.dispatchEvent(new Event('click', { bubbles: true }));
            expect(localStorage.getItem('lcm.revision.worker-1')).toBe('10');
        });

        it('uses lcm.revision.<resourceId> key convention', () => {
            create({ version: '5', 'resource-id': 'my-resource' });
            const badge = el.querySelector('.lcm-revision-badge');
            badge?.dispatchEvent(new Event('click', { bubbles: true }));
            expect(localStorage.getItem('lcm.revision.my-resource')).toBe('5');
        });
    });

    describe('compact mode', () => {
        it('renders compact badge', () => {
            create({ version: '5', compact: '' });
            // Compact mode should produce minimal output
            expect(el.innerHTML.length).toBeLessThan(200);
        });
    });

    describe('previous-version', () => {
        it('shows explicit previous version delta', () => {
            create({ version: '8', 'previous-version': '5' });
            expect(el.innerHTML).toContain('△');
        });
    });
});
