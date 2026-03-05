/**
 * LCM Event Types
 *
 * Extends the core @neuroglia/ui-core EventTypes with domain-specific
 * events for the Lablet Cloud Manager application.
 */

import { EventTypes as CoreEventTypes } from '@neuroglia/ui-core';

/**
 * LCM-specific event types extending core events
 */
export const LcmEventTypes = {
    // Include core event types
    ...CoreEventTypes,

    // Worker events
    WORKER_CREATED: 'worker.created',
    WORKER_IMPORTED: 'worker.imported',
    WORKER_UPDATED: 'worker.updated',
    WORKER_DELETED: 'worker.deleted',
    WORKER_STATUS_CHANGED: 'worker.status.changed',
    WORKER_METRICS_UPDATED: 'worker.metrics.updated',
    WORKER_SNAPSHOT: 'worker.snapshot',
    WORKER_TERMINATED: 'worker.terminated',
    WORKER_ACTIVITY_UPDATED: 'worker.activity.updated',
    WORKER_IDLE_DETECTION_TOGGLED: 'worker.idle_detection.toggled',
    WORKER_PAUSED: 'worker.paused',
    WORKER_RESUMED: 'worker.resumed',
    WORKER_REFRESH_THROTTLED: 'worker.refresh.throttled',
    WORKER_DATA_REFRESHED: 'worker.data.refreshed',
    WORKER_ENDPOINT_UPDATED: 'worker.endpoint.updated',
    WORKER_EC2_DETAILS_UPDATED: 'worker.ec2_details.updated',
    WORKER_TIMING_UPDATED: 'worker.timing.updated',
    WORKER_ACTIVE_CHANGED: 'worker.active.changed',
    WORKER_LICENSE_REGISTRATION_STARTED: 'worker.license.registration.started',
    WORKER_LICENSE_REGISTRATION_COMPLETED: 'worker.license.registration.completed',
    WORKER_LICENSE_REGISTRATION_FAILED: 'worker.license.registration.failed',
    WORKER_LICENSE_DEREGISTERED: 'worker.license.deregistered',

    // Workers list events (bulk operations)
    WORKERS_REFRESH_COMPLETED: 'workers.refresh.completed',

    // System events
    SYSTEM_SSE_SHUTDOWN: 'system.sse.shutdown',

    // Lab events (legacy — worker-scoped lab sync)
    LAB_CREATED: 'lab.created',
    LAB_STARTED: 'lab.started',
    LAB_STOPPED: 'lab.stopped',
    LAB_WIPED: 'lab.wiped',
    LAB_DELETED: 'lab.deleted',
    LAB_UPDATED: 'lab.updated',

    // Lab Record events (Phase 10 — LabRecord aggregate lifecycle)
    LAB_RECORD_DISCOVERED: 'lab_record.discovered',
    LAB_RECORD_STATUS_UPDATED: 'lab_record.status.updated',
    LAB_RECORD_IMPORTED: 'lab_record.imported',
    LAB_RECORD_DELETED: 'lab_record.deleted',
    LAB_RECORD_ARCHIVED: 'lab_record.archived',
    LAB_RECORD_CLONED: 'lab_record.cloned',
    LAB_RECORD_BOUND: 'lab_record.bound',
    LAB_RECORD_UNBOUND: 'lab_record.unbound',
    LAB_RECORD_TOPOLOGY_UPDATED: 'lab_record.topology.updated',
    LAB_RECORD_SNAPSHOT: 'lab_record.snapshot',
    LAB_RECORD_ACTION_QUEUED: 'lab_record.action.queued',
    LAB_RECORD_ACTION_COMPLETED: 'lab_record.action.completed',
    LAB_RECORD_ACTION_FAILED: 'lab_record.action.failed',
    LAB_RECORD_ERROR: 'lab_record.error',
    LAB_RECORDS_REFRESH_COMPLETED: 'lab_records.refresh.completed',

    // Lablet Session events (Phase 7 — replaces Lablet Instance events)
    LABLET_SESSION_CREATED: 'lablet.session.created',
    LABLET_SESSION_UPDATED: 'lablet.session.updated',
    LABLET_SESSION_DELETED: 'lablet.session.deleted',
    LABLET_SESSION_STATUS_CHANGED: 'lablet.session.status.changed',
    LABLET_SESSION_SCHEDULED: 'lablet.session.scheduled',
    LABLET_SESSION_INSTANTIATING: 'lablet.session.instantiating',
    LABLET_SESSION_READY: 'lablet.session.ready',
    LABLET_SESSION_RUNNING: 'lablet.session.running',
    LABLET_SESSION_COLLECTING: 'lablet.session.collecting',
    LABLET_SESSION_GRADING: 'lablet.session.grading',
    LABLET_SESSION_STOPPING: 'lablet.session.stopping',
    LABLET_SESSION_STOPPED: 'lablet.session.stopped',
    LABLET_SESSION_ARCHIVED: 'lablet.session.archived',
    LABLET_SESSION_TERMINATED: 'lablet.session.terminated',
    LABLET_SESSION_SNAPSHOT: 'lablet.session.snapshot',
    LABLET_SESSIONS_REFRESH_COMPLETED: 'lablet.sessions.refresh.completed',

    // Backward-compat aliases (old SSE wire names → new keys)
    LABLET_INSTANCE_CREATED: 'lablet.session.created',
    LABLET_INSTANCE_UPDATED: 'lablet.session.updated',
    LABLET_INSTANCE_DELETED: 'lablet.session.deleted',
    LABLET_INSTANCE_STATUS_CHANGED: 'lablet.session.status.changed',
    LABLET_INSTANCE_SNAPSHOT: 'lablet.session.snapshot',
    LABLET_INSTANCES_REFRESH_COMPLETED: 'lablet.sessions.refresh.completed',

    // Lablet Definition events
    LABLET_DEFINITION_CREATED: 'lablet.definition.created',
    LABLET_DEFINITION_UPDATED: 'lablet.definition.updated',
    LABLET_DEFINITION_ACTIVATED: 'lablet.definition.activated',
    LABLET_DEFINITION_DEACTIVATED: 'lablet.definition.deactivated',
    LABLET_DEFINITION_DELETED: 'lablet.definition.deleted',
    LABLET_DEFINITION_SNAPSHOT: 'lablet.definition.snapshot',
    LABLET_DEFINITION_CONTENT_SYNCED: 'lablet.definition.content_synced',
    LABLET_DEFINITION_DEPRECATED: 'lablet.definition.deprecated',
    LABLET_DEFINITION_SYNC_REQUESTED: 'lablet.definition.sync_requested',
    LABLET_DEFINITIONS_REFRESH_COMPLETED: 'lablet.definitions.refresh.completed',

    // Worker Template events
    WORKER_TEMPLATE_CREATED: 'worker.template.created',
    WORKER_TEMPLATE_UPDATED: 'worker.template.updated',
    WORKER_TEMPLATE_DELETED: 'worker.template.deleted',
    WORKER_TEMPLATE_ENABLED: 'worker.template.enabled',
    WORKER_TEMPLATE_DISABLED: 'worker.template.disabled',

    // Session events (Phase 7 — composite UI events)
    SESSIONS_REFRESH_COMPLETED: 'sessions.refresh.completed',

    // UI events
    UI_VIEW_CHANGED: 'ui.view.changed',
    UI_FILTER_CHANGED: 'ui.filter.changed',
    UI_MODAL_OPENED: 'ui.modal.opened',
    UI_MODAL_CLOSED: 'ui.modal.closed',
    UI_TAB_CHANGED: 'ui.tab.changed',
};

/**
 * Alias for backward compatibility
 * @deprecated Use LcmEventTypes instead
 */
export const EventTypes = LcmEventTypes;

export default LcmEventTypes;
