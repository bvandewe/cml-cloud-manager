/**
 * Sessions Slice — Phase 7 (migrated from Phase 11)
 *
 * State management for LabletSession entities.
 * LabletSessions are the unified aggregate replacing the old
 * LabletInstance + LabletRecordRun composition.
 *
 * Provides:
 * - CRUD state for sessions (byId, allIds)
 * - Loading/error states
 * - Filter state (status, definition, owner)
 * - Active session detail
 * - Selectors for efficient component access
 * - Action creators for API-backed operations
 *
 * @module app/slices/sessionsSlice
 */

import { eventBus, LcmEventTypes } from '../eventBus.js';
import * as sessionsApi from '../../api/sessions.js';

// ==============================================================================
// Initial State
// ==============================================================================

const initialState = {
    /** Map of session (lablet instance) ID to session object */
    byId: {},
    /** Ordered list of session IDs */
    allIds: [],
    /** Currently selected session ID */
    activeId: null,
    /** Active session detail (instance + runs) */
    activeDetail: null,
    /** Loading states */
    loading: {
        list: false,
        detail: false,
    },
    /** Error states */
    errors: {},
    /** Last refresh timestamp */
    lastRefreshedAt: null,
    /** Active filters */
    filters: {
        status: null,
        definition_id: null,
        owner_id: null,
        include_terminal: false,
        search: '',
    },
};

// ==============================================================================
// Slice Definition
// ==============================================================================

export const sessionsSlice = {
    name: 'sessions',
    initialState,

    reducers: {
        /**
         * Set the active/selected session
         */
        setActiveSession(state, sessionId) {
            return { ...state, activeId: sessionId };
        },

        /**
         * Set the active session detail (instance + runs)
         */
        setActiveDetail(state, detail) {
            return { ...state, activeDetail: detail };
        },

        /**
         * Upsert a single session (create or merge)
         */
        upsertSession(state, session) {
            if (!session || !session.id) return state;

            const isNew = !state.byId[session.id];
            const existing = state.byId[session.id] || {};

            const merged = { ...existing };
            Object.entries(session).forEach(([key, value]) => {
                if (value !== undefined) {
                    merged[key] = value;
                }
            });

            return {
                ...state,
                byId: { ...state.byId, [session.id]: merged },
                allIds: isNew ? [...state.allIds, session.id] : state.allIds,
            };
        },

        /**
         * Replace all sessions (full refresh)
         */
        replaceAll(state, sessions) {
            if (!Array.isArray(sessions)) return state;

            const byId = {};
            const allIds = [];

            sessions.forEach(s => {
                if (!s || !s.id) return;
                byId[s.id] = s;
                allIds.push(s.id);
            });

            return {
                ...state,
                byId,
                allIds,
                lastRefreshedAt: new Date().toISOString(),
            };
        },

        /**
         * Remove a session from state
         */
        removeSession(state, sessionId) {
            if (!sessionId) return state;

            const { [sessionId]: _removed, ...restById } = state.byId;
            return {
                ...state,
                byId: restById,
                allIds: state.allIds.filter(id => id !== sessionId),
                activeId: state.activeId === sessionId ? null : state.activeId,
            };
        },

        /**
         * Set list loading state
         */
        setListLoading(state, loading) {
            return {
                ...state,
                loading: { ...state.loading, list: loading },
            };
        },

        /**
         * Set detail loading state
         */
        setDetailLoading(state, loading) {
            return {
                ...state,
                loading: { ...state.loading, detail: loading },
            };
        },

        /**
         * Set error
         */
        setError(state, { key, error }) {
            return {
                ...state,
                errors: { ...state.errors, [key]: error },
            };
        },

        /**
         * Update filters
         */
        setFilters(state, filters) {
            return {
                ...state,
                filters: { ...state.filters, ...filters },
            };
        },

        /**
         * Clear all filters
         */
        clearFilters(state) {
            return {
                ...state,
                filters: { ...initialState.filters },
            };
        },
    },
};

// ==============================================================================
// Selectors
// ==============================================================================

