/**
 * LCM SSE Adapter
 *
 * Wraps the @neuroglia/ui-core SSEClient with LCM-specific event processing.
 * Handles:
 * - SSE event mapping to LCM EventBus events
 * - Data normalization (extracting worker data from envelopes)
 * - Toast notifications for important events
 * - Store updates for worker/lablet events
 */

import { SSEClient } from '@neuroglia/ui-core';
import { eventBus, LcmEventTypes } from '../eventBus.js';
import { store } from '../store.js';
import { sseEventMap, toastEventTypes } from './eventMap.js';
import { showToast } from '../../ui/notifications.js';

/**
 * LCM SSE Adapter
 *
 * Extends SSEClient functionality with LCM-specific event handling.
 */
class LcmSSEAdapter {
    constructor() {
        this.sseClient = null;
        this._reconnectTimer = null;
    }

    /**
     * Initialize and connect to SSE endpoint
     */
    connect() {
        if (this.sseClient) {
            console.log('[LCM SSE] Already connected');
            return;
        }

        console.log('[LCM SSE] Connecting to /api/events/stream...');

        // Create SSE client with LCM event map
        this.sseClient = new SSEClient('/api/events/stream', eventBus, {
            eventMap: sseEventMap,
            withCredentials: true,
            autoReconnect: true,
            reconnectInterval: 1000,
            maxReconnectInterval: 30000,
        });

        // Set up event preprocessing
        this._setupEventPreprocessing();

        // Set up store updates
        this._setupStoreUpdates();

        // Set up toast notifications
        this._setupToastNotifications();

        // Connect
        this.sseClient.connect();
    }

    /**
     * Disconnect from SSE
     */
    disconnect() {
        if (this._reconnectTimer) {
            clearTimeout(this._reconnectTimer);
            this._reconnectTimer = null;
        }

        if (this.sseClient) {
            this.sseClient.disconnect();
            this.sseClient = null;
            console.log('[LCM SSE] Disconnected');
        }
    }

    /**
     * Get connection status
     */
    getStatus() {
        if (!this.sseClient) {
            return { connected: false, reconnecting: false };
        }
        return this.sseClient.getStatus();
    }

    /**
     * Set up preprocessing for raw SSE events before they hit the EventBus
     */
    _setupEventPreprocessing() {
        // Add middleware to preprocess events
        eventBus.use(async (event, next) => {
            // Preprocess worker.snapshot events
            if (event.type === LcmEventTypes.WORKER_SNAPSHOT) {
                event.data = this._normalizeWorkerSnapshot(event.data);
            }

            await next();
        });
    }

    /**
     * Normalize worker snapshot data from various SSE envelope formats
     */
    _normalizeWorkerSnapshot(data) {
        // Extract worker from envelope structure: {worker_id, reason, worker: {...}}
        const workerData = data?.data?.worker || data?.data || data;

        // Ensure id field is set (use worker_id if id is missing)
        if (workerData && !workerData.id && (data?.data?.worker_id || data?.worker_id)) {
            workerData.id = data?.data?.worker_id || data?.worker_id;
        }

        // Normalize metrics from nested structures if top-level fields are missing
        if (workerData) {
            const getMetric = field => {
                return workerData.cml_system_info?.[field] ?? workerData.metrics?.system_info?.[field];
            };

            if (workerData.cpu_utilization === undefined) {
                workerData.cpu_utilization = getMetric('cpu_utilization');
            }
            if (workerData.memory_utilization === undefined) {
                workerData.memory_utilization = getMetric('memory_utilization');
            }
            if (workerData.storage_utilization === undefined) {
                workerData.storage_utilization = getMetric('storage_utilization');
            }
        }

        return workerData;
    }

