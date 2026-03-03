/**
 * workerStore.js
 * Central in-memory store for worker data, timing metadata, and request deduplication.
 *
 * State changes are published to EventBus for component subscriptions.
 */

import * as workersApi from '../api/workers.js';
import { eventBus, EventTypes } from '../core/EventBus.js';

const state = {
    workers: new Map(), // id -> worker object
    timing: new Map(), // id -> { pollInterval, nextRefreshAt, lastRefreshedAt }
    activeWorkerId: null,
    inflight: new Map(), // key: region:id -> promise
};

export function setActiveWorker(id) {
    state.activeWorkerId = id;
    eventBus.emit(EventTypes.WORKER_ACTIVE_CHANGED, { worker_id: id });
}

export function getActiveWorker() {
    return state.workers.get(state.activeWorkerId) || null;
}

export function getWorker(id) {
    return state.workers.get(id) || null;
}

export function getAllWorkers() {
    return Array.from(state.workers.values());
}

export function upsertWorkerSnapshot(snapshot) {
    if (!snapshot || !snapshot.id) return;
    const existing = state.workers.get(snapshot.id) || {};
    const isNew = !existing.id;

    console.log('[workerStore] upsertWorkerSnapshot called:', {
        id: snapshot.id,
        isNew,
        license_status: snapshot.license_status,
        cml_license_info: snapshot.cml_license_info,
        existing_license_status: existing.license_status,
        existing_cml_license_info: existing.cml_license_info,
    });

    // Merge snapshot into existing, allowing null to overwrite (clears stale data)
    // Only skip undefined values to preserve existing data when snapshot is partial
    const merged = { ...existing };
    Object.entries(snapshot).forEach(([k, v]) => {
        if (v !== undefined) {
            merged[k] = v; // Allow null to overwrite
        }
    });

    console.log('[workerStore] After merge:', {
        id: merged.id,
        license_status: merged.license_status,
        cml_license_info: merged.cml_license_info,
    });

    state.workers.set(snapshot.id, merged);

    // Publish to EventBus
    if (isNew) {
        eventBus.emit(EventTypes.WORKER_CREATED, merged);
    } else {
        eventBus.emit(EventTypes.WORKER_SNAPSHOT, merged);

        // Check for status change and emit specific event
        if (existing.status !== merged.status) {
            console.log('[workerStore] Status changed:', existing.status, '->', merged.status);
            eventBus.emit(EventTypes.WORKER_STATUS_CHANGED, {
                worker_id: merged.id,
                old_status: existing.status,
                new_status: merged.status,
                updated_at: merged.updated_at || new Date().toISOString(),
            });
        }
    }
}

// Specialized update for metrics-only SSE events
export function updateWorkerMetrics(id, metrics) {
    if (!id) return;
    const existing = state.workers.get(id) || { id };
    const updated = { ...existing, ...metrics };
    state.workers.set(id, updated);

    // Publish to EventBus
    eventBus.emit(EventTypes.WORKER_METRICS_UPDATED, {
        worker_id: id,
        ...metrics,
    });
}

export function removeWorker(id) {
    if (!id) return;
    const worker = state.workers.get(id);
    state.workers.delete(id);
    state.timing.delete(id);
    if (state.activeWorkerId === id) state.activeWorkerId = null;

    // Publish to EventBus
    if (worker) {
        eventBus.emit(EventTypes.WORKER_DELETED, { worker_id: id, worker });
    }
}

export function updateTiming(id, { poll_interval, next_refresh_at, last_refreshed_at }) {
    if (!id) return;
    state.timing.set(id, {
        pollInterval: poll_interval,
        nextRefreshAt: next_refresh_at,
        lastRefreshedAt: last_refreshed_at,
        updatedAt: new Date().toISOString(),
    });

    // Emit timing update event
    eventBus.emit(EventTypes.WORKER_TIMING_UPDATED, {
        worker_id: id,
        poll_interval,
        next_refresh_at,
        last_refreshed_at,
    });
}

export function getTiming(id) {
    return state.timing.get(id) || null;
}

export async function fetchWorkerDetails(region, id, options = {}) {
    const key = `${region}:${id}`;
    // Determine if we already have a fully populated worker
    if (!options.force) {
        const existing = state.workers.get(id);
        if (existing) {
            const detailFields = ['ami_id', 'ami_name', 'ami_creation_date', 'created_at', 'cml_license_info'];
            const hasDetails = detailFields.some(f => existing[f] !== undefined && existing[f] !== null);
            if (existing.detailsLoaded || hasDetails) {
                return existing; // sufficient detail; skip network
            }
        }
    }
    // Deduplicate in-flight requests
    if (state.inflight.has(key)) {
        return state.inflight.get(key);
    }
    const promise = workersApi
        .getWorkerDetails(region, id)
        .then(worker => {
            // Normalize potential timing fields
            if (worker.cloudwatch_poll_interval && !worker.poll_interval) {
                worker.poll_interval = worker.cloudwatch_poll_interval;
            }
            if (worker.cloudwatch_next_refresh_at && !worker.next_refresh_at) {
                worker.next_refresh_at = worker.cloudwatch_next_refresh_at;
            }
            worker.detailsLoaded = true;
            upsertWorkerSnapshot(worker);
            if (worker.poll_interval && worker.next_refresh_at) {
                updateTiming(worker.id, {
                    poll_interval: worker.poll_interval,
                    next_refresh_at: worker.next_refresh_at,
                    last_refreshed_at: worker.cloudwatch_last_collected_at || new Date().toISOString(),
                });
            }
            return worker;
        })
        .catch(err => {
            console.error('[workerStore] fetchWorkerDetails error', { region, id, err });
            throw err;
        })
        .finally(() => {
            state.inflight.delete(key);
        });
    state.inflight.set(key, promise);
    return promise;
}

export function getStateSnapshot() {
    return {
        activeWorkerId: state.activeWorkerId,
        workersCount: state.workers.size,
        timingCount: state.timing.size,
        inflightCount: state.inflight.size,
    };
}

// Debug helper
export function logStoreSnapshot(label = 'store') {
    const snapshot = getStateSnapshot();
    console.log(`[workerStore] ${label}`, snapshot);
}

// TEST-ONLY: reset store state (used by unit tests)
export function __resetStoreForTests() {
    state.workers.clear();
    state.timing.clear();
    state.inflight.clear();
    state.activeWorkerId = null;
}
