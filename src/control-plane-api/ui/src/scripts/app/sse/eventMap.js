/**
 * LCM SSE Event Mappings
 *
 * Maps server-sent SSE event types to LCM EventBus event types.
 * Used by the SSE adapter to route events correctly.
 */

import { LcmEventTypes } from '../eventTypes.js';

/**
 * Mapping from SSE event type (server) to EventBus event type (client)
 *
 * Format: { 'sse.event.name': 'eventbus.event.type' }
 */
export const sseEventMap = {
    // Connection events (handled internally by SSEClient via onopen/onerror)
    // NOTE: Do NOT map 'connected' here — SSEClient already emits SSE_CONNECTED
    // from its onopen handler. Mapping it again causes duplicate event emissions.
    heartbeat: null, // Ignored, handled internally

    // Worker events
    'worker.snapshot': LcmEventTypes.WORKER_SNAPSHOT,
    'worker.metrics.updated': LcmEventTypes.WORKER_METRICS_UPDATED,
    'worker.metrics.updated.batch': LcmEventTypes.WORKER_METRICS_UPDATED_BATCH,
    'worker.status.updated': LcmEventTypes.WORKER_STATUS_CHANGED,
    'worker.created': LcmEventTypes.WORKER_CREATED,
    'worker.imported': LcmEventTypes.WORKER_IMPORTED,
    'worker.terminated': LcmEventTypes.WORKER_TERMINATED,
    'worker.activity.updated': LcmEventTypes.WORKER_ACTIVITY_UPDATED,
    'worker.idle_detection.toggled': LcmEventTypes.WORKER_IDLE_DETECTION_TOGGLED,
    'worker.paused': LcmEventTypes.WORKER_PAUSED,
    'worker.resumed': LcmEventTypes.WORKER_RESUMED,
    'worker.endpoint.updated': LcmEventTypes.WORKER_ENDPOINT_UPDATED,
    'worker.ec2_details.updated': LcmEventTypes.WORKER_EC2_DETAILS_UPDATED,
    'worker.refresh.throttled': LcmEventTypes.WORKER_REFRESH_THROTTLED,
    'worker.data.refreshed': LcmEventTypes.WORKER_DATA_REFRESHED,
    'worker.labs.updated': LcmEventTypes.LAB_UPDATED,
    'workers.refresh.completed': LcmEventTypes.WORKERS_REFRESH_COMPLETED,

    // License events
    'worker.license.registration.started': LcmEventTypes.WORKER_LICENSE_REGISTRATION_STARTED,
    'worker.license.registration.completed': LcmEventTypes.WORKER_LICENSE_REGISTRATION_COMPLETED,
    'worker.license.registration.failed': LcmEventTypes.WORKER_LICENSE_REGISTRATION_FAILED,
    'worker.license.deregistered': LcmEventTypes.WORKER_LICENSE_DEREGISTERED,

    // Lablet session events (Phase 7 — replaces instance events)
    // New wire names (lablet.session.*)
    'lablet.session.created': LcmEventTypes.LABLET_SESSION_CREATED,
    'lablet.session.updated': LcmEventTypes.LABLET_SESSION_UPDATED,
    'lablet.session.deleted': LcmEventTypes.LABLET_SESSION_DELETED,
    'lablet.session.status.changed': LcmEventTypes.LABLET_SESSION_STATUS_CHANGED,
    // AD-SSE-RACE-001 Fix 7: The following per-status wire types are RESERVED
    // but never emitted by the backend. All lifecycle transitions use the single
    // 'lablet.session.status.changed' wire type with a `status` field.
    // Kept for potential future fine-grained filtering; no sseAdapter handlers exist.
    // 'lablet.session.scheduled': LcmEventTypes.LABLET_SESSION_SCHEDULED,
    // 'lablet.session.instantiating': LcmEventTypes.LABLET_SESSION_INSTANTIATING,
    // 'lablet.session.ready': LcmEventTypes.LABLET_SESSION_READY,
    // 'lablet.session.running': LcmEventTypes.LABLET_SESSION_RUNNING,
    // 'lablet.session.collecting': LcmEventTypes.LABLET_SESSION_COLLECTING,
    // 'lablet.session.grading': LcmEventTypes.LABLET_SESSION_GRADING,
    // 'lablet.session.stopping': LcmEventTypes.LABLET_SESSION_STOPPING,
    // 'lablet.session.stopped': LcmEventTypes.LABLET_SESSION_STOPPED,
    // 'lablet.session.archived': LcmEventTypes.LABLET_SESSION_ARCHIVED,
    'lablet.session.terminated': LcmEventTypes.LABLET_SESSION_TERMINATED,
    'lablet.session.snapshot': LcmEventTypes.LABLET_SESSION_SNAPSHOT,
    'lablet.session.pipeline.progress': LcmEventTypes.LABLET_SESSION_PIPELINE_PROGRESS,
    'lablet.session.desired_status.changed': LcmEventTypes.LABLET_SESSION_DESIRED_STATUS_CHANGED,
    'lablet.session.score.recorded': LcmEventTypes.LABLET_SESSION_SCORE_RECORDED,
    'lablet.session.timeslot.extended': LcmEventTypes.LABLET_SESSION_TIMESLOT_EXTENDED,
    'lablet.session.ports.released': LcmEventTypes.LABLET_SESSION_PORTS_RELEASED,
    'lablet.sessions.refresh.completed': LcmEventTypes.LABLET_SESSIONS_REFRESH_COMPLETED,

    // Pipeline CloudEvents (Sprint G — G5 granular per-step observability)
    'pipeline.step.started.v1': LcmEventTypes.PIPELINE_STEP_STARTED,
    'pipeline.step.completed.v1': LcmEventTypes.PIPELINE_STEP_COMPLETED,
    'pipeline.step.failed.v1': LcmEventTypes.PIPELINE_STEP_FAILED,
    'pipeline.completed.v1': LcmEventTypes.PIPELINE_COMPLETED,
    // Backward-compat: old wire names still route correctly
    'lablet.instance.created': LcmEventTypes.LABLET_SESSION_CREATED,
    'lablet.instance.updated': LcmEventTypes.LABLET_SESSION_UPDATED,
    'lablet.instance.deleted': LcmEventTypes.LABLET_SESSION_DELETED,
    'lablet.instance.status.changed': LcmEventTypes.LABLET_SESSION_STATUS_CHANGED,
    'lablet.instance.snapshot': LcmEventTypes.LABLET_SESSION_SNAPSHOT,
    'lablet.instances.refresh.completed': LcmEventTypes.LABLET_SESSIONS_REFRESH_COMPLETED,

    // Lablet definition events
    'lablet.definition.created': LcmEventTypes.LABLET_DEFINITION_CREATED,
    'lablet.definition.updated': LcmEventTypes.LABLET_DEFINITION_UPDATED,
    'lablet.definition.activated': LcmEventTypes.LABLET_DEFINITION_ACTIVATED,
    'lablet.definition.deactivated': LcmEventTypes.LABLET_DEFINITION_DEACTIVATED,
    'lablet.definition.deleted': LcmEventTypes.LABLET_DEFINITION_DELETED,
    'lablet.definition.snapshot': LcmEventTypes.LABLET_DEFINITION_SNAPSHOT,
    'lablet.definition.content_synced': LcmEventTypes.LABLET_DEFINITION_CONTENT_SYNCED,
    'lablet.definition.deprecated': LcmEventTypes.LABLET_DEFINITION_DEPRECATED,
    'lablet.definition.sync_requested': LcmEventTypes.LABLET_DEFINITION_SYNC_REQUESTED,
    'lablet.definitions.refresh.completed': LcmEventTypes.LABLET_DEFINITIONS_REFRESH_COMPLETED,

    // Worker template events
    'worker.template.created': LcmEventTypes.WORKER_TEMPLATE_CREATED,
    'worker.template.updated': LcmEventTypes.WORKER_TEMPLATE_UPDATED,
    'worker.template.deleted': LcmEventTypes.WORKER_TEMPLATE_DELETED,

    // Lab Record events (Phase 10)
    // Lab Record events (Phase 10)
    // Wire names use 'lab.' prefix — must match server SSE event_type values
    'lab.discovered': LcmEventTypes.LAB_RECORD_DISCOVERED,
    'lab.status.updated': LcmEventTypes.LAB_RECORD_STATUS_UPDATED,
    'lab.imported': LcmEventTypes.LAB_RECORD_IMPORTED,
    'lab.cloned': LcmEventTypes.LAB_RECORD_CLONED,
    'lab.bound': LcmEventTypes.LAB_RECORD_BOUND,
    'lab.unbound': LcmEventTypes.LAB_RECORD_UNBOUND,
    'lab.topology.updated': LcmEventTypes.LAB_RECORD_TOPOLOGY_UPDATED,
    'lab.snapshot': LcmEventTypes.LAB_RECORD_SNAPSHOT,
    'lab.action.requested': LcmEventTypes.LAB_RECORD_ACTION_QUEUED,
    'lab.action.completed': LcmEventTypes.LAB_RECORD_ACTION_COMPLETED,
    'lab.action.failed': LcmEventTypes.LAB_RECORD_ACTION_FAILED,
    'lab.error': LcmEventTypes.LAB_RECORD_ERROR,
    'lab_records.refresh.completed': LcmEventTypes.LAB_RECORDS_REFRESH_COMPLETED,

    // System events
    'system.sse.shutdown': LcmEventTypes.SYSTEM_SSE_SHUTDOWN,

    // Auth events
    'auth.session.expired': LcmEventTypes.AUTH_SESSION_EXPIRED,
};