    /**
     * Set up store updates from SSE events
     *
     * IMPORTANT: Use store.dispatch() directly here instead of action creators.
     * Action creators (workersActions, definitionsActions, sessionsActions) re-emit the same EventBus
     * events after dispatching, which causes infinite recursion when called from
     * an EventBus handler. Action creators are intended for user-initiated actions
     * (button clicks, form submissions) where event re-emission is desirable.
     */
    _setupStoreUpdates() {
        // Worker events -> update store (dispatch directly to avoid re-emission loop)
        eventBus.on(LcmEventTypes.WORKER_SNAPSHOT, data => {
            store.dispatch('workers', 'upsertWorker', data);
        });

        eventBus.on(LcmEventTypes.WORKER_CREATED, data => {
            store.dispatch('workers', 'upsertWorker', data);
        });

        eventBus.on(LcmEventTypes.WORKER_IMPORTED, data => {
            store.dispatch('workers', 'upsertWorker', data);
        });

        eventBus.on(LcmEventTypes.WORKER_METRICS_UPDATED, data => {
            const workerId = data.worker_id || data.id;
            if (workerId) {
                store.dispatch('workers', 'updateMetrics', { workerId, metrics: data });
            }
        });

        // Batch metrics: unwrap { batch_id, count, events: [...] } envelope (ADR-013)
        eventBus.on(LcmEventTypes.WORKER_METRICS_UPDATED_BATCH, data => {
            const events = data?.events;
            if (Array.isArray(events)) {
                for (const metric of events) {
                    const workerId = metric.worker_id || metric.id;
                    if (workerId) {
                        store.dispatch('workers', 'updateMetrics', { workerId, metrics: metric });
                    }
                }
            }
        });

        eventBus.on(LcmEventTypes.WORKER_TERMINATED, data => {
            const workerId = data.worker_id || data.id;
            if (workerId) {
                store.dispatch('workers', 'removeWorker', workerId);
            }
        });

        // Lablet session events -> update sessions store (M3-PREP: domain separation)
        // NOTE: Domain SSE payloads use `session_id` as the identifier field,
        // but the sessionsSlice `upsertSession` reducer requires `id`.
        // All handlers below normalize `session_id` → `id` before dispatch.
        eventBus.on(LcmEventTypes.LABLET_SESSION_SNAPSHOT, data => {
            store.dispatch('sessions', 'upsertSession', data);
        });

        eventBus.on(LcmEventTypes.LABLET_SESSION_CREATED, data => {
            const normalized = this._normalizeSessionId(data);
            // Created events carry minimal fields; set initial status
            if (!normalized.status) normalized.status = 'pending';
            store.dispatch('sessions', 'upsertSession', normalized);
        });

        eventBus.on(LcmEventTypes.LABLET_SESSION_UPDATED, data => {
            store.dispatch('sessions', 'upsertSession', this._normalizeSessionId(data));
        });

        eventBus.on(LcmEventTypes.LABLET_SESSION_STATUS_CHANGED, data => {
            store.dispatch('sessions', 'upsertSession', this._normalizeSessionId(data));
        });

        // Pipeline progress SSE → merge into session's pipeline_progress (ADR-034 Sprint E)
        eventBus.on(LcmEventTypes.LABLET_SESSION_PIPELINE_PROGRESS, data => {
            const sessionId = data.session_id || data.id;
            if (!sessionId) return;
            const pipelineName = data.pipeline_name;
            if (!pipelineName) return;
            // Retrieve current session from store to merge pipeline_progress
            const sessionState = store.getState('sessions');
            const session = sessionState?.byId?.[sessionId];
            const merged = { ...(session?.pipeline_progress || {}) };
            merged[pipelineName] = data.progress || {};
            store.dispatch('sessions', 'upsertSession', {
                id: sessionId,
                pipeline_progress: merged,
            });
        });

        // Desired status changed SSE → update session in store (ADR-034 Sprint E)
        eventBus.on(LcmEventTypes.LABLET_SESSION_DESIRED_STATUS_CHANGED, data => {
            const sessionId = data.session_id || data.id;
            if (sessionId && data.new_desired_status) {
                store.dispatch('sessions', 'upsertSession', {
                    id: sessionId,
                    desired_status: data.new_desired_status,
                });
            }
        });

        // Score recorded SSE → merge score data into session (AD-SSE-RACE-001 Fix 6)
        // Backend sends: { session_id, score_report_id, grade_result, scored_at }
        eventBus.on(LcmEventTypes.LABLET_SESSION_SCORE_RECORDED, data => {
            const sessionId = data.session_id || data.id;
            if (sessionId) {
                store.dispatch('sessions', 'upsertSession', {
                    id: sessionId,
                    score_report_id: data.score_report_id,
                    scored_at: data.scored_at,
                    grade_result: data.grade_result,
                });
            }
        });

        // Timeslot extended SSE → update timeslot end in session (AD-SSE-RACE-001 Fix 5)
        // Backend sends: { session_id, old_timeslot_end, new_timeslot_end, extended_by, extended_at }
        eventBus.on(LcmEventTypes.LABLET_SESSION_TIMESLOT_EXTENDED, data => {
            const sessionId = data.session_id || data.id;
            if (sessionId && data.new_timeslot_end) {
                store.dispatch('sessions', 'upsertSession', {
                    id: sessionId,
                    timeslot_end: data.new_timeslot_end,
                });
            }
        });

        // Ports released SSE → informational, update session (Track 2 §5.2)
        eventBus.on(LcmEventTypes.LABLET_SESSION_PORTS_RELEASED, data => {
            const sessionId = data.session_id || data.id;
            if (sessionId) {
                console.log(`[LCM SSE] Ports released for session ${sessionId}`);
                store.dispatch('sessions', 'upsertSession', {
                    id: sessionId,
                    ports: null,
                });
            }
        });

        // Pipeline CloudEvents (Sprint G — G5 granular per-step observability)
        // These carry individual step-level events for real-time pipeline visualization.
        // Re-emit as a unified event that PipelineProgressPanel components can subscribe to.
        eventBus.on(LcmEventTypes.PIPELINE_STEP_STARTED, data => {
            const sessionId = data.session_id || data.aggregate_id;
            if (!sessionId) return;
            this._updatePipelineStep(sessionId, data.pipeline_name, data.step_name, 'in_progress');
        });

        eventBus.on(LcmEventTypes.PIPELINE_STEP_COMPLETED, data => {
            const sessionId = data.session_id || data.aggregate_id;
            if (!sessionId) return;
            this._updatePipelineStep(sessionId, data.pipeline_name, data.step_name, 'completed', {
                result_data: data.result_data,
            });
        });

        eventBus.on(LcmEventTypes.PIPELINE_STEP_FAILED, data => {
            const sessionId = data.session_id || data.aggregate_id;
            if (!sessionId) return;
            this._updatePipelineStep(sessionId, data.pipeline_name, data.step_name, 'failed', {
                error: data.error,
            });
        });

        eventBus.on(LcmEventTypes.PIPELINE_COMPLETED, data => {
            const sessionId = data.session_id || data.aggregate_id;
            if (!sessionId || !data.pipeline_name) return;
            // Re-emit as pipeline progress update so the panel refreshes
            eventBus.emit(LcmEventTypes.LABLET_SESSION_PIPELINE_PROGRESS, {
                session_id: sessionId,
                pipeline_name: data.pipeline_name,
                pipeline_status: data.status,
                steps_completed: data.steps_completed,
                steps_failed: data.steps_failed,
                steps_skipped: data.steps_skipped,
            });
        });

        eventBus.on(LcmEventTypes.LABLET_SESSION_TERMINATED, data => {
            const sessionId = data.session_id || data.id;
            if (sessionId) {
                store.dispatch('sessions', 'removeSession', sessionId);
            }
        });

        eventBus.on(LcmEventTypes.LABLET_SESSION_DELETED, data => {
            const sessionId = data.session_id || data.id;
            if (sessionId) {
                store.dispatch('sessions', 'removeSession', sessionId);
            }
        });

        // Worker template events -> update store
        eventBus.on(LcmEventTypes.WORKER_TEMPLATE_CREATED, data => {
            store.dispatch('templates', 'upsertTemplate', data);
        });

        eventBus.on(LcmEventTypes.WORKER_TEMPLATE_UPDATED, data => {
            store.dispatch('templates', 'upsertTemplate', data);
        });

        eventBus.on(LcmEventTypes.WORKER_TEMPLATE_DELETED, data => {
            const templateId = data.template_id || data.id;
            if (templateId) {
                store.dispatch('templates', 'removeTemplate', templateId);
            }
        });

        // Lablet definition events -> update definitions store (M3-PREP: domain separation)
        eventBus.on(LcmEventTypes.LABLET_DEFINITION_SNAPSHOT, data => {
            store.dispatch('definitions', 'upsertDefinition', data);
        });

        eventBus.on(LcmEventTypes.LABLET_DEFINITION_CREATED, data => {
            store.dispatch('definitions', 'upsertDefinition', data);
        });

        eventBus.on(LcmEventTypes.LABLET_DEFINITION_UPDATED, data => {
            store.dispatch('definitions', 'upsertDefinition', data);
        });

        eventBus.on(LcmEventTypes.LABLET_DEFINITION_DELETED, data => {
            const defId = data.definition_id || data.id;
            if (defId) {
                store.dispatch('definitions', 'removeDefinition', defId);
            }
        });

        // Lablet definition activation/deactivation -> update definitions store
        eventBus.on(LcmEventTypes.LABLET_DEFINITION_ACTIVATED, data => {
            store.dispatch('definitions', 'upsertDefinition', { ...data, is_active: true });
        });

        eventBus.on(LcmEventTypes.LABLET_DEFINITION_DEACTIVATED, data => {
            store.dispatch('definitions', 'upsertDefinition', { ...data, is_active: false });
        });

        // Lablet definition sync lifecycle -> update definitions store
        eventBus.on(LcmEventTypes.LABLET_DEFINITION_CONTENT_SYNCED, data => {
            if (data?.definition_id) {
                store.dispatch('definitions', 'upsertDefinition', {
                    id: data.definition_id,
                    sync_status: data.sync_status,
                    last_synced_at: data.synced_at,
                    status: data.sync_status === 'success' ? 'active' : undefined,
                });
            }
        });

        eventBus.on(LcmEventTypes.LABLET_DEFINITION_DEPRECATED, data => {
            if (data?.definition_id) {
                store.dispatch('definitions', 'upsertDefinition', {
                    id: data.definition_id,
                    status: 'deprecated',
                    deprecated_by: data.deprecated_by,
                    deprecated_at: data.deprecated_at,
                    deprecation_reason: data.deprecation_reason,
                    replacement_version: data.replacement_version,
                });
            }
        });

        eventBus.on(LcmEventTypes.LABLET_DEFINITION_SYNC_REQUESTED, data => {
            if (data?.definition_id) {
                store.dispatch('definitions', 'upsertDefinition', {
                    id: data.definition_id,
                    sync_status: 'sync_requested',
                });
            }
        });

        // Lab Record events -> update store (dispatch directly to avoid re-emission loop)
        eventBus.on(LcmEventTypes.LAB_RECORD_SNAPSHOT, data => {
            store.dispatch('labRecords', 'upsertLabRecord', data);
        });

        eventBus.on(LcmEventTypes.LAB_RECORD_DISCOVERED, data => {
            store.dispatch('labRecords', 'upsertLabRecord', data);
        });

        eventBus.on(LcmEventTypes.LAB_RECORD_IMPORTED, data => {
            store.dispatch('labRecords', 'upsertLabRecord', data);
        });

        eventBus.on(LcmEventTypes.LAB_RECORD_STATUS_UPDATED, data => {
            const labRecordId = data.lab_record_id || data.id;
            if (labRecordId && data.status) {
                store.dispatch('labRecords', 'updateStatus', {
                    labRecordId,
                    status: data.status,
                    updatedAt: data.updated_at,
                });
                // Re-emit as specific event for components that listen to
                // LAB_RECORD_DELETED / LAB_RECORD_ARCHIVED (e.g. close modal on delete)
                if (data.action === 'deleted') {
                    eventBus.emit(LcmEventTypes.LAB_RECORD_DELETED, data);
                } else if (data.action === 'archived') {
                    eventBus.emit(LcmEventTypes.LAB_RECORD_ARCHIVED, data);
                }
            }
        });

        eventBus.on(LcmEventTypes.LAB_RECORD_DELETED, data => {
            const labRecordId = data.lab_record_id || data.id;
            if (labRecordId) {
                store.dispatch('labRecords', 'updateStatus', {
                    labRecordId,
                    status: 'deleted',
                    updatedAt: data.updated_at,
                });
            }
        });

        eventBus.on(LcmEventTypes.LAB_RECORD_ARCHIVED, data => {
            const labRecordId = data.lab_record_id || data.id;
            if (labRecordId) {
                store.dispatch('labRecords', 'updateStatus', {
                    labRecordId,
                    status: 'archived',
                    updatedAt: data.updated_at,
                });
            }
        });

        eventBus.on(LcmEventTypes.LAB_RECORD_CLONED, data => {
            if (data) {
                store.dispatch('labRecords', 'upsertLabRecord', data);
            }
        });

        eventBus.on(LcmEventTypes.LAB_RECORD_TOPOLOGY_UPDATED, data => {
            if (data) {
                store.dispatch('labRecords', 'upsertLabRecord', data);
            }
        });

        // Lab Record binding events → update lab record in store (Track 2 §5.4)
        eventBus.on(LcmEventTypes.LAB_RECORD_BOUND, data => {
            if (data) {
                store.dispatch('labRecords', 'upsertLabRecord', data);
            }
        });

        eventBus.on(LcmEventTypes.LAB_RECORD_UNBOUND, data => {
            if (data) {
                store.dispatch('labRecords', 'upsertLabRecord', data);
            }
        });

        // Lab Record error events → update lab record error state in store (Track 2 §5.4)
        eventBus.on(LcmEventTypes.LAB_RECORD_ERROR, data => {
            const labRecordId = data.lab_record_id || data.id;
            if (labRecordId) {
                store.dispatch('labRecords', 'upsertLabRecord', {
                    id: labRecordId,
                    last_error: data.error || data.message,
                    last_error_at: data.occurred_at || new Date().toISOString(),
                });
            }
        });

        // Lab Record Action events -> update pending_action state (AD-023)
        eventBus.on(LcmEventTypes.LAB_RECORD_ACTION_QUEUED, data => {
            const labRecordId = data.lab_record_id || data.id;
            if (labRecordId && data.action) {
                store.dispatch('labRecords', 'setPendingAction', {
                    labRecordId,
                    action: data.action,
                    requested_at: data.requested_at,
                });
            }
        });

        eventBus.on(LcmEventTypes.LAB_RECORD_ACTION_COMPLETED, data => {
            const labRecordId = data.lab_record_id || data.id;
            if (labRecordId) {
                store.dispatch('labRecords', 'clearPendingAction', labRecordId);
            }
        });

        eventBus.on(LcmEventTypes.LAB_RECORD_ACTION_FAILED, data => {
            const labRecordId = data.lab_record_id || data.id;
            if (labRecordId) {
                store.dispatch('labRecords', 'clearPendingAction', labRecordId);
            }
        });

        // System shutdown - reconnect after delay
        eventBus.on(LcmEventTypes.SYSTEM_SSE_SHUTDOWN, () => {
            console.log('[LCM SSE] System shutdown received, will reconnect...');
            this.disconnect();
            this._reconnectTimer = setTimeout(() => {
                console.log('[LCM SSE] Attempting to reconnect after shutdown...');
                this.connect();
            }, 2000);
        });

        // Auth session expired - disconnect
        eventBus.on(LcmEventTypes.AUTH_SESSION_EXPIRED, () => {
            console.warn('[LCM SSE] Session expired, disconnecting');
            this.disconnect();
        });

        // SSE connected - show toast
        eventBus.on(LcmEventTypes.SSE_CONNECTED, () => {
            showToast('Realtime connected', 'success');
        });
    }

