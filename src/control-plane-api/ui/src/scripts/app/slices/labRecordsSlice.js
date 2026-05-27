/**
 * Lab Records Slice — Phase 10 (P10-4)
 *
 * State management for LabRecord entities.
 * Uses the StateStore slice pattern from @neuroglia/ui-core.
 *
 * Provides:
 * - CRUD state for lab records (byId, allIds)
 * - Loading/error states
 * - Filter state (worker, status, bound)
 * - Stats counters by status group
 * - Selectors for efficient component access
 * - Action creators for API-backed operations
 *
 * @module app/slices/labRecordsSlice
 */

import { eventBus, LcmEventTypes } from '../eventBus.js';
import * as labRecordsApi from '../../api/lab-records.js';

// ==============================================================================
// Initial State
// ==============================================================================

const initialState = {
    /** Map of lab record ID to lab record object */
    byId: {},
    /** Ordered list of lab record IDs */
    allIds: [],
    /** Currently selected lab record ID */
    activeId: null,
    /** Loading states */
    loading: {
        list: false,
        details: {},
    },
    /** Error states */
    errors: {},
    /** Last refresh timestamp */
    lastRefreshedAt: null,
    /** Active filters */
    filters: {
        worker_id: null,
        status: null,
        bound: null,
        include_terminal: false,
        search: '',
    },
};

// ==============================================================================
// Slice Definition
// ==============================================================================

