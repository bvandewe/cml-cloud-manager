/**
 * SessionDetailsModal Component Tests — ADR-034 Sprint E (Track C)
 *
 * Tests for the pipeline sub-tab system, dynamic step labels, desired_status
 * badge, and pipeline progress data normalization.
 *
 * Uses jsdom environment for DOM testing.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// ==============================================================================
// Mocks — must be declared before component import
// ==============================================================================

vi.mock('../../src/scripts/core/EventBus.js', () => ({
    EventTypes: {
        LABLET_SESSION_UPDATED: 'lablet.session.updated',
        LABLET_SESSION_STATUS_CHANGED: 'lablet.session.status.changed',
        LABLET_SESSION_PIPELINE_PROGRESS: 'lablet.session.pipeline.progress',
        LABLET_SESSION_DESIRED_STATUS_CHANGED: 'lablet.session.desired_status.changed',
    },
    LcmEventTypes: {},
    eventBus: {
        on: vi.fn(() => vi.fn()),
        off: vi.fn(),
        emit: vi.fn(),
        once: vi.fn(() => vi.fn()),
    },
    default: {
        on: vi.fn(() => vi.fn()),
        off: vi.fn(),
        emit: vi.fn(),
        once: vi.fn(() => vi.fn()),
    },
}));

vi.mock('../../src/scripts/app/eventBus.js', () => ({
    EventTypes: {
        LABLET_SESSION_UPDATED: 'lablet.session.updated',
        LABLET_SESSION_STATUS_CHANGED: 'lablet.session.status.changed',
        LABLET_SESSION_PIPELINE_PROGRESS: 'lablet.session.pipeline.progress',
        LABLET_SESSION_DESIRED_STATUS_CHANGED: 'lablet.session.desired_status.changed',
    },
    LcmEventTypes: {},
    eventBus: {
        on: vi.fn(() => vi.fn()),
        off: vi.fn(),
        emit: vi.fn(),
        once: vi.fn(() => vi.fn()),
    },
    default: {
        on: vi.fn(() => vi.fn()),
        off: vi.fn(),
        emit: vi.fn(),
        once: vi.fn(() => vi.fn()),
    },
}));

vi.mock('bootstrap', () => {
    class MockModal {
        constructor() {}
        show() {}
        hide() {}
        dispose() {}
    }
    MockModal.getInstance = vi.fn(() => null);
    return { Modal: MockModal };
});

vi.mock('../../src/scripts/api/lablet-sessions.js', () => ({
    getSession: vi.fn(),
    deleteSession: vi.fn(),
    listSessions: vi.fn(),
}));

vi.mock('../../src/scripts/api/lablet-definitions.js', () => ({
    getDefinition: vi.fn(),
    listDefinitions: vi.fn(),
}));

vi.mock('../../src/scripts/ui/notifications.js', () => ({
    showToast: vi.fn(),
}));

vi.mock('../../src/scripts/components/modals.js', () => ({
    showConfirmAsync: vi.fn(),
}));

vi.mock('../../src/scripts/api/scheduler.js', () => ({
    previewPlacement: vi.fn(),
}));

vi.mock('../../src/scripts/components/PlacementPreviewModal.js', () => ({
    showPlacementPreviewModal: vi.fn(),
}));

vi.mock('../../src/scripts/utils/dates.js', () => ({
    getRelativeTime: vi.fn(d => d || '—'),
    parseUTCDate: vi.fn(d => (d ? new Date(d) : null)),
    formatDuration: vi.fn(() => '—'),
}));

vi.mock('../../src/scripts/components/shared/definition-details-renderer.js', () => ({
    renderDefinitionDetailsHtml: vi.fn(() => ''),
    mountDefinitionContentViewer: vi.fn(),
}));

import { SessionDetailsModal } from '../../src/scripts/components/modals/SessionDetailsModal.js';

// ==============================================================================
// Test Data Factories
// ==============================================================================

function makeGenericProgress(pipelineName = 'teardown', overrides = {}) {
    const defaults = {
        stop_lab: { status: 'completed', order: 1, error: null, result_data: { lab_id: 'lab-123' } },
        deregister_lds: { status: 'in_progress', order: 2, error: null, result_data: null },
        wipe_lab: { status: 'pending', order: 3, error: null, result_data: null },
    };
    return { [pipelineName]: { ...defaults, ...overrides } };
}

function makeSession(overrides = {}) {
    return {
        id: 'session-001',
        status: 'instantiating',
        desired_status: null,
        pipeline_progress: null,
        ...overrides,
    };
}

// ==============================================================================
// Helpers
// ==============================================================================

function createElement() {
    const el = document.createElement('session-details-modal');
    document.body.appendChild(el);
    return el;
}

function teardown(el) {
    el?.remove();
}

// ==============================================================================
// Tests
// ==============================================================================

describe('SessionDetailsModal', () => {
    let element;

    afterEach(() => {
        teardown(element);
        element = null;
    });

    // ==========================================================================
    // Registration
    // ==========================================================================

    describe('custom element registration', () => {
        it('should register as custom element', () => {
            expect(customElements.get('session-details-modal')).toBeDefined();
        });

        it('should have _activePipelineSubTab initialized to null', () => {
            element = createElement();
            expect(element._activePipelineSubTab).toBeNull();
        });
    });

    // ==========================================================================
    // _prettifyName()
    // ==========================================================================

    describe('_prettifyName()', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should convert snake_case to Title Case', () => {
            expect(element._prettifyName('content_sync')).toBe('Content Sync');
        });

        it('should handle single word', () => {
            expect(element._prettifyName('teardown')).toBe('Teardown');
        });

        it('should handle multi-segment names', () => {
            expect(element._prettifyName('compute_grading_score')).toBe('Compute Grading Score');
        });

        it('should return dash for null', () => {
            expect(element._prettifyName(null)).toBe('—');
        });

        it('should return dash for empty string', () => {
            expect(element._prettifyName('')).toBe('—');
        });

        it('should handle names without underscores', () => {
            expect(element._prettifyName('instantiate')).toBe('Instantiate');
        });
    });

    // ==========================================================================
    // _collectPipelineData()
    // ==========================================================================

    describe('_collectPipelineData()', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should return empty object when no pipeline data exists', () => {
            const session = makeSession();
            const result = element._collectPipelineData(session);
            expect(result).toEqual({});
        });

        it('should collect generic pipeline_progress', () => {
            const session = makeSession({
                pipeline_progress: makeGenericProgress('teardown'),
            });
            const result = element._collectPipelineData(session);
            expect(result).toHaveProperty('teardown');
            expect(result.teardown.format).toBe('generic');
            expect(Object.keys(result.teardown.data)).toHaveLength(3);
        });

        it('should collect instantiate pipeline from pipeline_progress', () => {
            const genericInstantiate = {
                instantiate: {
                    content_sync: { status: 'completed', order: 1 },
                    lab_import: { status: 'in_progress', order: 2 },
                },
            };
            const session = makeSession({
                pipeline_progress: genericInstantiate,
            });
            const result = element._collectPipelineData(session);
            expect(result.instantiate.format).toBe('generic');
            expect(Object.keys(result.instantiate.data)).toHaveLength(2);
        });

        it('should collect multiple generic pipelines', () => {
            const session = makeSession({
                pipeline_progress: {
                    ...makeGenericProgress('teardown'),
                    collect_evidence: {
                        capture_configs: { status: 'completed', order: 1 },
                        capture_screenshots: { status: 'pending', order: 2 },
                    },
                },
            });
            const result = element._collectPipelineData(session);
            expect(Object.keys(result)).toHaveLength(2);
            expect(result).toHaveProperty('teardown');
            expect(result).toHaveProperty('collect_evidence');
        });

        it('should skip generic pipeline with empty step dict', () => {
            const session = makeSession({
                pipeline_progress: { teardown: {} },
            });
            const result = element._collectPipelineData(session);
            expect(result).toEqual({});
        });
    });

    // ==========================================================================
    // _orderPipelineNames()
    // ==========================================================================

    describe('_orderPipelineNames()', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should order known pipelines by lifecycle', () => {
            const result = element._orderPipelineNames(['compute_grading', 'instantiate', 'teardown']);
            expect(result).toEqual(['instantiate', 'teardown', 'compute_grading']);
        });

        it('should append unknown names alphabetically after known', () => {
            const result = element._orderPipelineNames(['custom_pipeline', 'instantiate', 'another_one']);
            expect(result).toEqual(['instantiate', 'another_one', 'custom_pipeline']);
        });

        it('should handle only unknown names', () => {
            const result = element._orderPipelineNames(['zebra', 'alpha']);
            expect(result).toEqual(['alpha', 'zebra']);
        });

        it('should handle empty array', () => {
            const result = element._orderPipelineNames([]);
            expect(result).toEqual([]);
        });

        it('should handle all four canonical pipelines', () => {
            const result = element._orderPipelineNames(['compute_grading', 'collect_evidence', 'teardown', 'instantiate']);
            expect(result).toEqual(['instantiate', 'teardown', 'collect_evidence', 'compute_grading']);
        });
    });

    // ==========================================================================
    // _getPipelineSteps()
    // ==========================================================================

    describe('_getPipelineSteps()', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should normalize generic format steps sorted by order', () => {
            const pipeline = {
                format: 'generic',
                data: {
                    wipe_lab: { status: 'pending', order: 3 },
                    stop_lab: { status: 'completed', order: 1 },
                    deregister_lds: { status: 'in_progress', order: 2 },
                },
            };
            const steps = element._getPipelineSteps(pipeline);
            expect(steps).toHaveLength(3);
            // Sorted by order
            expect(steps[0].name).toBe('stop_lab');
            expect(steps[1].name).toBe('deregister_lds');
            expect(steps[2].name).toBe('wipe_lab');
        });

        it('should default missing fields in generic format', () => {
            const pipeline = {
                format: 'generic',
                data: {
                    some_step: { status: 'completed', order: 1 },
                },
            };
            const steps = element._getPipelineSteps(pipeline);
            expect(steps[0].error).toBeNull();
            expect(steps[0].result_data).toBeNull();
            expect(steps[0].completed_at).toBeNull();
            expect(steps[0].attempt_count).toBe(0);
            expect(steps[0].requires).toEqual([]);
        });

        it('should handle generic step with skip_reason as error', () => {
            const pipeline = {
                format: 'generic',
                data: {
                    optional_step: { status: 'skipped', order: 1, skip_reason: 'Not applicable' },
                },
            };
            const steps = element._getPipelineSteps(pipeline);
            expect(steps[0].error).toBe('Not applicable');
        });
    });

    // ==========================================================================
    // _pipelineStatusDot()
    // ==========================================================================

    describe('_pipelineStatusDot()', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should return success badge when all steps completed', () => {
            const pipeline = {
                format: 'generic',
                data: {
                    step_a: { status: 'completed', order: 1 },
                    step_b: { status: 'completed', order: 2 },
                },
            };
            const dot = element._pipelineStatusDot(pipeline);
            expect(dot).toContain('bg-success');
            expect(dot).toContain('✓');
        });

        it('should return success for mix of completed and skipped', () => {
            const pipeline = {
                format: 'generic',
                data: {
                    step_a: { status: 'completed', order: 1 },
                    step_b: { status: 'skipped', order: 2 },
                },
            };
            const dot = element._pipelineStatusDot(pipeline);
            expect(dot).toContain('bg-success');
        });

        it('should return danger badge when any step failed', () => {
            const pipeline = {
                format: 'generic',
                data: {
                    step_a: { status: 'completed', order: 1 },
                    step_b: { status: 'failed', order: 2 },
                },
            };
            const dot = element._pipelineStatusDot(pipeline);
            expect(dot).toContain('bg-danger');
            expect(dot).toContain('!');
        });

        it('should return spinner when step is in_progress', () => {
            const pipeline = {
                format: 'generic',
                data: {
                    step_a: { status: 'completed', order: 1 },
                    step_b: { status: 'in_progress', order: 2 },
                },
            };
            const dot = element._pipelineStatusDot(pipeline);
            expect(dot).toContain('spinner-border');
        });

        it('should return empty string when all steps are pending', () => {
            const pipeline = {
                format: 'generic',
                data: {
                    step_a: { status: 'pending', order: 1 },
                    step_b: { status: 'pending', order: 2 },
                },
            };
            const dot = element._pipelineStatusDot(pipeline);
            expect(dot).toBe('');
        });

        it('should return empty string when no steps exist', () => {
            const pipeline = { format: 'generic', data: {} };
            const dot = element._pipelineStatusDot(pipeline);
            expect(dot).toBe('');
        });

        it('should prioritize failed over in_progress', () => {
            const pipeline = {
                format: 'generic',
                data: {
                    step_a: { status: 'in_progress', order: 1 },
                    step_b: { status: 'failed', order: 2 },
                },
            };
            const dot = element._pipelineStatusDot(pipeline);
            expect(dot).toContain('bg-danger');
        });
    });

    // ==========================================================================
    // _renderDesiredStatusBadge()
    // ==========================================================================

    describe('_renderDesiredStatusBadge()', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should return empty string when no desired_status', () => {
            const result = element._renderDesiredStatusBadge({ status: 'running', desired_status: null });
            expect(result).toBe('');
        });

        it('should return empty string when desired equals current', () => {
            const result = element._renderDesiredStatusBadge({ status: 'running', desired_status: 'running' });
            expect(result).toBe('');
        });

        it('should return empty string when desired equals current (case-insensitive)', () => {
            const result = element._renderDesiredStatusBadge({ status: 'Running', desired_status: 'RUNNING' });
            expect(result).toBe('');
        });

        it('should show badge when desired differs from current', () => {
            const result = element._renderDesiredStatusBadge({ status: 'running', desired_status: 'stopped' });
            expect(result).toContain('bg-warning-subtle');
            expect(result).toContain('→ stopped');
        });

        it('should show terminated icon for terminated desired', () => {
            const result = element._renderDesiredStatusBadge({ status: 'running', desired_status: 'terminated' });
            expect(result).toContain('bi-x-circle');
            expect(result).toContain('→ terminated');
        });

        it('should show stop icon for stopped desired', () => {
            const result = element._renderDesiredStatusBadge({ status: 'running', desired_status: 'stopped' });
            expect(result).toContain('bi-stop-circle');
        });

        it('should show generic arrow icon for other desired states', () => {
            const result = element._renderDesiredStatusBadge({ status: 'stopped', desired_status: 'running' });
            expect(result).toContain('bi-arrow-right-circle');
        });
    });

    // ==========================================================================
    // _inferActivePipeline()
    // ==========================================================================

    describe('_inferActivePipeline()', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should select pipeline with in-progress step', () => {
            const pipelines = {
                instantiate: {
                    format: 'generic',
                    data: {
                        step_a: { status: 'completed', order: 1 },
                    },
                },
                teardown: {
                    format: 'generic',
                    data: {
                        step_b: { status: 'in_progress', order: 1 },
                    },
                },
            };
            const result = element._inferActivePipeline(['instantiate', 'teardown'], pipelines);
            expect(result).toBe('teardown');
        });

        it('should fall back to last pipeline with activity', () => {
            const pipelines = {
                instantiate: {
                    format: 'generic',
                    data: {
                        step_a: { status: 'completed', order: 1 },
                    },
                },
                teardown: {
                    format: 'generic',
                    data: {
                        step_b: { status: 'completed', order: 1 },
                    },
                },
            };
            const result = element._inferActivePipeline(['instantiate', 'teardown'], pipelines);
            expect(result).toBe('teardown');
        });

        it('should return null when all steps are pending', () => {
            const pipelines = {
                instantiate: {
                    format: 'generic',
                    data: {
                        step_a: { status: 'pending', order: 1 },
                    },
                },
            };
            const result = element._inferActivePipeline(['instantiate'], pipelines);
            expect(result).toBeNull();
        });
    });

    // ==========================================================================
    // _renderStepResultData()
    // ==========================================================================

    describe('_renderStepResultData()', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should render key-value pairs', () => {
            const html = element._renderStepResultData({ lab_id: 'lab-123', node_count: 5 });
            expect(html).toContain('lab_id');
            expect(html).toContain('lab-123');
            expect(html).toContain('node_count');
            expect(html).toContain('5');
        });

        it('should return empty string for empty data', () => {
            const html = element._renderStepResultData({});
            expect(html).toBe('');
        });

        it('should truncate long object values', () => {
            const longObj = { key: 'x'.repeat(100) };
            const html = element._renderStepResultData({ data: longObj });
            expect(html).toContain('…');
        });

        it('should show +N more for >5 entries', () => {
            const data = {};
            for (let i = 0; i < 8; i++) {
                data[`key_${i}`] = `val_${i}`;
            }
            const html = element._renderStepResultData(data);
            expect(html).toContain('+3 more');
        });
    });

    // ==========================================================================
    // _renderPipelineStepRow()
    // ==========================================================================

    describe('_renderPipelineStepRow()', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should render completed step with success icon', () => {
            const step = { name: 'content_sync', status: 'completed', error: null, result_data: null, completed_at: '2025-01-15T10:01:00Z', attempt_count: 1, requires: [], order: 1 };
            const html = element._renderPipelineStepRow(step);
            expect(html).toContain('bi-check-circle-fill');
            expect(html).toContain('text-success');
            expect(html).toContain('Content Sync');
            expect(html).toContain('completed');
        });

        it('should render failed step with error detail', () => {
            const step = { name: 'lab_start', status: 'failed', error: 'Connection timeout', result_data: null, completed_at: null, attempt_count: 1, requires: [], order: 2 };
            const html = element._renderPipelineStepRow(step);
            expect(html).toContain('bi-x-circle-fill');
            expect(html).toContain('text-danger');
            expect(html).toContain('Connection timeout');
            expect(html).toContain('failed');
        });

        it('should render in_progress step with spinner', () => {
            const step = { name: 'wait_converge', status: 'in_progress', error: null, result_data: null, completed_at: null, attempt_count: 1, requires: [], order: 3 };
            const html = element._renderPipelineStepRow(step);
            expect(html).toContain('spinner-border');
            expect(html).toContain('running');
        });

        it('should render skipped step', () => {
            const step = { name: 'optional_step', status: 'skipped', error: null, result_data: null, completed_at: null, attempt_count: 0, requires: [], order: 4 };
            const html = element._renderPipelineStepRow(step);
            expect(html).toContain('bi-skip-forward-fill');
            expect(html).toContain('skipped');
        });

        it('should render pending step with faded icon', () => {
            const step = { name: 'mark_ready', status: 'pending', error: null, result_data: null, completed_at: null, attempt_count: 0, requires: [], order: 5 };
            const html = element._renderPipelineStepRow(step);
            expect(html).toContain('bi-circle');
            expect(html).toContain('pending');
        });

        it('should render retry badge for attempt_count > 1', () => {
            const step = { name: 'flaky_step', status: 'completed', error: null, result_data: null, completed_at: null, attempt_count: 3, requires: [], order: 1 };
            const html = element._renderPipelineStepRow(step);
            expect(html).toContain('retry 3');
            expect(html).toContain('bg-warning-subtle');
        });

        it('should show prerequisites when present', () => {
            const step = { name: 'lab_start', status: 'pending', error: null, result_data: null, completed_at: null, attempt_count: 0, requires: ['content_sync', 'lab_import'], order: 3 };
            const html = element._renderPipelineStepRow(step);
            expect(html).toContain('requires:');
            expect(html).toContain('Content Sync');
            expect(html).toContain('Lab Import');
        });

        it('should render result data when present', () => {
            const step = { name: 'lab_import', status: 'completed', error: null, result_data: { lab_id: 'lab-42' }, completed_at: null, attempt_count: 1, requires: [], order: 1 };
            const html = element._renderPipelineStepRow(step);
            expect(html).toContain('lab_id');
            expect(html).toContain('lab-42');
        });
    });

    // ==========================================================================
    // _renderPipelineTab() — full integration rendering
    // ==========================================================================

    describe('_renderPipelineTab()', () => {
        beforeEach(() => {
            element = createElement();
            // Inject the modal shell so _renderPipelineTab() can find the container
            element.innerHTML = `<div id="session-tab-pipeline"></div>`;
        });

        it('should render empty state for session with no pipeline data', () => {
            element.currentSession = makeSession({ status: 'pending' });
            element._renderPipelineTab();
            const container = element.querySelector('#session-tab-pipeline');
            expect(container.textContent).toContain('Pipeline will start');
        });

        it('should render empty state for post-instantiation session with no data', () => {
            element.currentSession = makeSession({ status: 'running' });
            element._renderPipelineTab();
            const container = element.querySelector('#session-tab-pipeline');
            expect(container.textContent).toContain('Pipeline completed');
        });

        it('should render sub-tabs for single pipeline', () => {
            element.currentSession = makeSession({
                pipeline_progress: makeGenericProgress('instantiate'),
            });
            element._renderPipelineTab();

            const subTabs = element.querySelectorAll('[data-pipeline-tab]');
            expect(subTabs.length).toBe(1);
            expect(subTabs[0].dataset.pipelineTab).toBe('instantiate');
            expect(subTabs[0].textContent).toContain('Instantiate');
        });

        it('should render sub-tabs for multiple generic pipelines in lifecycle order', () => {
            element.currentSession = makeSession({
                pipeline_progress: {
                    compute_grading: {
                        load_rubric: { status: 'pending', order: 1 },
                    },
                    instantiate: {
                        content_sync: { status: 'completed', order: 1 },
                    },
                    teardown: {
                        stop_lab: { status: 'completed', order: 1 },
                    },
                },
            });
            element._renderPipelineTab();

            const subTabs = element.querySelectorAll('[data-pipeline-tab]');
            expect(subTabs.length).toBe(3);
            // Lifecycle order: instantiate → teardown → compute_grading
            expect(subTabs[0].dataset.pipelineTab).toBe('instantiate');
            expect(subTabs[1].dataset.pipelineTab).toBe('teardown');
            expect(subTabs[2].dataset.pipelineTab).toBe('compute_grading');
        });

        it('should render display names from PIPELINE_DISPLAY_NAMES', () => {
            element.currentSession = makeSession({
                pipeline_progress: {
                    teardown: { stop_lab: { status: 'completed', order: 1 } },
                    collect_evidence: { capture_configs: { status: 'pending', order: 1 } },
                },
            });
            element._renderPipelineTab();

            const html = element.querySelector('#pipeline-sub-tabs').innerHTML;
            expect(html).toContain('Release');
            expect(html).toContain('Collect Evidences');
        });

        it('should use _prettifyName() for unknown pipeline names', () => {
            element.currentSession = makeSession({
                pipeline_progress: {
                    custom_validation_check: {
                        step_one: { status: 'completed', order: 1 },
                    },
                },
            });
            element._renderPipelineTab();

            const html = element.querySelector('#pipeline-sub-tabs').innerHTML;
            expect(html).toContain('Custom Validation Check');
        });

        it('should render progress bar and step list', () => {
            element.currentSession = makeSession({
                pipeline_progress: makeGenericProgress('teardown'),
            });
            element._renderPipelineTab();

            const content = element.querySelector('#pipeline-sub-content');
            expect(content.innerHTML).toContain('progress-bar');
            expect(content.innerHTML).toContain('Stop Lab');
            expect(content.innerHTML).toContain('Deregister Lds');
            expect(content.innerHTML).toContain('Wipe Lab');
        });

        it('should render status dot on sub-tab button', () => {
            element.currentSession = makeSession({
                pipeline_progress: {
                    teardown: {
                        stop_lab: { status: 'completed', order: 1 },
                        wipe_lab: { status: 'completed', order: 2 },
                    },
                },
            });
            element._renderPipelineTab();

            const tabBtn = element.querySelector('[data-pipeline-tab="teardown"]');
            expect(tabBtn.innerHTML).toContain('bg-success');
            expect(tabBtn.innerHTML).toContain('✓');
        });

        it('should render multiple generic pipelines together', () => {
            element.currentSession = makeSession({
                pipeline_progress: {
                    ...makeGenericProgress('instantiate'),
                    ...makeGenericProgress('teardown'),
                },
            });
            element._renderPipelineTab();

            const subTabs = element.querySelectorAll('[data-pipeline-tab]');
            const names = Array.from(subTabs).map(t => t.dataset.pipelineTab);
            expect(names).toContain('instantiate');
            expect(names).toContain('teardown');
            // Should be in lifecycle order
            expect(names.indexOf('instantiate')).toBeLessThan(names.indexOf('teardown'));
        });

        it('should auto-select pipeline with in-progress step', () => {
            element.currentSession = makeSession({
                pipeline_progress: {
                    instantiate: {
                        content_sync: { status: 'completed', order: 1 },
                    },
                    teardown: {
                        stop_lab: { status: 'in_progress', order: 1 },
                    },
                },
            });
            element._renderPipelineTab();

            const activeTab = element.querySelector('[data-pipeline-tab].active');
            expect(activeTab.dataset.pipelineTab).toBe('teardown');
        });

        it('should render correct progress percentage', () => {
            element.currentSession = makeSession({
                pipeline_progress: {
                    teardown: {
                        step_a: { status: 'completed', order: 1 },
                        step_b: { status: 'completed', order: 2 },
                        step_c: { status: 'pending', order: 3 },
                        step_d: { status: 'pending', order: 4 },
                    },
                },
            });
            element._renderPipelineTab();

            const content = element.querySelector('#pipeline-sub-content');
            // 2 of 4 steps completed = 50%
            expect(content.textContent).toContain('50%');
        });

        it('should switch sub-tabs on click', () => {
            element.currentSession = makeSession({
                pipeline_progress: {
                    instantiate: { content_sync: { status: 'completed', order: 1 } },
                    teardown: { stop_lab: { status: 'pending', order: 1 } },
                },
            });
            element._renderPipelineTab();

            // Initially instantiate should be active (has activity)
            let activeTab = element.querySelector('[data-pipeline-tab].active');
            expect(activeTab.dataset.pipelineTab).toBe('instantiate');

            // Click teardown tab
            const teardownTab = element.querySelector('[data-pipeline-tab="teardown"]');
            teardownTab.click();

            // After click, _activePipelineSubTab should be set
            expect(element._activePipelineSubTab).toBe('teardown');
        });

        it('should respect sticky _activePipelineSubTab', () => {
            element._activePipelineSubTab = 'teardown';
            element.currentSession = makeSession({
                pipeline_progress: {
                    instantiate: { content_sync: { status: 'in_progress', order: 1 } },
                    teardown: { stop_lab: { status: 'pending', order: 1 } },
                },
            });
            element._renderPipelineTab();

            const activeTab = element.querySelector('[data-pipeline-tab].active');
            expect(activeTab.dataset.pipelineTab).toBe('teardown');
        });
    });

    // ==========================================================================
    // Static config
    // ==========================================================================

    describe('static config', () => {
        it('should have 4 canonical pipeline display names', () => {
            expect(Object.keys(SessionDetailsModal.PIPELINE_DISPLAY_NAMES)).toHaveLength(4);
            expect(SessionDetailsModal.PIPELINE_DISPLAY_NAMES.instantiate).toBe('Instantiate');
            expect(SessionDetailsModal.PIPELINE_DISPLAY_NAMES.teardown).toBe('Release');
            expect(SessionDetailsModal.PIPELINE_DISPLAY_NAMES.collect_evidence).toBe('Collect Evidences');
            expect(SessionDetailsModal.PIPELINE_DISPLAY_NAMES.compute_grading).toBe('Compute Grading');
        });

        it('should have 4 pipeline order entries', () => {
            expect(SessionDetailsModal.PIPELINE_ORDER).toEqual(['instantiate', 'teardown', 'collect_evidence', 'compute_grading']);
        });

        it('should have icons for all canonical pipelines', () => {
            for (const name of SessionDetailsModal.PIPELINE_ORDER) {
                expect(SessionDetailsModal.PIPELINE_ICONS[name]).toBeDefined();
                expect(SessionDetailsModal.PIPELINE_ICONS[name]).toMatch(/^bi-/);
            }
        });
    });

    // ==========================================================================
    // _resetTabCache
    // ==========================================================================

    describe('_resetTabCache()', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should reset _activePipelineSubTab', () => {
            element._activePipelineSubTab = 'teardown';
            element._resetTabCache();
            expect(element._activePipelineSubTab).toBeNull();
        });

        it('should reset all tab cache entries', () => {
            element._tabCache = { overview: true, pipeline: true, reports: true, resources: true };
            element._resetTabCache();
            expect(element._tabCache.overview).toBeNull();
            expect(element._tabCache.pipeline).toBeNull();
            expect(element._tabCache.reports).toBeNull();
            expect(element._tabCache.resources).toBeNull();
        });
    });
});
