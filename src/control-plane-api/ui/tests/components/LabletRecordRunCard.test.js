/**
 * LabletRecordRunCard Component Tests — Phase 11 (P11-24)
 *
 * Tests for the <lablet-record-run-card> custom element.
 * Verifies rendering, status display, port mapping, LDS/grading sections.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Mock dependencies before importing the component
vi.mock('../../src/scripts/core/EventBus.js', () => ({
    EventTypes: {
        LABLET_RECORD_RUN_STATUS_UPDATED: 'lablet_record_run.status.updated',
        LABLET_RECORD_RUN_ENDED: 'lablet_record_run.ended',
    },
    LcmEventTypes: {
        LABLET_RECORD_RUN_STATUS_UPDATED: 'lablet_record_run.status.updated',
        LABLET_RECORD_RUN_ENDED: 'lablet_record_run.ended',
    },
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
    LcmEventTypes: {
        LABLET_RECORD_RUN_STATUS_UPDATED: 'lablet_record_run.status.updated',
        LABLET_RECORD_RUN_ENDED: 'lablet_record_run.ended',
    },
    EventTypes: {
        LABLET_RECORD_RUN_STATUS_UPDATED: 'lablet_record_run.status.updated',
        LABLET_RECORD_RUN_ENDED: 'lablet_record_run.ended',
    },
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

vi.mock('../../src/scripts/api/lablet-record-runs.js', () => ({
    endRun: vi.fn(),
    listRuns: vi.fn(),
    getRun: vi.fn(),
}));

vi.mock('../../src/scripts/ui/notifications.js', () => ({
    showToast: vi.fn(),
}));

import { LabletRecordRunCard } from '../../src/scripts/components/sessions/LabletRecordRunCard.js';

// ==============================================================================
// Helpers
// ==============================================================================

function makeRun(overrides = {}) {
    return {
        id: 'run-abc12345-6789',
        lablet_instance_id: 'inst-001',
        lab_record_id: 'lab-001',
        status: 'active',
        started_at: '2025-01-15T10:00:00Z',
        ended_at: null,
        allocated_ports: {},
        created_by: 'alice',
        ...overrides,
    };
}

function createElement() {
    const el = document.createElement('lablet-record-run-card');
    document.body.appendChild(el);
    return el;
}

// ==============================================================================
// Tests
// ==============================================================================

describe('LabletRecordRunCard', () => {
    let element;

    afterEach(() => {
        element?.remove();
        element = null;
    });

    describe('registration', () => {
        it('should register as custom element', () => {
            expect(customElements.get('lablet-record-run-card')).toBeDefined();
        });
    });

    describe('initial render (no data)', () => {
        it('should show "No run data" when no run set', () => {
            element = createElement();
            expect(element.textContent).toContain('No run data');
        });
    });

    describe('setRun()', () => {
        it('should render run card with status badge', () => {
            element = createElement();
            element.setRun(makeRun({ status: 'active' }));

            expect(element.querySelector('.badge')).toBeTruthy();
            expect(element.textContent).toContain('Active');
        });

        it('should show truncated run ID', () => {
            element = createElement();
            element.setRun(makeRun({ id: 'run-abcdef12-3456-7890' }));

            const codeEl = element.querySelector('code');
            expect(codeEl.textContent).toContain('run-abcd');
        });

        it('should display started_at date', () => {
            element = createElement();
            element.setRun(makeRun({ started_at: '2025-01-15T10:00:00Z' }));

            expect(element.textContent).toContain('Started');
        });

        it('should show "In progress" for non-terminal runs', () => {
            element = createElement();
            element.setRun(makeRun({ status: 'active', ended_at: null }));

            expect(element.textContent).toContain('In progress');
        });

        it('should show ended_at for terminal runs', () => {
            element = createElement();
            element.setRun(
                makeRun({
                    status: 'ended',
                    ended_at: '2025-01-15T12:00:00Z',
                })
            );

            expect(element.textContent).toContain('Ended');
        });
    });

    describe('status badges', () => {
        const statusTests = [
            { status: 'provisioning', label: 'Provisioning', color: 'info' },
            { status: 'active', label: 'Active', color: 'success' },
            { status: 'paused', label: 'Paused', color: 'warning' },
            { status: 'ending', label: 'Ending', color: 'warning' },
            { status: 'ended', label: 'Ended', color: 'secondary' },
            { status: 'faulted', label: 'Faulted', color: 'danger' },
        ];

        statusTests.forEach(({ status, label, color }) => {
            it(`should render ${status} badge with correct color`, () => {
                element = createElement();
                element.setRun(makeRun({ status }));

                const badge = element.querySelector('.badge');
                expect(badge.textContent.trim()).toBe(label);
                expect(badge.classList.contains(`bg-${color}`)).toBe(true);
            });
        });
    });

    describe('port mappings section', () => {
        it('should show "No ports allocated" when empty', () => {
            element = createElement();
            element.setRun(makeRun({ allocated_ports: {} }));

            expect(element.textContent).toContain('No ports allocated');
        });

        it('should show port count badge when ports exist', () => {
            element = createElement();
            element.setRun(
                makeRun({
                    allocated_ports: {
                        'router-1': { protocol: 'ssh', external_port: 22, internal_port: 22 },
                        'switch-1': { protocol: 'http', external_port: 80, internal_port: 80 },
                    },
                })
            );

            expect(element.textContent).toContain('2 device(s)');
        });

        it('should create port-mapping-table element', () => {
            element = createElement();
            element.setRun(
                makeRun({
                    allocated_ports: {
                        'router-1': { protocol: 'ssh', external_port: 22, internal_port: 22 },
                    },
                })
            );

            const portTable = element.querySelector('port-mapping-table');
            expect(portTable).toBeTruthy();
        });
    });

    describe('LDS session section', () => {
        it('should not render LDS section when no LDS data', () => {
            element = createElement();
            element.setRun(makeRun({ lds_session_id: null, has_lds_session: false }));

            expect(element.textContent).not.toContain('LDS Session');
        });

        it('should render LDS section with status', () => {
            element = createElement();
            element.setRun(
                makeRun({
                    has_lds_session: true,
                    lds_session_id: 'lds-001',
                    lds_session_status: 'active',
                })
            );

            expect(element.textContent).toContain('LDS Session');
            expect(element.textContent).toContain('active');
        });

        it('should render Open Lab Session button when URL present', () => {
            element = createElement();
            element.setRun(
                makeRun({
                    has_lds_session: true,
                    lds_session_id: 'lds-001',
                    lds_login_url: 'https://lds.example.com/lab/123',
                })
            );

            const link = element.querySelector('a[target="_blank"]');
            expect(link).toBeTruthy();
            expect(link.textContent).toContain('Open Lab Session');
        });
    });

    describe('grading section', () => {
        it('should not render grading section when no grading data', () => {
            element = createElement();
            element.setRun(makeRun({ grading_session_id: null, has_grading: false }));

            expect(element.textContent).not.toContain('Grading');
        });

        it('should render grading section with score', () => {
            element = createElement();
            element.setRun(
                makeRun({
                    has_grading: true,
                    grading_session_id: 'grade-001',
                    grading_status: 'submitted',
                    grading_score: 85,
                    grading_max_score: 100,
                })
            );

            expect(element.textContent).toContain('Grading');
            expect(element.textContent).toContain('85');
            expect(element.textContent).toContain('100');
        });
    });

    describe('footer / actions', () => {
        it('should show End Run button for non-terminal runs', () => {
            element = createElement();
            element.setRun(makeRun({ status: 'active' }));

            const btn = element.querySelector('[data-action="end-run"]');
            expect(btn).toBeTruthy();
            expect(btn.textContent).toContain('End Run');
        });

        it('should NOT show End Run button for terminal runs', () => {
            element = createElement();
            element.setRun(makeRun({ status: 'ended' }));

            const btn = element.querySelector('[data-action="end-run"]');
            expect(btn).toBeNull();
        });

        it('should NOT show End Run button for faulted runs', () => {
            element = createElement();
            element.setRun(makeRun({ status: 'faulted' }));

            const btn = element.querySelector('[data-action="end-run"]');
            expect(btn).toBeNull();
        });

        it('should display created_by in footer', () => {
            element = createElement();
            element.setRun(makeRun({ status: 'active', created_by: 'bob' }));

            expect(element.textContent).toContain('bob');
        });
    });

    describe('duration display', () => {
        it('should show duration when available', () => {
            element = createElement();
            element.setRun(makeRun({ duration_seconds: 3661 }));

            expect(element.textContent).toContain('Duration');
            expect(element.textContent).toContain('1h 1m');
        });

        it('should format seconds correctly', () => {
            element = createElement();
            element.setRun(makeRun({ duration_seconds: 45 }));
            expect(element.textContent).toContain('45s');
        });

        it('should format minutes correctly', () => {
            element = createElement();
            element.setRun(makeRun({ duration_seconds: 125 }));
            expect(element.textContent).toContain('2m 5s');
        });

        it('should not show duration when null', () => {
            element = createElement();
            element.setRun(makeRun({ duration_seconds: null }));
            expect(element.textContent).not.toContain('Duration');
        });
    });

    describe('status_reason', () => {
        it('should display status reason when present', () => {
            element = createElement();
            element.setRun(makeRun({ status_reason: 'User requested termination' }));

            expect(element.textContent).toContain('User requested termination');
        });

        it('should not display status reason when absent', () => {
            element = createElement();
            element.setRun(makeRun({ status_reason: null }));

            const infoIcons = element.querySelectorAll('.bi-info-circle');
            // status_reason block should not appear
            expect(element.innerHTML).not.toContain('info-circle');
        });
    });

    describe('identity references', () => {
        it('should display session_part_id when present', () => {
            element = createElement();
            element.setRun(makeRun({ session_part_id: 'part-123456789012' }));

            expect(element.textContent).toContain('Session Part');
            // Component uses .substring(0, 12) — 12 chars + ellipsis
            expect(element.textContent).toContain('part-1234567…');
        });

        it('should display form_qualified_name when present', () => {
            element = createElement();
            element.setRun(makeRun({ form_qualified_name: 'lab.network.basics' }));

            expect(element.textContent).toContain('Form');
            expect(element.textContent).toContain('lab.network.basics');
        });
    });
});