/**
 * Event types that should show toast notifications
 */
export const toastEventTypes = {
    [LcmEventTypes.WORKER_CREATED]: { message: data => (data?.name ? `Worker created: ${data.name}` : null), type: 'info' },
    [LcmEventTypes.WORKER_IMPORTED]: { message: data => (data?.name ? `Worker imported: ${data.name}` : null), type: 'success' },
    [LcmEventTypes.WORKER_TERMINATED]: { message: data => (data?.name ? `Worker terminated: ${data.name}` : null), type: 'warning' },
    [LcmEventTypes.WORKER_REFRESH_THROTTLED]: {
        message: data => {
            if (!data) return null;
            const retryMsg = data.retry_after_seconds ? ` Please wait ${data.retry_after_seconds}s.` : '';
            return `Refresh rate limited.${retryMsg}`;
        },
        type: 'warning',
    },
    [LcmEventTypes.WORKERS_REFRESH_COMPLETED]: {
        message: data => {
            if (!data) return null; // No data payload — skip toast
            if (data.status === 'success' && data.total_imported > 0) {
                return `Workers refresh complete: ${data.total_imported} new worker(s) imported.`;
            }
            if (data.error) {
                return `Workers refresh failed: ${data.error}`;
            }
            return null; // Don't show toast
        },
        type: data => (data?.error ? 'error' : 'success'),
    },
    [LcmEventTypes.WORKER_LICENSE_REGISTRATION_STARTED]: {
        message: data => (data ? `License registration started for ${data.worker_name || data.worker_id}` : null),
        type: 'info',
    },
    [LcmEventTypes.WORKER_LICENSE_REGISTRATION_COMPLETED]: {
        message: data => (data ? `✅ License registered successfully for ${data.worker_name || data.worker_id}! Click to dismiss.` : null),
        type: 'success',
        duration: 0, // Persistent
    },
    [LcmEventTypes.WORKER_LICENSE_REGISTRATION_FAILED]: {
        message: data => (data ? `License registration failed for ${data.worker_name || data.worker_id}: ${data.reason || 'Unknown error'}` : null),
        type: 'error',
        duration: 8000,
    },
    [LcmEventTypes.WORKER_LICENSE_DEREGISTERED]: {
        message: data => (data ? `License deregistered from ${data.worker_name || data.worker_id}` : null),
        type: 'info',
    },
    [LcmEventTypes.SYSTEM_SSE_SHUTDOWN]: {
        message: () => 'Server restarting, reconnecting...',
        type: 'warning',
    },
    [LcmEventTypes.LAB_RECORD_DISCOVERED]: {
        message: data => (data?.title ? `Lab discovered: ${data.title}` : null),
        type: 'info',
    },
    [LcmEventTypes.LAB_RECORD_ACTION_COMPLETED]: {
        message: data => {
            if (!data) return null;
            const action = data.action || 'action';
            const title = data.title || data.lab_record_id;
            return `Lab ${action} completed: ${title}`;
        },
        type: 'success',
    },
    [LcmEventTypes.LAB_RECORD_ACTION_FAILED]: {
        message: data => {
            if (!data) return null;
            const action = data.action || 'action';
            const title = data.title || data.lab_record_id;
            return `Lab ${action} failed: ${title} — ${data.reason || 'Unknown error'}`;
        },
        type: 'error',
        duration: 8000,
    },
    [LcmEventTypes.LABLET_DEFINITION_CREATED]: {
        message: data => (data?.name ? `Definition created: ${data.name} v${data.version || '?'}` : null),
        type: 'success',
    },
    [LcmEventTypes.LABLET_DEFINITION_CONTENT_SYNCED]: {
        message: data => {
            if (!data) return null;
            if (data.sync_status === 'success') {
                return `Definition synced successfully`;
            }
            return `Definition sync failed: ${data.error_message || 'Unknown error'}`;
        },
        type: data => (data?.sync_status === 'success' ? 'success' : 'error'),
        duration: data => (data?.sync_status === 'success' ? 4000 : 8000),
    },
    [LcmEventTypes.LABLET_DEFINITION_DEPRECATED]: {
        message: data => (data?.name ? `Definition deprecated: ${data.name} v${data.version || '?'}` : null),
        type: 'warning',
    },

    // Pipeline CloudEvents (Sprint G — G5)
    [LcmEventTypes.PIPELINE_STEP_FAILED]: {
        message: data => {
            if (!data) return null;
            const step = data.step_name || 'step';
            const pipeline = data.pipeline_name || 'pipeline';
            const error = data.error ? `: ${data.error}` : '';
            return `Pipeline ${pipeline} — step "${step}" failed${error}`;
        },
        type: 'error',
        duration: 8000,
    },
    [LcmEventTypes.PIPELINE_COMPLETED]: {
        message: data => {
            if (!data) return null;
            const pipeline = data.pipeline_name || 'pipeline';
            const status = data.status || 'completed';
            if (status === 'failed') return `Pipeline ${pipeline} failed`;
            if (status === 'partial') return `Pipeline ${pipeline} completed with failures`;
            return `Pipeline ${pipeline} completed successfully`;
        },
        type: data => {
            const status = data?.status || 'completed';
            if (status === 'failed') return 'error';
            if (status === 'partial') return 'warning';
            return 'success';
        },
    },
};

export default sseEventMap;