/** Select all sessions as array */
export function selectAllSessions(state) {
    const slice = state.sessions || initialState;
    return slice.allIds.map(id => slice.byId[id]).filter(Boolean);
}

/** Select a session by ID */
export function selectSessionById(state, id) {
    return state.sessions?.byId?.[id] || null;
}

/** Select the active session */
export function selectActiveSession(state) {
    const slice = state.sessions || initialState;
    return slice.activeId ? slice.byId[slice.activeId] || null : null;
}

/** Select the active session detail (with runs) */
export function selectActiveSessionDetail(state) {
    return state.sessions?.activeDetail || null;
}

/** Select list loading state */
export function selectSessionsListLoading(state) {
    return state.sessions?.loading?.list || false;
}

/** Select detail loading state */
export function selectSessionDetailLoading(state) {
    return state.sessions?.loading?.detail || false;
}

/** Select current filters */
export function selectSessionFilters(state) {
    return state.sessions?.filters || initialState.filters;
}

/** Select sessions count */
export function selectSessionsCount(state) {
    return state.sessions?.allIds?.length || 0;
}

/** Select sessions by status */
export function selectSessionsByStatus(state, status) {
    return selectAllSessions(state).filter(s => s.status === status);
}

/** Compute session status summary */
export function selectSessionStatusSummary(state) {
    const sessions = selectAllSessions(state);
    const summary = {
        total: sessions.length,
        scheduled: 0,
        instantiating: 0,
        running: 0,
        ready: 0,
        collecting: 0,
        grading: 0,
        graded: 0,
        terminated: 0,
        error: 0,
        active: 0,
    };

    const terminalStatuses = new Set(['terminated', 'archived', 'deleted']);

    sessions.forEach(s => {
        const st = s.status?.toLowerCase();
        if (st && st in summary) {
            summary[st]++;
        }
        if (!terminalStatuses.has(st)) {
            summary.active++;
        }
    });

    return summary;
}

// ==============================================================================
// Action Creators (API-backed operations)
// ==============================================================================

/**
 * Create action creators bound to a store instance
 * @param {Object} store - The StateStore instance
 * @returns {Object} Action creators
 */
export function createSessionsActions(store) {
    return {
        /**
         * Load all sessions from API
         */
        async loadSessions(filters = {}) {
            store.dispatch('sessions', 'setListLoading', true);
            try {
                const sessions = await sessionsApi.listSessions(filters);
                const data = Array.isArray(sessions) ? sessions : sessions.items || sessions.data || [];
                store.dispatch('sessions', 'replaceAll', data);
                eventBus.emit(LcmEventTypes.SESSIONS_REFRESH_COMPLETED, { count: data.length });
            } catch (error) {
                console.error('[sessionsSlice] Failed to load sessions:', error);
                store.dispatch('sessions', 'setError', { key: '_list', error: error.message });
            } finally {
                store.dispatch('sessions', 'setListLoading', false);
            }
        },

        /**
         * Load a session detail (instance + runs)
         */
        async loadSessionDetail(sessionId) {
            store.dispatch('sessions', 'setDetailLoading', true);
            try {
                const detail = await sessionsApi.getSessionDetail(sessionId);
                store.dispatch('sessions', 'setActiveDetail', detail);
                store.dispatch('sessions', 'upsertSession', detail);
                return detail;
            } catch (error) {
                console.error('[sessionsSlice] Failed to load session detail:', error);
                store.dispatch('sessions', 'setError', { key: sessionId, error: error.message });
                return null;
            } finally {
                store.dispatch('sessions', 'setDetailLoading', false);
            }
        },

        /**
         * Set the active session
         */
        setActiveSession(sessionId) {
            store.dispatch('sessions', 'setActiveSession', sessionId);
        },

        /**
         * Update filters and reload
         */
        async setFiltersAndReload(filters) {
            store.dispatch('sessions', 'setFilters', filters);
            const currentFilters = store.getSlice('sessions')?.filters || {};
            await this.loadSessions(currentFilters);
        },
    };
}

export default sessionsSlice;
