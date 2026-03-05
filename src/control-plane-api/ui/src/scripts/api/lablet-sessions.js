/**
 * Lablet Sessions API Client — Phase 7J
 *
 * Handles all API calls related to LabletSession lifecycle.
 * Maps to the LabletSessionsController endpoints (/api/lablet-sessions/*).
 *
 * Replaces lablet-instances.js (Phase 7 entity model migration).
 *
 * @module api/lablet-sessions
 */

import { apiRequest } from './client.js';

// ==============================================================================
// Read Operations (Queries)
// ==============================================================================

/**
 * List lablet sessions with optional filtering
 * @param {Object} [filters] - Filter parameters
 * @param {string} [filters.status] - Filter by status
 * @param {string} [filters.worker_id] - Filter by assigned worker
 * @param {string} [filters.owner_id] - Filter by owner
 * @param {string} [filters.definition_id] - Filter by definition
 * @param {boolean} [filters.include_terminated] - Include terminated sessions
 * @param {number} [filters.skip] - Pagination offset
 * @param {number} [filters.limit] - Pagination limit
 * @returns {Promise<Array>}
 */
export async function listLabletSessions(filters = {}) {
    const params = new URLSearchParams();

    if (filters.status) params.append('status', filters.status);
    if (filters.worker_id) params.append('worker_id', filters.worker_id);
    if (filters.owner_id) params.append('owner_id', filters.owner_id);
    if (filters.definition_id) params.append('definition_id', filters.definition_id);
    if (filters.include_terminated) params.append('include_terminated', 'true');
    if (filters.skip) params.append('skip', filters.skip.toString());
    if (filters.limit) params.append('limit', filters.limit.toString());

    const queryString = params.toString() ? `?${params.toString()}` : '';
    const response = await apiRequest(`/api/lablet-sessions/${queryString}`, {
        method: 'GET',
    });
    return await response.json();
}

/**
 * Get lablet session details by ID
 * @param {string} sessionId - Session UUID
 * @returns {Promise<Object>}
 */
export async function getLabletSession(sessionId) {
    const response = await apiRequest(`/api/lablet-sessions/${sessionId}`, {
        method: 'GET',
    });
    return await response.json();
}

/**
 * Get lablet session by reservation ID
 * @param {string} reservationId - External reservation ID
 * @returns {Promise<Object>}
 */
export async function getLabletSessionByReservation(reservationId) {
    const response = await apiRequest(`/api/lablet-sessions/by-reservation/${reservationId}`, {
        method: 'GET',
    });
    return await response.json();
}

// ==============================================================================
// Write Operations (Commands)
// ==============================================================================

/**
 * Create a new lablet session (reservation)
 * @param {Object} sessionData - Session creation data
 * @param {string} sessionData.definition_id - Definition ID
 * @param {string} sessionData.timeslot_start - Start time (ISO 8601)
 * @param {string} sessionData.timeslot_end - End time (ISO 8601)
 * @param {string} [sessionData.reservation_id] - Optional external reservation ID
 * @returns {Promise<Object>}
 */
export async function createLabletSession(sessionData) {
    const response = await apiRequest('/api/lablet-sessions/', {
        method: 'POST',
        body: JSON.stringify(sessionData),
    });
    return await response.json();
}

/**
 * Terminate a lablet session
 * @param {string} sessionId - Session UUID
 * @param {string} [reason] - Optional termination reason
 * @returns {Promise<Object>}
 */
export async function terminateLabletSession(sessionId, reason = null) {
    const body = reason ? JSON.stringify({ reason }) : null;
    const response = await apiRequest(`/api/lablet-sessions/${sessionId}`, {
        method: 'DELETE',
        body,
    });
    return await response.json();
}

/**
 * Transition a lablet session to a new status (AD-P7-06 manual actions)
 *
 * Valid transitions per LabletSessionStatus state machine:
 *   READY → RUNNING
 *   RUNNING → COLLECTING, STOPPING, TERMINATED
 *   COLLECTING → GRADING, STOPPING
 *   GRADING → STOPPING
 *   STOPPED → ARCHIVED
 *
 * @param {string} sessionId - Session UUID
 * @param {string} targetStatus - Target status (e.g., "RUNNING", "COLLECTING")
 * @param {string} [reason] - Optional reason for transition
 * @returns {Promise<Object>}
 */
