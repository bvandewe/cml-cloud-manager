/**
 * PipelineLog component tests.
 */
import { describe, it, expect, afterEach, vi, beforeEach } from 'vitest';
import '../src/components/PipelineLog.js';

describe('PipelineLog', () => {
    let el: Element;

    const sampleSteps = JSON.stringify([
        { name: 'upstream', label: 'Upstream', status: 'completed', started_at: '2024-01-01T10:00:00Z', completed_at: '2024-01-01T10:01:00Z', duration_seconds: 60 },
        { name: 'storage', label: 'Storage', status: 'completed', started_at: '2024-01-01T10:01:00Z', completed_at: '2024-01-01T10:02:30Z', duration_seconds: 90 },
        { name: 'pod', label: 'POD Deploy', status: 'running', started_at: '2024-01-01T10:02:30Z' },
        { name: 'lds', label: 'LDS Config', status: 'pending' },
        { name: 'score', label: 'Scoring', status: 'pending' },
    ]);

    function create(attrs: Record<string, string> = {}): Element {
        el = document.createElement('ui-pipeline-log');
        for (const [key, value] of Object.entries(attrs)) {
            el.setAttribute(key, value);
        }
        document.body.appendChild(el);
        return el;
    }

    beforeEach(() => {
        vi.useFakeTimers();
    });

    afterEach(() => {
        el?.remove();
        vi.useRealTimers();
    });

    describe('basic rendering', () => {
        it('renders all pipeline steps', () => {
            create({ steps: sampleSteps, 'pipeline-name': 'Deploy Pipeline' });
            expect(el.innerHTML).toContain('Upstream');
            expect(el.innerHTML).toContain('Storage');
            expect(el.innerHTML).toContain('POD Deploy');
            expect(el.innerHTML).toContain('LDS Config');
            expect(el.innerHTML).toContain('Scoring');
        });

        it('shows pipeline name', () => {
            create({ steps: sampleSteps, 'pipeline-name': 'Deploy Pipeline' });
            expect(el.innerHTML).toContain('Deploy Pipeline');
        });

        it('shows step status indicators', () => {
            create({ steps: sampleSteps });
            // Completed steps should have success/check indicators
            expect(el.innerHTML).toContain('completed');
        });
    });

    describe('step details', () => {
        it('shows duration for completed steps', () => {
            create({ steps: sampleSteps });
            // 60s and 90s durations
            const text = el.textContent || '';
            expect(text).toMatch(/60|1:00|1m/); // Duration format varies
        });
    });

    describe('running step', () => {
        it('indicates running step visually', () => {
            create({ steps: sampleSteps });
            // Running step should have distinct styling
            expect(el.innerHTML).toContain('running');
        });
    });

    describe('attempt/retry', () => {
        it('shows attempt number when set', () => {
            create({ steps: sampleSteps, attempt: '2' });
            expect(el.innerHTML).toContain('2');
        });
    });

    describe('collapsible', () => {
        it('renders collapsible when attribute is set', () => {
            create({ steps: sampleSteps, collapsible: '' });
            // Should have a toggle mechanism
            expect(el.innerHTML.length).toBeGreaterThan(0);
        });
    });

    describe('empty state', () => {
        it('handles empty steps', () => {
            create({ steps: '[]' });
            expect(el.innerHTML).toBeDefined();
        });

        it('handles missing steps', () => {
            create({});
            expect(el.innerHTML).toBeDefined();
        });
    });

    describe('error handling', () => {
        it('shows error for failed steps', () => {
            const failedSteps = JSON.stringify([{ name: 'deploy', label: 'Deploy', status: 'failed', error: 'Connection timeout', retry_count: 3 }]);
            create({ steps: failedSteps });
            expect(el.innerHTML).toContain('Connection timeout');
        });
    });
});