    /**
     * Set up toast notifications for important events
     */
    _setupToastNotifications() {
        Object.entries(toastEventTypes).forEach(([eventType, config]) => {
            eventBus.on(eventType, data => {
                const message = typeof config.message === 'function' ? config.message(data) : config.message;

                if (!message) return; // Skip if message is null/empty

                const type = typeof config.type === 'function' ? config.type(data) : config.type;
                const duration = typeof config.duration === 'function' ? config.duration(data) : config.duration;

                showToast(message, type, duration);
            });
        });
    }

    /**
     * Normalize session event data so it always has an `id` field.
     * Domain SSE payloads use `session_id`, but the store's upsertSession
     * reducer requires `id`.
     *
     * @param {Object} data - Raw SSE event data
     * @returns {Object} Data with `id` field set
     */
    _normalizeSessionId(data) {
        if (!data) return data;
        const id = data.id || data.session_id;
        if (!id) return data;
        return { ...data, id };
    }

    /**
     * Update a single pipeline step in the session's pipeline_progress store entry.
     * Called by pipeline CloudEvent handlers (Sprint G — G5).
     *
     * @param {string} sessionId - LabletSession ID
     * @param {string} pipelineName - Pipeline name (e.g. "instantiate")
     * @param {string} stepName - Step name (e.g. "create_lab")
     * @param {string} newStatus - Step status ("in_progress", "completed", "failed")
     * @param {Object} [extra] - Optional extra fields (result_data, error)
     */
    _updatePipelineStep(sessionId, pipelineName, stepName, newStatus, extra = {}) {
        if (!sessionId || !pipelineName || !stepName) return;

        const sessionState = store.getState('sessions');
        const session = sessionState?.byId?.[sessionId];
        const currentProgress = { ...(session?.pipeline_progress || {}) };
        const pipelineSteps = { ...(currentProgress[pipelineName] || {}) };

        pipelineSteps[stepName] = {
            ...(pipelineSteps[stepName] || {}),
            status: newStatus,
            ...extra,
        };

        currentProgress[pipelineName] = pipelineSteps;

        store.dispatch('sessions', 'upsertSession', {
            id: sessionId,
            pipeline_progress: currentProgress,
        });
    }
}

// Singleton instance
export const lcmSSEAdapter = new LcmSSEAdapter();

// Convenience exports
export const connect = () => lcmSSEAdapter.connect();
export const disconnect = () => lcmSSEAdapter.disconnect();
export const getStatus = () => lcmSSEAdapter.getStatus();
export const connectSSE = connect;
export const disconnectSSE = disconnect;

export default lcmSSEAdapter;