export const labRecordsSlice = {
    name: 'labRecords',
    initialState,

    reducers: {
        /**
         * Set the active/selected lab record
         */
        setActiveLabRecord(state, labRecordId) {
            return { ...state, activeId: labRecordId };
        },

        /**
         * Upsert a single lab record (create or merge)
         */
        upsertLabRecord(state, labRecord) {
            if (!labRecord || !labRecord.id) return state;

            const isNew = !state.byId[labRecord.id];
            const existing = state.byId[labRecord.id] || {};

            // Merge: allow null to overwrite, skip undefined
            const merged = { ...existing };
            Object.entries(labRecord).forEach(([key, value]) => {
                if (value !== undefined) {
                    merged[key] = value;
                }
            });

            return {
                ...state,
                byId: { ...state.byId, [labRecord.id]: merged },
                allIds: isNew ? [...state.allIds, labRecord.id] : state.allIds,
            };
        },

        /**
         * Upsert multiple lab records (bulk list load)
         */
        upsertLabRecords(state, labRecords) {
            if (!Array.isArray(labRecords)) return state;

            const newById = { ...state.byId };
            const newAllIds = [...state.allIds];

            labRecords.forEach(lr => {
                if (!lr || !lr.id) return;
                const isNew = !newById[lr.id];
                newById[lr.id] = { ...(newById[lr.id] || {}), ...lr };
                if (isNew) newAllIds.push(lr.id);
            });

            return {
                ...state,
                byId: newById,
                allIds: newAllIds,
                lastRefreshedAt: new Date().toISOString(),
            };
        },

        /**
         * Update lab record status
         */
        updateStatus(state, { labRecordId, status, updatedAt }) {
            if (!labRecordId || !state.byId[labRecordId]) return state;

            const existing = state.byId[labRecordId];
            return {
                ...state,
                byId: {
                    ...state.byId,
                    [labRecordId]: {
                        ...existing,
                        status,
                        updated_at: updatedAt || new Date().toISOString(),
                    },
                },
            };
        },

        /**
         * Remove a lab record from state
         */
        removeLabRecord(state, labRecordId) {
            if (!labRecordId) return state;

            const { [labRecordId]: _removed, ...restById } = state.byId;
            return {
                ...state,
                byId: restById,
                allIds: state.allIds.filter(id => id !== labRecordId),
                activeId: state.activeId === labRecordId ? null : state.activeId,
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
         * Set detail loading state for a specific lab record
         */
        setDetailLoading(state, { labRecordId, loading }) {
            return {
                ...state,
                loading: {
                    ...state.loading,
                    details: { ...state.loading.details, [labRecordId]: loading },
                },
            };
        },

        /**
         * Set error for a lab record
         */
        setError(state, { labRecordId, error }) {
            return {
                ...state,
                errors: { ...state.errors, [labRecordId]: error },
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

        /**
         * Replace all lab records (full refresh)
         */
        replaceAll(state, labRecords) {
            if (!Array.isArray(labRecords)) return state;

            const byId = {};
            const allIds = [];

            labRecords.forEach(lr => {
                if (!lr || !lr.id) return;
                byId[lr.id] = lr;
                allIds.push(lr.id);
            });

            return {
                ...state,
                byId,
                allIds,
                lastRefreshedAt: new Date().toISOString(),
            };
        },

        /**
         * Set pending action on a lab record (AD-023).
         * Called when LAB_RECORD_ACTION_QUEUED SSE event is received.
         * @param {object} payload - { labRecordId, action, requested_at }
         */
        setPendingAction(state, { labRecordId, action, requested_at }) {
            if (!labRecordId || !state.byId[labRecordId]) return state;

            const existing = state.byId[labRecordId];
            return {
                ...state,
                byId: {
                    ...state.byId,
                    [labRecordId]: {
                        ...existing,
                        pending_action: action,
                        pending_action_requested_at: requested_at || new Date().toISOString(),
                    },
                },
            };
        },

        /**
         * Clear pending action from a lab record (AD-023).
         * Called when LAB_RECORD_ACTION_COMPLETED or LAB_RECORD_ACTION_FAILED SSE event is received.
         * @param {string} labRecordId - The lab record ID
         */
        clearPendingAction(state, labRecordId) {
            if (!labRecordId || !state.byId[labRecordId]) return state;

            const existing = state.byId[labRecordId];
            return {
                ...state,
                byId: {
                    ...state.byId,
                    [labRecordId]: {
                        ...existing,
                        pending_action: null,
                        pending_action_requested_at: null,
                    },
                },
            };
        },

        /**
         * Update node-level state for a lab (ADR-041: WebSocket state_change events).
         * Finds lab by cml_lab_id and merges node/link state data.
         * @param {object} payload - { lab_id, worker_id, element_type, element_id, event, data }
         */
        updateLabNodeState(state, { lab_id, worker_id, element_type, element_id, event, data }) {
            if (!lab_id) return state;

            // Find lab record by cml_lab_id
            const labRecordId = state.allIds.find(id => state.byId[id]?.cml_lab_id === lab_id);
            if (!labRecordId) return state;

            const existing = state.byId[labRecordId];
            const nodeStates = { ...(existing.node_states || {}) };

            // Key by element_type:element_id (e.g. "node:n0", "link:l0")
            const key = `${element_type || 'node'}:${element_id || 'unknown'}`;
            nodeStates[key] = {
                state: event,
                ...(data || {}),
                updated_at: new Date().toISOString(),
            };

            return {
                ...state,
                byId: {
                    ...state.byId,
                    [labRecordId]: {
                        ...existing,
                        node_states: nodeStates,
                        last_ws_update_at: new Date().toISOString(),
                    },
                },
            };
        },

        /**
         * Update per-lab resource statistics (ADR-041: WebSocket lab_stats events).
         * Finds lab by cml_lab_id and merges node/link metrics.
         * @param {object} payload - { lab_id, worker_id, nodes, links, ... }
         */
        updateLabStats(state, { lab_id, worker_id, nodes, links, ...rest }) {
            if (!lab_id) return state;

            // Find lab record by cml_lab_id
            const labRecordId = state.allIds.find(id => state.byId[id]?.cml_lab_id === lab_id);
            if (!labRecordId) return state;

            const existing = state.byId[labRecordId];

            return {
                ...state,
                byId: {
                    ...state.byId,
                    [labRecordId]: {
                        ...existing,
                        lab_stats: {
                            nodes: nodes ?? existing.lab_stats?.nodes,
                            links: links ?? existing.lab_stats?.links,
                            ...rest,
                        },
                        last_ws_update_at: new Date().toISOString(),
                    },
                },
            };
        },
    },
};

// ==============================================================================
// Selectors
// ==============================================================================

/** Select all lab records as array */
export function selectAllLabRecords(state) {
    const slice = state.labRecords || initialState;
    return slice.allIds.map(id => slice.byId[id]).filter(Boolean);
}

/** Select a lab record by ID */
export function selectLabRecordById(state, id) {
    return state.labRecords?.byId?.[id] || null;
}

/** Select the active/selected lab record */
export function selectActiveLabRecord(state) {
    const slice = state.labRecords || initialState;
    return slice.activeId ? slice.byId[slice.activeId] || null : null;
}

/** Select list loading state */
export function selectIsListLoading(state) {
    return state.labRecords?.loading?.list || false;
}

/** Select detail loading state for a lab record */
export function selectIsDetailLoading(state, labRecordId) {
    return state.labRecords?.loading?.details?.[labRecordId] || false;
}

/** Select error for a lab record */
export function selectLabRecordError(state, labRecordId) {
    return state.labRecords?.errors?.[labRecordId] || null;
}

/** Select current filters */
export function selectFilters(state) {
    return state.labRecords?.filters || initialState.filters;
}

/** Select lab records count */
export function selectLabRecordsCount(state) {
    return state.labRecords?.allIds?.length || 0;
}

/** Select lab records filtered by worker ID */
export function selectLabRecordsByWorker(state, workerId) {
    return selectAllLabRecords(state).filter(lr => lr.worker_id === workerId);
}

/** Select lab records filtered by status */
export function selectLabRecordsByStatus(state, status) {
    return selectAllLabRecords(state).filter(lr => lr.status === status);
}

/** Compute status summary counts */
export function selectStatusSummary(state) {
    const records = selectAllLabRecords(state);
    const summary = {
        total: records.length,
        defined: 0,
        discovered: 0,
        importing: 0,
        imported: 0,
        booting: 0,
        booted: 0,
        converging: 0,
        converged: 0,
        stopping: 0,
        stopped: 0,
        wiping: 0,
        wiped: 0,
        deleting: 0,
        deleted: 0,
        archived: 0,
        error: 0,
        // Groups
        running: 0, // booted + converging + converged
        active: 0, // all non-terminal
    };

    const terminalStatuses = new Set(['deleted', 'archived']);

    records.forEach(lr => {
        const s = lr.status?.toLowerCase();
        if (s && s in summary) {
            summary[s]++;
        } else {
            summary.error++;
        }

        // Running group
        if (['booted', 'converging', 'converged'].includes(s)) {
            summary.running++;
        }

        // Active (non-terminal)
        if (!terminalStatuses.has(s)) {
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
export function createLabRecordsActions(store) {
    return {
        /**
         * Load all lab records from API
         */
        async loadLabRecords(filters = {}) {
            store.dispatch('labRecords', 'setListLoading', true);
            try {
                const records = await labRecordsApi.listLabRecords(filters);
                const data = Array.isArray(records) ? records : records.items || records.data || [];
                store.dispatch('labRecords', 'replaceAll', data);
                eventBus.emit(LcmEventTypes.LAB_RECORDS_REFRESH_COMPLETED, { count: data.length });
            } catch (error) {
                console.error('[labRecordsSlice] Failed to load lab records:', error);
                store.dispatch('labRecords', 'setError', { labRecordId: '_list', error: error.message });
            } finally {
                store.dispatch('labRecords', 'setListLoading', false);
            }
        },

        /**
         * Load a single lab record detail
         */
        async loadLabRecordDetail(labRecordId) {
            store.dispatch('labRecords', 'setDetailLoading', { labRecordId, loading: true });
            try {
                const detail = await labRecordsApi.getLabRecord(labRecordId);
                store.dispatch('labRecords', 'upsertLabRecord', detail);
                return detail;
            } catch (error) {
                console.error('[labRecordsSlice] Failed to load lab record detail:', error);
                store.dispatch('labRecords', 'setError', { labRecordId, error: error.message });
                return null;
            } finally {
                store.dispatch('labRecords', 'setDetailLoading', { labRecordId, loading: false });
            }
        },

        /**
         * Start a lab record
         */
        async startLabRecord(labRecordId) {
            try {
                const result = await labRecordsApi.startLabRecord(labRecordId);
                eventBus.emit(LcmEventTypes.LAB_RECORD_ACTION_QUEUED, {
                    lab_record_id: labRecordId,
                    action: 'start',
                    result,
                });
                return result;
            } catch (error) {
                console.error('[labRecordsSlice] Failed to start lab record:', error);
                throw error;
            }
        },

        /**
         * Stop a lab record
         */
        async stopLabRecord(labRecordId) {
            try {
                const result = await labRecordsApi.stopLabRecord(labRecordId);
                eventBus.emit(LcmEventTypes.LAB_RECORD_ACTION_QUEUED, {
                    lab_record_id: labRecordId,
                    action: 'stop',
                    result,
                });
                return result;
            } catch (error) {
                console.error('[labRecordsSlice] Failed to stop lab record:', error);
                throw error;
            }
        },

        /**
         * Wipe a lab record
         */
        async wipeLabRecord(labRecordId) {
            try {
                const result = await labRecordsApi.wipeLabRecord(labRecordId);
                eventBus.emit(LcmEventTypes.LAB_RECORD_ACTION_QUEUED, {
                    lab_record_id: labRecordId,
                    action: 'wipe',
                    result,
                });
                return result;
            } catch (error) {
                console.error('[labRecordsSlice] Failed to wipe lab record:', error);
                throw error;
            }
        },

        /**
         * Delete a lab record
         */
        async deleteLabRecord(labRecordId) {
            try {
                const result = await labRecordsApi.deleteLabRecord(labRecordId);
                eventBus.emit(LcmEventTypes.LAB_RECORD_ACTION_QUEUED, {
                    lab_record_id: labRecordId,
                    action: 'delete',
                    result,
                });
                return result;
            } catch (error) {
                console.error('[labRecordsSlice] Failed to delete lab record:', error);
                throw error;
            }
        },

        /**
         * Set the active lab record
         */
        setActiveLabRecord(labRecordId) {
            store.dispatch('labRecords', 'setActiveLabRecord', labRecordId);
        },

        /**
         * Update filters and reload
         */
        async setFiltersAndReload(filters) {
            store.dispatch('labRecords', 'setFilters', filters);
            const currentFilters = store.getSlice('labRecords')?.filters || {};
            await this.loadLabRecords(currentFilters);
        },
    };
}

export default labRecordsSlice;
