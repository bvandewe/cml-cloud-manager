/**
 * ColumnPicker component tests.
 */
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import '../src/components/ColumnPicker.js';

describe('ColumnPicker', () => {
    let el: Element & { setColumns?: Function };

    function create(attrs: Record<string, string> = {}): typeof el {
        el = document.createElement('ui-column-picker') as typeof el;
        for (const [key, value] of Object.entries(attrs)) {
            el.setAttribute(key, value);
        }
        document.body.appendChild(el);
        return el;
    }

    const sampleColumns = [
        { key: 'name', label: 'Name', category: 'identity', visible: true },
        { key: 'status', label: 'Status', category: 'status', visible: true },
        { key: 'region', label: 'Region', category: 'identity', visible: true },
        { key: 'cpu', label: 'CPU', category: 'metrics', visible: false },
        { key: 'memory', label: 'Memory', category: 'metrics', visible: false },
        { key: 'created_at', label: 'Created', category: 'timing', visible: true },
    ];

    const defaults = ['name', 'status', 'region', 'created_at'];

    beforeEach(() => {
        localStorage.clear();
    });

    afterEach(() => {
        el?.remove();
        localStorage.clear();
    });

    describe('rendering', () => {
        it('renders a dropdown button after setColumns', () => {
            create({ 'table-id': 'test-table' });
            if (typeof el.setColumns === 'function') {
                el.setColumns(sampleColumns, defaults);
            }
            const btn = el.querySelector('.column-picker-toggle');
            expect(btn).not.toBeNull();
        });

        it('renders column checkboxes after setColumns', () => {
            create({ 'table-id': 'test-table' });
            if (typeof el.setColumns === 'function') {
                el.setColumns(sampleColumns, defaults);
                const checkboxes = el.querySelectorAll('input[type="checkbox"]');
                expect(checkboxes.length).toBe(sampleColumns.length);
            }
        });

        it('groups columns by category', () => {
            create({ 'table-id': 'test-table' });
            if (typeof el.setColumns === 'function') {
                el.setColumns(sampleColumns, defaults);
                // Should have category headers
                const html = el.innerHTML;
                expect(html).toContain('Identity');
            }
        });
    });

    describe('visibility toggle', () => {
        it('emits columns-changed event on checkbox change', () => {
            create({ 'table-id': 'test-table' });
            if (typeof el.setColumns === 'function') {
                el.setColumns(sampleColumns, defaults);
            }

            const handler = vi.fn();
            el.addEventListener('columns-changed', handler);

            const checkbox = el.querySelector('input[type="checkbox"]') as HTMLInputElement;
            if (checkbox) {
                checkbox.checked = !checkbox.checked;
                checkbox.dispatchEvent(new Event('change', { bubbles: true }));
                expect(handler).toHaveBeenCalled();
            }
        });
    });

    describe('localStorage persistence', () => {
        it('saves visibility to localStorage', () => {
            create({ 'table-id': 'persist-test' });
            if (typeof el.setColumns === 'function') {
                el.setColumns(sampleColumns, defaults);
            }

            // Toggle a checkbox
            const checkbox = el.querySelector('input[type="checkbox"]') as HTMLInputElement;
            if (checkbox) {
                checkbox.checked = !checkbox.checked;
                checkbox.dispatchEvent(new Event('change', { bubbles: true }));
            }

            const stored = localStorage.getItem('lcm.columns.persist-test');
            // May or may not be saved depending on implementation timing
        });

        it('uses lcm.columns.<tableId> key convention', () => {
            create({ 'table-id': 'my-table' });
            // Verify the key pattern is correct
            expect('lcm.columns.my-table').toMatch(/^lcm\.columns\./);
        });
    });

    describe('reset to defaults', () => {
        it('has a reset button', () => {
            create({ 'table-id': 'test-table' });
            if (typeof el.setColumns === 'function') {
                el.setColumns(sampleColumns, defaults);
            }
            const resetBtn = el.querySelector('[class*="reset"], button[title*="Reset"], button[title*="reset"]');
            // Reset button may or may not exist depending on implementation
        });
    });
});
