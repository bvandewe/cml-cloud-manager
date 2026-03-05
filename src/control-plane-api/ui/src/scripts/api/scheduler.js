/**
 * Resource Scheduler API Client
 *
 * Provides functions for querying the resource-scheduler service:
 * - Leader status
 * - Scheduling statistics
 * - Manual reconciliation trigger
 * - Placement preview (dry-run)
 *
 * Note: The resource-scheduler runs as a separate service with its own API.
 * Requests are proxied through the CPA's SchedulerProxyController at /api/scheduler/*.
 *
 * @module api/scheduler
 */

import { apiRequest } from './client.js';

/**
 * Base URL for scheduler API.
 * CPA proxies /api/scheduler/* → resource-scheduler:8081/*
 * In development, can be overridden via APP_CONFIG.schedulerApiUrl
 */
function getBaseUrl() {
    return window.APP_CONFIG?.schedulerApiUrl || '/api/scheduler';
}

/**
 * Get scheduler leader status
 * @returns {Promise<Object>} Leader status object
 */
export async function getLeaderStatus() {
    const response = await apiRequest(`${getBaseUrl()}/admin/leader-status`, {
        method: 'GET',
    });
    return await response.json();
}

/**
 * Get scheduler statistics
 * @returns {Promise<Object>} Scheduler stats
 */
export async function getSchedulerStats() {
    const response = await apiRequest(`${getBaseUrl()}/admin/stats`, {
        method: 'GET',
    });
    return await response.json();
}

/**
 * Trigger immediate reconciliation cycle
 * @returns {Promise<Object>} Trigger result
 */
export async function triggerReconcile() {
    const response = await apiRequest(`${getBaseUrl()}/admin/trigger-reconcile`, {
        method: 'POST',
    });
    return await response.json();
}

/**
 * Resign leadership (admin)
 * @returns {Promise<Object>} Resign result
 */
export async function resignLeadership() {
    const response = await apiRequest(`${getBaseUrl()}/admin/resign-leadership`, {
        method: 'POST',
    });
    return await response.json();
}

/**
 * Preview placement (dry-run) for a lablet definition.
 *
 * Runs the real PlacementEngine algorithm without executing the decision.
 * Returns candidate scores, per-worker rejection reasons, and estimated
 * resource utilization after placement.
 *
 * AD-SCHED-001/002: Available to all authenticated users (read-only).
 *
 * @param {Object} params - Preview parameters
 * @param {string} params.definition_id - LabletDefinition ID to preview scheduling for
 * @param {string} [params.timeslot_start] - Optional timeslot start (ISO 8601)
 * @param {string} [params.timeslot_end] - Optional timeslot end (ISO 8601)
 * @returns {Promise<Object>} Enriched placement preview result
 */
export async function previewPlacement({ definition_id, timeslot_start, timeslot_end }) {
    const body = { definition_id };
    if (timeslot_start) body.timeslot_start = timeslot_start;
    if (timeslot_end) body.timeslot_end = timeslot_end;

    const response = await apiRequest(`${getBaseUrl()}/scheduling/preview`, {
        method: 'POST',
        body: JSON.stringify(body),
    });
    return await response.json();
}
