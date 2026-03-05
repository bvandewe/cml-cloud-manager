/**
 * Workers Slice
 *
 * State management for CML workers, migrated from the legacy workerStore.js.
 * Uses the StateStore slice pattern from @neuroglia/ui-core.
 */

import { eventBus, LcmEventTypes } from '../eventBus.js';

/**
 * Initial state for workers slice
 */
const initialState = {
    /** Map of worker ID to worker object */
    byId: {},
    /** Ordered list of worker IDs */
    allIds: [],
    /** Currently active/selected worker ID */
    activeId: null,
    /** Timing metadata by worker ID */
    timing: {},
    /** Loading states */
    loading: {
        list: false,
        details: {},
    },
    /** Error states */
    errors: {},
    /** Last refresh timestamp */
    lastRefreshedAt: null,
};

/**
 * Workers slice definition
 */
export const workersSlice = {
    name: 'workers',
    initialState,

    /**
     * Reducers - pure functions that update state
     */
    reducers: {
        /**
         * Set the active worker
         */
        setActiveWorker(state, workerId) {
            return {
                ...state,
                activeId: workerId,
            };
        },

        /**
         * Upsert a worker (create or update)
         */
        upsertWorker(state, worker) {
            if (!worker || !worker.id) return state;

            const isNew = !state.byId[worker.id];
            const existing = state.byId[worker.id] || {};

            // Merge worker data (allow null to overwrite, skip undefined)
            const merged = { ...existing };
            Object.entries(worker).forEach(([key, value]) => {
                if (value !== undefined) {
                    merged[key] = value;
                }
            });

            const newById = {
                ...state.byId,
                [worker.id]: merged,
            };

            const newAllIds = isNew ? [...state.allIds, worker.id] : state.allIds;

            return {
                ...state,
                byId: newById,
                allIds: newAllIds,
            };
        },

        /**
         * Update worker metrics
         */
        updateMetrics(state, { workerId, metrics }) {
            if (!workerId || !state.byId[workerId]) return state;

            const existing = state.byId[workerId];
            const updated = { ...existing, ...metrics };

            return {
                ...state,
                byId: {
                    ...state.byId,
                    [workerId]: updated,
                },
            };
        },

        /**
         * Update worker status
         */
        updateStatus(state, { workerId, status, updatedAt }) {
            if (!workerId || !state.byId[workerId]) return state;

            const existing = state.byId[workerId];
            const updated = {
                ...existing,
                status,
                updated_at: updatedAt || new Date().toISOString(),
            };

            return {
                ...state,
                byId: {
                    ...state.byId,
                    [workerId]: updated,
                },
            };
        },

        /**
         * Remove a worker
         */
        removeWorker(state, workerId) {
            if (!workerId) return state;

            const { [workerId]: removed, ...restById } = state.byId;
            const { [workerId]: removedTiming, ...restTiming } = state.timing;

            return {
                ...state,
                byId: restById,
                allIds: state.allIds.filter(id => id !== workerId),
                timing: restTiming,
                activeId: state.activeId === workerId ? null : state.activeId,
            };
        },

        /**
         * Update timing metadata for a worker
         */
        updateTiming(state, { workerId, timing }) {
            if (!workerId) return state;

            return {
                ...state,
                timing: {
                    ...state.timing,
                    [workerId]: {
                        pollInterval: timing.poll_interval,
                        nextRefreshAt: timing.next_refresh_at,
                        lastRefreshedAt: timing.last_refreshed_at,
                        updatedAt: new Date().toISOString(),
                    },
                },
            };
        },

        /**
         * Set loading state
         */
        setLoading(state, { key, workerId, loading }) {
            if (workerId) {
                return {
                    ...state,
                    loading: {
                        ...state.loading,
                        [key]: {
                            ...state.loading[key],
                            [workerId]: loading,
                        },
                    },
                };
            }
            return {
                ...state,
                loading: {
                    ...state.loading,
                    [key]: loading,
                },
            };
        },

        /**
         * Set error state
         */
        setError(state, { workerId, error }) {
            if (!workerId) return state;

            return {
                ...state,
                errors: {
                    ...state.errors,
                    [workerId]: error,
                },
            };
        },

        /**
         * Clear all errors
         */
        clearErrors(state) {
            return {
                ...state,
                errors: {},
            };
        },

        /**
         * Set last refresh timestamp
         */
        setLastRefreshed(state, timestamp) {
            return {
                ...state,
                lastRefreshedAt: timestamp || new Date().toISOString(),
            };
        },

        /**
         * Reset state to initial
         */
        reset() {
            return initialState;
        },
    },
};

