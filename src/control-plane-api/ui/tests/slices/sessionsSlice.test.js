/**
 * Sessions Slice Unit Tests — Phase 11 (P11-24)
 *
 * Tests for reducers and selectors in sessionsSlice.
 * Pure state logic — no DOM, no API.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import {
    sessionsSlice,
    selectAllSessions,
    selectSessionById,
    selectActiveSession,
    selectActiveSessionDetail,
    selectSessionsListLoading,
    selectSessionDetailLoading,
    selectSessionFilters,
    selectSessionsCount,
    selectSessionsByStatus,
    selectSessionStatusSummary,
} from '../../src/scripts/app/slices/sessionsSlice.js';

// ==============================================================================
// Helpers
// ==============================================================================

const { reducers, initialState } = sessionsSlice;

function makeSession(overrides = {}) {
    return {
        id: `sess-${Math.random().toString(36).slice(2, 8)}`,
        status: 'running',
        definition_name: 'Lab 101',
        definition_id: 'def-001',
        owner_id: 'alice',
        worker_name: 'worker-01',
        ...overrides,
    };
}

function wrapState(sliceState) {
    return { sessions: sliceState };
}

// ==============================================================================
// Reducer Tests
// ==============================================================================

describe('sessionsSlice reducers', () => {
    let state;

    beforeEach(() => {
        state = {
            ...initialState,
            byId: {},
            allIds: [],
            loading: { list: false, detail: false },
            errors: {},
            filters: { ...initialState.filters },
        };
    });

    describe('setActiveSession', () => {
        it('should set the active session ID', () => {
            const next = reducers.setActiveSession(state, 'sess-123');
            expect(next.activeId).toBe('sess-123');
        });

        it('should clear active session when set to null', () => {
            state.activeId = 'sess-123';
            const next = reducers.setActiveSession(state, null);
            expect(next.activeId).toBeNull();
        });
    });

    describe('setActiveDetail', () => {
        it('should set the active session detail', () => {
            const detail = { id: 'sess-1', runs: [{ id: 'run-1' }] };
            const next = reducers.setActiveDetail(state, detail);
            expect(next.activeDetail).toEqual(detail);
        });
    });

    describe('upsertSession', () => {
        it('should insert a new session', () => {
            const session = makeSession({ id: 'sess-1' });
            const next = reducers.upsertSession(state, session);

            expect(next.byId['sess-1']).toBeDefined();
            expect(next.allIds).toContain('sess-1');
        });

        it('should merge into an existing session', () => {
            const session = makeSession({ id: 'sess-1', status: 'running' });
            state = reducers.upsertSession(state, session);

            const updated = reducers.upsertSession(state, { id: 'sess-1', status: 'terminated' });
            expect(updated.byId['sess-1'].status).toBe('terminated');
            expect(updated.allIds.length).toBe(1);
        });

        it('should not overwrite existing fields with undefined', () => {
            const session = makeSession({ id: 'sess-1', owner_id: 'alice' });
            state = reducers.upsertSession(state, session);

            const updated = reducers.upsertSession(state, { id: 'sess-1', status: 'ready', owner_id: undefined });
            expect(updated.byId['sess-1'].owner_id).toBe('alice');
        });

        it('should ignore null or missing id', () => {
            expect(reducers.upsertSession(state, null)).toBe(state);
            expect(reducers.upsertSession(state, {})).toBe(state);
        });
    });

    describe('replaceAll', () => {
        it('should replace all sessions', () => {
            state = reducers.upsertSession(state, makeSession({ id: 'old-1' }));
            const newSessions = [makeSession({ id: 'new-1' }), makeSession({ id: 'new-2' })];

            const next = reducers.replaceAll(state, newSessions);
            expect(next.allIds).toEqual(['new-1', 'new-2']);
            expect(next.byId['old-1']).toBeUndefined();
            expect(next.lastRefreshedAt).toBeTruthy();
        });

        it('should handle non-array', () => {
            expect(reducers.replaceAll(state, null)).toBe(state);
        });
    });

    describe('removeSession', () => {
        it('should remove a session', () => {
            state = reducers.upsertSession(state, makeSession({ id: 'sess-1' }));
            const next = reducers.removeSession(state, 'sess-1');
            expect(next.byId['sess-1']).toBeUndefined();
            expect(next.allIds).not.toContain('sess-1');
        });

        it('should clear activeId if removed session was active', () => {
            state = reducers.upsertSession(state, makeSession({ id: 'sess-1' }));
            state = reducers.setActiveSession(state, 'sess-1');
            const next = reducers.removeSession(state, 'sess-1');
            expect(next.activeId).toBeNull();
        });
    });

    describe('loading states', () => {
        it('should set list loading', () => {
            const next = reducers.setListLoading(state, true);
            expect(next.loading.list).toBe(true);
        });

        it('should set detail loading', () => {
            const next = reducers.setDetailLoading(state, true);
            expect(next.loading.detail).toBe(true);
        });
    });

    describe('setError', () => {
        it('should set an error by key', () => {
            const next = reducers.setError(state, { key: 'sess-1', error: 'Not found' });
            expect(next.errors['sess-1']).toBe('Not found');
        });
    });

    describe('filters', () => {
        it('should update partial filters', () => {
            const next = reducers.setFilters(state, { status: 'running', search: 'lab' });
            expect(next.filters.status).toBe('running');
            expect(next.filters.search).toBe('lab');
            expect(next.filters.include_terminal).toBe(false); // default unchanged
        });

        it('should clear all filters', () => {
            state = reducers.setFilters(state, { status: 'running', search: 'test' });
            const next = reducers.clearFilters(state);
            expect(next.filters.status).toBeNull();
            expect(next.filters.search).toBe('');
        });
    });
});

// ==============================================================================
// Selector Tests
// ==============================================================================

describe('sessionsSlice selectors', () => {
    let state;

    beforeEach(() => {
        const s1 = makeSession({ id: 's1', status: 'running' });
        const s2 = makeSession({ id: 's2', status: 'ready' });
        const s3 = makeSession({ id: 's3', status: 'terminated' });
        const s4 = makeSession({ id: 's4', status: 'grading' });
        const s5 = makeSession({ id: 's5', status: 'error' });

        state = wrapState({
            ...initialState,
            byId: { s1, s2, s3, s4, s5 },
            allIds: ['s1', 's2', 's3', 's4', 's5'],
            activeId: 's2',
            activeDetail: { id: 's2', runs: [] },
            loading: { list: false, detail: false },
            errors: {},
            filters: { ...initialState.filters },
        });
    });

    describe('selectAllSessions', () => {
        it('should return all sessions as array', () => {
            expect(selectAllSessions(state)).toHaveLength(5);
        });

        it('should return empty array for missing slice', () => {
            expect(selectAllSessions({})).toEqual([]);
        });
    });

    describe('selectSessionById', () => {
        it('should return session by ID', () => {
            const session = selectSessionById(state, 's1');
            expect(session.id).toBe('s1');
        });

        it('should return null for unknown ID', () => {
            expect(selectSessionById(state, 'unknown')).toBeNull();
        });
    });

    describe('selectActiveSession', () => {
        it('should return the active session', () => {
            const session = selectActiveSession(state);
            expect(session.id).toBe('s2');
        });

        it('should return null if no active session', () => {
            state.sessions.activeId = null;
            expect(selectActiveSession(state)).toBeNull();
        });
    });

    describe('selectActiveSessionDetail', () => {
        it('should return active detail', () => {
            const detail = selectActiveSessionDetail(state);
            expect(detail.id).toBe('s2');
        });
    });

    describe('selectSessionsListLoading', () => {
        it('should return false by default', () => {
            expect(selectSessionsListLoading(state)).toBe(false);
        });
    });

    describe('selectSessionDetailLoading', () => {
        it('should return false by default', () => {
            expect(selectSessionDetailLoading(state)).toBe(false);
        });
    });

    describe('selectSessionFilters', () => {
        it('should return current filters', () => {
            const filters = selectSessionFilters(state);
            expect(filters.status).toBeNull();
            expect(filters.include_terminal).toBe(false);
        });
    });

    describe('selectSessionsCount', () => {
        it('should return total count', () => {
            expect(selectSessionsCount(state)).toBe(5);
        });
    });

    describe('selectSessionsByStatus', () => {
        it('should filter by status', () => {
            const running = selectSessionsByStatus(state, 'running');
            expect(running).toHaveLength(1);
            expect(running[0].id).toBe('s1');
        });
    });

    describe('selectSessionStatusSummary', () => {
        it('should compute status summary', () => {
            const summary = selectSessionStatusSummary(state);
            expect(summary.total).toBe(5);
            expect(summary.running).toBe(1);
            expect(summary.ready).toBe(1);
            expect(summary.terminated).toBe(1);
            expect(summary.grading).toBe(1);
            expect(summary.error).toBe(1);
        });

        it('should count non-terminal sessions as active', () => {
            const summary = selectSessionStatusSummary(state);
            // terminated is terminal; running, ready, grading, error are not
            expect(summary.active).toBe(4);
        });

        it('should return zeroes for empty state', () => {
            const summary = selectSessionStatusSummary({});
            expect(summary.total).toBe(0);
        });
    });
});
