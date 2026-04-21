/**
 * Lab Records API Client
 * Handles all API calls related to LabRecord management (Phase 10: P10-5).
 *
 * Maps to the LabRecordsController endpoints (/api/lab-records/*).
 * Architecture ref: §8.1 (BFF endpoints), §9.4 (Labs Management Page).
 *
 * @module api/lab-records
 */

import { apiRequest } from './client.js';

// ==============================================================================
// Read Operations (Queries)
// ==============================================================================

/**
 * List lab records with optional filters
 * @param {Object} [filters] - Filter options
 * @param {string} [filters.worker_id] - Filter by worker ID
 * @param {string} [filters.status] - Filter by LabRecordStatus (e.g., booted, stopped, defined)
 * @param {string} [filters.owner] - Filter by owner username
 * @param {boolean} [filters.bound] - Filter by bound state (true=has active binding)
 * @param {boolean} [filters.include_terminal] - Include terminal-state labs (deleted, archived)
 * @returns {Promise<Array>} List of lab record summaries
 */
export async function listLabRecords(filters = {}) {
    const params = new URLSearchParams();
    if (filters.worker_id) params.append('worker_id', filters.worker_id);
    if (filters.status) params.append('status', filters.status);
    if (filters.owner) params.append('owner', filters.owner);
    if (filters.bound !== undefined && filters.bound !== null) params.append('bound', String(filters.bound));
    if (filters.include_terminal) params.append('include_terminal', 'true');
    const queryString = params.toString() ? `?${params.toString()}` : '';
    const response = await apiRequest(`/api/lab-records/${queryString}`, { method: 'GET' });
    return await response.json();
}

/**
 * Get a single lab record with full details
 * @param {string} labRecordId - The LabRecord aggregate ID
 * @returns {Promise<Object>} Full lab record detail
 */
export async function getLabRecord(labRecordId) {
    const response = await apiRequest(`/api/lab-records/${labRecordId}`, { method: 'GET' });
    return await response.json();
}

/**
 * Get the current topology specification for a lab record
 * @param {string} labRecordId - The LabRecord aggregate ID
 * @returns {Promise<Object>} Topology spec with node/link counts and checksums
 */
export async function getLabRecordTopology(labRecordId) {
    const response = await apiRequest(`/api/lab-records/${labRecordId}/topology`, { method: 'GET' });
    return await response.json();
}

/**
 * Get the revision history for a lab record
 * @param {string} labRecordId - The LabRecord aggregate ID
 * @returns {Promise<Array>} Ordered list of LabRevision entries
 */
export async function getLabRecordRevisions(labRecordId) {
    const response = await apiRequest(`/api/lab-records/${labRecordId}/revisions`, { method: 'GET' });
    return await response.json();
}

/**
 * Get the run history for a lab record
 * @param {string} labRecordId - The LabRecord aggregate ID
 * @returns {Promise<Array>} Ordered list of LabRunRecord entries (most recent first)
 */
export async function getLabRecordRuns(labRecordId) {
    const response = await apiRequest(`/api/lab-records/${labRecordId}/runs`, { method: 'GET' });
    return await response.json();
}

/**
 * Get lablet bindings for a lab record
 * @param {string} labRecordId - The LabRecord aggregate ID
 * @returns {Promise<Array>} Active and released lablet bindings
 */
export async function getLabRecordBindings(labRecordId) {
    const response = await apiRequest(`/api/lab-records/${labRecordId}/bindings`, { method: 'GET' });
    return await response.json();
}

// ==============================================================================
// Write Operations (Commands)
// ==============================================================================

/**
 * Queue a lab start action (ADR-017: async action)
 * @param {string} labRecordId - The LabRecord aggregate ID
 * @returns {Promise<Object>} Accepted response with action ID
 */
export async function startLabRecord(labRecordId) {
    const response = await apiRequest(`/api/lab-records/${labRecordId}/start`, { method: 'POST' });
    return await response.json();
}

/**
 * Queue a lab stop action
 * @param {string} labRecordId - The LabRecord aggregate ID
 * @returns {Promise<Object>} Accepted response with action ID
 */
