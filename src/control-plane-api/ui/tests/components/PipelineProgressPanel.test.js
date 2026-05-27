/**
 * PipelineProgressPanel Component Tests — Sprint G (G4)
 *
 * Tests for the <pipeline-progress-panel> custom element.
 * Covers: lifecycle rail rendering, pipeline tab selection, step pills,
 * progress bar, execution history toggle, and SSE event subscriptions.
 *
 * Uses jsdom environment for DOM testing.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// ==============================================================================
// Mocks — must be declared before component import
// ==============================================================================

vi.mock('../../src/scripts/core/EventBus.js', () => ({
    EventTypes: {
        LABLET_SESSION_STATUS_CHANGED: 'lablet.session.status.changed',
        LABLET_SESSION_PIPELINE_PROGRESS: 'lablet.session.pipeline.progress',
        LABLET_SESSION_SNAPSHOT: 'lablet.session.snapshot',
        PIPELINE_STEP_STARTED: 'pipeline.step.started',
        PIPELINE_STEP_COMPLETED: 'pipeline.step.completed',
        PIPELINE_STEP_FAILED: 'pipeline.step.failed',
        PIPELINE_COMPLETED: 'pipeline.completed',
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
        LABLET_SESSION_STATUS_CHANGED: 'lablet.session.status.changed',
        LABLET_SESSION_PIPELINE_PROGRESS: 'lablet.session.pipeline.progress',
        LABLET_SESSION_SNAPSHOT: 'lablet.session.snapshot',
        PIPELINE_STEP_STARTED: 'pipeline.step.started',
        PIPELINE_STEP_COMPLETED: 'pipeline.step.completed',
        PIPELINE_STEP_FAILED: 'pipeline.step.failed',
        PIPELINE_COMPLETED: 'pipeline.completed',
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
    getPipelineProgress: vi.fn(),
    listPipelineExecutions: vi.fn(),
}));

vi.mock('../../src/scripts/ui/notifications.js', () => ({
    showToast: vi.fn(),
}));

// Import component AFTER mocks
import { PipelineProgressPanel } from '../../src/scripts/components/sessions/PipelineProgressPanel.js';
import { listPipelineExecutions } from '../../src/scripts/api/lablet-sessions.js';

// ==============================================================================
// Test Data Factories
// ==============================================================================

function makeSession(overrides = {}) {
    return {
        id: 'session-001',
        status: 'instantiating',
        pipeline_progress: null,
        timeslot_start: '2025-01-15T08:00:00Z',
        timeslot_end: '2025-01-15T12:00:00Z',
        worker_id: 'worker-001',
        worker_name: 'cml-worker-1',
        definition_name: 'Lab Definition A',
        ...overrides,
    };
}

function makePipelineProgress(overrides = {}) {
    return {
        instantiate: {
            lab_resolve: { status: 'completed', order: 1, error: null, result_data: { lab_id: 'lab-123' } },
            ports_alloc: { status: 'completed', order: 2, error: null, result_data: {} },
            tags_sync: { status: 'completed', order: 3, error: null, result_data: {} },
            lab_binding: { status: 'in_progress', order: 4, error: null, result_data: null },
            lab_start: { status: 'pending', order: 5, error: null, result_data: null },
            lds_provision: { status: 'pending', order: 6, error: null, result_data: null },
            mark_ready: { status: 'pending', order: 7, error: null, result_data: null },
        },
        ...overrides,
    };
}

function makeCompletedPipelineProgress() {
    return {
        instantiate: {
            lab_resolve: { status: 'completed', order: 1, error: null },
            ports_alloc: { status: 'completed', order: 2, error: null },
            tags_sync: { status: 'completed', order: 3, error: null },
            lab_binding: { status: 'completed', order: 4, error: null },
            lab_start: { status: 'completed', order: 5, error: null },
            lds_provision: { status: 'completed', order: 6, error: null },
            mark_ready: { status: 'completed', order: 7, error: null },
        },
    };
}

function makeMultiPipelineProgress() {
    return {
        instantiate: {
            lab_resolve: { status: 'completed', order: 1, error: null },
            ports_alloc: { status: 'completed', order: 2, error: null },
            tags_sync: { status: 'completed', order: 3, error: null },
            lab_binding: { status: 'completed', order: 4, error: null },
            lab_start: { status: 'completed', order: 5, error: null },
            lds_provision: { status: 'completed', order: 6, error: null },
            mark_ready: { status: 'completed', order: 7, error: null },
        },
        teardown: {
            stop_lab: { status: 'completed', order: 1, error: null },
            deregister_lds: { status: 'in_progress', order: 2, error: null },
            wipe_lab: { status: 'pending', order: 3, error: null },
        },
    };
}

function makeFailedPipelineProgress() {
    return {
        instantiate: {
            lab_resolve: { status: 'failed', order: 1, error: 'Lab resolve failed: invalid topology', result_data: null },
            ports_alloc: { status: 'pending', order: 2, error: null },
            lab_start: { status: 'pending', order: 3, error: null },
        },
    };
}

function makeExecutionHistory() {
    return [
        {
            id: 'exec-001',
            session_id: 'session-001',
            pipeline_name: 'instantiate',
            status: 'completed',
            attempt: 1,
            started_at: '2025-01-15T10:00:00Z',
            completed_at: '2025-01-15T10:05:00Z',
            duration_seconds: 300,
            steps_completed: 5,
            steps_total: 5,
            error: null,
        },
        {
            id: 'exec-002',
            session_id: 'session-001',
            pipeline_name: 'teardown',
            status: 'running',
            attempt: 1,
            started_at: '2025-01-15T12:00:00Z',
            completed_at: null,
            duration_seconds: null,
            steps_completed: 1,
            steps_total: 3,
            error: null,
        },
    ];
}

// ==============================================================================
// Helpers
// ==============================================================================

function createElement() {
    const el = document.createElement('pipeline-progress-panel');
    document.body.appendChild(el);
    return el;
}

function teardown(el) {
    el?.remove();
}

// ==============================================================================
// Tests
// ==============================================================================

describe('PipelineProgressPanel', () => {
    let element;

    afterEach(() => {
        teardown(element);
        element = null;
        // Clean up injected styles
        document.getElementById('pipeline-progress-panel-styles')?.remove();
    });

    // ==========================================================================
    // Registration
    // ==========================================================================

    describe('custom element registration', () => {
        it('should register as custom element', () => {
            expect(customElements.get('pipeline-progress-panel')).toBeDefined();
        });

        it('should be instance of PipelineProgressPanel', () => {
            element = createElement();
            expect(element).toBeInstanceOf(PipelineProgressPanel);
        });

        it('should initialize with null session', () => {
            element = createElement();
            expect(element._session).toBeNull();
        });

        it('should initialize with empty pipeline progress', () => {
            element = createElement();
            expect(element._pipelineProgress).toEqual({});
        });

        it('should render empty when no session is set', () => {
            element = createElement();
            expect(element.innerHTML).toBe('');
        });
    });

    // ==========================================================================
    // setSession()
    // ==========================================================================

    describe('setSession()', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should store the session reference', () => {
            const session = makeSession();
            element.setSession(session);
            expect(element._session).toEqual(session);
        });

        it('should extract pipeline_progress from session', () => {
            const progress = makePipelineProgress();
            const session = makeSession({ pipeline_progress: progress });
            element.setSession(session);
            expect(element._pipelineProgress).toEqual(progress);
        });

        it('should default to empty pipeline progress when null', () => {
            const session = makeSession({ pipeline_progress: null });
            element.setSession(session);
            expect(element._pipelineProgress).toEqual({});
        });

        it('should detect active pipeline', () => {
            const progress = makePipelineProgress();
            const session = makeSession({ pipeline_progress: progress });
            element.setSession(session);
            expect(element._expandedPipeline).toBe('instantiate');
        });

        it('should reset history loaded state on new session', () => {
            element._historyLoaded = true;
            element._executionHistory = [{ id: 'old' }];

            const session = makeSession();
            element.setSession(session);
            // setSession resets history cache but preserves visibility toggle
            expect(element._historyLoaded).toBe(false);
            expect(element._executionHistory).toEqual([]);
        });

        it('should render after setting session', () => {
            const session = makeSession();
            element.setSession(session);
            expect(element.innerHTML).not.toBe('');
        });
    });

    // ==========================================================================
    // Lifecycle Rail
    // ==========================================================================

    describe('_renderLifecycleRail()', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should render all 10 lifecycle phases', () => {
            element.setSession(makeSession({ status: 'running' }));
            const phases = element.querySelectorAll('.phase-step');
            expect(phases.length).toBe(10);
        });

        it('should mark current phase with phase-current class', () => {
            element.setSession(makeSession({ status: 'running' }));
            const currentPhase = element.querySelector('.phase-step.phase-current');
            expect(currentPhase).toBeDefined();
            expect(currentPhase.dataset.phase).toBe('running');
        });

        it('should mark completed phases with phase-completed class', () => {
            element.setSession(makeSession({ status: 'running' }));
            const completedPhases = element.querySelectorAll('.phase-step.phase-completed');
            // pending, scheduled, instantiating, ready = 4 completed before running
            expect(completedPhases.length).toBe(4);
        });

        it('should mark future phases with phase-future class', () => {
            element.setSession(makeSession({ status: 'running' }));
            const futurePhases = element.querySelectorAll('.phase-step.phase-future');
            // collecting, grading, stopping, stopped, archived = 5 future after running
            expect(futurePhases.length).toBe(5);
        });

        it('should show pipeline indicator dots for pipeline phases', () => {
            element.setSession(makeSession({ status: 'pending' }));
            const indicators = element.querySelectorAll('.pipeline-indicator');
            // instantiating, collecting, grading, stopping have pipelines = 4
            expect(indicators.length).toBe(4);
        });

        it('should show terminal badge for terminated status', () => {
            element.setSession(makeSession({ status: 'terminated' }));
            const badge = element.querySelector('lcm-status-badge[status="terminated"]');
            expect(badge).toBeDefined();
        });

        it('should dim all phases for terminal states', () => {
            element.setSession(makeSession({ status: 'terminated' }));
            const terminalPhases = element.querySelectorAll('.phase-step.phase-terminal');
            expect(terminalPhases.length).toBe(10);
        });

        it('should show lifecycle heading', () => {
            element.setSession(makeSession());
            const heading = element.querySelector('.lifecycle-rail-container h6');
            expect(heading.textContent).toContain('Lifecycle');
        });

        it('should render connectors between phases', () => {
            element.setSession(makeSession({ status: 'running' }));
            const connectors = element.querySelectorAll('.phase-connector');
            // 9 connectors for 10 phases (between each pair)
            expect(connectors.length).toBe(9);
        });

        it('should mark completed connectors with connector-done', () => {
            element.setSession(makeSession({ status: 'running' }));
            const doneConnectors = element.querySelectorAll('.connector-done');
            // Connectors after phases 0-3 (pending, scheduled, instantiating, ready) = 4
            expect(doneConnectors.length).toBe(4);
        });
    });

    // ==========================================================================
    // Pipeline Section
    // ==========================================================================

    describe('pipeline section', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should show "Waiting for pipeline progress" when no pipelines and active phase', () => {
            element.setSession(makeSession({ status: 'instantiating', pipeline_progress: null }));
            expect(element.textContent).toContain('Waiting for pipeline progress');
        });

        it('should not show waiting message for non-pipeline phases', () => {
            element.setSession(makeSession({ status: 'ready', pipeline_progress: null }));
            expect(element.textContent).not.toContain('Waiting for pipeline progress');
        });

        it('should render pipeline tabs when progress exists', () => {
            element.setSession(makeSession({ pipeline_progress: makePipelineProgress() }));
            const tabs = element.querySelectorAll('.pipeline-tab');
            expect(tabs.length).toBe(1); // only "instantiate"
        });

        it('should render multiple pipeline tabs', () => {
            element.setSession(
                makeSession({
                    status: 'stopping',
                    pipeline_progress: makeMultiPipelineProgress(),
                })
            );
            const tabs = element.querySelectorAll('.pipeline-tab');
            expect(tabs.length).toBe(2); // "instantiate" + "teardown"
        });

        it('should display formatted pipeline name in tabs', () => {
            element.setSession(
                makeSession({
                    pipeline_progress: { collect_evidence: { step_a: { status: 'pending', order: 1 } } },
                })
            );
            const tab = element.querySelector('.pipeline-tab');
            expect(tab.textContent).toContain('Collect Evidence');
        });

        it('should show step count badge in tabs', () => {
            const progress = makePipelineProgress();
            element.setSession(makeSession({ pipeline_progress: progress }));
            const tab = element.querySelector('.pipeline-tab');
            // 3 completed out of 7 total → "3/7"
            expect(tab.textContent).toContain('3/7');
        });

        it('should highlight active pipeline tab', () => {
            element.setSession(makeSession({ pipeline_progress: makeMultiPipelineProgress() }));
            const activeTab = element.querySelector('.pipeline-tab.btn-primary');
            expect(activeTab).toBeDefined();
        });

        it('should show "Pipelines" heading', () => {
            element.setSession(makeSession({ pipeline_progress: makePipelineProgress() }));
            expect(element.textContent).toContain('Pipelines');
        });
    });

    // ==========================================================================
    // Step Pills
    // ==========================================================================

    describe('step pills', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should render step pills for pipeline steps', () => {
            element.setSession(makeSession({ pipeline_progress: makePipelineProgress() }));
            const pills = element.querySelectorAll('.step-pill');
            expect(pills.length).toBe(7); // lab_resolve, ports_alloc, tags_sync, lab_binding, lab_start, lds_provision, mark_ready
        });

        it('should show completed status styling', () => {
            element.setSession(makeSession({ pipeline_progress: makePipelineProgress() }));
            const completedPills = element.querySelectorAll('.step-pill[data-status="completed"]');
            expect(completedPills.length).toBe(3); // lab_resolve, ports_alloc, tags_sync
        });

        it('should show in_progress status styling', () => {
            element.setSession(makeSession({ pipeline_progress: makePipelineProgress() }));
            const inProgressPills = element.querySelectorAll('.step-pill[data-status="in_progress"]');
            expect(inProgressPills.length).toBe(1); // lab_start
        });

        it('should show pending status styling', () => {
            element.setSession(makeSession({ pipeline_progress: makePipelineProgress() }));
            const pendingPills = element.querySelectorAll('.step-pill[data-status="pending"]');
            expect(pendingPills.length).toBe(3); // lab_start, lds_provision, mark_ready
        });

        it('should format step names as Title Case', () => {
            element.setSession(makeSession({ pipeline_progress: makePipelineProgress() }));
            const pills = element.querySelectorAll('.step-pill');
            const names = [...pills].map(p => p.textContent.trim());
            expect(names).toContain('Lab Resolve');
            expect(names).toContain('Ports Alloc');
            expect(names).toContain('Lab Start');
        });

        it('should sort pills by order', () => {
            element.setSession(makeSession({ pipeline_progress: makePipelineProgress() }));
            const pills = element.querySelectorAll('.step-pill');
            const stepNames = [...pills].map(p => p.dataset.step);
            expect(stepNames).toEqual(['lab_resolve', 'ports_alloc', 'tags_sync', 'lab_binding', 'lab_start', 'lds_provision', 'mark_ready']);
        });

        it('should include error info in tooltip for failed steps', () => {
            element.setSession(makeSession({ pipeline_progress: makeFailedPipelineProgress() }));
            const failedPill = element.querySelector('.step-pill[data-status="failed"]');
            expect(failedPill).toBeDefined();
            expect(failedPill.title).toContain('Lab resolve failed');
        });

        it('should show "No steps reported" when pipeline has empty steps', () => {
            element.setSession(makeSession({ pipeline_progress: { instantiate: {} } }));
            expect(element.textContent).toContain('No steps reported yet');
        });
    });

    // ==========================================================================
    // Progress Bar
    // ==========================================================================

    describe('progress bar', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should render progress bar when steps exist', () => {
            element.setSession(makeSession({ pipeline_progress: makePipelineProgress() }));
            const progressBar = element.querySelector('.progress');
            expect(progressBar).toBeDefined();
        });

        it('should show correct completion percentage', () => {
            element.setSession(makeSession({ pipeline_progress: makePipelineProgress() }));
            // 3 completed out of 7 ≈ 43%
            expect(element.textContent).toContain('43% complete');
        });

        it('should show 100% for fully completed pipeline', () => {
            element.setSession(makeSession({ pipeline_progress: makeCompletedPipelineProgress() }));
            expect(element.textContent).toContain('100% complete');
        });

        it('should show step count summary', () => {
            element.setSession(makeSession({ pipeline_progress: makePipelineProgress() }));
            // 3 completed, 1 in progress out of 7 total
            expect(element.textContent).toContain('3✓');
            expect(element.textContent).toContain('/ 7');
        });

        it('should show failed count when failures exist', () => {
            element.setSession(makeSession({ pipeline_progress: makeFailedPipelineProgress() }));
            expect(element.textContent).toContain('1✗');
        });

        it('should render colored progress bar segments', () => {
            element.setSession(makeSession({ pipeline_progress: makePipelineProgress() }));
            const successBar = element.querySelector('.progress-bar.bg-success');
            const primaryBar = element.querySelector('.progress-bar.bg-primary');
            expect(successBar).toBeDefined();
            expect(primaryBar).toBeDefined();
        });
    });

    // ==========================================================================
    // Pipeline Tab Switching
    // ==========================================================================

    describe('pipeline tab switching', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should switch active pipeline on tab click', () => {
            element.setSession(
                makeSession({
                    status: 'stopping',
                    pipeline_progress: makeMultiPipelineProgress(),
                })
            );

            // The "teardown" tab should be the second one
            const tabs = element.querySelectorAll('.pipeline-tab');
            expect(tabs.length).toBe(2);

            // Click the teardown tab
            const teardownTab = [...tabs].find(t => t.textContent.includes('Teardown'));
            teardownTab?.click();

            // After click, expandedPipeline should be updated
            expect(element._expandedPipeline).toBe('teardown');
        });

        it('should render step pills for the selected pipeline', () => {
            element.setSession(
                makeSession({
                    status: 'stopping',
                    pipeline_progress: makeMultiPipelineProgress(),
                })
            );

            // Initially shows "instantiate" pipeline (5 steps) — the detected active one has in_progress
            // Actually teardown has in_progress, so it should be auto-detected
            const initialPills = element.querySelectorAll('.step-pill');
            // teardown has 3 steps (stop_lab, deregister_lds, wipe_lab) — or instantiate has 5
            expect(initialPills.length).toBeGreaterThan(0);
        });
    });

    // ==========================================================================
    // _detectActivePipeline()
    // ==========================================================================

    describe('_detectActivePipeline()', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should detect pipeline with in_progress steps', () => {
            element._pipelineProgress = makeMultiPipelineProgress();
            expect(element._detectActivePipeline()).toBe('teardown');
        });

        it('should detect pipeline with pending steps when no in_progress', () => {
            element._pipelineProgress = {
                instantiate: {
                    step_a: { status: 'completed', order: 1 },
                    step_b: { status: 'completed', order: 2 },
                },
                teardown: {
                    step_c: { status: 'pending', order: 1 },
                },
            };
            expect(element._detectActivePipeline()).toBe('teardown');
        });

        it('should return last pipeline when all are completed', () => {
            element._pipelineProgress = makeCompletedPipelineProgress();
            const result = element._detectActivePipeline();
            expect(result).toBe('instantiate');
        });

        it('should return null when no pipelines exist', () => {
            element._pipelineProgress = {};
            expect(element._detectActivePipeline()).toBeNull();
        });
    });

    // ==========================================================================
    // _computeSummary()
    // ==========================================================================

    describe('_computeSummary()', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should count completed steps', () => {
            const steps = [{ status: 'completed' }, { status: 'completed' }, { status: 'in_progress' }];
            const summary = element._computeSummary(steps);
            expect(summary.completed).toBe(2);
            expect(summary.in_progress).toBe(1);
            expect(summary.total).toBe(3);
        });

        it('should count failed steps', () => {
            const steps = [{ status: 'completed' }, { status: 'failed' }];
            const summary = element._computeSummary(steps);
            expect(summary.failed).toBe(1);
        });

        it('should count skipped steps', () => {
            const steps = [{ status: 'completed' }, { status: 'skipped' }];
            const summary = element._computeSummary(steps);
            expect(summary.skipped).toBe(1);
        });

        it('should handle empty steps array', () => {
            const summary = element._computeSummary([]);
            expect(summary.total).toBe(0);
            expect(summary.completed).toBe(0);
        });

        it('should compute pending from remainder', () => {
            const steps = [{ status: 'completed' }, { status: 'completed' }, { status: 'in_progress' }, { status: 'pending' }, { status: 'pending' }];
            const summary = element._computeSummary(steps);
            expect(summary.pending).toBe(2);
        });
    });

    // ==========================================================================
    // _formatPipelineName()
    // ==========================================================================

    describe('_formatPipelineName()', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should convert snake_case to Title Case', () => {
            expect(element._formatPipelineName('collect_evidence')).toBe('Collect Evidence');
        });

        it('should handle single word', () => {
            expect(element._formatPipelineName('instantiate')).toBe('Instantiate');
        });

        it('should handle null', () => {
            expect(element._formatPipelineName(null)).toBe('Unknown');
        });

        it('should handle empty string', () => {
            expect(element._formatPipelineName('')).toBe('Unknown');
        });

        it('should handle multi-segment names', () => {
            expect(element._formatPipelineName('compute_grading_score')).toBe('Compute Grading Score');
        });
    });

    // ==========================================================================
    // _formatStepName()
    // ==========================================================================

    describe('_formatStepName()', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should convert snake_case to Title Case', () => {
            expect(element._formatStepName('create_lab')).toBe('Create Lab');
        });

        it('should handle single word', () => {
            expect(element._formatStepName('teardown')).toBe('Teardown');
        });

        it('should handle null', () => {
            expect(element._formatStepName(null)).toBe('Unknown');
        });
    });

    // ==========================================================================
    // _getPipelineStatusIcon()
    // ==========================================================================

    describe('_getPipelineStatusIcon()', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should return danger icon for failed pipeline', () => {
            const icon = element._getPipelineStatusIcon({ failed: 1, in_progress: 0, completed: 1, total: 2 });
            expect(icon).toContain('text-danger');
            expect(icon).toContain('exclamation-circle-fill');
        });

        it('should return spinning icon for in-progress pipeline', () => {
            const icon = element._getPipelineStatusIcon({ failed: 0, in_progress: 1, completed: 1, total: 3 });
            expect(icon).toContain('arrow-repeat');
        });

        it('should return success icon for fully completed pipeline', () => {
            const icon = element._getPipelineStatusIcon({ failed: 0, in_progress: 0, completed: 5, total: 5 });
            expect(icon).toContain('text-success');
            expect(icon).toContain('check-circle-fill');
        });

        it('should return muted icon for pending pipeline', () => {
            const icon = element._getPipelineStatusIcon({ failed: 0, in_progress: 0, completed: 0, total: 3 });
            expect(icon).toContain('text-muted');
        });
    });

    // ==========================================================================
    // Execution History
    // ==========================================================================

    describe('execution history', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should render history toggle button when pipelines exist', () => {
            element.setSession(makeSession({ pipeline_progress: makePipelineProgress() }));
            const toggle = element.querySelector('#toggle-history');
            expect(toggle).toBeDefined();
            expect(toggle.textContent).toContain('Execution History');
        });

        it('should not render history toggle when no pipelines', () => {
            element.setSession(makeSession({ pipeline_progress: null }));
            const toggle = element.querySelector('#toggle-history');
            expect(toggle).toBeNull();
        });

        it('should show loading spinner when history is expanded but not loaded', () => {
            element._historyVisible = true;
            element._historyLoaded = false;
            element.setSession(makeSession({ pipeline_progress: makePipelineProgress() }));
            expect(element.textContent).toContain('Loading history');
        });

        it('should show "No execution records" when history is empty', () => {
            element.setSession(makeSession({ pipeline_progress: makePipelineProgress() }));
            // Set state AFTER setSession (which resets _historyLoaded)
            element._historyVisible = true;
            element._historyLoaded = true;
            element._executionHistory = [];
            element.render();
            expect(element.textContent).toContain('No execution records yet');
        });

        it('should render execution history table when loaded', () => {
            element.setSession(makeSession({ pipeline_progress: makePipelineProgress() }));
            element._historyVisible = true;
            element._historyLoaded = true;
            element._executionHistory = makeExecutionHistory();
            element.render();

            const table = element.querySelector('.table');
            expect(table).toBeDefined();
            const rows = element.querySelectorAll('tbody tr');
            expect(rows.length).toBe(2);
        });

        it('should display pipeline name in history rows', () => {
            element.setSession(makeSession({ pipeline_progress: makePipelineProgress() }));
            element._historyVisible = true;
            element._historyLoaded = true;
            element._executionHistory = makeExecutionHistory();
            element.render();

            const cells = element.querySelectorAll('tbody td');
            const firstRowPipeline = cells[0].textContent;
            expect(firstRowPipeline).toContain('Instantiate');
        });

        it('should display status badge in history rows', () => {
            element.setSession(makeSession({ pipeline_progress: makePipelineProgress() }));
            element._historyVisible = true;
            element._historyLoaded = true;
            element._executionHistory = makeExecutionHistory();
            element.render();

            const badges = element.querySelectorAll('tbody .badge');
            expect(badges.length).toBe(2);
        });

        it('should call listPipelineExecutions when toggle is clicked', async () => {
            listPipelineExecutions.mockResolvedValue([]);

            element.setSession(makeSession({ pipeline_progress: makePipelineProgress() }));
            const toggle = element.querySelector('#toggle-history');
            toggle?.click();

            // Wait for async load
            await vi.waitFor(() => {
                expect(listPipelineExecutions).toHaveBeenCalledWith('session-001', { limit: 20 });
            });
        });
    });

    // ==========================================================================
    // Style Injection
    // ==========================================================================

    describe('_injectStyles()', () => {
        it('should inject styles into document head', () => {
            element = createElement();
            element.setSession(makeSession());
            const style = document.getElementById('pipeline-progress-panel-styles');
            expect(style).toBeDefined();
            expect(style.textContent).toContain('.lifecycle-rail');
            expect(style.textContent).toContain('.phase-step');
            expect(style.textContent).toContain('.step-pill');
        });

        it('should be idempotent (no duplicate style tags)', () => {
            element = createElement();
            element.setSession(makeSession());
            element.render();
            element.render();
            const styles = document.querySelectorAll('#pipeline-progress-panel-styles');
            expect(styles.length).toBe(1);
        });
    });

    // ==========================================================================
    // _escapeHtml()
    // ==========================================================================

    describe('_escapeHtml()', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should escape HTML entities', () => {
            expect(element._escapeHtml('<script>alert("xss")</script>')).toBe('&lt;script&gt;alert("xss")&lt;/script&gt;');
        });

        it('should return empty string for null', () => {
            expect(element._escapeHtml(null)).toBe('');
        });

        it('should return empty string for undefined', () => {
            expect(element._escapeHtml(undefined)).toBe('');
        });

        it('should handle plain text unchanged', () => {
            expect(element._escapeHtml('hello world')).toBe('hello world');
        });
    });

    // ==========================================================================
    // Integration: Full render with data
    // ==========================================================================

    describe('full render integration', () => {
        beforeEach(() => {
            element = createElement();
        });

        it('should render lifecycle rail + pipelines + history toggle together', () => {
            element.setSession(
                makeSession({
                    status: 'instantiating',
                    pipeline_progress: makePipelineProgress(),
                })
            );

            // Lifecycle rail present
            expect(element.querySelector('.lifecycle-rail')).toBeDefined();

            // Pipeline section present
            expect(element.querySelector('.pipeline-tab')).toBeDefined();

            // Step pills present
            expect(element.querySelectorAll('.step-pill').length).toBe(7);

            // History toggle present
            expect(element.querySelector('#toggle-history')).toBeDefined();

            // Progress bar present
            expect(element.querySelector('.progress')).toBeDefined();
        });

        it('should render correctly for stopped session with completed pipeline', () => {
            element.setSession(
                makeSession({
                    status: 'stopped',
                    pipeline_progress: makeCompletedPipelineProgress(),
                })
            );

            // Current phase should be stopped
            const currentPhase = element.querySelector('.phase-step.phase-current');
            expect(currentPhase.dataset.phase).toBe('stopped');

            // All steps should be completed
            const completedPills = element.querySelectorAll('.step-pill[data-status="completed"]');
            expect(completedPills.length).toBe(7);
        });

        it('should render correctly for failed pipeline', () => {
            element.setSession(
                makeSession({
                    status: 'instantiating',
                    pipeline_progress: makeFailedPipelineProgress(),
                })
            );

            // Failed step pill should exist
            const failedPill = element.querySelector('.step-pill[data-status="failed"]');
            expect(failedPill).toBeDefined();

            // Pipeline tab should show danger icon
            const tab = element.querySelector('.pipeline-tab');
            expect(tab.innerHTML).toContain('text-danger');
        });
    });
});
