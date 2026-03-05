/**
 * LabletRecordRuns Slice Unit Tests — Phase 11 (P11-24)
 *
 * Tests for reducers and selectors in labletRecordRunsSlice.
 * Pure state logic — no DOM, no API.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import {
    labletRecordRunsSlice,
    selectAllRuns,
    selectRunById,
    selectActiveRun,
    selectRunsListLoading,
    selectRunsByInstance,
    selectRunsByLabRecord,
    selectRunsByStatus,
    selectActiveRuns,
    selectRunStatusSummary,
} from '../../src/scripts/app/slices/labletRecordRunsSlice.js';

// ==============================================================================
// Helpers
// ==============================================================================

const { reducers, initialState } = labletRecordRunsSlice;

function makeRun(overrides = {}) {
    return {
        id: `run-${Math.random().toString(36).slice(2, 8)}`,
        lablet_instance_id: 'inst-001',
        lab_record_id: 'lab-001',
        status: 'active',
        started_at: '2025-01-15T10:00:00Z',
        ended_at: null,
        ...overrides,
    };
}

function wrapState(sliceState) {
    return { labletRecordRuns: sliceState };
}

// ==============================================================================
// Reducer Tests
// ==============================================================================

describe('labletRecordRunsSlice reducers', () => {
    let state;

    beforeEach(() => {
        state = { ...initialState, byId: {}, allIds: [], loading: { list: false, details: {} }, errors: {} };
    });

    describe('setActiveRun', () => {
        it('should set the active run ID', () => {
            const next = reducers.setActiveRun(state, 'run-123');
            expect(next.activeId).toBe('run-123');
        });

        it('should clear active run when set to null', () => {
            state.activeId = 'run-123';
            const next = reducers.setActiveRun(state, null);
            expect(next.activeId).toBeNull();
        });
    });

    describe('upsertRun', () => {
        it('should insert a new run', () => {
            const run = makeRun({ id: 'run-1' });
            const next = reducers.upsertRun(state, run);

            expect(next.byId['run-1']).toBeDefined();
            expect(next.byId['run-1'].id).toBe('run-1');
            expect(next.allIds).toContain('run-1');
        });

        it('should merge into an existing run', () => {
            const run = makeRun({ id: 'run-1', status: 'active' });
            state = reducers.upsertRun(state, run);

            const updated = reducers.upsertRun(state, { id: 'run-1', status: 'ended' });
            expect(updated.byId['run-1'].status).toBe('ended');
            expect(updated.allIds.length).toBe(1); // no duplicate
        });

        it('should ignore null or missing id', () => {
            expect(reducers.upsertRun(state, null)).toBe(state);
            expect(reducers.upsertRun(state, {})).toBe(state);
        });

        it('should not overwrite existing fields with undefined', () => {
            const run = makeRun({ id: 'run-1', status: 'active', started_at: '2025-01-01T00:00:00Z' });
            state = reducers.upsertRun(state, run);

            const updated = reducers.upsertRun(state, { id: 'run-1', status: 'ended', started_at: undefined });
            expect(updated.byId['run-1'].started_at).toBe('2025-01-01T00:00:00Z');
        });
    });

    describe('upsertRuns', () => {
        it('should bulk insert runs', () => {
            const runs = [makeRun({ id: 'r1' }), makeRun({ id: 'r2' }), makeRun({ id: 'r3' })];
            const next = reducers.upsertRuns(state, runs);

            expect(next.allIds).toHaveLength(3);
            expect(next.byId['r1']).toBeDefined();
            expect(next.byId['r2']).toBeDefined();
            expect(next.byId['r3']).toBeDefined();
            expect(next.lastRefreshedAt).toBeTruthy();
        });

        it('should handle non-array input', () => {
            expect(reducers.upsertRuns(state, 'not-array')).toBe(state);
        });
    });

    describe('updateRunStatus', () => {
        it('should update run status and reason', () => {
            const run = makeRun({ id: 'run-1', status: 'active' });
            state = reducers.upsertRun(state, run);

            const next = reducers.updateRunStatus(state, {
                runId: 'run-1',
                status: 'ended',
                reason: 'user_request',
            });

            expect(next.byId['run-1'].status).toBe('ended');
            expect(next.byId['run-1'].status_reason).toBe('user_request');
        });

        it('should ignore unknown run ID', () => {
            const next = reducers.updateRunStatus(state, { runId: 'nonexistent', status: 'ended' });
            expect(next).toBe(state);
        });
    });

    describe('removeRun', () => {
        it('should remove a run by ID', () => {
            const run = makeRun({ id: 'run-1' });
            state = reducers.upsertRun(state, run);

            const next = reducers.removeRun(state, 'run-1');
            expect(next.byId['run-1']).toBeUndefined();
            expect(next.allIds).not.toContain('run-1');
        });

        it('should clear activeId if removed run was active', () => {
            state = reducers.upsertRun(state, makeRun({ id: 'run-1' }));
            state = reducers.setActiveRun(state, 'run-1');

            const next = reducers.removeRun(state, 'run-1');
            expect(next.activeId).toBeNull();
        });

        it('should not affect activeId if different run removed', () => {
            state = reducers.upsertRun(state, makeRun({ id: 'run-1' }));
            state = reducers.upsertRun(state, makeRun({ id: 'run-2' }));
            state = reducers.setActiveRun(state, 'run-1');

            const next = reducers.removeRun(state, 'run-2');
            expect(next.activeId).toBe('run-1');
        });
    });

    describe('replaceAll', () => {
        it('should replace all runs', () => {
            state = reducers.upsertRun(state, makeRun({ id: 'old-1' }));
            const newRuns = [makeRun({ id: 'new-1' }), makeRun({ id: 'new-2' })];

            const next = reducers.replaceAll(state, newRuns);
            expect(next.allIds).toEqual(['new-1', 'new-2']);
            expect(next.byId['old-1']).toBeUndefined();
            expect(next.lastRefreshedAt).toBeTruthy();
        });

        it('should handle empty array', () => {
            state = reducers.upsertRun(state, makeRun({ id: 'run-1' }));
            const next = reducers.replaceAll(state, []);
            expect(next.allIds).toHaveLength(0);
        });

        it('should handle non-array input', () => {
            expect(reducers.replaceAll(state, null)).toBe(state);
        });
    });

    describe('setListLoading', () => {
        it('should set list loading to true', () => {
            const next = reducers.setListLoading(state, true);
            expect(next.loading.list).toBe(true);
        });

        it('should set list loading to false', () => {
            state.loading.list = true;
            const next = reducers.setListLoading(state, false);
            expect(next.loading.list).toBe(false);
        });
    });

    describe('setDetailLoading', () => {
        it('should set detail loading for a specific run', () => {
            const next = reducers.setDetailLoading(state, { runId: 'run-1', loading: true });
            expect(next.loading.details['run-1']).toBe(true);
        });
    });

    describe('setError', () => {
        it('should set an error by key', () => {
            const next = reducers.setError(state, { key: '_list', error: 'Network error' });
            expect(next.errors._list).toBe('Network error');
        });
    });
});

// ==============================================================================
// Selector Tests
// ==============================================================================

describe('labletRecordRunsSlice selectors', () => {
    let state;

    beforeEach(() => {
        const slice = {
            ...initialState,
            byId: {},
            allIds: [],
            loading: { list: false, details: {} },
            errors: {},
        };
        const r1 = makeRun({ id: 'r1', status: 'active', lablet_instance_id: 'inst-A', lab_record_id: 'lab-1' });
        const r2 = makeRun({ id: 'r2', status: 'provisioning', lablet_instance_id: 'inst-A', lab_record_id: 'lab-2' });
        const r3 = makeRun({ id: 'r3', status: 'ended', lablet_instance_id: 'inst-B', lab_record_id: 'lab-1' });
        const r4 = makeRun({ id: 'r4', status: 'faulted', lablet_instance_id: 'inst-B', lab_record_id: 'lab-3' });
        const r5 = makeRun({ id: 'r5', status: 'paused', lablet_instance_id: 'inst-A', lab_record_id: 'lab-4' });

        const byId = { r1, r2, r3, r4, r5 };
        const allIds = ['r1', 'r2', 'r3', 'r4', 'r5'];

        state = wrapState({ ...slice, byId, allIds, activeId: 'r1' });
    });

    describe('selectAllRuns', () => {
        it('should return all runs as array', () => {
            const runs = selectAllRuns(state);
            expect(runs).toHaveLength(5);
        });

        it('should return empty array for missing slice', () => {
            expect(selectAllRuns({})).toEqual([]);
        });
    });

    describe('selectRunById', () => {
        it('should return run by ID', () => {
            const run = selectRunById(state, 'r1');
            expect(run).toBeDefined();
            expect(run.id).toBe('r1');
        });

        it('should return null for unknown ID', () => {
            expect(selectRunById(state, 'unknown')).toBeNull();
        });
    });

    describe('selectActiveRun', () => {
        it('should return the active run', () => {
            const run = selectActiveRun(state);
            expect(run).toBeDefined();
            expect(run.id).toBe('r1');
        });

        it('should return null if no active run', () => {
            state.labletRecordRuns.activeId = null;
            expect(selectActiveRun(state)).toBeNull();
        });
    });

    describe('selectRunsListLoading', () => {
        it('should return false by default', () => {
            expect(selectRunsListLoading(state)).toBe(false);
        });

        it('should return true when loading', () => {
            state.labletRecordRuns.loading.list = true;
            expect(selectRunsListLoading(state)).toBe(true);
        });
    });

    describe('selectRunsByInstance', () => {
        it('should filter runs by lablet_instance_id', () => {
            const runs = selectRunsByInstance(state, 'inst-A');
            expect(runs).toHaveLength(3);
            expect(runs.every(r => r.lablet_instance_id === 'inst-A')).toBe(true);
        });

        it('should return empty for unknown instance', () => {
            expect(selectRunsByInstance(state, 'unknown')).toEqual([]);
        });
    });

    describe('selectRunsByLabRecord', () => {
        it('should filter runs by lab_record_id', () => {
            const runs = selectRunsByLabRecord(state, 'lab-1');
            expect(runs).toHaveLength(2);
        });
    });

    describe('selectRunsByStatus', () => {
        it('should filter runs by status', () => {
            const active = selectRunsByStatus(state, 'active');
            expect(active).toHaveLength(1);
            expect(active[0].id).toBe('r1');
        });
    });

    describe('selectActiveRuns', () => {
        it('should exclude terminal runs (ended, faulted)', () => {
            const active = selectActiveRuns(state);
            expect(active).toHaveLength(3); // r1=active, r2=provisioning, r5=paused
            const ids = active.map(r => r.id);
            expect(ids).not.toContain('r3');
            expect(ids).not.toContain('r4');
        });
    });

    describe('selectRunStatusSummary', () => {
        it('should compute status summary', () => {
            const summary = selectRunStatusSummary(state);
            expect(summary.total).toBe(5);
            expect(summary.active).toBe(1);
            expect(summary.provisioning).toBe(1);
            expect(summary.ended).toBe(1);
            expect(summary.faulted).toBe(1);
            expect(summary.paused).toBe(1);
        });

        it('should return zeroes for empty state', () => {
            const summary = selectRunStatusSummary({});
            expect(summary.total).toBe(0);
        });
    });
});
