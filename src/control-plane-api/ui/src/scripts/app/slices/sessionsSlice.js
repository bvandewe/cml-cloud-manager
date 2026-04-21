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
import * as labletSessionsApi from '../../api/lablet-sessions.js';

const SESSION_LOGICAL_TIMESTAMP_FIELDS = [
    'updated_at',
    'instantiation_failed_at',
    'instantiation_completed_at',
    'instantiation_started_at',
    'scheduled_at',
    'ready_at',
    'started_at',
    'running_at',
    'collecting_at',
    'grading_at',
    'stopped_at',
    'terminated_at',
    'archived_at',
    'expired_at',
    'scored_at',
    'extended_at',
    'created_at',
];

function toTimestamp(value) {
    if (!value) return 0;
    const normalizedValue = typeof value === 'string' ? value.replace(/([+-]\d{2}:\d{2})Z$/, '$1') : value;
    const parsed = new Date(normalizedValue).getTime();
    return Number.isFinite(parsed) ? parsed : 0;
}

function getLogicalSessionTimestamp(session) {
    if (!session || typeof session !== 'object') return null;

    for (const field of SESSION_LOGICAL_TIMESTAMP_FIELDS) {
        if (session[field]) {
            return session[field];
        }
    }

    return null;
}

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
         * Upsert a single session (create or merge).
         * Stamps _sseUpdatedAt so merge-based refreshes can detect
         * SSE-driven updates that should not be overwritten by stale HTTP data.
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

            const incomingLogicalTimestamp = getLogicalSessionTimestamp(session);
            const currentLogicalTimestamp = merged.updated_at || getLogicalSessionTimestamp(existing) || existing._sseUpdatedAt;

            if (incomingLogicalTimestamp && toTimestamp(incomingLogicalTimestamp) >= toTimestamp(currentLogicalTimestamp)) {
                merged.updated_at = incomingLogicalTimestamp;
            }

            // Stamp using the best domain/logical timestamp available so follow-up
            // backend refreshes are not incorrectly treated as stale just because the
            // SSE event arrived slightly later on the client.
            merged._sseUpdatedAt = incomingLogicalTimestamp || merged.updated_at || existing._sseUpdatedAt || new Date().toISOString();

            return {
                ...state,
                byId: { ...state.byId, [session.id]: merged },
                allIds: isNew ? [...state.allIds, session.id] : state.allIds,
            };
        },

        /**
         * Replace all sessions (full refresh).
         * @deprecated Prefer mergeAll to avoid overwriting SSE-driven updates.
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
         * Merge sessions from an HTTP refresh without overwriting newer
         * SSE-driven updates (AD-SSE-RACE-001).
         *
         * For each incoming session:
         * - If the session doesn't exist locally → add it.
         * - If the session exists but has no recent SSE update → overwrite.
         * - If the session exists AND has a recent SSE update → merge,
         *   but keep SSE-driven status/pipeline fields if the HTTP data
         *   has an older or equal updated_at timestamp.
         */
        mergeAll(state, sessions) {
            if (!Array.isArray(sessions)) return state;

            const byId = { ...state.byId };
            const existingIds = new Set(state.allIds);
            const incomingIds = new Set();

            sessions.forEach(s => {
                if (!s || !s.id) return;
                incomingIds.add(s.id);

                const existing = byId[s.id];
                if (!existing) {
                    // New session from server — add directly
                    byId[s.id] = s;
                } else if (!existing._sseUpdatedAt) {
                    // No SSE update since last refresh — safe to overwrite
                    byId[s.id] = s;
                } else {
                    // SSE-driven fields present — merge carefully.
                    // Keep SSE-driven status if it's newer than the HTTP data.
                    const sseTime = toTimestamp(existing._sseUpdatedAt);
                    const httpTime = toTimestamp(s.updated_at);

                    if (httpTime >= sseTime) {
                        // HTTP data is newer or equal — full overwrite
                        byId[s.id] = s;
                    } else {
                        // SSE data is newer — merge HTTP fields underneath,
                        // but preserve SSE-driven status, pipeline_progress,
                        // worker_id, desired_status.
                        const sseProtectedFields = ['status', 'pipeline_progress', 'worker_id', 'desired_status', '_sseUpdatedAt'];
                        const merged = { ...s };
                        sseProtectedFields.forEach(field => {
                            if (existing[field] !== undefined) {
                                merged[field] = existing[field];
                            }
                        });
                        byId[s.id] = merged;
                    }
                }
            });

            // Build allIds: incoming order, plus any existing IDs not in the
            // incoming set (sessions that SSE added but HTTP hasn't seen yet)
            const allIds = [...incomingIds];
            state.allIds.forEach(id => {
                if (!incomingIds.has(id) && byId[id]) {
                    allIds.push(id);
                }
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

/**
 * Compute session status summary.
 *
 * Aligned with canonical LabletSessionStatus enum (12 states):
 * pending, scheduled, instantiating, ready, running, collecting,
 * grading, stopping, stopped, archived, terminated, expired
 */
export function selectSessionStatusSummary(state) {
    const sessions = selectAllSessions(state);
    const summary = {
        total: sessions.length,
        pending: 0,
        scheduled: 0,
        instantiating: 0,
        ready: 0,
        running: 0,
        collecting: 0,
        grading: 0,
        stopping: 0,
        stopped: 0,
        archived: 0,
        terminated: 0,
        expired: 0,
        active: 0,
    };

    const terminalStatuses = new Set(['terminated', 'archived', 'expired']);

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
        async loadSessions(filters = {}, options = {}) {
            store.dispatch('sessions', 'setListLoading', true);
            try {
                const sessions = await sessionsApi.listSessions(filters);
                const data = Array.isArray(sessions) ? sessions : sessions.items || sessions.data || [];
                // Default to merge-based refreshes so partial SSE updates are not
                // immediately clobbered by slightly older HTTP reads. Manual refreshes
                // can opt into replace mode to force a full backend reload.
                store.dispatch('sessions', options.replace ? 'replaceAll' : 'mergeAll', data);
                eventBus.emit(LcmEventTypes.SESSIONS_REFRESH_COMPLETED, { count: data.length });
                return data;
            } catch (error) {
                console.error('[sessionsSlice] Failed to load sessions:', error);
                store.dispatch('sessions', 'setError', { key: '_list', error: error.message });
                return [];
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

        /**
         * Requeue a session for reconciliation
         */
        async requeueSession(sessionId, reason = null) {
            try {
                await labletSessionsApi.requeueLabletSession(sessionId, reason);
                await this.loadSessions();
            } catch (error) {
                console.error('[sessionsSlice] Failed to requeue session:', error);
                throw error;
            }
        },

        /**
         * Terminate a session
         */
        async terminateSession(sessionId, reason = null) {
            try {
                await labletSessionsApi.terminateLabletSession(sessionId, reason);
                store.dispatch('sessions', 'removeSession', sessionId);
            } catch (error) {
                console.error('[sessionsSlice] Failed to terminate session:', error);
                throw error;
            }
        },

        /**
         * Bulk requeue sessions for reconciliation
         */
        async bulkRequeue(sessionIds, reason = null) {
            try {
                const result = await labletSessionsApi.bulkRequeueLabletSessions(sessionIds, reason);
                await this.loadSessions();
                return result;
            } catch (error) {
                console.error('[sessionsSlice] Failed to bulk requeue sessions:', error);
                throw error;
            }
        },

        /**
         * Request resource observation for a RUNNING session (ADR-030)
         */
        async observeResources(sessionId) {
            try {
                return await labletSessionsApi.requestResourceObservation(sessionId);
            } catch (error) {
                console.error('[sessionsSlice] Failed to observe resources:', error);
                throw error;
            }
        },

        /**
         * Clear all filters and reload
         */
        clearFilters() {
            store.dispatch('sessions', 'clearFilters');
        },
    };
}

export default sessionsSlice;