export async function transitionLabletSession(sessionId, targetStatus, reason = null) {
    const body = { status: targetStatus };
    if (reason) body.reason = reason;
    const response = await apiRequest(`/api/lablet-sessions/${sessionId}/transition`, {
        method: 'POST',
        body: JSON.stringify(body),
    });
    return await response.json();
}

/**
 * Requeue a lablet session for reconciliation (re-trigger processing)
 * @param {string} sessionId - Session UUID
 * @param {string} [reason] - Optional reason for re-queuing
 * @returns {Promise<Object>}
 */
export async function requeueLabletSession(sessionId, reason = null) {
    const body = reason ? JSON.stringify({ reason }) : JSON.stringify({});
    const response = await apiRequest(`/api/lablet-sessions/${sessionId}/requeue`, {
        method: 'POST',
        body,
    });
    return await response.json();
}

/**
 * Bulk requeue lablet sessions for reconciliation
 * @param {string[]} sessionIds - Array of session UUIDs
 * @param {string} [reason] - Optional reason for re-queuing
 * @returns {Promise<Object>} Summary with success_count, fail_count, errors
 */
export async function bulkRequeueLabletSessions(sessionIds, reason = null) {
    const body = { session_ids: sessionIds };
    if (reason) body.reason = reason;
    const response = await apiRequest('/api/lablet-sessions/bulk/requeue', {
        method: 'POST',
        body: JSON.stringify(body),
    });
    return await response.json();
}

// ==============================================================================
// Sub-entity Read Operations (Phase 1 UX — child entity BFF routes)
// ==============================================================================

/**
 * Get the UserSession (LDS tracking) linked to a lablet session
 * @param {string} sessionId - Parent LabletSession UUID
 * @returns {Promise<Object>} UserSession details
 */
export async function getUserSession(sessionId) {
    const response = await apiRequest(`/api/lablet-sessions/${sessionId}/user-session`, {
        method: 'GET',
    });
    return await response.json();
}

/**
 * Get the GradingSession linked to a lablet session
 * @param {string} sessionId - Parent LabletSession UUID
 * @returns {Promise<Object>} GradingSession details
 */
export async function getGradingSession(sessionId) {
    const response = await apiRequest(`/api/lablet-sessions/${sessionId}/grading-session`, {
        method: 'GET',
    });
    return await response.json();
}

/**
 * Get the ScoreReport (assessment results) linked to a lablet session
 * @param {string} sessionId - Parent LabletSession UUID
 * @returns {Promise<Object>} ScoreReport details
 */
export async function getScoreReport(sessionId) {
    const response = await apiRequest(`/api/lablet-sessions/${sessionId}/score-report`, {
        method: 'GET',
    });
    return await response.json();
}

// ==============================================================================
// Resource Observation (ADR-030)
// ==============================================================================

/**
 * Request resource observation for a RUNNING session (ADR-030).
 * Triggers lablet-controller to observe CML runtime resources asynchronously.
 * @param {string} sessionId - Session UUID
 * @returns {Promise<Object>} Accepted response with message
 */
export async function requestResourceObservation(sessionId) {
    const response = await apiRequest(`/api/lablet-sessions/${sessionId}/observe-resources`, {
        method: 'POST',
    });
    return await response.json();
}

// ==============================================================================
// Statistics
// ==============================================================================

/**
 * Get session statistics (computed client-side)
 * @returns {Promise<Object>} Statistics by status
 */
export async function getSessionStatistics() {
    const sessions = await listLabletSessions({ include_terminated: false });

    const stats = {
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
    };

    for (const session of sessions) {
        const status = (session.status || '').toLowerCase();
        if (stats.hasOwnProperty(status)) {
            stats[status]++;
        }
    }

    return stats;
}
