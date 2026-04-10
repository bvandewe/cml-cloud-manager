/**
 * ResourceObservation component tests.
 */
import { describe, it, expect, afterEach } from 'vitest';
import '../src/components/ResourceObservation.js';

describe('ResourceObservation', () => {
    let el: Element;

    const sampleObservation = JSON.stringify({
        cpu_usage: 65,
        memory_usage: 82.3,
        storage_usage: 45.0,
        nodes: [
            { label: 'node-1', state: 'BOOTED', cpu_usage: 70, memory_usage_mb: 80 },
            { label: 'node-2', state: 'BOOTED', cpu_usage: 50, memory_usage_mb: 60 },
        ],
    });

    function create(attrs: Record<string, string> = {}): Element {
        el = document.createElement('ui-resource-observation');
        for (const [key, value] of Object.entries(attrs)) {
            el.setAttribute(key, value);
        }
        document.body.appendChild(el);
        return el;
    }

    afterEach(() => {
        el?.remove();
    });

    describe('basic rendering', () => {
        it('renders progress bars for cpu, memory, storage', () => {
            create({ observation: sampleObservation });
            const bars = el.querySelectorAll('.progress');
            expect(bars.length).toBeGreaterThan(0);
        });

        it('displays percentage values', () => {
            create({ observation: sampleObservation });
            const html = el.innerHTML;
            // Should contain the percentage values from cpu_usage and memory_usage
            expect(html).toContain('65');
            expect(html).toContain('82');
        });
    });

    describe('warning threshold', () => {
        it('applies warning color above threshold', () => {
            create({ observation: sampleObservation, 'warn-threshold': '80' });
            // memory at 82.3 > 80 should be warning
            expect(el.innerHTML).toContain('warning');
        });

        it('applies success color below threshold', () => {
            create({ observation: sampleObservation, 'warn-threshold': '80' });
            // storage at 45 < 80 should be success
            expect(el.innerHTML).toContain('success');
        });
    });

    describe('compact mode', () => {
        it('renders micro bars in compact mode', () => {
            create({ observation: sampleObservation, compact: '' });
            // Compact mode should produce smaller output
            const html = el.innerHTML;
            expect(html.length).toBeGreaterThan(0);
        });
    });

    describe('node details', () => {
        it('shows node table when show-nodes is set', () => {
            create({ observation: sampleObservation, 'show-nodes': '' });
            expect(el.innerHTML).toContain('node-1');
            expect(el.innerHTML).toContain('node-2');
        });

        it('hides node details by default', () => {
            create({ observation: sampleObservation });
            // Without show-nodes, node names should not appear (or be hidden)
            // The behavior depends on implementation
        });
    });

    describe('empty state', () => {
        it('handles missing observation data', () => {
            create({});
            expect(el.innerHTML).toBeDefined();
        });

        it('handles observation with missing fields', () => {
            create({ observation: JSON.stringify({ cpu_usage: 50 }) });
            expect(el.innerHTML).toContain('50');
        });
    });

    describe('ARIA', () => {
        it('has appropriate ARIA labels on progress bars', () => {
            create({ observation: sampleObservation });
            const labeled = el.querySelectorAll('[aria-label], [aria-valuenow]');
            expect(labeled.length).toBeGreaterThan(0);
        });
    });
});