// ============================================================================
// Selectors
// ============================================================================

/**
 * Get all workers as an array
 */
export function selectAllWorkers(state) {
    const workers = state.workers;
    if (!workers) return [];
    return workers.allIds.map(id => workers.byId[id]).filter(Boolean);
}

/**
 * Get a worker by ID
 */
export function selectWorkerById(state, workerId) {
    return state.workers?.byId?.[workerId] || null;
}

/**
 * Get the active worker
 */
export function selectActiveWorker(state) {
    const workers = state.workers;
    if (!workers?.activeId) return null;
    return workers.byId[workers.activeId] || null;
}

/**
 * Get worker timing info
 */
export function selectWorkerTiming(state, workerId) {
    return state.workers?.timing?.[workerId] || null;
}

/**
 * Check if worker list is loading
 */
export function selectIsListLoading(state) {
    return state.workers?.loading?.list || false;
}

/**
 * Check if a specific worker is loading
 */
export function selectIsWorkerLoading(state, workerId) {
    return state.workers?.loading?.details?.[workerId] || false;
}

/**
 * Get worker error
 */
export function selectWorkerError(state, workerId) {
    return state.workers?.errors?.[workerId] || null;
}

/**
 * Get workers count
 */
export function selectWorkersCount(state) {
    return state.workers?.allIds?.length || 0;
}

/**
 * Get workers by status
 */
export function selectWorkersByStatus(state, status) {
    return selectAllWorkers(state).filter(w => w.status === status);
}

// ============================================================================
// Actions (thunks that dispatch reducers and emit events)
// ============================================================================

/**
 * Create action creators bound to a store instance
 */
export function createWorkersActions(store) {
    return {
        /**
         * Set the active worker and emit event
         */
        setActiveWorker(workerId) {
            store.dispatch('workers', 'setActiveWorker', workerId);
            eventBus.emit(LcmEventTypes.WORKER_ACTIVE_CHANGED, { worker_id: workerId });
        },

        /**
         * Upsert a worker snapshot and emit appropriate events
         */
        upsertWorkerSnapshot(snapshot) {
            if (!snapshot || !snapshot.id) return;

            const state = store.getState();
            const existing = state.workers?.byId?.[snapshot.id];
            const isNew = !existing?.id;

            store.dispatch('workers', 'upsertWorker', snapshot);

            // Emit events
            if (isNew) {
                eventBus.emit(LcmEventTypes.WORKER_CREATED, snapshot);
            } else {
                eventBus.emit(LcmEventTypes.WORKER_SNAPSHOT, snapshot);

                // Check for status change
                if (existing.status !== snapshot.status) {
                    eventBus.emit(LcmEventTypes.WORKER_STATUS_CHANGED, {
                        worker_id: snapshot.id,
                        old_status: existing.status,
                        new_status: snapshot.status,
                        updated_at: snapshot.updated_at || new Date().toISOString(),
                    });
                }
            }
        },

        /**
         * Update worker metrics and emit event
         */
        updateWorkerMetrics(workerId, metrics) {
            if (!workerId) return;

            store.dispatch('workers', 'updateMetrics', { workerId, metrics });
            eventBus.emit(LcmEventTypes.WORKER_METRICS_UPDATED, {
                worker_id: workerId,
                ...metrics,
            });
        },

        /**
         * Remove a worker and emit event
         */
        removeWorker(workerId) {
            if (!workerId) return;

            const state = store.getState();
            const worker = state.workers?.byId?.[workerId];

            store.dispatch('workers', 'removeWorker', workerId);

            if (worker) {
                eventBus.emit(LcmEventTypes.WORKER_DELETED, { worker_id: workerId, worker });
            }
        },

        /**
         * Update timing and emit event
         */
        updateTiming(workerId, timing) {
            if (!workerId) return;

            store.dispatch('workers', 'updateTiming', { workerId, timing });
            eventBus.emit(LcmEventTypes.WORKER_TIMING_UPDATED, {
                worker_id: workerId,
                ...timing,
            });
        },
    };
}

export default workersSlice;