export async function stopLabRecord(labRecordId) {
    const response = await apiRequest(`/api/lab-records/${labRecordId}/stop`, { method: 'POST' });
    return await response.json();
}

/**
 * Queue a lab wipe action
 * @param {string} labRecordId - The LabRecord aggregate ID
 * @returns {Promise<Object>} Accepted response with action ID
 */
export async function wipeLabRecord(labRecordId) {
    const response = await apiRequest(`/api/lab-records/${labRecordId}/wipe`, { method: 'POST' });
    return await response.json();
}

/**
 * Queue a lab delete action
 * @param {string} labRecordId - The LabRecord aggregate ID
 * @returns {Promise<Object>} Accepted response with action ID
 */
export async function deleteLabRecord(labRecordId) {
    const response = await apiRequest(`/api/lab-records/${labRecordId}/delete`, { method: 'POST' });
    return await response.json();
}

/**
 * Clone a lab record
 * @param {string} labRecordId - The LabRecord aggregate ID
 * @param {string} [title] - Title for the cloned lab (null = 'Copy of <original>')
 * @returns {Promise<Object>} Cloned lab record info
 */
export async function cloneLabRecord(labRecordId, title = null) {
    const body = title ? { title } : {};
    const response = await apiRequest(`/api/lab-records/${labRecordId}/clone`, {
        method: 'POST',
        body: JSON.stringify(body),
    });
    return await response.json();
}

/**
 * Export/download lab as YAML
 * @param {string} labRecordId - The LabRecord aggregate ID
 * @returns {Promise<string>} Lab YAML content
 */
export async function exportLabRecord(labRecordId) {
    const response = await apiRequest(`/api/lab-records/${labRecordId}/export`, { method: 'POST' });
    return await response.text();
}

/**
 * Archive a lab record
 * @param {string} labRecordId - The LabRecord aggregate ID
 * @returns {Promise<Object>} Accepted response
 */
export async function archiveLabRecord(labRecordId) {
    const response = await apiRequest(`/api/lab-records/${labRecordId}/archive`, { method: 'POST' });
    return await response.json();
}

/**
 * Bind a lab to a lablet session
 * @param {string} labRecordId - The LabRecord aggregate ID
 * @param {string} labletSessionId - LabletSession aggregate ID to bind to
 * @param {string} [role='primary'] - Binding role: primary, secondary, or auxiliary
 * @param {Object} [metadata] - Optional binding metadata (e.g., port mappings)
 * @returns {Promise<Object>} Binding result
 */
export async function bindLabToLablet(labRecordId, labletSessionId, role = 'primary', metadata = null) {
    const body = { lablet_session_id: labletSessionId, role };
    if (metadata) body.metadata = metadata;
    const response = await apiRequest(`/api/lab-records/${labRecordId}/bind`, {
        method: 'POST',
        body: JSON.stringify(body),
    });
    return await response.json();
}

/**
 * Unbind a lab from a lablet session
 * @param {string} labRecordId - The LabRecord aggregate ID
 * @param {string} labletSessionId - LabletSession aggregate ID to unbind from
 * @param {string} [reason] - Reason for unbinding (e.g., timeslot_end, user_request)
 * @returns {Promise<Object>} Unbinding result
 */
export async function unbindLabFromLablet(labRecordId, labletSessionId, reason = null) {
    const body = { lablet_session_id: labletSessionId };
    if (reason) body.reason = reason;
    const response = await apiRequest(`/api/lab-records/${labRecordId}/unbind`, {
        method: 'POST',
        body: JSON.stringify(body),
    });
    return await response.json();
}

export const bindLabToLabletSession = bindLabToLablet;
export const unbindLabFromLabletSession = unbindLabFromLablet;

/**
 * Import a lab from a YAML file
 * @param {string} workerId - Worker ID to import on
 * @param {File} file - YAML file to import
 * @returns {Promise<Object>} Import result
 */
export async function importLabRecord(workerId, file) {
    const formData = new FormData();
    formData.append('file', file);
    const response = await apiRequest(`/api/lab-records/import?worker_id=${workerId}`, {
        method: 'POST',
        body: formData,
    });
    return await response.json();
}
