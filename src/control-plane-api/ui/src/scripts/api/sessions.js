/**
 * Sessions API Client — Phase 7J
 *
 * Provides session-centric views of LabletSessions.
 * Thin wrapper over lablet-sessions.js for backward compatibility with
 * SessionsPage and SessionDetailPage consumers.
 *
 * Phase 7J: Simplified from old LabletInstance+LabletRecordRun composition
 * to direct calls to LabletSession endpoints.
 *
 * @module api/sessions
 */

import * as labletSessionsApi from './lablet-sessions.js';

// ==============================================================================
// Session Views (direct LabletSession queries)
// ==============================================================================

/**
 * Get sessions — fetches lablet sessions.
 * Each LabletSession represents a complete lab session lifecycle.
 *
 * @param {Object} [filters] - Filter options
 * @param {string} [filters.status] - Filter by session status
 * @param {string} [filters.definition_id] - Filter by lablet definition
 * @param {string} [filters.owner_id] - Filter by owner
 * @param {boolean} [filters.include_terminal] - Include terminated sessions
 * @returns {Promise<Array>} List of session objects
 */
export async function listSessions(filters = {}) {
    return await labletSessionsApi.listLabletSessions({
        status: filters.status || null,
        definition_id: filters.definition_id || null,
        owner_id: filters.owner_id || null,
        include_terminated: filters.include_terminal || false,
    });
}

/**
 * Get a single session detail by ID.
 * @param {string} sessionId - The LabletSession ID
 * @returns {Promise<Object>} Session detail
 */
export async function getSessionDetail(sessionId) {
    return await labletSessionsApi.getLabletSession(sessionId);
}

/**
 * Transition a session to a new status.
 * @param {string} sessionId - The LabletSession ID
 * @param {string} targetStatus - Target status
 * @param {string} [reason] - Optional reason
 * @returns {Promise<Object>} Updated session
 */
export async function transitionSession(sessionId, targetStatus, reason = null) {
    return await labletSessionsApi.transitionLabletSession(sessionId, targetStatus, reason);
}
